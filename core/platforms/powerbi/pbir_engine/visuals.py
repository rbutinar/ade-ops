"""PBIR Visual generators (MVP subset).

Ogni funzione ritorna un dict completo per ``visual.json``.
PBIR schema 2.4.0+.

Subset MVP 2026-05-24: card, cardVisual, bar_chart (anche column / clustered),
table, textbox.
Extended 2026-07-09 (AcmeSales command-center use case): line/area chart,
combo chart (column + line on Y2, gotcha #8), donut, treemap, scatter,
slicer, matrix (pivotTable), nav_button (actionButton page navigation),
insight_panel. Still out: gauge, KPI, ribbon, decomposition tree.

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
    border_color: str = "#EDEDED",
    border_radius: int = 10,
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
        obj["border"] = _border_object(color=border_color, radius=border_radius)
    obj["background"] = _background_object(
        show=True, color=background_color, transparency=0.0
    )
    if shadow:
        obj["dropShadow"] = [
            {"properties": {"show": _literal(True), "preset": _literal("Bottom")}}
        ]
    return obj


def _not_blank_filter(field_def: dict) -> dict:
    """Build a filter-pane entry excluding blank values of a column.

    Standard "not in (blank)" Categorical filter (Version 2 semantic-query
    shape). Used to hide unmapped dimension members (e.g. fact rows whose
    key has no match in the dimension) from category-style visuals.
    """
    alias = field_def["entity"][:1].lower()
    return {
        "name": _filter_guid(),
        "field": _build_field_expr(field_def),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": alias, "Entity": field_def["entity"], "Type": 0}],
            "Where": [
                {
                    "Condition": {
                        "Not": {
                            "Expression": {
                                "In": {
                                    "Expressions": [
                                        {
                                            "Column": {
                                                "Expression": {
                                                    "SourceRef": {"Source": alias}
                                                },
                                                "Property": field_def["property"],
                                            }
                                        }
                                    ],
                                    "Values": [[{"Literal": {"Value": "null"}}]],
                                }
                            }
                        }
                    }
                }
            ],
        },
    }


def _filter_config_with_not_blank(
    plain_fields: list[dict],
    not_blank_field: dict | None,
) -> dict:
    """filterConfig where ``not_blank_field`` carries a not-blank condition.

    The conditioned field replaces its plain filter-pane entry (a duplicate
    entry for the same field would shadow the condition).
    """
    config = _build_filter_config(plain_fields)
    if not_blank_field is not None:
        config["filters"].insert(0, _not_blank_filter(not_blank_field))
    return config


def _axis_objects(
    objects: dict,
    axis_color: str | None,
    gridline_color: str | None,
) -> None:
    """Emit categoryAxis / valueAxis label + gridline colors (dark themes).

    Axis titles are switched off whenever explicit axis styling is used —
    modern base themes (CY25+) show them by default and the raw field names
    (``sale_date``) add noise a curated layout doesn't want.
    """
    if not axis_color and not gridline_color:
        return
    cat_props: dict = {"showAxisTitle": _literal(False)}
    val_props: dict = {"showAxisTitle": _literal(False)}
    if axis_color:
        cat_props["labelColor"] = _solid_color(axis_color)
        val_props["labelColor"] = _solid_color(axis_color)
    if gridline_color:
        val_props["gridlineColor"] = _solid_color(gridline_color)
    objects["categoryAxis"] = [{"properties": cat_props}]
    objects["valueAxis"] = [{"properties": val_props}]


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
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    value_color: str | None = None,
) -> dict:
    """Generate a card (single KPI) visual.

    ``display_units`` accepts an int (``0`` auto / ``1000`` K / ``1000000`` M /
    ``1000000000`` B) or the same value as a string. ddf-operator F2 fix
    (2026-05-24): the previous default emitted a STRING literal ``'1000'``
    which Power BI ignored — the "Display units = Thousands" selector had
    no effect. Cast to int so ``_literal`` emits ``1000L`` (numeric form).
    """
    label_props = {
        "labelDisplayUnits": _literal(int(display_units)),
        "fontSize": _literal(float(font_size)),
        "bold": _literal(True),
        "labelPrecision": _literal(precision),
    }
    if value_color:
        label_props["color"] = _solid_color(value_color)
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
                "labels": [{"properties": label_props}],
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
                border_color=border_color,
                border_radius=border_radius,
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
    border_color: str = "#EDEDED",
    border_radius: int = 10,
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
        border_color=border_color,
        border_radius=border_radius,
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
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    axis_color: str | None = None,
    gridline_color: str | None = None,
    label_color: str | None = None,
    exclude_blank: bool = False,
) -> dict:
    """Generate a bar / column chart visual.

    Args:
        horizontal: ``True`` for ``barChart``, ``False`` for ``columnChart``.
        clustered: ``True`` for the clustered variant.
        data_point_color: hex (e.g. ``"#5B9BD5"``) for default data point
            color override. Sets ``objects.dataPoint[].properties.defaultColor``.
            Use to brand a chart against the report theme accent.
        axis_color / gridline_color: axis label + gridline overrides for
            dark layouts where the theme defaults are unreadable.
        exclude_blank: filter out blank category members (unmapped keys).
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
        label_props: dict = {"show": _literal(True)}
        if label_color:
            label_props["color"] = _solid_color(label_color)
        objects["labels"] = [{"properties": label_props}]
    if data_point_color:
        objects["dataPoint"] = [{"properties": {"defaultColor": _solid_color(data_point_color)}}]
    _axis_objects(objects, axis_color, gridline_color)

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
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _filter_config_with_not_blank(
            value_fields if exclude_blank else [category_field] + value_fields,
            category_field if exclude_blank else None,
        ),
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
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    sort_field: dict | None = None,
    heat_field: dict | None = None,
    heat_color: str = "#118DFF",
    heat_base: str | None = None,
    header_background: str | None = None,
    header_color: str | None = None,
    row_background: str | None = None,
    row_alt_background: str | None = None,
    row_color: str | None = None,
    grid_color: str | None = None,
) -> dict:
    """Generate a table (``tableEx``) visual.

    Args:
        sort_field: optional field to sort by (descending) instead of the
            default first-column order.
        heat_field: optional measure to shade with a background color scale
            (conditional formatting ``FillRule`` on that column).
        heat_color / heat_base: gradient endpoints for the heat scale.
            ``heat_base`` defaults to ``background_color`` (or white).
        header_background / header_color / row_background /
        row_alt_background / row_color / grid_color: explicit grid styling
            (dark layouts) — theme-independent, emitted per-visual.
    """
    query: dict = {
        "queryState": {
            "Values": {"projections": [_build_projection(f) for f in fields]}
        }
    }
    if sort_field is not None:
        query["sortDefinition"] = _sort_definition(sort_field)

    grid_props: dict = {"gridVertical": _literal(True)}
    if grid_color:
        grid_props["gridVerticalColor"] = _solid_color(grid_color)
        grid_props["gridHorizontalColor"] = _solid_color(grid_color)
    objects: dict = {"grid": [{"properties": grid_props}]}
    if header_background or header_color:
        header_props: dict = {}
        if header_background:
            header_props["backColor"] = _solid_color(header_background)
        if header_color:
            header_props["fontColor"] = _solid_color(header_color)
            header_props["bold"] = _literal(True)
        objects["columnHeaders"] = [{"properties": header_props}]
    if row_background or row_color:
        values_props: dict = {}
        if row_background:
            values_props["backColor"] = _solid_color(row_background)
            values_props["backColorSecondary"] = _solid_color(
                row_alt_background or row_background
            )
        if row_color:
            values_props["fontColorPrimary"] = _solid_color(row_color)
            values_props["fontColorSecondary"] = _solid_color(row_color)
        objects["values"] = [{"properties": values_props}]
    if heat_field is not None:
        from .fields import _build_query_ref

        base = heat_base or background_color or "#FFFFFF"
        objects.setdefault("values", []).append(
            {
                "selector": {"metadata": _build_query_ref(heat_field)},
                "properties": {
                    "backColor": {
                        "expr": {
                            "FillRule": {
                                "Input": _build_field_expr(heat_field),
                                "FillRule": {
                                    "linearGradient2": {
                                        "min": {
                                            "color": {
                                                "expr": {"Literal": {"Value": f"'{base}'"}}
                                            }
                                        },
                                        "max": {
                                            "color": {
                                                "expr": {"Literal": {"Value": f"'{heat_color}'"}}
                                            }
                                        },
                                    }
                                },
                            }
                        }
                    }
                },
            }
        )

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "tableEx",
            "query": query,
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
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


