"""Engine for ``/ops-publish`` — copy lab → public target with sanitization.

Loads ``core/conventions/_private_sanitization_values.yaml`` (lab-only,
gitignored), parses BLOCK / REPLACE / ALLOW rules, walks the source tree
applying:

1. **Path filter** — exclude lab-only paths (ops.log, feedback/, backlog/,
   marketing-manager/**, client-specific distributions, demo-claude,
   state/, credentials.yaml, .mcp.json, agent memory directories, the
   private sanitization values file itself, etc).
2. **Skill whitelist** — read distribution's ``skills.include`` and prune
   ``.claude/commands/`` accordingly (via ``ProjectConfig.is_skill_included``).
3. **REPLACE rules** — substitute matching patterns in flight (text files).
4. **BLOCK rules** — refuse to publish if a BLOCK pattern matches the
   post-REPLACE text. Returns the violation list to the CLI.
5. **ALLOW rules** — verify positive assertions on the materialised target
   (e.g. ``Roberto Butinar`` must appear in ``LICENSE``).

The public sibling ``core/conventions/sanitization-patterns.md`` is
structural-only documentation (no literal pattern values) and ships
verbatim as part of the public publish.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Literal

import yaml

from .config import ProjectConfig, load_project

# ---------------------------------------------------------------------------
# Path filter: lab-only paths that never ship in a public publish.
# ---------------------------------------------------------------------------

# Glob patterns relative to the lab root. Any source path matching one of
# these is silently dropped from the publish target.
_LAB_ONLY_PATH_GLOBS: tuple[str, ...] = (
    # Framework-level narrative / state
    "docs/ops.log",
    "docs/feedback/**",
    "docs/backlog/**",
    "docs/notes/**",
    "docs/handoffs/**",
    "docs/design.md",          # internal architecture doc, lab-only V1
    "docs/toolkit_design.md",  # internal design patterns, lab-only V1
    "docs/migrations/**",
    # Internal operational reference (gotchas, Edge profile patterns, MCP scope
    # priority) — contain lab-policy-specific workarounds that should not be
    # presented as primary guidance in the public distribution. F2 will
    # selectively re-include cleaned-up subsets.
    "core/docs/**",
    # Git submodule references (lab pulls in client-specific submodules)
    "**/.gitmodules",
    # Personal Claude Code settings (paths, env, MCP scope per user)
    ".claude/settings.local.json",
    ".claude/settings.json",
    # Agent memory (per-skill, contains user-specific state)
    ".claude/agents/*/CONTEXT.md",
    ".claude/agents/*/IDENTITY.md",
    ".claude/agents/*/sessions/**",
    ".claude/agents/*/handoffs/**",
    ".claude/agents/*/local/**",
    ".claude/agents/*/drafts/**",
    ".claude/agents/*/sources/**",
    ".claude/agents/_threads/**",
    # Marketing-manager: entirely lab-only (drafts, sources, editorial plan)
    ".claude/agents/marketing-manager/**",
    # Ops-manager: framework maintainer agent memory (CONTEXT.md history,
    # IDENTITY.md learned behaviors, port-back queue + sessions). All
    # lab-only — never expose maintainer-internal operational state.
    ".claude/agents/ops-manager/**",
    # Archived working folders
    "**/_archived/**",
    # Lab distributions (client-specific, demo-claude, _lab, etc) — only the
    # published distribution survives, all others are filtered at the walk
    # boundary. (Handled in walk_publishable() rather than glob — needs the slug.)
    # Credentials + MCP config
    # NOTE: .mcp.example.json IS published — it is the setup template for
    # fresh clones (documents canonical server names dde→databricks-mcp-server
    # and serena→powerbi-modeling-mcp). Finding #4 from ade-ops-2 dogfooding.
    "**/credentials.yaml",
    "**/.mcp.json",
    # Sanitization literal values (lab-only sibling of the structural .md)
    "core/conventions/_private_sanitization_values.yaml",
    # State (pulled from remote, not source of truth)
    "**/state/**",
    # Build artefacts / VCS
    "**/__pycache__/**",
    "**/*.pyc",
    ".git/**",
    ".venv/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    # Per-user editor / IDE local
    "**/local/**",
    "**/.vscode/**",
    "**/.idea/**",
    # PBI runtime cache (deployable items only)
    "**/.pbi/cache.abf",
    "**/.playwright-mcp/**",
)

# Skill name prefixes that are lab/enterprise-only and never publish, used
# as a defensive fallback when the distribution defines no explicit
# ``skills.include`` whitelist. Resolved during the .claude/commands/ walk.
_DEFAULT_DENY_SKILL_PREFIXES: tuple[str, ...] = (
    "cnh-",          # noqa: ade-ops-sanitize=client-slug-cnh reason="literal prefix used as deny-list key, not a client reference"
    "ddf-",          # Databricks→Fabric demo-claude skills
    "marketing-",    # marketing-manager (lab-only meta-agent)
    "ops-manager",   # framework manager (enterprise-tier, never public)
    "ops-port-back", # lab port-back skill (DevOps→lab)
    "weekly-team-",  # weekly-team-update (private team reporting)
)

# Text file extensions we run BLOCK / REPLACE on. Binary files are copied
# byte-for-byte without content scan. Includes non-extensioned conventions
# (.gitignore, .gitattributes, .env.example) so the REPLACE pass catches
# corporate-name mentions in those files.
_TEXT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".txt", ".rst", ".sh", ".ps1", ".bat", ".sql", ".tmdl", ".tmsl",
    ".gitignore", ".gitattributes", ".env.example",
})

# Files without an extension that are nonetheless text and should be
# scanned (e.g. ``LICENSE``, ``Makefile``, ``Dockerfile``).
_TEXT_NAMES_NO_EXT: frozenset[str] = frozenset({
    "LICENSE", "Makefile", "Dockerfile", "CODEOWNERS",
})


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile a gitignore-style glob into a regex.

    Supports gitignore semantics:

    - ``**/X`` matches ``X`` at any depth, including the root (zero dirs).
      Implemented as ``(?:.*/)?X``. Without this, ``**/.mcp.json`` would
      match ``subdir/.mcp.json`` but miss the root-level ``.mcp.json``.
    - ``**`` standalone (not followed by ``/``) matches anything including
      slashes — ``.*``.
    - ``*`` matches within a single path segment — ``[^/]*``.
    - ``?`` matches a single non-slash character — ``[^/]``.

    Other regex metacharacters are escaped. Pattern is anchored ``^...$``.
    """
    escaped: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if i + 1 < len(glob) and glob[i + 1] == "*":
                # ``**/`` → zero or more directory segments (incl. root)
                if i + 2 < len(glob) and glob[i + 2] == "/":
                    escaped.append("(?:.*/)?")
                    i += 3
                    continue
                # Standalone ``**`` → anything including slashes
                escaped.append(".*")
                i += 2
                continue
            escaped.append(r"[^/]*")
        elif c == "?":
            escaped.append(r"[^/]")
        elif c in r".+()[]{}^$|\\":
            escaped.append("\\" + c)
        else:
            escaped.append(c)
        i += 1
    return re.compile("^" + "".join(escaped) + "$")


