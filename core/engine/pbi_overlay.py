"""Power BI semantic-model overlay transforms for ade-ops.

Ported from the ADE ``deploy/push.py`` ``transform_model_parts`` cascade.

Operates on the assembled file map (``path -> bytes``) produced by
:func:`overlay.assemble_scope`, *before* the files are grouped into Fabric
parts. This is the structural counterpart to the per-file text transforms in
:func:`overlay.apply_overlay_to_content` (catalog remap, generic replaces):
those edit content in place, this one adds/removes whole model objects.

Per-environment overlays may declare, under ``power_bi``:

    tables_excluded:    list[str]
        Tables whose backing Databricks objects are not yet promoted to the
        target environment. Their TMDL files are dropped entirely.
    column_exclusions:  dict[str, list[str]]
        Columns to strip from tables that are kept (column exists in the source
        env but not yet in the target catalog).
    item_renames:       dict[str, str]
        ``Item="old"`` -> ``Item="new"`` rewrites in M expressions.

When a table is excluded the cascade also removes, to keep the model
consistent and deployable:

    - relationships referencing the excluded table,
    - measures (in *kept* tables) whose DAX references the excluded table,
    - perspective entries for the excluded table,
    - linguistic-metadata (cultures) Entity/Relationship entries,
    - ``ref table`` lines + ``PBI_QueryOrder`` entries in ``model.tmdl``,
    - any ``LocalDateTable_``/``DateTableTemplate_`` left orphaned (only
      referenced by now-excluded tables).

Paths are matched on their ``definition/...`` suffix so the logic works
regardless of the ``<name>.SemanticModel/`` folder prefix that ade-ops keeps
relative to ``src/power_bi``.
"""

from __future__ import annotations

import base64  # noqa: F401  (kept for parity with ADE part-format helpers)
import json
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Path matchers — tolerant of the <Model>.SemanticModel/ prefix that ade-ops
# keeps (paths are relative to src/power_bi, e.g.
# "sales.SemanticModel/definition/tables/ft_spend.tmdl").
# ---------------------------------------------------------------------------
def _is_table_file(path: str) -> bool:
    return "definition/tables/" in path and path.endswith(".tmdl")


def _is_relationships(path: str) -> bool:
    return path.endswith("definition/relationships.tmdl")


def _is_model(path: str) -> bool:
    return path.endswith("definition/model.tmdl")


def _is_perspective(path: str) -> bool:
    return "definition/perspectives/" in path and path.endswith(".tmdl")


def _is_culture(path: str) -> bool:
    return "definition/cultures/" in path and path.endswith(".tmdl")


def apply_pbi_model_overlay(
    files: dict[str, bytes], overlay: dict
) -> dict[str, bytes]:
    """Apply semantic-model exclusions/renames to an assembled file map.

    No-op (returns the input unchanged) when the overlay declares no
    ``power_bi`` exclusions or renames, or when the file map contains no
    semantic-model TMDL files.

    Args:
        files: Assembled scope, mapping relative paths to content bytes.
        overlay: Overlay configuration dict.

    Returns:
        A new file map with excluded tables dropped and the dependency
        cascade cleaned. Binary / non-UTF-8 files pass through untouched.
    """
    pbi = overlay.get("power_bi") or {}
    tables_excluded = set(pbi.get("tables_excluded") or [])
    column_exclusions = pbi.get("column_exclusions") or {}
    item_renames = pbi.get("item_renames") or {}

    if not tables_excluded and not column_exclusions and not item_renames:
        return files

    # First pass: read relationships.tmdl to find LocalDateTables that become
    # orphaned once the excluded tables are dropped.
    relationships_content = ""
    for path, blob in files.items():
        if _is_relationships(path):
            try:
                relationships_content = blob.decode("utf-8")
            except UnicodeDecodeError:
                relationships_content = ""
            break

    excluded_local_dates: set[str] = set()
    if relationships_content and tables_excluded:
        excluded_local_dates = _find_orphaned_local_dates(
            relationships_content, tables_excluded
        )

    all_excluded = tables_excluded | excluded_local_dates

    result: dict[str, bytes] = {}
    excluded_tables: set[str] = set()
    excluded_measures_count = 0
    excluded_culture_entries = 0

    for path, blob in sorted(files.items()):
        try:
            content = blob.decode("utf-8")
        except UnicodeDecodeError:
            # Binary file — no text transforms.
            result[path] = blob
            continue

        # Drop excluded table files entirely.
        if _is_table_file(path) and Path(path).stem in all_excluded:
            excluded_tables.add(Path(path).stem)
            continue

        # Item renames (M expression references).
        for old, new in item_renames.items():
            pattern = f'Item="{old}"'
            if pattern in content:
                content = content.replace(pattern, f'Item="{new}"')

        # Column exclusions on kept table files.
        if _is_table_file(path) and Path(path).stem in column_exclusions:
            content, _ = _strip_columns(content, column_exclusions[Path(path).stem])

        # Clean model.tmdl — ref lines + PBI_QueryOrder.
        if _is_model(path) and all_excluded:
            content, _ = _clean_model_refs(content, all_excluded)

        # Clean relationships involving excluded tables.
        if _is_relationships(path) and all_excluded:
            content, _ = _clean_relationships(content, all_excluded)

        # Clean perspective entries for excluded tables.
        if _is_perspective(path) and all_excluded:
            content, _ = _clean_perspective(content, all_excluded)

        # Clean measures (in kept tables) referencing excluded tables.
        if _is_table_file(path) and all_excluded:
            content, count = _clean_measures_referencing_excluded(content, all_excluded)
            excluded_measures_count += count

        # Clean cultures linguistic-metadata entries for excluded tables.
        if _is_culture(path) and all_excluded:
            content, count = _clean_cultures(content, all_excluded)
            excluded_culture_entries += count

        result[path] = content.encode("utf-8")

    if excluded_tables:
        print(
            f"  [PBI OVERLAY] Excluded {len(excluded_tables)} table(s): "
            f"{', '.join(sorted(excluded_tables))}"
        )
    if excluded_local_dates:
        print(
            f"  [PBI OVERLAY] Excluded {len(excluded_local_dates)} orphaned "
            f"date table(s)"
        )
    if excluded_measures_count:
        print(
            f"  [PBI OVERLAY] Removed {excluded_measures_count} measure(s) "
            f"referencing excluded tables"
        )
    if excluded_culture_entries:
        print(
            f"  [PBI OVERLAY] Removed {excluded_culture_entries} linguistic "
            f"metadata entry(ies) for excluded tables"
        )

    return result