# ---------------------------------------------------------------------------
# LINE / AREA CHART
# ---------------------------------------------------------------------------
def line_chart(
    title: str,
    category_field: dict,
    value_fields: list[dict],
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    area: bool = False,
    stacked: bool = False,
    series_field: dict | None = None,
    stroke_width: int = 3,
    show_markers: bool = False,
    show_legend: bool | None = None,
    show_labels: bool = False,
    label_color: str | None = None,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    axis_color: str | None = None,
    gridline_color: str | None = None,
    data_point_color: str | None = None,
    sort_ascending_by_category: bool = True,
) -> dict:
    """Generate a line / area chart visual.

    Args:
        area: ``True`` renders ``areaChart`` (``stackedAreaChart`` when
            ``stacked`` is also set); default is ``lineChart``.
        series_field: optional legend/series split column.
        sort_ascending_by_category: time-series default — sort by the axis
            field ascending instead of by value descending.
    """
    if area:
        vtype = "stackedAreaChart" if stacked else "areaChart"
    else:
        vtype = "lineChart"

    query_state: dict = {
        "Category": {"projections": [_build_projection(category_field, active=True)]},
        "Y": {"projections": [_build_projection(f) for f in value_fields]},
    }
    if series_field is not None:
        query_state["Series"] = {"projections": [_build_projection(series_field)]}

    if show_legend is None:
        show_legend = series_field is not None or len(value_fields) > 1

    objects: dict = {
        "lineStyles": [
            {
                "properties": {
                    "strokeWidth": _literal(int(stroke_width)),
                    "showMarker": _literal(show_markers),
                }
            }
        ],
    }
    if not show_legend:
        objects["legend"] = [{"properties": {"show": _literal(False)}}]
    elif axis_color:
        objects["legend"] = [
            {"properties": {"show": _literal(True), "labelColor": _solid_color(axis_color)}}
        ]
    if show_labels:
        label_props: dict = {"show": _literal(True)}
        if label_color:
            label_props["color"] = _solid_color(label_color)
        objects["labels"] = [{"properties": label_props}]
    if data_point_color:
        objects["dataPoint"] = [
            {"properties": {"defaultColor": _solid_color(data_point_color)}}
        ]
    _axis_objects(objects, axis_color, gridline_color)

    sort_def = (
        _sort_definition(category_field, direction="Ascending")
        if sort_ascending_by_category
        else _sort_definition(value_fields[0])
    )

    all_fields = [category_field] + value_fields
    if series_field is not None:
        all_fields.append(series_field)

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": vtype,
            "query": {
                "queryState": query_state,
                "sortDefinition": sort_def,
            },
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config(all_fields),
    }