# Cached compiled lab-only globs (compiled once on first use)
_LAB_ONLY_REGEXES: list[re.Pattern[str]] = []


def _matches_any_glob(rel_path: str, globs: Iterable[str]) -> bool:
    """Return True if ``rel_path`` matches any of the given glob patterns."""
    rel_path = rel_path.replace("\\", "/")
    for g in globs:
        if _glob_to_regex(g).match(rel_path):
            return True
    return False


def _matches_lab_only(rel_path: str) -> bool:
    """Return True if ``rel_path`` is in the lab-only exclusion list."""
    global _LAB_ONLY_REGEXES
    if not _LAB_ONLY_REGEXES:
        _LAB_ONLY_REGEXES = [_glob_to_regex(g) for g in _LAB_ONLY_PATH_GLOBS]
    rel_path = rel_path.replace("\\", "/")
    return any(rgx.match(rel_path) for rgx in _LAB_ONLY_REGEXES)


# ---------------------------------------------------------------------------
# Sanitization rules — parsed from sanitization-patterns.md
# ---------------------------------------------------------------------------

Category = Literal["block", "replace", "allow"]


@dataclass(frozen=True)
class SanitizationRule:
    name: str
    pattern: re.Pattern
    category: Category
    scope_globs: tuple[str, ...]  # which files the rule applies to
    replacement: str | None = None  # only for REPLACE
    rationale: str = ""

    def applies_to(self, rel_path: str) -> bool:
        if not self.scope_globs:
            return True
        # Use the engine's _glob_to_regex (gitignore-style ``**/X`` matches at
        # any depth including root) rather than pathlib.Path.match, which
        # silently misses root-level files for ``**/*`` patterns.
        rel = rel_path.replace("\\", "/")
        for g in self.scope_globs:
            # Fast-path: ``**/*`` means "any file" — pathlib disagrees.
            if g == "**/*":
                return True
            if _glob_to_regex(g).match(rel):
                return True
        return False


