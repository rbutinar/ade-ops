"""PBIR Visual generators (MVP subset).

Ogni funzione ritorna un dict completo per ``visual.json``.
PBIR schema 2.4.0+.

Subset MVP 2026-05-24: card, cardVisual, bar_chart (anche column / clustered),
table, textbox. Skip rispetto a ADE: donut/pie, line, pivot, slicer, treemap
— aggiungere on-demand quando emerge use case reale.

Gotchas embedded (`core/playbooks/pbir-gotchas.md`):

- **#1** container styling (title, background, border) sotto
  ``visualContainerObjects`` (NOT ``objects``).
- **#2** background transparency ``0D`` di default → opaque. ADE pbir_engine
  usava ``transparency=10`` causando pastel rendering — fix qui.
- **#3** ``title.text`` come property di ``visualContainerObjects.title`` per
  forzare il testo (altrimenti Fabric auto-genera ``<Measure> by <Category>``).
"""
from __future__ import annotations

import uuid

from .fields import _build_field_expr, _build_projection

SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/"
    "definition/visualContainer/2.8.0/schema.json"
)


def _visual_id() -> str:
    """Generate a 20-char hex ID like Power BI does."""
    return uuid.uuid4().hex[:20]


def _filter_guid() -> str:
    """Generate a filter GUID (Filter + hex)."""
    return f"Filter{uuid.uuid4().hex[:24]}"


def _build_filter_config(fields: list[dict]) -> dict:
    """Build filterConfig for a visual based on its bound fields."""
    filters = []
    for field_def in fields:
        f = {
            "name": _filter_guid(),
            "field": _build_field_expr(field_def),
        }
        if field_def["_type"] in ("measure", "aggregation"):
            f["type"] = "Advanced"
        else:
            f["type"] = "Categorical"
        filters.append(f)
    return {"filters": filters}


def _literal(value) -> dict:
    """Wrap a value in PBIR Literal expression.

    Numeric formatting follows ADE convention (``42L`` for ints, ``3.14D`` for
    floats) but normalises whole-number floats to integer form for the ``D``
    suffix: ``0.0`` → ``0D`` (not ``0.0D``). Matches the form documented in
    ``core/playbooks/pbir-gotchas.md`` gotcha #2 example.
    """
    if isinstance(value, bool):
        return {"expr": {"Literal": {"Value": "true" if value else "false"}}}
    if isinstance(value, int):
        return {"expr": {"Literal": {"Value": f"{value}L"}}}
    if isinstance(value, float):
        if value == int(value):
            return {"expr": {"Literal": {"Value": f"{int(value)}D"}}}
        return {"expr": {"Literal": {"Value": f"{value}D"}}}
    if isinstance(value, str):
        return {"expr": {"Literal": {"Value": f"'{value}'"}}}
    return {"expr": {"Literal": {"Value": str(value)}}}


def _solid_color(hex_color: str) -> dict:
    """Build a solid color expression."""
    return {"solid": {"color": _literal(hex_color)}}


def _position(
    x: float,
    y: float,
    width: float,
    height: float,
    z: int = 0,
    tab_order: int = 0,
) -> dict:
    return {
        "x": x,
        "y": y,
        "z": z,
        "height": height,
        "width": width,
        "tabOrder": tab_order,
    }


def _title_object(
    text: str,
    show: bool = True,
    font_size: int = 12,
    font_color: str | None = None,
    bold: bool = False,
) -> list:
    """Build visualContainerObjects.title (gotcha #3 — text under container)."""
    props = {
        "text": _literal(text),
        "show": _literal(show),
    }
    if font_size != 12:
        props["fontSize"] = _literal(float(font_size))
    if font_color:
        props["fontColor"] = _solid_color(font_color)
    if bold:
        props["bold"] = _literal(True)
    return [{"properties": props}]


def _border_object(
    show: bool = True, color: str = "#EDEDED", radius: int = 10
) -> list:
    props: dict = {"show": _literal(show)}
    if color:
        props["color"] = _solid_color(color)
    if radius:
        props["radius"] = _literal(float(radius))
    return [{"properties": props}]


def _background_object(
    show: bool = True,
    color: str | None = None,
    transparency: float = 0.0,
) -> list:
    """Build visualContainerObjects.background.

    **Gotcha #2 fix**: default ``transparency=0`` (fully opaque). ALWAYS
    emette la proprieta' esplicitamente, anche per ``0``, perche' senza
    valore esplicito Fabric applica un default non-zero e renderizza
    pastel. ADE pbir_engine NON faceva questo (skippava emission quando
    valore ``<= 0``) → bug riprodotto da `ddf-operator` 2026-05-23.
    """
    props: dict = {"show": _literal(show)}
    if color:
        props["color"] = _solid_color(color)
    props["transparency"] = _literal(float(transparency))
    return [{"properties": props}]