# ---------------------------------------------------------------------------
# COMBO CHART (columns + lines on secondary axis)
# ---------------------------------------------------------------------------
def combo_chart(
    title: str,
    category_field: dict,
    column_fields: list[dict],
    line_fields: list[dict],
    x: float = 0,
    y: float = 0,
    width: float = 600,
    height: float = 350,
    z: int = 0,
    tab_order: int = 0,
    stacked: bool = False,
    show_legend: bool = True,
    legend_position: str = "Top",
    stroke_width: int = 3,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    axis_color: str | None = None,
    gridline_color: str | None = None,
    column_color: str | None = None,
    sort_ascending_by_category: bool = True,
) -> dict:
    """Generate a combo chart (columns + lines).

    **Gotcha #8**: the line measures go in ``queryState.Y2`` — a bucket named
    ``LineY`` is silently dropped and the chart renders as plain columns.
    """
    vtype = "lineStackedColumnComboChart" if stacked else "lineClusteredColumnComboChart"

    query_state = {
        "Category": {"projections": [_build_projection(category_field, active=True)]},
        "Y": {"projections": [_build_projection(f) for f in column_fields]},
        "Y2": {"projections": [_build_projection(f) for f in line_fields]},
    }

    objects: dict = {
        "lineStyles": [{"properties": {"strokeWidth": _literal(int(stroke_width))}}],
    }
    if show_legend:
        legend_props: dict = {
            "show": _literal(True),
            "position": _literal(legend_position),
        }
        if axis_color:
            legend_props["labelColor"] = _solid_color(axis_color)
        objects["legend"] = [{"properties": legend_props}]
    else:
        objects["legend"] = [{"properties": {"show": _literal(False)}}]
    if column_color:
        objects["dataPoint"] = [
            {"properties": {"defaultColor": _solid_color(column_color)}}
        ]
    _axis_objects(objects, axis_color, gridline_color)

    sort_def = (
        _sort_definition(category_field, direction="Ascending")
        if sort_ascending_by_category
        else _sort_definition(column_fields[0])
    )

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": vtype,
            "query": {
                "queryState": query_state,
                "sortDefinition": sort_def,
            },
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _build_filter_config(
            [category_field] + column_fields + line_fields
        ),
    }


