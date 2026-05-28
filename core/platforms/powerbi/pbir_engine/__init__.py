"""PBIR Engine — Programmatic Power BI Report Generation.

Generates complete PBIR report folder structures from high-level specs.
Output is ready for Fabric REST deployment via `FabricConnector`.

Provenance: portato da ADE workshop (`ade_app.platforms.powerbi.pbir_engine`)
2026-05-24, MVP subset (5 visual types: card, cardVisual, bar/column chart,
table, textbox). Skip rispetto a ADE: donut, line, pivot, slicer, treemap,
reader (round-trip), extractor (reverse-eng). On-demand backlog.

Gotchas embedded as defaults (`core/playbooks/pbir-gotchas.md`):
- #1 visualContainerObjects vs objects: container styling under visualContainerObjects
- #2 transparency 0D: default opaque, NOT pastel-by-default
- #3 title.text container slot: title text under visualContainerObjects.title

Usage::

    from core.platforms.powerbi.pbir_engine import ReportBuilder, measure

    report = ReportBuilder("Sales Demo", model_name="AcmeSales")
    page = report.add_page("Overview")
    page.add_card("Total Revenue", measure("FactSales", "Total Revenue"))
    report.save("./out")
"""

from .add_page import add_page_from_spec_file, add_page_to_report
from .builder import PageBuilder, ReportBuilder
from .clone import clone_report_template
from .fields import aggregation, column, measure
from .layout import auto_layout, grid_layout

__all__ = [
    "PageBuilder",
    "ReportBuilder",
    "add_page_from_spec_file",
    "add_page_to_report",
    "clone_report_template",
    "measure",
    "column",
    "aggregation",
    "auto_layout",
    "grid_layout",
]
