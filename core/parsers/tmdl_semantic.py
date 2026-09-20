"""Semantic (content-aware) diff for Power BI TMDL semantic models.

A pulled Fabric ``.SemanticModel`` is serialized TMDL. Comparing it to the
authored source as raw text is dominated by *cosmetic* churn — re-generated
``lineageTag`` / ``sourceLineageTag`` values, ``annotation`` lines, object
ordering, auto-generated date tables, and CRLF — none of which is model
content. That noise made the pre-push drift signal cry wolf: a real "0 columns
lost" change looked like a ~170-line "wide drift" that *looked* like clobbering
another team's work (TICK-041).

This module parses a semantic model into the objects an operator actually cares
about — the same surface ``INFO.VIEW.COLUMNS`` / ``INFO.VIEW.MEASURES`` exposes:
tables, columns, measures, partitions, relationships — and diffs *those*. Each
object carries a **content fingerprint**: its body lines with the cosmetic lines
stripped and whitespace normalized, so a change in a ``lineageTag`` or the order
of two columns is invisible, while a changed ``dataType``, ``sourceColumn``,
calculated-column DAX, measure DAX, or partition source query is reported.

The parser is intentionally line-oriented and tolerant: TMDL it does not
recognize is ignored, never raises. It is *not* a full TMDL grammar — it is a
content-presence extractor for the drift gate. Known scope limits are documented
on :func:`parse_model`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Mapping

_SUFFIX = ".SemanticModel"

# Lines that are pure serialization metadata, never model content. Stripped from
# every object's fingerprint so their churn cannot register as drift.
_COSMETIC_PREFIXES = ("lineageTag:", "sourceLineageTag:", "annotation ")

# A `variation` block under a column wires an auto-generated date hierarchy; its
# body is regenerated lineageTag/relationship references — cosmetic for content.
_VARIATION_KW = "variation"

# Auto-generated date scaffolding tables. Power BI emits one LocalDateTable per
# date column plus a shared template; they carry no authored content and their
# GUID-suffixed names + count churn between pulls. Excluded from the diff.
_AUTO_DATE_PREFIXES = ("LocalDateTable_", "DateTableTemplate_")


# =============================================================================
# Parsed model
# =============================================================================

@dataclass
class Table:
    """A model table reduced to its content-bearing objects.

    ``columns`` / ``measures`` / ``partitions`` map an object name to its content
    fingerprint (see module docstring). ``is_auto_date`` marks Power BI's
    auto-generated date tables, which are excluded from the diff.
    """

    name: str
    columns: dict[str, str] = field(default_factory=dict)
    measures: dict[str, str] = field(default_factory=dict)
    partitions: dict[str, str] = field(default_factory=dict)
    is_auto_date: bool = False


@dataclass
class SemanticModel:
    """A parsed semantic model: its non-auto-date tables and relationships.

    ``relationships`` is keyed by the ``(from_column, to_column)`` pair (the
    content identity — the regenerated relationship GUID is ignored) with the
    body fingerprint as value. Relationships touching an auto-date table are
    dropped.
    """

    name: str
    tables: dict[str, Table] = field(default_factory=dict)
    relationships: dict[tuple[str, str], str] = field(default_factory=dict)

    def content_tables(self) -> dict[str, Table]:
        """Tables that carry authored content (auto-date scaffolding excluded)."""
        return {n: t for n, t in self.tables.items() if not t.is_auto_date}


# =============================================================================
# Parsing
# =============================================================================

def _depth(line: str) -> int:
    """Number of leading TAB characters (TMDL indents with tabs)."""
    n = 0
    for ch in line:
        if ch == "\t":
            n += 1
        else:
            break
    return n


def _decode(blob: bytes) -> str:
    """Decode TMDL bytes, normalizing CRLF/CR to LF so line endings never drift."""
    text = blob.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_auto_date(table_name: str) -> bool:
    return any(table_name.startswith(p) for p in _AUTO_DATE_PREFIXES)


def _parse_object_name(rest: str) -> str:
    """Extract an object name from the text after a ``column``/``measure``/…
    keyword.

    Handles quoted names (``'Market Basket' = IF(...)``) and bare names
    (``cd_part``, ``dm_part = m``), discarding any trailing ``= expr`` / ``= m``
    that follows the name on the header line.
    """
    rest = rest.strip()
    if rest.startswith("'"):
        end = rest.find("'", 1)
        if end != -1:
            return rest[1:end]
        return rest[1:].strip()
    # Bare name: up to the first whitespace or '='.
    token = rest.split("=", 1)[0]
    return token.split()[0] if token.split() else token.strip()


def _inline_expression(rest: str) -> str | None:
    """Return the inline ``= …`` expression on an object header line, if any."""
    if "=" not in rest:
        return None
    expr = rest.split("=", 1)[1].strip()
    return f"= {expr}" if expr else None


def _is_cosmetic(stripped: str) -> bool:
    return any(stripped.startswith(p) for p in _COSMETIC_PREFIXES)


def _parse_table_file(text: str) -> Table | None:
    """Parse one ``definition/tables/<name>.tmdl`` file into a :class:`Table`."""
    lines = text.split("\n")
    table: Table | None = None
    cur_kind: str | None = None          # "column" | "measure" | "partition"
    cur_name: str | None = None
    cur_body: list[str] = []
    skip_variation_above: int | None = None  # depth of an open `variation` block

    def flush() -> None:
        nonlocal cur_kind, cur_name, cur_body
        if table is not None and cur_kind and cur_name is not None:
            bucket = getattr(table, cur_kind + "s")
            bucket[cur_name] = "\n".join(cur_body)
        cur_kind = cur_name = None
        cur_body = []

    for raw in lines:
        if not raw.strip():
            continue
        depth = _depth(raw)
        stripped = raw.strip()

        # Close a `variation` sub-block once we dedent back to/above its level.
        if skip_variation_above is not None and depth <= skip_variation_above:
            skip_variation_above = None
        if skip_variation_above is not None:
            continue

        if stripped.startswith("///"):
            continue  # doc comment — not model content

        if depth == 0:
            if stripped.startswith("table "):
                name = _parse_object_name(stripped[len("table "):])
                table = Table(name=name, is_auto_date=_is_auto_date(name))
            continue

        if table is None:
            continue

        if depth == 1:
            for kw in ("column", "measure", "partition"):
                if stripped.startswith(kw + " "):
                    flush()
                    cur_kind = kw
                    rest = stripped[len(kw) + 1:]
                    cur_name = _parse_object_name(rest)
                    inline = _inline_expression(rest)
                    cur_body = [inline] if inline else []
                    break
            else:
                # A table-level property (lineageTag, annotation, isHidden, a
                # `hierarchy`, …). Closes any open object; not tracked as content.
                flush()
            continue

        # depth >= 2 — a property of the current object.
        if cur_kind is None:
            continue
        if stripped.startswith(_VARIATION_KW + " ") or stripped == _VARIATION_KW:
            skip_variation_above = depth
            continue
        if _is_cosmetic(stripped):
            continue
        cur_body.append(stripped)

    flush()
    return table


def _parse_relationships(text: str) -> dict[tuple[str, str], str]:
    """Parse ``definition/relationships.tmdl`` into ``{(from, to): fingerprint}``.

    Relationships whose endpoints touch an auto-date table are dropped (Power BI
    regenerates those wholesale). Identity is the column pair, not the GUID.
    """
    out: dict[tuple[str, str], str] = {}
    body: list[str] = []
    from_col = to_col = None

    def flush() -> None:
        nonlocal body, from_col, to_col
        if from_col and to_col:
            ft = from_col.split(".", 1)[0].strip("'")
            tt = to_col.split(".", 1)[0].strip("'")
            if not (_is_auto_date(ft) or _is_auto_date(tt)):
                out[(from_col, to_col)] = "\n".join(sorted(body))
        body = []
        from_col = to_col = None

    for raw in text.split("\n"):
        if not raw.strip():
            continue
        stripped = raw.strip()
        if _depth(raw) == 0:
            if stripped.startswith("relationship "):
                flush()
            continue
        if stripped.startswith("fromColumn:"):
            from_col = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("toColumn:"):
            to_col = stripped.split(":", 1)[1].strip()
        if not _is_cosmetic(stripped):
            body.append(stripped)

    flush()
    return out


def split_semantic_models(files: Mapping[str, str | bytes]) -> dict[str, dict[str, bytes]]:
    """Group a flat ``{rel_path: content}`` map into ``{model_name: {in_model_path: bytes}}``.

    Splits on the path segment ending in ``.SemanticModel`` (wherever it sits —
    state nests it under a ``SemanticModel/`` folder, src may not), keying by the
    model base name and re-rooting each file at the model folder. Files with no
    ``.SemanticModel`` segment are ignored (left to the byte-level diff).
    """
    models: dict[str, dict[str, bytes]] = defaultdict(dict)
    for path, content in files.items():
        parts = path.split("/")
        idx = next((i for i, p in enumerate(parts) if p.endswith(_SUFFIX)), None)
        if idx is None:
            continue
        key = parts[idx][: -len(_SUFFIX)]
        rel = "/".join(parts[idx + 1:])
        blob = content.encode("utf-8") if isinstance(content, str) else content
        models[key][rel] = blob
    return dict(models)


def parse_model(files: Mapping[str, bytes], name: str = "") -> SemanticModel:
    """Parse a single model's files (re-rooted at the model folder) into a model.

    Routes ``definition/tables/*.tmdl`` to the table parser and
    ``definition/relationships.tmdl`` to the relationship parser. Other files
    (``model.tmdl``, ``database.tmdl``, ``cultures/``, ``perspectives/``,
    ``expressions.tmdl``) are skipped — they hold configuration/presentation, not
    the table/column/measure content the gate guards. Shared ``expressions.tmdl``
    M is a known scope limit (partition sources are still compared in-table).
    """
    model = SemanticModel(name=name)
    for rel, blob in files.items():
        rel_posix = rel.replace("\\", "/")
        if rel_posix.startswith("definition/tables/") and rel_posix.endswith(".tmdl"):
            table = _parse_table_file(_decode(blob))
            if table is not None:
                model.tables[table.name] = table
        elif rel_posix == "definition/relationships.tmdl":
            model.relationships = _parse_relationships(_decode(blob))
    return model


def scope_has_semantic_model(files: Mapping[str, str | bytes]) -> bool:
    """True when any path is inside a ``.SemanticModel`` folder."""
    return any(
        any(p.endswith(_SUFFIX) for p in path.split("/")) for path in files
    )


# =============================================================================
# Canonicalization (TICK-041 ACT-002) — byte-stable state baseline on pull
# =============================================================================
#
# Fabric re-serializes a semantic model on every getDefinition: lineageTag /
# annotation churn, nondeterministic object ordering, and CRLF. Pulled into a
# tracked, committed state/ mirror that is perpetual `git diff state/` noise and
# a dirty diff baseline. Canonicalizing on pull gives the baseline a trustworthy
# zero: the same remote model serializes to the same bytes each pull.
#
# DESIGN — the pull path writes the team-shared state/, so canonicalization is
# FAIL-CLOSED: it only ever (a) strips lines that are never valid DAX/M
# (lineageTag/sourceLineageTag/annotation — a purely textual, body-safe strip)
# and (b) REORDERS whole top-level object blocks; it never edits an expression
# body. A self-check verifies the object-header multiset is unchanged and falls
# back to the unsorted (strip-only) form on any mismatch, so a sort bug can
# never silently drop a column/measure (the TICK-027 silent-loss class).
#
# Known residual (deliberately out of scope — coupled to relationship GUIDs
# referenced by column `variation` blocks; the semantic gate already ignores
# both): regenerated relationship/variation GUIDs may still churn. Relationships
# are at least order-stabilized by their from->to identity.

_OBJECT_KINDS = ("column", "measure", "partition", "hierarchy")
_HEADER_KINDS = _OBJECT_KINDS + ("table", "relationship")


@dataclass
class _Block:
    """A TMDL block: a header line plus its verbatim body (deeper-indented) lines,
    optionally prefixed by its leading ``///`` doc comments."""

    kind: str
    name: str
    lines: list[str]


def _strip_cosmetic_lines(text: str) -> list[str]:
    """Drop pure-serialization lines. ``lineageTag:`` / ``sourceLineageTag:`` are
    never valid DAX/M so the strip is body-safe; ``annotation`` likewise in
    practice. Trailing whitespace is normalized."""
    out: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(("lineageTag:", "sourceLineageTag:")):
            continue
        if s == "annotation" or s.startswith("annotation "):
            continue
        out.append(line.rstrip())
    return out


def _collapse_blanks(lines: list[str]) -> list[str]:
    """Collapse runs of blank lines to one and trim leading/trailing blanks."""
    out: list[str] = []
    prev_blank = False
    for ln in lines:
        blank = ln.strip() == ""
        if blank and prev_blank:
            continue
        out.append(ln)
        prev_blank = blank
    while out and out[0].strip() == "":
        out.pop(0)
    while out and out[-1].strip() == "":
        out.pop()
    return out


def _object_headers(lines: list[str]) -> Counter:
    """Multiset of object/relationship/table header lines (the content identity)."""
    c: Counter = Counter()
    for line in lines:
        s = line.strip()
        if any(s.startswith(k + " ") for k in _HEADER_KINDS):
            c[s] += 1
    return c


def _group_table_children(body: list[str]) -> list[_Block]:
    """Group a table's body (non-blank, depth>=1) into blocks; leading ``///``
    comments bind to the following object block."""
    blocks: list[_Block] = []
    comment_buf: list[str] = []
    cur: _Block | None = None
    for line in body:
        s = line.strip()
        if _depth(line) == 1:
            if s.startswith("///"):
                comment_buf.append(line)
                continue
            if cur is not None:
                blocks.append(cur)
            kind = next((k for k in _OBJECT_KINDS if s.startswith(k + " ")), "prop")
            name = _parse_object_name(s[len(kind) + 1:]) if kind != "prop" else s
            cur = _Block(kind, name, [*comment_buf, line])
            comment_buf = []
        elif cur is not None:
            cur.lines.append(line)
    if cur is not None:
        blocks.append(cur)
    if comment_buf:
        blocks.append(_Block("prop", "", comment_buf))
    return blocks


def _canonical_table(lines: list[str]) -> list[str]:
    """Canonicalize a tables/<t>.tmdl: table props in place, object blocks sorted."""
    i = 0
    prefix: list[str] = []
    while i < len(lines) and lines[i].strip().startswith("///"):
        prefix.append(lines[i])
        i += 1
    if i >= len(lines) or not lines[i].strip().startswith("table "):
        raise ValueError("no table header")
    header = lines[i]
    blocks = _group_table_children(lines[i + 1:])
    props = [b for b in blocks if b.kind == "prop"]
    objs = sorted((b for b in blocks if b.kind != "prop"), key=lambda b: (b.kind, b.name))
    out = [*prefix, header]
    for b in props:
        out += b.lines
    for b in objs:
        out.append("")
        out += b.lines
    return out


def _canonical_relationships(lines: list[str]) -> list[str]:
    """Canonicalize relationships.tmdl: blocks sorted by from->to identity."""
    blocks: list[_Block] = []
    cur: _Block | None = None
    for line in lines:
        s = line.strip()
        if _depth(line) == 0 and s.startswith("relationship "):
            if cur is not None:
                blocks.append(cur)
            cur = _Block("relationship", "", [line])
        elif cur is not None:
            cur.lines.append(line)
    if cur is not None:
        blocks.append(cur)

    def key(b: _Block) -> tuple[str, str, str]:
        f = t = ""
        for line in b.lines:
            s = line.strip()
            if s.startswith("fromColumn:"):
                f = s.split(":", 1)[1].strip()
            elif s.startswith("toColumn:"):
                t = s.split(":", 1)[1].strip()
        return (f, t, b.lines[0].strip())

    blocks.sort(key=key)
    out: list[str] = []
    for n, b in enumerate(blocks):
        if n:
            out.append("")
        out += b.lines
    return out


def canonicalize_tmdl(text: str) -> str:
    """Return a byte-stable canonical form of one ``.tmdl`` file.

    CRLF/CR -> LF; strip lineageTag/sourceLineageTag/annotation; sort top-level
    object blocks (table children; relationships by from->to). Idempotent and
    fail-closed — never raises, and never changes the object-header multiset
    (falls back to the strip-only form otherwise).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped = _strip_cosmetic_lines(text)
    nonblank = [ln for ln in stripped if ln.strip() != ""]
    try:
        if any(_depth(ln) == 0 and ln.strip().startswith("relationship ") for ln in nonblank):
            result = _canonical_relationships(nonblank)
        elif any(_depth(ln) == 0 and ln.strip().startswith("table ") for ln in nonblank):
            result = _canonical_table(nonblank)
        else:
            result = stripped
    except Exception:
        result = stripped
    if _object_headers(stripped) != _object_headers(result):
        result = stripped  # fail-closed: a reorder must never lose an object
    out = _collapse_blanks(result)
    return ("\n".join(out) + "\n") if out else ""


def canonicalize_tmdl_bytes(blob: bytes) -> bytes:
    """Canonicalize ``.tmdl`` bytes (UTF-8, BOM-stripped). Non-decodable bytes
    pass through unchanged."""
    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        return blob
    return canonicalize_tmdl(text).encode("utf-8")


# =============================================================================
# Diff
# =============================================================================

@dataclass
class TableDelta:
    """Per-table content delta (only populated buckets are reported)."""

    name: str
    columns_added: list[str] = field(default_factory=list)
    columns_removed: list[str] = field(default_factory=list)
    columns_changed: list[str] = field(default_factory=list)
    measures_added: list[str] = field(default_factory=list)
    measures_removed: list[str] = field(default_factory=list)
    measures_changed: list[str] = field(default_factory=list)
    partitions_changed: list[str] = field(default_factory=list)

    def has_loss(self) -> bool:
        """A removed or changed object — the push would drop/alter live content."""
        return bool(
            self.columns_removed or self.measures_removed
            or self.columns_changed or self.measures_changed
            or self.partitions_changed
        )

    def is_empty(self) -> bool:
        return not (
            self.columns_added or self.columns_removed or self.columns_changed
            or self.measures_added or self.measures_removed or self.measures_changed
            or self.partitions_changed
        )


@dataclass
class SemanticDiff:
    """Result of diffing a baseline (live/state) against a proposal (src).

    ``added`` is the operator's own new work (safe). ``removed`` is the clobber
    signal — objects live has that the push would delete. ``changed`` is content
    drift (a binding/expression/dataType differs). ``is_clean`` is the gate
    verdict: no removed, no changed — i.e. ``src ⊇ live`` with no regressions.
    """

    model: str
    tables_added: list[str] = field(default_factory=list)
    tables_removed: list[str] = field(default_factory=list)
    table_deltas: list[TableDelta] = field(default_factory=list)
    relationships_added: list[str] = field(default_factory=list)
    relationships_removed: list[str] = field(default_factory=list)
    relationships_changed: list[str] = field(default_factory=list)

    @property
    def has_content_loss(self) -> bool:
        """Removed/changed content anywhere — the real drift signal."""
        return bool(
            self.tables_removed or self.relationships_removed
            or self.relationships_changed
            or any(d.has_loss() for d in self.table_deltas)
        )

    @property
    def has_additions(self) -> bool:
        return bool(
            self.tables_added or self.relationships_added
            or any(d.columns_added or d.measures_added for d in self.table_deltas)
        )

    @property
    def is_clean(self) -> bool:
        """Gate verdict: src is a superset of live with no content regression."""
        return not self.has_content_loss

    def counts(self) -> dict[str, int]:
        """Object-level added / removed / changed tallies across the model."""
        added = len(self.tables_added) + len(self.relationships_added)
        removed = len(self.tables_removed) + len(self.relationships_removed)
        changed = len(self.relationships_changed)
        for d in self.table_deltas:
            added += len(d.columns_added) + len(d.measures_added)
            removed += len(d.columns_removed) + len(d.measures_removed)
            changed += len(d.columns_changed) + len(d.measures_changed) + len(d.partitions_changed)
        return {"added": added, "removed": removed, "changed": changed}


def _diff_bucket(
    baseline: dict[str, str], proposed: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """Return (added, removed, changed) names comparing proposed against baseline."""
    added = sorted(k for k in proposed if k not in baseline)
    removed = sorted(k for k in baseline if k not in proposed)
    changed = sorted(
        k for k in proposed if k in baseline and proposed[k] != baseline[k]
    )
    return added, removed, changed


def diff_models(baseline: SemanticModel, proposed: SemanticModel) -> SemanticDiff:
    """Diff a proposed model (src) against a baseline (live/state).

    Direction matters: ``removed`` = in baseline (live) but not in proposed (src)
    — the content a push would clobber; ``added`` = the operator's new objects.
    """
    base_tables = baseline.content_tables()
    prop_tables = proposed.content_tables()

    diff = SemanticDiff(model=proposed.name or baseline.name)
    diff.tables_added = sorted(n for n in prop_tables if n not in base_tables)
    diff.tables_removed = sorted(n for n in base_tables if n not in prop_tables)

    for name in sorted(set(base_tables) & set(prop_tables)):
        bt, pt = base_tables[name], prop_tables[name]
        delta = TableDelta(name=name)
        delta.columns_added, delta.columns_removed, delta.columns_changed = _diff_bucket(
            bt.columns, pt.columns
        )
        delta.measures_added, delta.measures_removed, delta.measures_changed = _diff_bucket(
            bt.measures, pt.measures
        )
        _, _, delta.partitions_changed = _diff_bucket(bt.partitions, pt.partitions)
        if not delta.is_empty():
            diff.table_deltas.append(delta)

    r_added, r_removed, r_changed = _diff_bucket(
        {f"{f} -> {t}": v for (f, t), v in baseline.relationships.items()},
        {f"{f} -> {t}": v for (f, t), v in proposed.relationships.items()},
    )
    diff.relationships_added = r_added
    diff.relationships_removed = r_removed
    diff.relationships_changed = r_changed
    return diff


def summary_lines(diff: SemanticDiff) -> list[str]:
    """Render a compact, operator-readable summary of a :class:`SemanticDiff`."""
    c = diff.counts()
    lines: list[str] = []
    if diff.is_clean:
        if diff.has_additions:
            lines.append(
                f"CONTENT CLEAN — src ⊇ live: +{c['added']} new object(s), "
                f"0 removed, 0 changed (no clobber; the rest is serialization noise)"
            )
        else:
            lines.append("CONTENT CLEAN — no semantic difference")
    else:
        lines.append(
            f"CONTENT DRIFT — {c['removed']} removed, {c['changed']} changed, "
            f"{c['added']} added (removed/changed would alter live content)"
        )

    def _emit(label: str, names: list[str]) -> None:
        if names:
            shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
            lines.append(f"  {label}: {shown}")

    _emit("tables removed", diff.tables_removed)
    _emit("tables added", diff.tables_added)
    for d in diff.table_deltas:
        _emit(f"[{d.name}] columns removed", d.columns_removed)
        _emit(f"[{d.name}] columns changed", d.columns_changed)
        _emit(f"[{d.name}] columns added", d.columns_added)
        _emit(f"[{d.name}] measures removed", d.measures_removed)
        _emit(f"[{d.name}] measures changed", d.measures_changed)
        _emit(f"[{d.name}] measures added", d.measures_added)
        _emit(f"[{d.name}] partitions changed", d.partitions_changed)
    _emit("relationships removed", diff.relationships_removed)
    _emit("relationships changed", diff.relationships_changed)
    _emit("relationships added", diff.relationships_added)
    return lines