# ---------------------------------------------------------------------------
# DONUT CHART
# ---------------------------------------------------------------------------
def donut_chart(
    title: str,
    category_field: dict,
    value_field: dict,
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    show_legend: bool = True,
    legend_position: str = "Right",
    label_style: str = "Category, percent of total",
    label_color: str | None = None,
    label_size: int = 9,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    exclude_blank: bool = False,
) -> dict:
    """Generate a donut chart visual.

    ``label_style`` is a Power BI detail-label enum string, e.g.
    ``"Category"``, ``"Data value"``, ``"Percent of total"``,
    ``"Category, percent of total"``.
    """
    label_props: dict = {
        "show": _literal(True),
        "labelStyle": _literal(label_style),
        "fontSize": _literal(float(label_size)),
    }
    if label_color:
        label_props["color"] = _solid_color(label_color)

    objects: dict = {"labels": [{"properties": label_props}]}
    if show_legend:
        legend_props: dict = {
            "show": _literal(True),
            "position": _literal(legend_position),
        }
        if label_color:
            legend_props["labelColor"] = _solid_color(label_color)
        objects["legend"] = [{"properties": legend_props}]
    else:
        objects["legend"] = [{"properties": {"show": _literal(False)}}]

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "donutChart",
            "query": {
                "queryState": {
                    "Category": {
                        "projections": [_build_projection(category_field, active=True)]
                    },
                    "Y": {"projections": [_build_projection(value_field)]},
                },
                "sortDefinition": _sort_definition(value_field),
            },
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _filter_config_with_not_blank(
            [value_field] if exclude_blank else [category_field, value_field],
            category_field if exclude_blank else None,
        ),
    }


