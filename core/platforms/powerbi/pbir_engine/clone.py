"""Clone an existing PBIR `.Report` folder and retarget bindings.

The empirical pattern Roberto used for years in production: pick a report
that already renders correctly, copy it, swap the data bindings to point at
a different model / table / measure, optionally rename pages and visual
titles, and deploy. More reliable than build-from-scratch because the
template has already validated layout, theme embedding, and rendering
against Fabric — the only thing that changes is data binding.

Three rebinding scopes (composable in one call):

1. **Entity (table) rebind** — every reference to ``Entity: "FactSales"`` becomes
   ``Entity: "FactCategorySpend"``. ``queryRef`` strings are rewritten too.
2. **Property rebind** — every ``Property: "Total Revenue"`` on a given entity
   becomes ``Property: "Total Category Spend"``. Optional, separate from entity
   rebind (you can rename a table without renaming any of its columns).
3. **Model rebind** — ``definition.pbir datasetReference.byConnection`` rewritten
   to point at a new ``model_id`` (and optionally a new workspace_display_name /
   initial_catalog).

Plus cosmetic renames:

- Pages: rename ``displayName`` on selected pages.
- Visual titles: override the ``visualContainerObjects.title.text`` literal.

The function does NOT mutate the source folder. Output goes to a fresh
location specified by the caller.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clone_report_template(
    template_path: str | Path,
    output_path: str | Path,
    rebind_entities: dict[str, str] | None = None,
    rebind_properties: dict[str, dict[str, str]] | None = None,
    new_model_id: str | None = None,
    new_workspace_display_name: str | None = None,
    new_initial_catalog: str | None = None,
    rename_pages: dict[str, str] | None = None,
    rename_visuals: dict[str, str] | None = None,
    new_report_name: str | None = None,
    strip_sidecar: bool = True,
) -> Path:
    """Clone a PBIR ``.Report`` folder and retarget bindings.

    Args:
        template_path: Source ``.Report`` folder (existing, valid PBIR).
        output_path: Destination parent directory. A new folder named
            ``{new_report_name}.Report`` is created inside (or the
            template's original folder name if ``new_report_name`` is None).
        rebind_entities: ``{"OldEntity": "NewEntity", ...}`` — rewrites
            every ``Entity`` field across ``visual.json`` queries and filters,
            and every ``queryRef`` prefix.
        rebind_properties: ``{"EntityName": {"OldProp": "NewProp", ...}, ...}``
            — rewrites ``Property`` fields and ``queryRef`` suffixes. Use the
            **post-rebind** entity name as the outer key when combining with
            ``rebind_entities`` (rebinds are applied entity-first then property).
        new_model_id: GUID of the Fabric semantic model to bind to via
            ``byConnection``. Rewrites ``definition.pbir``.
        new_workspace_display_name: Optional. When provided together with
            ``new_model_id``, the engine emits the full PBI service
            ``connectionString`` form (matches Power BI Desktop emission).
        new_initial_catalog: Optional, defaults to the connection string's
            existing catalog if present.
        rename_pages: ``{"OldDisplayName": "NewDisplayName", ...}`` — page
            display name only (page_id GUIDs are NOT changed; safer for
            external references).
        rename_visuals: ``{"OldTitleText": "NewTitleText", ...}`` — replaces
            the ``visualContainerObjects.title[].properties.text`` literal.
            Match is exact-string on the current title text.
        new_report_name: When provided, overrides the output folder name +
            the ``.platform.metadata.displayName``. The ``logicalId`` is
            always regenerated to avoid collision with the template's
            published item.
        strip_sidecar: When True (default), removes ``.fabric.json`` from
            the cloned folder. The sidecar carries the template's source
            workspace/item provenance, which is misleading for the clone.

    Returns:
        Path to the cloned ``.Report`` folder.
    """
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.is_dir():
        raise FileNotFoundError(f"Template not found: {template_path}")
    if not template_path.name.endswith(".Report"):
        raise ValueError(
            f"Template folder name must end with '.Report': {template_path.name}"
        )

    # Resolve the destination folder name.
    if new_report_name:
        dest_folder_name = f"{new_report_name}.Report"
    else:
        dest_folder_name = template_path.name
    dest_dir = output_path / dest_folder_name

    if dest_dir.exists():
        raise FileExistsError(
            f"Destination already exists: {dest_dir}. Refusing to overwrite."
        )

    # Copy the tree verbatim — we mutate in place after.
    shutil.copytree(template_path, dest_dir)

    if strip_sidecar:
        sidecar = dest_dir / ".fabric.json"
        if sidecar.exists():
            sidecar.unlink()

    # 1) Regenerate logicalId in .platform and apply new displayName if set.
    platform_path = dest_dir / ".platform"
    if platform_path.exists():
        platform = _read_json(platform_path)
        if "config" in platform:
            platform["config"]["logicalId"] = _new_logical_id()
        if new_report_name and "metadata" in platform:
            platform["metadata"]["displayName"] = new_report_name
        _write_json(platform_path, platform)

    # 2) Rewrite definition.pbir for model rebind.
    if new_model_id:
        pbir_path = dest_dir / "definition.pbir"
        if pbir_path.exists():
            pbir = _read_json(pbir_path)
            pbir["datasetReference"] = _build_dataset_reference(
                new_model_id,
                new_workspace_display_name,
                new_initial_catalog,
            )
            _write_json(pbir_path, pbir)

    # 3) Rename pages by display name.
    if rename_pages:
        pages_dir = dest_dir / "definition" / "pages"
        if pages_dir.is_dir():
            for page_dir in pages_dir.iterdir():
                if not page_dir.is_dir():
                    continue
                page_json_path = page_dir / "page.json"
                if not page_json_path.exists():
                    continue
                page = _read_json(page_json_path)
                old_name = page.get("displayName")
                if old_name and old_name in rename_pages:
                    page["displayName"] = rename_pages[old_name]
                    _write_json(page_json_path, page)

    # 4) Rebind entities + properties + rename visual titles across visual.json.
    if rebind_entities or rebind_properties or rename_visuals:
        for visual_json in dest_dir.rglob("visual.json"):
            data = _read_json(visual_json)
            if rebind_entities:
                _rebind_entities_recursive(data, rebind_entities)
                _rebind_query_refs(data, rebind_entities)
            if rebind_properties:
                _rebind_properties_recursive(data, rebind_properties)
                _rebind_query_refs_properties(data, rebind_properties)
            if rename_visuals:
                _rename_visual_title(data, rename_visuals)
            _write_json(visual_json, data)

    return dest_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_logical_id() -> str:
    """Generate a fresh logicalId in 8-4-4-4-12 hex format."""
    parts = [
        uuid.uuid4().hex[:8],
        uuid.uuid4().hex[:4],
        uuid.uuid4().hex[:4],
        uuid.uuid4().hex[:4],
        uuid.uuid4().hex[:12],
    ]
    return "-".join(parts)


def _build_dataset_reference(
    model_id: str,
    workspace_display_name: str | None,
    initial_catalog: str | None,
) -> dict:
    """Build a ``datasetReference`` block for ``definition.pbir``."""
    if workspace_display_name:
        catalog = initial_catalog or "model"
        return {
            "byConnection": {
                "connectionString": (
                    f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/"
                    f"{workspace_display_name};"
                    f"initial catalog={catalog};"
                    f"integrated security=ClaimsToken;"
                    f"semanticmodelid={model_id}"
                )
            }
        }
    return {
        "byConnection": {
            "connectionString": f"semanticModelId={model_id}",
            "pbiServiceModelId": None,
            "pbiModelVirtualServerName": "sobe_wowvirtualserver",
            "pbiModelDatabaseName": None,
            "name": "EntityDataSource",
            "connectionType": "pbiServiceXmlaStyleLive",
        }
    }


def _rebind_entities_recursive(obj: Any, mapping: dict[str, str]) -> None:
    """Walk an object tree and rewrite ``Entity`` field values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "Entity" and isinstance(value, str) and value in mapping:
                obj[key] = mapping[value]
            elif key == "entity" and isinstance(value, str) and value in mapping:
                # Filter config uses lowercase "entity"
                obj[key] = mapping[value]
            else:
                _rebind_entities_recursive(value, mapping)
    elif isinstance(obj, list):
        for item in obj:
            _rebind_entities_recursive(item, mapping)


def _rebind_properties_recursive(
    obj: Any, mapping: dict[str, dict[str, str]]
) -> None:
    """Walk and rewrite ``Property`` values when the enclosing SourceRef
    matches an entity in the mapping.

    Property mapping keys are the **current** entity names (post entity
    rebind, if any). Matching requires walking the parent chain to find
    the SourceRef.Entity sibling.
    """
    _walk_for_property_rebind(obj, mapping, current_entity=None)


def _walk_for_property_rebind(
    obj: Any,
    mapping: dict[str, dict[str, str]],
    current_entity: str | None,
) -> None:
    """Walk recursively, tracking the SourceRef Entity in scope."""
    if isinstance(obj, dict):
        # If this node carries a SourceRef.Entity, capture it for nested walks.
        local_entity = current_entity
        if "Expression" in obj and isinstance(obj["Expression"], dict):
            src = obj["Expression"].get("SourceRef")
            if isinstance(src, dict) and "Entity" in src:
                local_entity = src["Entity"]
        # Filter shape uses lowercase {"expression": {"sourceRef": {"entity":}}}
        elif "expression" in obj and isinstance(obj["expression"], dict):
            src = obj["expression"].get("sourceRef") or obj["expression"].get("SourceRef")
            if isinstance(src, dict):
                ent = src.get("entity") or src.get("Entity")
                if ent:
                    local_entity = ent

        # Apply property rebind if we're in an entity scope and the key is "Property".
        if local_entity and local_entity in mapping:
            ent_map = mapping[local_entity]
            for key in ("Property", "property"):
                if key in obj and isinstance(obj[key], str) and obj[key] in ent_map:
                    obj[key] = ent_map[obj[key]]

        for value in obj.values():
            _walk_for_property_rebind(value, mapping, local_entity)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_property_rebind(item, mapping, current_entity)


def _rebind_query_refs(obj: Any, mapping: dict[str, str]) -> None:
    """Rewrite ``queryRef`` / ``nativeQueryRef`` prefixes (entity portion)."""
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if key in ("queryRef", "nativeQueryRef") and isinstance(value, str):
                # queryRef shapes: "Entity.Property" or "Func(Entity.Property)"
                obj[key] = _rewrite_query_ref_entity(value, mapping)
            else:
                _rebind_query_refs(value, mapping)
    elif isinstance(obj, list):
        for item in obj:
            _rebind_query_refs(item, mapping)


def _rebind_query_refs_properties(
    obj: Any, mapping: dict[str, dict[str, str]]
) -> None:
    """Rewrite the property portion of ``queryRef`` strings when the entity
    matches."""
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if key in ("queryRef", "nativeQueryRef") and isinstance(value, str):
                obj[key] = _rewrite_query_ref_property(value, mapping)
            else:
                _rebind_query_refs_properties(value, mapping)
    elif isinstance(obj, list):
        for item in obj:
            _rebind_query_refs_properties(item, mapping)


def _rewrite_query_ref_entity(qref: str, mapping: dict[str, str]) -> str:
    """Rewrite ``Entity.Prop`` and ``Func(Entity.Prop)`` query refs."""
    for old, new in mapping.items():
        # Function-wrapped form: Sum(Old.Prop), Avg(Old.Prop), etc.
        # Plain form: Old.Prop or Old (entity alone, rare in queryRefs).
        if "(" in qref and ")" in qref:
            head, inner = qref.split("(", 1)
            body, tail = inner.rsplit(")", 1)
            if body.startswith(old + "."):
                body = new + body[len(old):]
                qref = f"{head}({body}){tail}"
        elif qref.startswith(old + "."):
            qref = new + qref[len(old):]
        elif qref == old:
            qref = new
    return qref


def _rewrite_query_ref_property(
    qref: str, mapping: dict[str, dict[str, str]]
) -> str:
    """Rewrite the property portion of an Entity.Prop queryRef.

    Uses the **current** entity (after entity rebind) to look up the
    property map.
    """
    for entity, ent_map in mapping.items():
        # Function-wrapped form.
        if "(" in qref and ")" in qref:
            head, inner = qref.split("(", 1)
            body, tail = inner.rsplit(")", 1)
            if body.startswith(entity + "."):
                prop = body[len(entity) + 1:]
                if prop in ent_map:
                    qref = f"{head}({entity}.{ent_map[prop]}){tail}"
        elif qref.startswith(entity + "."):
            prop = qref[len(entity) + 1:]
            if prop in ent_map:
                qref = f"{entity}.{ent_map[prop]}"
    return qref


def _rename_visual_title(data: dict, rename: dict[str, str]) -> None:
    """Replace ``visualContainerObjects.title[].properties.text`` literal."""
    visual = data.get("visual")
    if not isinstance(visual, dict):
        return
    container = visual.get("visualContainerObjects")
    if not isinstance(container, dict):
        return
    title_block = container.get("title")
    if not isinstance(title_block, list):
        return
    for entry in title_block:
        props = entry.get("properties") if isinstance(entry, dict) else None
        if not isinstance(props, dict):
            continue
        text_node = props.get("text")
        if not isinstance(text_node, dict):
            continue
        literal = (
            text_node.get("expr", {})
            .get("Literal", {})
        )
        current = literal.get("Value", "")
        # PBIR literals are quoted: "'My Title'"
        stripped = current.strip("'")
        if stripped in rename:
            new_value = rename[stripped]
            literal["Value"] = f"'{new_value}'"


def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