def _sort_definition(field_def: dict, direction: str = "Descending") -> dict:
    return {
        "sort": [
            {
                "field": _build_field_expr(field_def),
                "direction": direction,
            }
        ],
        "isDefaultSort": True,
    }


def _default_container_objects(
    title: str | None = None,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
) -> dict:
    """Standard visualContainerObjects (gotcha #1 — container styling slot).

    Background defaults to opaque (gotcha #2 fix). If ``background_color`` is
    not provided, white-ish default applies via Fabric theme. Setting
    ``transparency=0`` ensures the chosen color renders crisp.
    """
    obj: dict = {}
    if title:
        obj["title"] = _title_object(title, font_color=title_color, bold=True)
    if border:
        obj["border"] = _border_object()
    obj["background"] = _background_object(
        show=True, color=background_color, transparency=0.0
    )
    if shadow:
        obj["dropShadow"] = [
            {"properties": {"show": _literal(True), "preset": _literal("Bottom")}}
        ]
    return obj


# ---------------------------------------------------------------------------
# CARD (legacy KPI card)
# ---------------------------------------------------------------------------
def card(
    title: str,
    value_field: dict,
    x: float = 0,
    y: float = 0,
    width: float = 150,
    height: float = 80,
    z: int = 0,
    tab_order: int = 0,
    font_size: int = 15,
    precision: int = 2,
    display_units: int | str = 0,
    show_category: bool = False,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
) -> dict:
    """Generate a card (single KPI) visual.

    ``display_units`` accepts an int (``0`` auto / ``1000`` K / ``1000000`` M /
    ``1000000000`` B) or the same value as a string. ddf-operator F2 fix
    (2026-05-24): the previous default emitted a STRING literal ``'1000'``
    which Power BI ignored — the "Display units = Thousands" selector had
    no effect. Cast to int so ``_literal`` emits ``1000L`` (numeric form).
    """
    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "card",
            "query": {
                "queryState": {
                    "Values": {"projections": [_build_projection(value_field)]}
                },
                "sortDefinition": _sort_definition(value_field),
            },
            "objects": {
                "labels": [
                    {
                        "properties": {
                            "labelDisplayUnits": _literal(int(display_units)),
                            "fontSize": _literal(float(font_size)),
                            "bold": _literal(True),
                            "labelPrecision": _literal(precision),
                        }
                    }
                ],
                "categoryLabels": [
                    {"properties": {"show": _literal(show_category)}}
                ],
            },
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config([value_field]),
    }


# ---------------------------------------------------------------------------
# CARD VISUAL (new-style KPI card)
# ---------------------------------------------------------------------------
def card_visual(
    title: str,
    value_field: dict,
    x: float = 0,
    y: float = 0,
    width: float = 180,
    height: float = 100,
    z: int = 0,
    tab_order: int = 0,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    show_container_title: bool | None = None,
) -> dict:
    """Generate a cardVisual (modern KPI card).

    ``show_container_title`` (ddf-operator F1 fix, 2026-05-24):
    ``cardVisual`` carries an internal text label derived from the measure
    name, so emitting a container header on top of it produces visible
    duplication. Default behaviour: when the container title text equals
    the measure ``Property``, the container title is suppressed; the
    visual still gets ``visualContainerObjects.title.show: False`` so
    other container styling (background, border) survives.

    Pass ``show_container_title=True`` to force the header back on (e.g.
    when the title differs from the measure name and you want both).
    Pass ``False`` to always suppress.
    """
    if show_container_title is None:
        measure_name = value_field.get("property") or ""
        show_container_title = title.strip() != measure_name.strip()

    container_objects = _default_container_objects(
        title=title if show_container_title else None,
        title_color=title_color,
        background_color=background_color,
        border=border,
        shadow=shadow,
    )
    # If suppressing, still ensure title.show = False is emitted so any
    # inherited theme title styling doesn't sneak back in.
    if not show_container_title:
        container_objects["title"] = [{"properties": {
            "show": _literal(False),
        }}]

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "cardVisual",
            "query": {
                "queryState": {
                    "Data": {"projections": [_build_projection(value_field)]}
                }
            },
            "visualContainerObjects": container_objects,
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config([value_field]),
    }


