"""Append a new page to an existing PBIR ``.Report`` folder in-place.

Two modes (MVP — interactive mode deferred to backlog):

1. **Spec build** — visuals come from a YAML page spec (sub-shape of the
   ``ReportBuilder.from_spec`` page section). Build via ``PageBuilder``.
2. **Clone from existing page** — copy ``page.json`` + ``visuals/*`` subtree
   of a source page (by ``displayName``), regenerate the page_id and all
   visual_ids (anti-collision), rename the new page.

In both cases:

- The new page_id is appended to ``pages.json:pageOrder`` (or inserted at
  a caller-specified index).
- ``activePageName`` is preserved by default; ``set_active=True`` switches
  it to the new page.

Out of scope for this MVP (separate skills / backlog):

- Interactive prompt loop (skill body responsibility, not engine).
- Field rebinding when cloning (overlap with ``clone.py``; if requested,
  use ``rebind_entities`` / ``rebind_properties`` on a per-page basis —
  not implemented here, file a focused need).
- Deleting pages (``/pbir-remove-page`` future skill).
- Re-ordering existing pages (``/pbir-reorder-pages`` future skill).
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from . import visuals as V
from .builder import (
    PageBuilder,
    _add_visual_from_spec,
    _write_json,
)


def _new_page_id() -> str:
    return uuid.uuid4().hex[:20]


def _new_visual_id() -> str:
    return uuid.uuid4().hex[:20]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_page_by_name(pages_dir: Path, display_name: str) -> Path | None:
    """Return the page folder whose page.json displayName matches, or None."""
    for page_dir in pages_dir.iterdir():
        if not page_dir.is_dir():
            continue
        page_json = page_dir / "page.json"
        if not page_json.exists():
            continue
        try:
            data = _read_json(page_json)
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("displayName") == display_name:
            return page_dir
    return None


def _read_pages_metadata(pages_dir: Path) -> dict:
    pages_json = pages_dir / "pages.json"
    if not pages_json.exists():
        raise FileNotFoundError(
            f"pages.json missing under {pages_dir}; not a valid PBIR pages directory."
        )
    return _read_json(pages_json)


def _build_page_from_spec(page_spec: dict) -> PageBuilder:
    """Construct a PageBuilder from a YAML page spec dict.

    Accepts the same per-page shape as ``ReportBuilder.from_spec`` pages:

        name: "Page Name"
        background_color: "#FAFAFA"          # optional
        visuals:
          - type: card
            title: "..."
            value: { entity: ..., property: ..., _type: measure }
            position: { x: ..., y: ..., width: ..., height: ... }
          ...
    """
    if "name" not in page_spec:
        raise ValueError("page spec missing required 'name' field")
    page = PageBuilder(
        display_name=page_spec["name"],
        background_color=page_spec.get("background_color"),
    )
    for v_spec in page_spec.get("visuals", []):
        _add_visual_from_spec(page, v_spec)
    return page


def _clone_page_folder(
    source_page_dir: Path,
    target_page_dir: Path,
    new_page_id: str,
    new_display_name: str,
) -> None:
    """Copy a page folder, renaming and regenerating GUIDs.

    Rewrites:
    - ``page.json``: ``name`` -> new_page_id, ``displayName`` -> new_display_name
    - ``visuals/{old_id}/visual.json``: ``name`` field if present, folder rename
    """
    if target_page_dir.exists():
        raise FileExistsError(
            f"target page dir already exists: {target_page_dir}. Refusing to overwrite."
        )

    target_page_dir.mkdir(parents=True)

    source_page_json = _read_json(source_page_dir / "page.json")
    source_page_json["name"] = new_page_id
    source_page_json["displayName"] = new_display_name
    _write_json(target_page_dir / "page.json", source_page_json)

    source_visuals = source_page_dir / "visuals"
    if source_visuals.exists() and source_visuals.is_dir():
        target_visuals = target_page_dir / "visuals"
        target_visuals.mkdir()
        for visual_dir in source_visuals.iterdir():
            if not visual_dir.is_dir():
                continue
            visual_json_path = visual_dir / "visual.json"
            if not visual_json_path.exists():
                continue
            visual_data = _read_json(visual_json_path)
            new_visual_id = _new_visual_id()
            if "name" in visual_data:
                visual_data["name"] = new_visual_id
            new_visual_dir = target_visuals / new_visual_id
            new_visual_dir.mkdir()
            _write_json(new_visual_dir / "visual.json", visual_data)


def add_page_to_report(
    report_path: str | Path,
    page_name: str,
    page_spec: dict | None = None,
    clone_from_page: str | None = None,
    insert_at: int | None = None,
    set_active: bool = False,
) -> str:
    """Append (or insert) a new page to an existing ``.Report`` folder.

    Exactly one of ``page_spec`` or ``clone_from_page`` must be provided.

    Args:
        report_path: Existing ``.Report`` folder (must contain
            ``definition/pages/pages.json``).
        page_name: ``displayName`` of the new page. Must not collide with
            any existing page's displayName (raises ``ValueError``).
        page_spec: YAML-derived spec dict for the new page (see
            ``_build_page_from_spec`` for shape). Mutually exclusive with
            ``clone_from_page``.
        clone_from_page: ``displayName`` of an existing page to clone. The
            clone gets fresh GUIDs for page_id and every visual_id.
            Mutually exclusive with ``page_spec``.
        insert_at: 0-based index in ``pageOrder`` to insert the new page.
            ``None`` (default) appends at the end. Negative indices follow
            Python list semantics.
        set_active: If True, switches ``activePageName`` to the new page.
            Default False (preserve current active page).

    Returns:
        The new page_id (20-char hex).

    Raises:
        FileNotFoundError: If ``report_path`` or its ``definition/pages/``
            structure is missing.
        ValueError: If neither or both of ``page_spec`` / ``clone_from_page``
            are provided, or if ``page_name`` collides with an existing page.
        FileNotFoundError: If ``clone_from_page`` is provided but no page
            with that displayName exists.
    """
    if (page_spec is None) == (clone_from_page is None):
        raise ValueError(
            "Exactly one of 'page_spec' or 'clone_from_page' must be provided."
        )

    report_path = Path(report_path)
    pages_dir = report_path / "definition" / "pages"
    if not pages_dir.exists():
        raise FileNotFoundError(
            f"pages directory missing under {report_path}; not a valid PBIR report folder."
        )

    if _find_page_by_name(pages_dir, page_name) is not None:
        raise ValueError(
            f"a page named {page_name!r} already exists in {report_path.name}. "
            "Pick a unique displayName."
        )

    new_page_id = _new_page_id()
    new_page_dir = pages_dir / new_page_id

    if clone_from_page is not None:
        source_page_dir = _find_page_by_name(pages_dir, clone_from_page)
        if source_page_dir is None:
            raise FileNotFoundError(
                f"source page named {clone_from_page!r} not found in {report_path.name}."
            )
        _clone_page_folder(source_page_dir, new_page_dir, new_page_id, page_name)
    else:
        page = _build_page_from_spec({**page_spec, "name": page_name})
        page.page_id = new_page_id
        new_page_dir.mkdir()
        _write_json(new_page_dir / "page.json", page.page_json())
        if page.visuals:
            visuals_dir = new_page_dir / "visuals"
            visuals_dir.mkdir()
            for visual in page.visuals:
                visual_id = visual.get("name") or _new_visual_id()
                visual["name"] = visual_id
                visual_dir = visuals_dir / visual_id
                visual_dir.mkdir()
                _write_json(visual_dir / "visual.json", visual)

    metadata = _read_pages_metadata(pages_dir)
    page_order: list[str] = metadata.get("pageOrder", [])
    if insert_at is None:
        page_order.append(new_page_id)
    else:
        page_order.insert(insert_at, new_page_id)
    metadata["pageOrder"] = page_order
    if set_active or not metadata.get("activePageName"):
        metadata["activePageName"] = new_page_id
    _write_json(pages_dir / "pages.json", metadata)

    return new_page_id


def add_page_from_spec_file(
    report_path: str | Path,
    spec_path: str | Path,
    insert_at: int | None = None,
    set_active: bool = False,
) -> str:
    """Convenience wrapper: load a page spec from YAML and add it.

    Spec file shape::

        page:
          name: "New Page Name"
          background_color: "#FAFAFA"
          visuals:
            - type: card
              title: "..."
              value: { entity: ..., property: ..., _type: measure }
              position: { x: 10, y: 110, width: 300, height: 80 }
            ...
    """
    import yaml

    spec_path = Path(spec_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    page_spec = spec.get("page")
    if not isinstance(page_spec, dict):
        raise ValueError(
            f"{spec_path} must contain a top-level 'page:' dict; got {type(page_spec).__name__}."
        )
    page_name = page_spec.get("name")
    if not page_name:
        raise ValueError(f"{spec_path} 'page:' block missing required 'name' field.")
    return add_page_to_report(
        report_path,
        page_name=page_name,
        page_spec=page_spec,
        insert_at=insert_at,
        set_active=set_active,
    )