def parse_patterns_yaml(patterns_path: Path) -> list[SanitizationRule]:
    """Parse the private sanitization values YAML and return the rule list.

    Expected shape (under each of ``block``, ``replace``, ``allow`` keys):

    .. code-block:: yaml

        block:
          - name: <rule-name>
            pattern: '<python-regex>'
            scope: ['**/*']
            rationale: "<why>"
            last_updated: '2026-MM-DD'

        replace:
          - name: ...
            pattern: ...
            replacement: '<sub-string>'
            scope: [...]

        allow:
          - name: ...
            pattern: ...
            scope: [...]
    """
    with patterns_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    rules: list[SanitizationRule] = []
    for category in ("block", "replace", "allow"):
        for entry in data.get(category) or []:
            name = entry.get("name", "")
            pattern_str = entry.get("pattern")
            if not pattern_str:
                continue
            try:
                pat = re.compile(pattern_str)
            except re.error:
                continue  # malformed — skip rather than crash publish
            scope = entry.get("scope") or ["**/*"]
            if isinstance(scope, str):
                scope = [scope]
            rules.append(
                SanitizationRule(
                    name=name,
                    pattern=pat,
                    category=category,  # type: ignore[arg-type]
                    scope_globs=tuple(scope),
                    replacement=entry.get("replacement"),
                    rationale=entry.get("rationale", ""),
                )
            )
    return rules


# Back-compat shim — callers/tests that still reference the old name get the
# YAML loader. The .md file is now structural-only documentation.
parse_patterns_file = parse_patterns_yaml


# ---------------------------------------------------------------------------
# Publish report
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    file: str
    line: int
    pattern_name: str
    matched_text: str

    def __str__(self) -> str:
        return (
            f"{self.file}:{self.line} pattern={self.pattern_name} "
            f"match={self.matched_text!r}"
        )


@dataclass
class Replacement:
    file: str
    pattern_name: str
    count: int


@dataclass
class PublishReport:
    target_dir: Path
    files_published: int = 0
    files_filtered: int = 0
    replacements: list[Replacement] = field(default_factory=list)
    block_violations: list[Violation] = field(default_factory=list)
    allow_misses: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.block_violations and not self.allow_misses


# ---------------------------------------------------------------------------
# Walk + filter
# ---------------------------------------------------------------------------