# ---------------------------------------------------------------------------
# BAR / COLUMN CHART
# ---------------------------------------------------------------------------
def bar_chart(
    title: str,
    category_field: dict,
    value_fields: list[dict],
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    horizontal: bool = False,
    clustered: bool = False,
    show_legend: bool = True,
    show_labels: bool = False,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    data_point_color: str | None = None,
) -> dict:
    """Generate a bar / column chart visual.

    Args:
        horizontal: ``True`` for ``barChart``, ``False`` for ``columnChart``.
        clustered: ``True`` for the clustered variant.
        data_point_color: hex (e.g. ``"#5B9BD5"``) for default data point
            color override. Sets ``objects.dataPoint[].properties.defaultColor``.
            Use to brand a chart against the report theme accent.
    """
    if horizontal:
        vtype = "clusteredBarChart" if clustered else "barChart"
    else:
        vtype = "clusteredColumnChart" if clustered else "columnChart"

    query_state = {
        "Category": {"projections": [_build_projection(category_field, active=True)]},
        "Y": {"projections": [_build_projection(f) for f in value_fields]},
    }

    objects: dict = {}
    if not show_legend:
        objects["legend"] = [{"properties": {"show": _literal(False)}}]
    if show_labels:
        objects["labels"] = [{"properties": {"show": _literal(True)}}]
    if data_point_color:
        objects["dataPoint"] = [{"properties": {"defaultColor": _solid_color(data_point_color)}}]

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": vtype,
            "query": {
                "queryState": query_state,
                "sortDefinition": _sort_definition(value_fields[0]),
            },
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config([category_field] + value_fields),
    }


# ---------------------------------------------------------------------------
# TABLE
# ---------------------------------------------------------------------------
def table(
    title: str,
    fields: list[dict],
    x: float = 0,
    y: float = 0,
    width: float = 600,
    height: float = 400,
    z: int = 0,
    tab_order: int = 0,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
) -> dict:
    """Generate a table (``tableEx``) visual."""
    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "tableEx",
            "query": {
                "queryState": {
                    "Values": {
                        "projections": [_build_projection(f) for f in fields]
                    }
                }
            },
            "objects": {
                "grid": [{"properties": {"gridVertical": _literal(True)}}]
            },
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config(fields),
    }


# ---------------------------------------------------------------------------
# BANNER / HEADER TEXTBOX (styled textbox with container background)
# ---------------------------------------------------------------------------
def banner(
    title_text: str,
    subtitle_text: str | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 1280,
    height: float = 84,
    z: int = 0,
    tab_order: int = 0,
    background_color: str = "#1F4E79",
    title_color: str = "#FFFFFF",
    subtitle_color: str = "#D9E2EE",
    title_size_pt: int = 22,
    subtitle_size_pt: int = 11,
    leading_space: bool = True,
) -> dict:
    """Generate a banner / header textbox with a coloured container background.

    Two-paragraph structure: large bold title + smaller subtitle (optional).
    Container background uses the gotcha #2 fix (``transparency: 0D`` explicit).
    Pattern matches the AcmeSales sample header (legacy ``qsXXtitle`` style).
    """
    leading = " " if leading_space else ""
    paragraphs = [
        {
            "textRuns": [{
                "value": f"{leading}{title_text}",
                "textStyle": {
                    "fontSize": f"{title_size_pt}pt",
                    "fontWeight": "bold",
                    "color": title_color,
                },
            }],
        },
    ]
    if subtitle_text:
        paragraphs.append({
            "textRuns": [{
                "value": f"{leading}{subtitle_text}",
                "textStyle": {
                    "fontSize": f"{subtitle_size_pt}pt",
                    "color": subtitle_color,
                },
            }],
        })

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [{"properties": {"paragraphs": paragraphs}}]
            },
            "visualContainerObjects": {
                "background": [{"properties": {
                    "show": _literal(True),
                    "color": _solid_color(background_color),
                    "transparency": _literal(0.0),
                }}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


# ---------------------------------------------------------------------------
# TEXTBOX
# ---------------------------------------------------------------------------
def textbox(
    text: str,
    x: float = 0,
    y: float = 0,
    width: float = 300,
    height: float = 50,
    z: int = 0,
    tab_order: int = 0,
    font_size: int = 14,
    bold: bool = False,
    font_color: str = "#000000",
) -> dict:
    """Generate a textbox visual.

    Textbox uses a paragraphs structure rather than a data query.
    """
    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "paragraphs": [
                                {
                                    "textRuns": [
                                        {
                                            "value": text,
                                            "textStyle": {
                                                "fontFamily": (
                                                    "wf_standard-font, helvetica, arial, sans-serif"
                                                ),
                                                "fontSize": f"{font_size}px",
                                                "fontWeight": "bold" if bold else "normal",
                                                "color": font_color,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            },
            "visualContainerObjects": {},
        },
    }