# ---------------------------------------------------------------------------
# TREEMAP
# ---------------------------------------------------------------------------
def treemap(
    title: str,
    group_field: dict,
    value_field: dict,
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    show_value_labels: bool = True,
    label_color: str | None = None,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    exclude_blank: bool = False,
) -> dict:
    """Generate a treemap visual (``Group`` + ``Values`` buckets)."""
    category_props: dict = {"show": _literal(True)}
    value_props: dict = {"show": _literal(show_value_labels)}
    if label_color:
        category_props["color"] = _solid_color(label_color)
        value_props["color"] = _solid_color(label_color)

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "treemap",
            "query": {
                "queryState": {
                    "Group": {
                        "projections": [_build_projection(group_field, active=True)]
                    },
                    "Values": {"projections": [_build_projection(value_field)]},
                },
                "sortDefinition": _sort_definition(value_field),
            },
            "objects": {
                "categoryLabels": [{"properties": category_props}],
                "labels": [{"properties": value_props}],
            },
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _filter_config_with_not_blank(
            [value_field] if exclude_blank else [group_field, value_field],
            group_field if exclude_blank else None,
        ),
    }


# ---------------------------------------------------------------------------
# SCATTER / BUBBLE CHART
# ---------------------------------------------------------------------------
def scatter_chart(
    title: str,
    detail_field: dict,
    x_field: dict,
    y_field: dict,
    size_field: dict | None = None,
    series_field: dict | None = None,
    x: float = 0,
    y: float = 0,
    width: float = 600,
    height: float = 400,
    z: int = 0,
    tab_order: int = 0,
    show_legend: bool | None = None,
    legend_position: str = "Top",
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    axis_color: str | None = None,
    gridline_color: str | None = None,
    exclude_blank_series: bool = False,
) -> dict:
    """Generate a scatter / bubble chart.

    Buckets: ``Category`` (detail points), optional ``Series`` (legend
    color), ``X``, ``Y``, optional ``Size`` (bubbles).
    """
    query_state: dict = {
        "Category": {"projections": [_build_projection(detail_field, active=True)]},
        "X": {"projections": [_build_projection(x_field)]},
        "Y": {"projections": [_build_projection(y_field)]},
    }
    if series_field is not None:
        query_state["Series"] = {"projections": [_build_projection(series_field)]}
    if size_field is not None:
        query_state["Size"] = {"projections": [_build_projection(size_field)]}

    if show_legend is None:
        show_legend = series_field is not None

    objects: dict = {
        "fillPoint": [{"properties": {"show": _literal(True)}}],
    }
    if show_legend:
        legend_props: dict = {
            "show": _literal(True),
            "position": _literal(legend_position),
        }
        if axis_color:
            legend_props["labelColor"] = _solid_color(axis_color)
        objects["legend"] = [{"properties": legend_props}]
    else:
        objects["legend"] = [{"properties": {"show": _literal(False)}}]
    _axis_objects(objects, axis_color, gridline_color)

    plain_fields = [detail_field, x_field, y_field]
    if size_field is not None:
        plain_fields.append(size_field)
    not_blank = None
    if series_field is not None:
        if exclude_blank_series:
            not_blank = series_field
        else:
            plain_fields.append(series_field)

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "scatterChart",
            "query": {"queryState": query_state},
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _filter_config_with_not_blank(plain_fields, not_blank),
    }


# ---------------------------------------------------------------------------
# SLICER
# ---------------------------------------------------------------------------
def slicer(
    field: dict,
    x: float = 0,
    y: float = 0,
    width: float = 250,
    height: float = 48,
    z: int = 0,
    tab_order: int = 0,
    mode: str = "Basic",
    horizontal: bool = True,
    title: str | None = None,
    title_color: str | None = None,
    item_color: str | None = None,
    item_background: str | None = None,
    font_size: int = 10,
    background_color: str | None = None,
    border: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
) -> dict:
    """Generate a slicer visual.

    Args:
        mode: ``"Basic"`` (list / chips) or ``"Dropdown"``.
        horizontal: ``True`` renders Basic mode as a horizontal chip strip.
        title: optional container title (the slicer header itself is hidden
            so container styling stays consistent with the other visuals).
    """
    items_props: dict = {"fontSize": _literal(float(font_size))}
    if item_color:
        items_props["fontColor"] = _solid_color(item_color)
    if item_background:
        items_props["background"] = _solid_color(item_background)

    objects: dict = {
        "data": [{"properties": {"mode": _literal(mode)}}],
        "header": [{"properties": {"show": _literal(False)}}],
        "items": [{"properties": items_props}],
    }
    if horizontal and mode == "Basic":
        objects["general"] = [{"properties": {"orientation": _literal(1.0)}}]

    container = _default_container_objects(
        title=title,
        title_color=title_color,
        background_color=background_color,
        border=border,
        shadow=False,
        border_color=border_color,
        border_radius=border_radius,
    )

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "slicer",
            "query": {
                "queryState": {
                    "Values": {"projections": [_build_projection(field)]}
                }
            },
            "objects": objects,
            "visualContainerObjects": container,
            "drillFilterOtherVisuals": True,
        },
    }