def walk_publishable(
    lab_root: Path,
    distribution_slug: str,
    skill_whitelist: set[str] | None,
) -> Iterator[Path]:
    """Yield lab-relative paths that should be copied to the target.

    Applies:
    - Lab-only path globs (excludes ops.log, feedback, marketing, state, ...)
    - Other distributions excluded (only ``distributions/{slug}/`` survives
      among distributions)
    - Skill whitelist on ``.claude/commands/`` (None = include-all)
    """
    for src in lab_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(lab_root).as_posix()

        # Exclude .git and other VCS / cache aggressively at the top
        if any(seg in {".git", ".venv", "__pycache__", "node_modules"}
               for seg in src.relative_to(lab_root).parts):
            continue

        # Other distributions: keep only the requested slug
        if rel.startswith("distributions/") and not rel.startswith(
            f"distributions/{distribution_slug}/"
        ):
            continue

        # Lab-only path globs
        if _matches_lab_only(rel):
            continue

        # Skill filtering on .claude/commands/<name>.md
        if rel.startswith(".claude/commands/") and rel.endswith(".md"):
            skill_name = Path(rel).stem
            if skill_whitelist is not None:
                # Explicit whitelist wins
                if skill_name not in skill_whitelist:
                    continue
            else:
                # Defensive default-deny on known lab/enterprise prefixes
                if any(skill_name.startswith(p) for p in _DEFAULT_DENY_SKILL_PREFIXES):
                    continue

        yield src


# ---------------------------------------------------------------------------
# Sanitization application
# ---------------------------------------------------------------------------


_NOQA_PATTERN = re.compile(
    r"noqa:\s*ade-ops-sanitize=([\w\-]+)",
    re.IGNORECASE,
)


def _line_has_noqa(line: str, rule_name: str) -> bool:
    """Return True if the line carries a noqa exemption for ``rule_name``."""
    for m in _NOQA_PATTERN.finditer(line):
        if m.group(1) == rule_name:
            return True
    return False


def apply_replacements(
    text: str, rel_path: str, rules: list[SanitizationRule]
) -> tuple[str, list[Replacement]]:
    """Run all REPLACE rules in scope on ``text``. Return new text + log."""
    log: list[Replacement] = []
    for rule in rules:
        if rule.category != "replace":
            continue
        if not rule.applies_to(rel_path):
            continue
        new_text, count = rule.pattern.subn(rule.replacement or "", text)
        if count:
            log.append(Replacement(rel_path, rule.name, count))
            text = new_text
    return text, log


def scan_block_violations(
    text: str, rel_path: str, rules: list[SanitizationRule]
) -> list[Violation]:
    """Run all BLOCK rules in scope. Honours per-line noqa exemptions."""
    violations: list[Violation] = []
    lines = text.splitlines()
    for rule in rules:
        if rule.category != "block":
            continue
        if not rule.applies_to(rel_path):
            continue
        for n, line in enumerate(lines, start=1):
            for m in rule.pattern.finditer(line):
                if _line_has_noqa(line, rule.name):
                    continue
                violations.append(
                    Violation(rel_path, n, rule.name, m.group(0))
                )
    return violations


def verify_allow_assertions(
    target_dir: Path, rules: list[SanitizationRule]
) -> list[str]:
    """Return the names of ALLOW rules whose pattern is missing in target."""
    misses: list[str] = []
    for rule in rules:
        if rule.category != "allow":
            continue
        # The scope globs identify which file(s) must contain the pattern.
        found = False
        candidate_paths = list(target_dir.rglob("*"))
        for g in rule.scope_globs:
            for path in candidate_paths:
                if not path.is_file():
                    continue
                rel = path.relative_to(target_dir).as_posix()
                if not Path(rel).match(g):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if rule.pattern.search(text):
                    found = True
                    break
            if found:
                break
        if not found:
            misses.append(rule.name)
    return misses


# ---------------------------------------------------------------------------
# Top-level publish
# ---------------------------------------------------------------------------


