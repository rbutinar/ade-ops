"""Layout helpers for automatic visual positioning.

Grid-based + auto-layout functions che calcolano x/y/width/height per visual
su una pagina. Portato verbatim da ADE 2026-05-24 (puri helpers).
"""
from __future__ import annotations


PADDING = 10
DEFAULT_PAGE_WIDTH = 1280
DEFAULT_PAGE_HEIGHT = 720


def grid_layout(
    n_visuals: int,
    cols: int,
    page_width: int = DEFAULT_PAGE_WIDTH,
    page_height: int = DEFAULT_PAGE_HEIGHT,
    start_x: float = 0,
    start_y: float = 0,
    available_width: float | None = None,
    available_height: float | None = None,
    padding: float = PADDING,
) -> list[dict]:
    """Calculate grid positions for N visuals.

    Returns:
        List of ``{x, y, width, height}`` dicts, one per visual.
    """
    avail_w = available_width or (page_width - start_x)
    avail_h = available_height or (page_height - start_y)
    rows = (n_visuals + cols - 1) // cols

    cell_w = (avail_w - padding * (cols - 1)) / cols
    cell_h = (avail_h - padding * (rows - 1)) / rows

    positions = []
    for i in range(n_visuals):
        row = i // cols
        col = i % cols
        positions.append(
            {
                "x": round(start_x + col * (cell_w + padding), 2),
                "y": round(start_y + row * (cell_h + padding), 2),
                "width": round(cell_w, 2),
                "height": round(cell_h, 2),
            }
        )
    return positions


def auto_layout(
    visual_specs: list[dict],
    page_width: int = DEFAULT_PAGE_WIDTH,
    page_height: int = DEFAULT_PAGE_HEIGHT,
    padding: float = PADDING,
) -> list[dict]:
    """Automatically lay out visuals based on their type.

    Each spec should have a ``"type"`` key. Layout rules:

    - Cards in a horizontal row at the top.
    - Charts fill the middle area in a grid (up to 3 cols).
    - Tables / matrices span the bottom.

    Returns:
        List of ``{x, y, width, height}`` dicts matching input order.
    """
    cards: list[int] = []
    charts: list[int] = []
    tables: list[int] = []

    for i, spec in enumerate(visual_specs):
        vtype = spec.get("type", "")
        if vtype in ("card", "cardVisual"):
            cards.append(i)
        elif vtype in ("tableEx", "pivotTable", "table"):
            tables.append(i)
        else:
            charts.append(i)

    positions: list[dict | None] = [None] * len(visual_specs)
    y_cursor = padding

    if cards:
        card_height = 80
        card_positions = grid_layout(
            len(cards),
            cols=len(cards),
            page_width=page_width,
            page_height=page_height,
            start_x=padding,
            start_y=y_cursor,
            available_width=page_width - 2 * padding,
            available_height=card_height,
            padding=padding,
        )
        for idx, card_idx in enumerate(cards):
            positions[card_idx] = card_positions[idx]
        y_cursor += card_height + padding

    if charts:
        remaining_h = page_height - y_cursor - padding
        chart_height = remaining_h * 0.6 if tables else remaining_h

        cols = min(len(charts), 3)
        chart_positions = grid_layout(
            len(charts),
            cols=cols,
            page_width=page_width,
            page_height=page_height,
            start_x=padding,
            start_y=y_cursor,
            available_width=page_width - 2 * padding,
            available_height=chart_height,
            padding=padding,
        )
        for idx, chart_idx in enumerate(charts):
            positions[chart_idx] = chart_positions[idx]
        y_cursor += chart_height + padding

    if tables:
        table_height = page_height - y_cursor - padding
        table_positions = grid_layout(
            len(tables),
            cols=min(len(tables), 2),
            page_width=page_width,
            page_height=page_height,
            start_x=padding,
            start_y=y_cursor,
            available_width=page_width - 2 * padding,
            available_height=table_height,
            padding=padding,
        )
        for idx, table_idx in enumerate(tables):
            positions[table_idx] = table_positions[idx]

    return positions