# ---------------------------------------------------------------------------
# MATRIX (pivotTable)
# ---------------------------------------------------------------------------
def matrix(
    title: str,
    row_fields: list[dict],
    column_fields: list[dict],
    value_fields: list[dict],
    x: float = 0,
    y: float = 0,
    width: float = 500,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    subtotals: bool = False,
    title_color: str | None = None,
    background_color: str | None = None,
    border: bool = True,
    shadow: bool = False,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
    exclude_blank_rows: bool = False,
    header_background: str | None = None,
    header_color: str | None = None,
    row_background: str | None = None,
    row_alt_background: str | None = None,
    row_color: str | None = None,
    grid_color: str | None = None,
) -> dict:
    """Generate a matrix (``pivotTable``) visual.

    Grid styling params mirror ``table`` — explicit per-visual emission so
    dark layouts don't depend on theme parsing.
    """
    objects: dict = {}
    if not subtotals:
        objects["subTotals"] = [
            {
                "properties": {
                    "rowSubtotals": _literal(False),
                    "columnSubtotals": _literal(False),
                }
            }
        ]
    if header_background or header_color:
        header_props: dict = {}
        if header_background:
            header_props["backColor"] = _solid_color(header_background)
        if header_color:
            header_props["fontColor"] = _solid_color(header_color)
            header_props["bold"] = _literal(True)
        objects["columnHeaders"] = [{"properties": dict(header_props)}]
        objects["rowHeaders"] = [{"properties": dict(header_props)}]
    if row_background or row_color:
        values_props: dict = {}
        if row_background:
            values_props["backColor"] = _solid_color(row_background)
            values_props["backColorSecondary"] = _solid_color(
                row_alt_background or row_background
            )
        if row_color:
            values_props["fontColorPrimary"] = _solid_color(row_color)
            values_props["fontColorSecondary"] = _solid_color(row_color)
        objects["values"] = [{"properties": values_props}]
    if grid_color:
        objects["grid"] = [
            {
                "properties": {
                    "gridVerticalColor": _solid_color(grid_color),
                    "gridHorizontalColor": _solid_color(grid_color),
                }
            }
        ]

    if exclude_blank_rows:
        plain = row_fields[1:] + column_fields + value_fields
        not_blank = row_fields[0]
    else:
        plain = row_fields + column_fields + value_fields
        not_blank = None

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "pivotTable",
            "query": {
                "queryState": {
                    "Rows": {
                        "projections": [
                            _build_projection(f, active=(i == 0))
                            for i, f in enumerate(row_fields)
                        ]
                    },
                    "Columns": {"projections": [_build_projection(f) for f in column_fields]},
                    "Values": {"projections": [_build_projection(f) for f in value_fields]},
                }
            },
            "objects": objects,
            "visualContainerObjects": _default_container_objects(
                title=title,
                title_color=title_color,
                background_color=background_color,
                border=border,
                shadow=shadow,
                border_color=border_color,
                border_radius=border_radius,
            ),
            "drillFilterOtherVisuals": True,
        },
        "filterConfig": _filter_config_with_not_blank(plain, not_blank),
    }