# ---------------------------------------------------------------------------
# Cascade helpers (ported 1:1 from ADE deploy/push.py)
# ---------------------------------------------------------------------------
def _find_orphaned_local_dates(
    relationships_content: str, excluded_tables: set
) -> set:
    """Find LocalDateTable_ entries only referenced by excluded tables."""
    local_date_refs: dict[str, set] = {}  # LocalDateTable -> referencing tables
    for match in re.finditer(
        r"relationship\s+(\S+)\s*\n(.*?)(?=\nrelationship\s|\Z)",
        relationships_content,
        re.DOTALL,
    ):
        block = match.group(2)
        tables_in_rel = re.findall(r"(?:fromColumn|toColumn):\s*(\S+)\.", block)
        local_dates = [
            t
            for t in tables_in_rel
            if "LocalDateTable_" in t or "DateTableTemplate_" in t
        ]
        other_tables = [t for t in tables_in_rel if t not in local_dates]
        for ld in local_dates:
            local_date_refs.setdefault(ld, set()).update(other_tables)

    orphaned = set()
    for ld, refs in local_date_refs.items():
        if refs and refs.issubset(excluded_tables):
            orphaned.add(ld)
    return orphaned


def _strip_columns(content: str, columns_to_strip: list) -> tuple[str, int]:
    """Remove column blocks from TMDL content."""
    cols = set(columns_to_strip)
    lines = content.splitlines(keepends=True)
    result = []
    skip = False
    removed = 0

    for line in lines:
        m = re.match(r"^\t(column) ([^\s=]+)", line)
        if m and m.group(2) in cols:
            skip = True
            removed += 1
            continue
        if skip:
            # Reset only when a new top-level block starts (single-tab indent).
            # Empty lines within a column block must NOT reset skip.
            if re.match(
                r"^\t(column|partition|annotation|measure|hierarchy|changedProperty)\s",
                line,
            ):
                skip = False
            else:
                continue
        result.append(line)

    return "".join(result), removed


def _clean_model_refs(content: str, excluded: set) -> tuple[str, int]:
    """Remove 'ref table X' lines AND filter PBI_QueryOrder list in model.tmdl."""
    lines = content.splitlines(keepends=True)
    result = []
    removed = 0
    for line in lines:
        m = re.match(r"\s*ref table (\S+)", line)
        if m and m.group(1) in excluded:
            removed += 1
            continue
        result.append(line)
    new_content = "".join(result)

    # Filter PBI_QueryOrder annotation (cosmetic: table order in Query pane).
    qo_match = re.search(
        r'^(annotation PBI_QueryOrder = )(\[[^\]]*\])', new_content, re.MULTILINE
    )
    if qo_match:
        try:
            tables = json.loads(qo_match.group(2))
            filtered = [t for t in tables if t not in excluded]
            if len(filtered) != len(tables):
                new_list = json.dumps(filtered, separators=(",", ":"))
                new_content = (
                    new_content[: qo_match.start(2)]
                    + new_list
                    + new_content[qo_match.end(2):]
                )
                removed += len(tables) - len(filtered)
        except json.JSONDecodeError:
            pass

    return new_content, removed


def _clean_relationships(content: str, excluded: set) -> tuple[str, int]:
    """Remove relationship blocks involving excluded tables."""
    blocks = re.split(r"(?=^relationship\s)", content, flags=re.MULTILINE)
    result = []
    removed = 0
    for block in blocks:
        tables = re.findall(r"(?:fromColumn|toColumn):\s*(\S+)\.", block)
        if any(t in excluded for t in tables):
            removed += 1
            continue
        result.append(block)
    return "".join(result), removed