def publish(
    lab_root: Path,
    distribution_slug: str,
    target_dir: Path,
    *,
    patterns_file: Path | None = None,
    dry_run: bool = False,
) -> PublishReport:
    """Materialise a public publish of the given distribution.

    Args:
        lab_root: Lab repo root (contains ``core/`` and ``distributions/``).
        distribution_slug: e.g. ``reference``. Only this distribution + ``core/``
            + whitelisted skills + root files survive in the target.
        target_dir: Destination directory. Created if missing. Existing
            contents are preserved unless overwritten by this publish
            (idempotent re-runnable, no destructive delete).
        patterns_file: Override the default
            ``{lab_root}/core/conventions/sanitization-patterns.md``.
        dry_run: When True, no files are written and target_dir is not
            touched. The report still includes the violation list and the
            replacement log (computed in memory).

    Returns:
        ``PublishReport`` with the publish stats + any violations / misses.
        Caller (CLI) decides whether to abort on ``not report.ok``.
    """
    lab_root = lab_root.resolve()
    target_dir = target_dir.resolve()
    patterns_file = patterns_file or (
        lab_root / "core" / "conventions" / "_private_sanitization_values.yaml"
    )
    if not patterns_file.exists():
        raise FileNotFoundError(
            f"private sanitization values not found at {patterns_file}. "
            f"This file is lab-only (gitignored) and required for the publish "
            f"engine to construct the BLOCK / REPLACE / ALLOW rule set."
        )

    rules = parse_patterns_yaml(patterns_file)

    # Resolve distribution's skill whitelist
    dist_project_yaml = (
        lab_root / "distributions" / distribution_slug / "projects"
    )
    skill_whitelist: set[str] | None = None
    for proj_dir in dist_project_yaml.glob("*"):
        cfg_path = proj_dir / "config" / "project.yaml"
        if not cfg_path.exists():
            continue
        try:
            cfg = load_project(proj_dir)
        except (FileNotFoundError, KeyError):
            continue
        if cfg.skills_include is not None:
            skill_whitelist = set(cfg.skills_include)
            break  # first project's whitelist wins (V1 — single-project distros)

    report = PublishReport(target_dir=target_dir)

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    for src in walk_publishable(lab_root, distribution_slug, skill_whitelist):
        rel = src.relative_to(lab_root).as_posix()
        dst = target_dir / rel

        # Binary files: byte copy, no content scan. ``LICENSE``, ``Makefile``,
        # ``Dockerfile``, ``CODEOWNERS`` are extensionless but text — promote
        # them to the text path so REPLACE rules can rewrite corporate-name
        # mentions there.
        is_text_by_ext = src.suffix.lower() in _TEXT_EXTENSIONS
        is_text_by_name = src.name in _TEXT_NAMES_NO_EXT
        if not (is_text_by_ext or is_text_by_name):
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            report.files_published += 1
            continue

        # Text file: read, REPLACE, BLOCK-scan, write
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Treat as binary if UTF-8 fails
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            report.files_published += 1
            continue

        new_text, replacements = apply_replacements(text, rel, rules)
        report.replacements.extend(replacements)

        violations = scan_block_violations(new_text, rel, rules)
        report.block_violations.extend(violations)

        if not dry_run and not violations:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(new_text, encoding="utf-8")
        report.files_published += 1

    if not dry_run and report.ok:
        report.allow_misses = verify_allow_assertions(target_dir, rules)

    return report


# ---------------------------------------------------------------------------
# Orphan release model: wipe target + single-commit force-push.
# ---------------------------------------------------------------------------

# Rationale: the public preview is a release artefact, not a developer
# workshop. Keeping the full git history would expose the prior state of
# every security fix and IP redaction via ``git log -p`` — even when the
# current HEAD is clean. Wiping the target before each publish + force-
# pushing a single commit guarantees that the public history reveals
# nothing about what was sanitized when. Provenance lives in the lab
# private repo, which retains the full author + co-author trail.
#
# Opt-out via ``preserve_history=True`` exists for the rare case of an
# incremental publish (e.g. CI re-run after a transient network failure).
# It is intentionally NOT the default.