# ---------------------------------------------------------------------------
# NAV BUTTON (actionButton with page navigation)
# ---------------------------------------------------------------------------
def nav_button(
    text: str,
    target_page_id: str,
    x: float = 0,
    y: float = 0,
    width: float = 120,
    height: float = 32,
    z: int = 0,
    tab_order: int = 0,
    fill_color: str = "#1F4E79",
    text_color: str = "#FFFFFF",
    font_size: int = 10,
    bold: bool = True,
) -> dict:
    """Generate a page-navigation button (``actionButton``).

    ``target_page_id`` is the target page ``name`` (the 20-hex id used as
    the page folder name), not its display name.
    """
    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "actionButton",
            "objects": {
                "icon": [
                    {
                        "properties": {"shapeType": _literal("blank")},
                        "selector": {"id": "default"},
                    }
                ],
                "outline": [{"properties": {"show": _literal(False)}}],
                "text": [
                    {"properties": {"show": _literal(True)}},
                    {
                        "properties": {
                            "text": _literal(text),
                            "fontColor": _solid_color(text_color),
                            "fontSize": _literal(float(font_size)),
                            "bold": _literal(bold),
                        },
                        "selector": {"id": "default"},
                    },
                ],
                "fill": [
                    {"properties": {"show": _literal(True)}},
                    {
                        "properties": {
                            "fillColor": _solid_color(fill_color),
                            "transparency": _literal(0.0),
                        },
                        "selector": {"id": "default"},
                    },
                ],
            },
            "visualContainerObjects": {
                "visualLink": [
                    {
                        "properties": {
                            "show": _literal(True),
                            "type": _literal("PageNavigation"),
                            "navigationSection": _literal(target_page_id),
                        }
                    }
                ],
            },
            "drillFilterOtherVisuals": True,
        },
    }


# ---------------------------------------------------------------------------
# INSIGHT PANEL (styled multi-bullet textbox)
# ---------------------------------------------------------------------------
def insight_panel(
    title_text: str,
    bullets: list[str],
    x: float = 0,
    y: float = 0,
    width: float = 380,
    height: float = 300,
    z: int = 0,
    tab_order: int = 0,
    background_color: str = "#1F2A44",
    title_color: str = "#FFFFFF",
    bullet_color: str = "#C7D4EA",
    title_size_pt: int = 13,
    bullet_size_pt: int = 10,
    bullet_marker: str = "▸ ",
    border: bool = True,
    border_color: str = "#EDEDED",
    border_radius: int = 10,
) -> dict:
    """Generate a data-storytelling panel: bold heading + bullet lines.

    Same textbox + container-background pattern as ``banner`` (gotcha #2
    explicit transparency), with one paragraph per bullet.
    """
    paragraphs: list[dict] = [
        {
            "textRuns": [
                {
                    "value": f" {title_text}",
                    "textStyle": {
                        "fontSize": f"{title_size_pt}pt",
                        "fontWeight": "bold",
                        "color": title_color,
                    },
                }
            ],
        },
        {"textRuns": [{"value": " ", "textStyle": {"fontSize": "4pt"}}]},
    ]
    for bullet in bullets:
        paragraphs.append(
            {
                "textRuns": [
                    {
                        "value": f" {bullet_marker}{bullet}",
                        "textStyle": {
                            "fontSize": f"{bullet_size_pt}pt",
                            "color": bullet_color,
                        },
                    }
                ],
            }
        )
        paragraphs.append(
            {"textRuns": [{"value": " ", "textStyle": {"fontSize": "5pt"}}]}
        )

    container: dict = {
        "background": [
            {
                "properties": {
                    "show": _literal(True),
                    "color": _solid_color(background_color),
                    "transparency": _literal(0.0),
                }
            }
        ],
    }
    if border:
        container["border"] = _border_object(color=border_color, radius=border_radius)

    return {
        "$schema": SCHEMA,
        "name": _visual_id(),
        "position": _position(x, y, width, height, z, tab_order),
        "visual": {
            "visualType": "textbox",
            "objects": {
                "general": [{"properties": {"paragraphs": paragraphs}}]
            },
            "visualContainerObjects": container,
        },
    }