def _clean_perspective(content: str, excluded: set) -> tuple[str, int]:
    """Remove perspective table blocks for excluded tables."""
    blocks = re.split(r"(?=\tperspectiveTable\s)", content)
    result = []
    removed = 0
    for block in blocks:
        m = re.match(r"\tperspectiveTable\s+'?(\S+?)'?\s*\n", block)
        table_name = m.group(1) if m else None
        if table_name and table_name in excluded:
            removed += 1
            continue
        result.append(block)
    return "".join(result), removed


def _clean_measures_referencing_excluded(
    content: str, excluded: set
) -> tuple[str, int]:
    """Remove measure blocks whose DAX expression references an excluded table.

    Matches references like ``TABLE[col]`` or ``'TABLE'[col]`` inside the
    expression. Also drops the preceding ``///`` doc-comment line(s), if any,
    to avoid orphans. Only measure blocks are handled; calculated columns
    referencing excluded tables are intentionally not removed here (rare, would
    need a dependent-column cascade).
    """
    if not excluded:
        return content, 0

    refs_re = re.compile(
        "|".join(
            r"(?:'" + re.escape(t) + r"'|\b" + re.escape(t) + r")\["
            for t in excluded
        )
    )

    lines = content.splitlines(keepends=True)
    result = []
    i = 0
    removed = 0

    while i < len(lines):
        line = lines[i]
        if not re.match(r"^\tmeasure\s", line):
            result.append(line)
            i += 1
            continue

        # Collect measure block: current line + continuation until the next
        # top-level block OR a /// doc-comment line (start of the NEXT entity).
        # Stopping at /// is critical: without it the block bleeds into the next
        # measure's doc-string, which may cite an excluded table in prose
        # ("Replaces legacy 'X'[Y]"), erroneously stripping the CURRENT measure.
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if re.match(
                r"^\t(column|partition|annotation|measure|ref|hierarchy|changedProperty)\s",
                nxt,
            ):
                break
            if re.match(r"^\t///", nxt):
                break
            if re.match(r"^[^\t\s]", nxt):
                break
            j += 1

        block_text = "".join(lines[i:j])
        if refs_re.search(block_text):
            # Drop preceding /// doc-comment line(s) to avoid orphan comments.
            while result and re.match(r"^\t///", result[-1]):
                result.pop()
            removed += 1
            i = j
            continue

        result.extend(lines[i:j])
        i = j

    return "".join(result), removed


def _clean_cultures(content: str, excluded: set) -> tuple[str, int]:
    """Remove linguistic-metadata Entity/Relationship entries for excluded tables.

    The cultures TMDL embeds a JSON blob after ``linguisticMetadata =`` indented
    with 3 tabs. Entries whose ``ConceptualEntity`` is an excluded table are
    dropped via parse -> filter -> re-serialize with the same indentation.
    """
    if not excluded:
        return content, 0

    # Work on LF internally; Fabric normalizes line endings on receive.
    content_lf = content.replace("\r\n", "\n")
    lines = content_lf.splitlines(keepends=True)

    # Locate JSON block: line after 'linguisticMetadata =' up to 'contentType'.
    start_idx = None
    end_idx = None
    for idx, ln in enumerate(lines):
        if start_idx is None and re.match(r"^\t+linguisticMetadata\s*=", ln):
            start_idx = idx + 1
        elif start_idx is not None and re.match(r"^\t+contentType\b", ln):
            end_idx = idx
            break

    if start_idx is None or end_idx is None:
        return content, 0

    INDENT = "\t\t\t"
    json_lines = []
    for ln in lines[start_idx:end_idx]:
        json_lines.append(ln[len(INDENT):] if ln.startswith(INDENT) else ln)
    json_text = "".join(json_lines)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  [WARN] cultures JSON parse failed, skipping: {e}")
        return content, 0

    # Filter Entities: Binding is nested under Definition.
    entities = data.get("Entities", {})
    entity_keys_to_remove = [
        k
        for k, v in entities.items()
        if isinstance(v, dict)
        and v.get("Definition", {}).get("Binding", {}).get("ConceptualEntity")
        in excluded
    ]
    for k in entity_keys_to_remove:
        del entities[k]

    # Filter Relationships: Binding is at the top level of each entry.
    relationships = data.get("Relationships", {})
    rel_keys_to_remove = [
        k
        for k, v in relationships.items()
        if isinstance(v, dict)
        and v.get("Binding", {}).get("ConceptualEntity") in excluded
    ]
    for k in rel_keys_to_remove:
        del relationships[k]

    total_removed = len(entity_keys_to_remove) + len(rel_keys_to_remove)
    if total_removed == 0:
        return content, 0

    new_json = json.dumps(data, indent=2)
    new_json_indented = "".join(INDENT + ln + "\n" for ln in new_json.splitlines())

    new_content = (
        "".join(lines[:start_idx]) + new_json_indented + "".join(lines[end_idx:])
    )
    return new_content, total_removed