def _on_rm_error(func, path, exc_info):
    """``shutil.rmtree`` error handler that clears read-only bits.

    Windows marks files under ``.git/objects/`` read-only; the default
    ``rmtree`` raises on those. This handler chmods +write and retries.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def wipe_for_orphan(target_dir: Path) -> int:
    """Remove every entry under ``target_dir`` (the dir itself survives).

    Returns the number of top-level entries removed. Safe on Windows
    against read-only ``.git/objects`` blobs.
    """
    target_dir = target_dir.resolve()
    if not target_dir.exists():
        return 0
    removed = 0
    for entry in target_dir.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, onerror=_on_rm_error)
        else:
            try:
                entry.chmod(stat.S_IWRITE)
            except OSError:
                pass
            entry.unlink()
        removed += 1
    return removed


@dataclass
class GitPublishResult:
    """Result of ``publish_to_git()``."""

    target_dir: Path
    remote: str
    branch: str
    commit_sha: str = ""
    commit_message: str = ""
    pushed: bool = False
    skipped_reason: str = ""


def _run_git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git subprocess in ``cwd`` and surface stderr on failure."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (cwd={cwd}):\n"
            f"  stdout: {proc.stdout.strip()}\n"
            f"  stderr: {proc.stderr.strip()}"
        )
    return proc


def publish_to_git(
    target_dir: Path,
    *,
    remote: str,
    branch: str = "main",
    lab_rev: str = "",
    commit_message: str | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
    dry_run: bool = False,
) -> GitPublishResult:
    """Initialise a fresh repo in ``target_dir`` and force-push a single commit.

    Implements the orphan release model: there is no resumption of any
    prior history. The caller is expected to have wiped ``target_dir``
    before populating it with publish output, but this function does NOT
    wipe — it only refuses to run if a ``.git/`` is already present
    (anti-foot-gun).

    Args:
        target_dir: Populated with publish output, ``.git`` absent.
        remote: HTTPS or SSH remote URL.
        branch: Branch name on the remote (default ``main``).
        lab_rev: Short SHA of the lab HEAD at publish time, recorded in
            the commit message for traceability back to the lab.
        commit_message: Override the auto-generated message. If None,
            generates ``Release YYYY-MM-DDTHH:MMZ | rev <lab_rev>``.
        author_name, author_email: Override identity. If None, uses
            target repo's local config or falls back to global config.
        dry_run: If True, validate inputs but do not execute git.

    Returns:
        ``GitPublishResult`` with commit SHA + message + push flag.

    Raises:
        RuntimeError: target has a ``.git/`` (caller must wipe first),
            or any git command fails.
        FileNotFoundError: target is empty (nothing to publish).
    """
    target_dir = target_dir.resolve()
    if not target_dir.exists():
        raise FileNotFoundError(f"target dir does not exist: {target_dir}")
    if (target_dir / ".git").exists():
        raise RuntimeError(
            f"target dir already contains a .git: {target_dir}. "
            f"The orphan release model requires a fresh repo per publish. "
            f"Wipe the target first (or pass --preserve-history to opt out)."
        )
    if not any(target_dir.iterdir()):
        raise FileNotFoundError(
            f"target dir is empty: {target_dir}. "
            f"Run the publish materialise step before the git step."
        )

    if commit_message is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        rev_part = f" | rev {lab_rev}" if lab_rev else ""
        commit_message = f"Release {ts}{rev_part}"

    result = GitPublishResult(
        target_dir=target_dir,
        remote=remote,
        branch=branch,
        commit_message=commit_message,
    )

    if dry_run:
        result.skipped_reason = "dry_run"
        return result

    # Fresh init. Use ``--initial-branch`` so we don't depend on whatever
    # ``init.defaultBranch`` is configured globally.
    _run_git(["init", f"--initial-branch={branch}"], cwd=target_dir)

    if author_name:
        _run_git(["config", "user.name", author_name], cwd=target_dir)
    if author_email:
        _run_git(["config", "user.email", author_email], cwd=target_dir)

    _run_git(["add", "."], cwd=target_dir)
    _run_git(["commit", "-m", commit_message], cwd=target_dir)

    sha_proc = _run_git(["rev-parse", "HEAD"], cwd=target_dir)
    result.commit_sha = sha_proc.stdout.strip()

    _run_git(["remote", "add", "origin", remote], cwd=target_dir)
    _run_git(["push", "--force", "origin", branch], cwd=target_dir)
    result.pushed = True

    return result


def lab_head_short(lab_root: Path) -> str:
    """Return the 7-char SHA of the lab repo HEAD, or '' if not a git repo."""
    try:
        proc = _run_git(
            ["rev-parse", "--short=7", "HEAD"],
            cwd=lab_root.resolve(),
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (FileNotFoundError, RuntimeError):
        pass
    return ""
