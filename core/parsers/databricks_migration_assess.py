"""Databricks → Fabric migration assessment.

Reads Databricks ``.py`` notebook sources, classifies each one by migration
effort, identifies the Databricks-specific constructs that need rewriting,
and produces a structured report (machine-readable JSON + human Markdown).

Classification levels:

- ``compat``           — PySpark + Delta + ``spark.sql`` only. Direct port.
- ``refactor_light``   — ``dbutils.fs.*`` / DBFS paths needing trivial rename.
- ``refactor_heavy``   — ``dbutils.secrets``, ``dbutils.widgets``, hardcoded
                          dbfs paths, ``dbutils.notebook.run`` chains, ``%sql``
                          on cross-catalog refs.
- ``impossible``       — ``%scala`` / ``%r`` magics, DLT decorators, structured
                          streaming with non-portable sinks.

Each ``Issue`` carries an estimated effort in minutes (rough but useful for
a first triage) and a one-line recovery hint pointing at the Fabric
equivalent.

This module is content-only: no REST, no auth, no Fabric write side. It
reads local notebook files (under ``state/{env}/notebooks/``) and emits an
in-memory ``AssessmentReport``. Callers (the ``/migration-assess`` skill)
serialize it and optionally pass converted ipynb dicts to the Fabric
notebook manager for deploy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

from core.parsers.databricks_to_ipynb import convert_source


Classification = Literal["compat", "refactor_light", "refactor_heavy", "impossible"]


@dataclass
class Issue:
    """A single Databricks-specific construct found in a notebook."""
    pattern: str                          # rule id, e.g. "dbutils.fs"
    severity: Classification              # impact on overall classification
    line_number: int
    matched_text: str
    effort_minutes: int
    recovery_hint: str


@dataclass
class NotebookAssessment:
    """Per-notebook assessment output."""
    name: str
    relative_path: str
    cell_count: int
    code_cells: int
    markdown_cells: int
    issues: list[Issue] = field(default_factory=list)
    classification: Classification = "compat"
    effort_minutes: int = 0
    converted_ipynb: dict | None = None   # None for ``impossible`` only

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop the heavy ipynb body from the JSON dump — it's written
        # separately as a .ipynb file.
        d.pop("converted_ipynb", None)
        return d


@dataclass
class AssessmentReport:
    """Aggregate report across a folder of notebooks."""
    source_path: str
    total_notebooks: int = 0
    total_effort_minutes: int = 0
    by_classification: dict[str, int] = field(default_factory=dict)
    notebooks: list[NotebookAssessment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "total_notebooks": self.total_notebooks,
            "total_effort_minutes": self.total_effort_minutes,
            "by_classification": self.by_classification,
            "notebooks": [n.to_dict() for n in self.notebooks],
        }


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

# Each rule: (pattern_id, regex, severity, effort_per_match_minutes, hint)
_RULES: list[tuple[str, re.Pattern, Classification, int, str]] = [
    (
        "dbutils.fs",
        re.compile(r"dbutils\.fs\."),
        "refactor_light",
        2,
        "Rename to `mssparkutils.fs.` — same API surface in Fabric.",
    ),
    (
        "dbfs_path_literal",
        re.compile(r"['\"]dbfs:/[^'\"]+['\"]"),
        "refactor_heavy",
        10,
        "Replace `dbfs:/` literal with Lakehouse abfss path or `Tables/`/`Files/` relative.",
    ),
    (
        "dbutils.secrets",
        re.compile(r"dbutils\.secrets\."),
        "refactor_heavy",
        30,
        "Re-provision secrets in Azure Key Vault; access via `mssparkutils.credentials.getSecret`.",
    ),
    (
        "dbutils.widgets",
        re.compile(r"dbutils\.widgets\."),
        "refactor_heavy",
        45,
        "Convert widgets to Fabric notebook parameters (cell tag `parameters`) + pipeline activity arguments.",
    ),
    (
        "dbutils.notebook.run",
        re.compile(r"dbutils\.notebook\.run\("),
        "refactor_heavy",
        20,
        "Replace with `mssparkutils.notebook.run` (same signature) or model as pipeline activity.",
    ),
    (
        "dbutils.notebook.exit",
        re.compile(r"dbutils\.notebook\.exit\("),
        "refactor_light",
        1,
        "Rename to `mssparkutils.notebook.exit(` — same signature in Fabric. Auto-rewritten by the converter.",
    ),
    (
        "unity_catalog_three_part",
        re.compile(r"['\"][a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*['\"]", re.IGNORECASE),
        "refactor_light",
        5,
        "Three-part UC name `catalog.schema.table` — replace with Lakehouse `Tables/<name>` or attach a default lakehouse.",
    ),
    (
        "magic_scala",
        re.compile(r"# MAGIC %scala\b"),
        "impossible",
        0,
        "Fabric notebooks do not support Scala magic in Python notebooks — rewrite cell in PySpark.",
    ),
    (
        "magic_r",
        re.compile(r"# MAGIC %r\b"),
        "impossible",
        0,
        "Fabric notebooks do not support `%r` magic — port to SparkR notebook or rewrite in Python.",
    ),
    (
        "dlt_decorator",
        re.compile(r"@dlt\."),
        "impossible",
        0,
        "DLT (Delta Live Tables) has no direct Fabric equivalent — refactor as Fabric Data Pipeline or Spark structured streaming.",
    ),
    (
        "spark_databricks_conf",
        re.compile(r"spark\.conf\.set\s*\(\s*['\"]spark\.databricks\."),
        "refactor_heavy",
        15,
        "Drop `spark.databricks.*` conf settings — Fabric has its own runtime tuning surface.",
    ),
    (
        "databricks_default_schema",
        # Catches Hive-style `default.<table>` (in quoted strings or bare SQL)
        # and `IN default` qualifiers from SHOW TABLES / DESCRIBE etc.
        # Fabric Lakehouse has no `default` schema — unqualified names resolve
        # via the attached default lakehouse instead.
        re.compile(r"\bdefault\.[a-z_][a-z0-9_]*\b|\bIN\s+default\b", re.IGNORECASE),
        "refactor_light",
        1,
        "Drop `default.` qualifier — Fabric Lakehouse resolves unqualified names "
        "via the attached default lakehouse. Auto-rewritten by the converter.",
    ),
]


# ---------------------------------------------------------------------------
# Auto-rewrites: text-level substitutions applied to the source before
# structural ipynb conversion. Each entry is (regex, replacement) where the
# regex must match a *safe* lexical pattern (string literal, SQL keyword
# context). Auto-rewrites are conservative: they only handle the cases the
# `_RULES` registry has classified as `refactor_light` and would otherwise
# leave to the user.
#
# Order matters: more specific patterns run first.
# ---------------------------------------------------------------------------

_AUTO_REWRITES: list[tuple[re.Pattern, str]] = [
    # `IN default` (SHOW TABLES IN default, DESCRIBE SCHEMA default, etc.) →
    # drop the qualifier. Fabric uses the attached default lakehouse instead.
    (re.compile(r"\s+IN\s+default\b", re.IGNORECASE), ""),
    # `default.<table>` → `<table>`. Safe because Fabric Lakehouse resolves
    # unqualified names through the default lakehouse attachment.
    (re.compile(r"\bdefault\.([a-z_][a-z0-9_]*)\b"), r"\1"),
    # `dbutils.fs.` → `mssparkutils.fs.` (same API surface in Fabric).
    (re.compile(r"\bdbutils\.fs\."), "mssparkutils.fs."),
    # `dbutils.notebook.exit(` and `dbutils.notebook.run(` → `mssparkutils.*`.
    # Both have the same signature on Fabric; the rewrite is symbolic only.
    # `dbutils.notebook.run` is still classified refactor_heavy upstream so
    # callers know to audit the orchestration pattern, but the rename itself
    # is mechanical and safe to apply automatically.
    (re.compile(r"\bdbutils\.notebook\.exit\("), "mssparkutils.notebook.exit("),
    (re.compile(r"\bdbutils\.notebook\.run\("), "mssparkutils.notebook.run("),
]


def apply_auto_rewrites(source_text: str) -> str:
    """Apply lossless Databricks→Fabric text rewrites to a notebook source.

    Currently handles the `default` schema qualifier (both `IN default` and
    `default.<table>`), which is the most common silent failure when porting
    notebooks that target the Databricks Hive metastore default DB.
    """
    out = source_text
    for regex, replacement in _AUTO_REWRITES:
        out = regex.sub(replacement, out)
    return out

# Rule severity ranking (high → low) for promoting overall classification.
_SEVERITY_RANK = {
    "compat": 0,
    "refactor_light": 1,
    "refactor_heavy": 2,
    "impossible": 3,
}


# ---------------------------------------------------------------------------
# Single-notebook scan
# ---------------------------------------------------------------------------

def scan_notebook_source(source_text: str) -> list[Issue]:
    """Run all rules against a notebook source and return matching issues."""
    issues: list[Issue] = []
    lines = source_text.splitlines()
    for pattern_id, regex, severity, effort, hint in _RULES:
        for line_no, line in enumerate(lines, start=1):
            for m in regex.finditer(line):
                issues.append(
                    Issue(
                        pattern=pattern_id,
                        severity=severity,
                        line_number=line_no,
                        matched_text=line.strip()[:120],
                        effort_minutes=effort,
                        recovery_hint=hint,
                    )
                )
    return issues


def classify(issues: list[Issue]) -> Classification:
    """Return the most severe classification across all issues (compat if empty)."""
    if not issues:
        return "compat"
    return max(
        (issue.severity for issue in issues),
        key=lambda s: _SEVERITY_RANK[s],
    )


def assess_notebook(path: Path, root: Path) -> NotebookAssessment:
    """Read one ``.py`` notebook from disk, scan, classify, convert."""
    source = path.read_text(encoding="utf-8")
    issues = scan_notebook_source(source)
    cls = classify(issues)
    effort = sum(i.effort_minutes for i in issues)

    converted = None
    if cls != "impossible":
        # Apply lossless Fabric rewrites (e.g. `default.X` → `X`) before the
        # structural conversion. Issues are still recorded above for audit,
        # but the produced ipynb is deploy-ready.
        rewritten = apply_auto_rewrites(source)
        converted = convert_source(rewritten)

    cells = converted.get("cells", []) if converted else []
    code_count = sum(1 for c in cells if c.get("cell_type") == "code")
    md_count = sum(1 for c in cells if c.get("cell_type") == "markdown")

    return NotebookAssessment(
        name=path.stem,
        relative_path=str(path.relative_to(root)).replace("\\", "/"),
        cell_count=len(cells),
        code_cells=code_count,
        markdown_cells=md_count,
        issues=issues,
        classification=cls,
        effort_minutes=effort,
        converted_ipynb=converted,
    )


# ---------------------------------------------------------------------------
# Folder-level assessment
# ---------------------------------------------------------------------------

def assess_notebooks_folder(root: Path | str) -> AssessmentReport:
    """Walk a folder of Databricks ``.py`` notebooks and assess each one.

    Single-root variant. For multi-root assessment that merges ``src/``
    and ``state/{env}/`` inputs, see :func:`assess_notebooks_merged`
    (closes P2-C from the ade-ops-2 release-readiness assessment).
    """
    root_path = Path(root)
    notebooks = sorted(root_path.rglob("*.py"))

    report = AssessmentReport(source_path=str(root_path))
    for nb_path in notebooks:
        # Skip non-notebook .py files (no Databricks header).
        text_head = nb_path.read_text(encoding="utf-8", errors="ignore")[:200]
        if "# Databricks notebook source" not in text_head:
            continue
        assessment = assess_notebook(nb_path, root_path)
        report.notebooks.append(assessment)
        report.total_effort_minutes += assessment.effort_minutes
        report.by_classification[assessment.classification] = (
            report.by_classification.get(assessment.classification, 0) + 1
        )
    report.total_notebooks = len(report.notebooks)
    return report


def assess_notebooks_merged(
    src_root: Path | str | None,
    state_root: Path | str | None,
) -> AssessmentReport:
    """Walk ``src/`` AND ``state/{env}/notebooks/`` together, merged.

    Closes P2-C: real migration scenarios may have notebooks that
    originate Fabric-side (no Databricks ancestor) — those live in
    ``src/notebooks/`` directly and never appear under ``state/`` until
    the first pull. Pulling Databricks notebooks lands them under
    ``state/{env}/notebooks/``. The migration assessment should consider
    both sources.

    Conflict resolution: if a relative path appears in both ``src/`` and
    ``state/``, ``src/`` wins (operator's local edits override the
    pulled mirror). This matches the assemble pipeline used by
    ``operations.push``.

    Args:
        src_root: Path to ``src/notebooks/`` (or any folder rooted at
            project src). Pass None to skip src.
        state_root: Path to ``state/{env}/notebooks/``. Pass None to
            skip state.

    Returns:
        ``AssessmentReport`` with combined notebooks, ``source_path``
        formatted as ``src=<path>+state=<path>``.
    """
    src_path = Path(src_root) if src_root else None
    state_path = Path(state_root) if state_root else None

    # Collect by relative path so we can deduplicate src + state.
    by_rel: dict[str, Path] = {}

    def _collect(root: Path | None) -> None:
        if root is None or not root.exists():
            return
        for nb_path in sorted(root.rglob("*.py")):
            rel = nb_path.relative_to(root).as_posix()
            # Skip non-notebook .py files (no Databricks header).
            text_head = nb_path.read_text(encoding="utf-8", errors="ignore")[:200]
            if "# Databricks notebook source" not in text_head:
                continue
            # src wins on conflict (operator edits override pulled mirror).
            if rel not in by_rel:
                by_rel[rel] = nb_path

    # Order matters: src first (wins on conflict), then state (fills gaps).
    _collect(src_path)
    _collect(state_path)

    source_label = "+".join(
        f"{label}={path}" for label, path in (
            ("src", src_path), ("state", state_path)
        ) if path is not None
    ) or "(no roots)"

    report = AssessmentReport(source_path=source_label)
    for rel, nb_path in sorted(by_rel.items()):
        # Determine the effective root for this notebook (src or state) so
        # the relative paths in the report make sense.
        if src_path is not None and nb_path.is_relative_to(src_path):
            effective_root = src_path
        elif state_path is not None and nb_path.is_relative_to(state_path):
            effective_root = state_path
        else:
            effective_root = nb_path.parent
        assessment = assess_notebook(nb_path, effective_root)
        report.notebooks.append(assessment)
        report.total_effort_minutes += assessment.effort_minutes
        report.by_classification[assessment.classification] = (
            report.by_classification.get(assessment.classification, 0) + 1
        )
    report.total_notebooks = len(report.notebooks)
    return report


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------

def render_markdown_report(report: AssessmentReport) -> str:
    lines: list[str] = []
    lines.append("# Databricks → Fabric Migration Assessment")
    lines.append("")
    lines.append(f"- **Source**: `{report.source_path}`")
    lines.append(f"- **Notebooks analyzed**: {report.total_notebooks}")
    lines.append(f"- **Total estimated effort**: {report.total_effort_minutes} min "
                 f"(~{report.total_effort_minutes / 60:.1f}h)")
    lines.append("")

    # Summary table
    lines.append("## Summary by classification")
    lines.append("")
    lines.append("| Classification | Count | Notes |")
    lines.append("|---|---|---|")
    for cls, label in (
        ("compat", "Direct port — no changes needed"),
        ("refactor_light", "Trivial rename / path adjustment"),
        ("refactor_heavy", "Manual rewrite required (secrets, widgets, DLT)"),
        ("impossible", "Cannot port automatically — rewrite from scratch"),
    ):
        count = report.by_classification.get(cls, 0)
        lines.append(f"| **{cls}** | {count} | {label} |")
    lines.append("")

    # Per-notebook detail
    lines.append("## Per-notebook detail")
    lines.append("")
    for nb in report.notebooks:
        lines.append(f"### `{nb.relative_path}`")
        lines.append("")
        lines.append(f"- Classification: **{nb.classification}**")
        lines.append(f"- Cells: {nb.cell_count} ({nb.code_cells} code, {nb.markdown_cells} markdown)")
        lines.append(f"- Estimated effort: {nb.effort_minutes} min")
        if nb.issues:
            lines.append("- Issues:")
            for issue in nb.issues:
                lines.append(
                    f"  - L{issue.line_number} `{issue.pattern}` ({issue.severity}, "
                    f"{issue.effort_minutes}min): {issue.recovery_hint}"
                )
        else:
            lines.append("- Issues: none")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def run_assessment(
    notebooks_root: Path | str,
    output_dir: Path | str,
) -> AssessmentReport:
    """Run the full assessment and write outputs to disk.

    Produces:
    - ``{output_dir}/assessment_report.md`` — human-readable summary
    - ``{output_dir}/assessment_report.json`` — machine-readable
    - ``{output_dir}/converted/<rel_path>.ipynb`` — one per non-``impossible`` notebook
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    converted_dir = out / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)

    report = assess_notebooks_folder(notebooks_root)

    (out / "assessment_report.md").write_text(
        render_markdown_report(report), encoding="utf-8"
    )
    (out / "assessment_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for nb in report.notebooks:
        if nb.converted_ipynb is None:
            continue
        target = converted_dir / Path(nb.relative_path).with_suffix(".ipynb")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(nb.converted_ipynb, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return report
