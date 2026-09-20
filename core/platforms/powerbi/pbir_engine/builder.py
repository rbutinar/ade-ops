"""ReportBuilder — Assembles visuals into a complete PBIR folder structure.

Output structure::

    {report_name}.Report/
    ├── .platform
    ├── definition.pbir
    └── definition/
        ├── report.json
        ├── version.json
        └── pages/
            ├── pages.json
            └── {page_id}/
                ├── page.json
                └── visuals/
                    └── {visual_id}/
                        └── visual.json

Portato da ADE 2026-05-24 (subset MVP — no round-trip / no reader).
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import visuals as V


def _page_id() -> str:
    """Generate a 20-char hex page ID."""
    return uuid.uuid4().hex[:20]


class PageBuilder:
    """Builder for a single report page with visual helpers."""

    def __init__(
        self,
        display_name: str,
        page_id: str | None = None,
        width: int = 1280,
        height: int = 720,
        background_color: str | None = None,
        wallpaper_color: str | None = None,
    ) -> None:
        self.display_name = display_name
        self.page_id = page_id or _page_id()
        self.width = width
        self.height = height
        self.background_color = background_color
        self.wallpaper_color = wallpaper_color
        self._visuals: list[dict] = []
        self._z_counter = 1000
        self._tab_counter = 1000

    def _next_z(self) -> int:
        self._z_counter += 1000
        return self._z_counter

    def _next_tab(self) -> int:
        self._tab_counter += 1000
        return self._tab_counter

    def _apply_z_tab(self, visual_dict: dict) -> dict:
        pos = visual_dict.get("position", {})
        if pos.get("z", 0) == 0:
            pos["z"] = self._next_z()
        if pos.get("tabOrder", 0) == 0:
            pos["tabOrder"] = self._next_tab()
        return visual_dict

    def add_visual(self, visual_dict: dict) -> "PageBuilder":
        """Add a raw visual dict (from ``visuals`` module)."""
        self._visuals.append(self._apply_z_tab(visual_dict))
        return self

    # -- Convenience helpers (MVP subset) ------------------------------------

    def add_card(self, title: str, value_field: dict, **kwargs) -> "PageBuilder":
        return self.add_visual(V.card(title, value_field, **kwargs))

    def add_card_visual(self, title: str, value_field: dict, **kwargs) -> "PageBuilder":
        return self.add_visual(V.card_visual(title, value_field, **kwargs))

    def add_bar_chart(
        self,
        title: str,
        category_field: dict,
        value_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(V.bar_chart(title, category_field, value_fields, **kwargs))

    def add_column_chart(
        self,
        title: str,
        category_field: dict,
        value_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(
            V.bar_chart(title, category_field, value_fields, horizontal=False, **kwargs)
        )

    def add_table(self, title: str, fields: list[dict], **kwargs) -> "PageBuilder":
        return self.add_visual(V.table(title, fields, **kwargs))

    def add_textbox(self, text: str, **kwargs) -> "PageBuilder":
        return self.add_visual(V.textbox(text, **kwargs))

    def add_banner(self, title_text: str, subtitle_text: str | None = None, **kwargs) -> "PageBuilder":
        """Add a styled header banner (textbox + container background)."""
        return self.add_visual(V.banner(title_text, subtitle_text, **kwargs))

    def add_line_chart(
        self,
        title: str,
        category_field: dict,
        value_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(V.line_chart(title, category_field, value_fields, **kwargs))

    def add_area_chart(
        self,
        title: str,
        category_field: dict,
        value_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(
            V.line_chart(title, category_field, value_fields, area=True, **kwargs)
        )

    def add_combo_chart(
        self,
        title: str,
        category_field: dict,
        column_fields: list[dict],
        line_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(
            V.combo_chart(title, category_field, column_fields, line_fields, **kwargs)
        )

    def add_donut_chart(
        self,
        title: str,
        category_field: dict,
        value_field: dict,
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(V.donut_chart(title, category_field, value_field, **kwargs))

    def add_treemap(
        self,
        title: str,
        group_field: dict,
        value_field: dict,
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(V.treemap(title, group_field, value_field, **kwargs))

    def add_scatter_chart(
        self,
        title: str,
        detail_field: dict,
        x_field: dict,
        y_field: dict,
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(
            V.scatter_chart(title, detail_field, x_field, y_field, **kwargs)
        )

    def add_slicer(self, field: dict, **kwargs) -> "PageBuilder":
        return self.add_visual(V.slicer(field, **kwargs))

    def add_matrix(
        self,
        title: str,
        row_fields: list[dict],
        column_fields: list[dict],
        value_fields: list[dict],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(
            V.matrix(title, row_fields, column_fields, value_fields, **kwargs)
        )

    def add_nav_button(self, text: str, target_page_id: str, **kwargs) -> "PageBuilder":
        return self.add_visual(V.nav_button(text, target_page_id, **kwargs))

    def add_insight_panel(
        self,
        title_text: str,
        bullets: list[str],
        **kwargs,
    ) -> "PageBuilder":
        return self.add_visual(V.insight_panel(title_text, bullets, **kwargs))

    @property
    def visuals(self) -> list[dict]:
        return self._visuals

    def page_json(self) -> dict:
        body = {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/page/2.1.0/schema.json"
            ),
            "name": self.page_id,
            "displayName": self.display_name,
            "displayOption": "FitToPage",
            "height": self.height,
            "width": self.width,
        }
        objects: dict = {}
        if self.background_color:
            objects["background"] = [{"properties": {
                "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{self.background_color}'"}}}}},
                "transparency": {"expr": {"Literal": {"Value": "0D"}}},
            }}]
        if self.wallpaper_color:
            objects["outspace"] = [{"properties": {
                "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{self.wallpaper_color}'"}}}}},
                "transparency": {"expr": {"Literal": {"Value": "0D"}}},
            }}]
        if objects:
            body["objects"] = objects
        return body


class ReportBuilder:
    """Builds a complete PBIR report folder structure."""

    def __init__(
        self,
        report_name: str,
        model_name: str | None = None,
        model_id: str | None = None,
        workspace_display_name: str | None = None,
        initial_catalog: str | None = None,
        width: int = 1280,
        height: int = 720,
        theme: str = "CY25SU11",
        theme_json: dict | None = None,
    ) -> None:
        """
        Args:
            report_name: Report display name (and folder base name).
            model_name: Semantic model name for ``byPath`` local reference
                (when the model lives as a sibling ``.SemanticModel`` folder).
            model_id: Fabric semantic model GUID for ``byConnection`` (when
                the model lives in a Fabric workspace and we bind to it).
                Mutually exclusive with ``model_name`` for the chosen path.
            workspace_display_name: Optional Fabric workspace display name —
                when set together with ``model_id``, the ``connectionString``
                uses the full PBI service form (``Data Source=powerbi://...``
                style) rather than the bare ``semanticModelId=`` form. The
                full form is what Power BI Desktop emits and what the demo
                ``build_and_deploy_report.py`` uses.
            initial_catalog: Optional. Defaults to ``model_name`` if given.
            width: Default page width.
            height: Default page height.
            theme: Base theme name (referenced in ``themeCollection``).
            theme_json: Optional Power BI theme JSON content. When provided,
                the engine writes ``StaticResources/SharedResources/BaseThemes/{theme}.json``
                and includes a ``resourcePackages`` entry in ``report.json``.
                Mitigates gotcha #4 (theme deployed-but-invisible-on-audit)
                by embedding the theme content in the deploy bundle.
        """
        self.report_name = report_name
        self.model_name = model_name
        self.model_id = model_id
        self.workspace_display_name = workspace_display_name
        self.initial_catalog = initial_catalog or model_name
        self.width = width
        self.height = height
        self.theme = theme
        self.theme_json = theme_json
        self._pages: list[PageBuilder] = []

    @property
    def pages(self) -> list[PageBuilder]:
        return self._pages

    def add_page(
        self,
        display_name: str,
        page_id: str | None = None,
        background_color: str | None = None,
        wallpaper_color: str | None = None,
    ) -> PageBuilder:
        page = PageBuilder(
            display_name,
            page_id=page_id,
            width=self.width,
            height=self.height,
            background_color=background_color,
            wallpaper_color=wallpaper_color,
        )
        self._pages.append(page)
        return page

    def get_page(self, name: str) -> PageBuilder | None:
        for p in self._pages:
            if p.display_name == name:
                return p
        return None

    # -- Spec-driven build (ddf-operator F5 fix, 2026-05-24) -----------------

    @classmethod
    def from_spec(
        cls,
        spec_path: str | Path,
        *,
        model_id: str | None = None,
        workspace_display_name: str | None = None,
        initial_catalog: str | None = None,
        theme_json: dict | None = None,
    ) -> "ReportBuilder":
        """Build a ReportBuilder from a YAML spec file.

        Reads the YAML with ``encoding="utf-8"`` explicitly — fixes the
        Windows cp1252 default that mangled em-dash / middle-dot / accented
        characters in titles and subtitles (ddf-operator F5, 2026-05-24).

        Optional overrides (``model_id`` etc.) take precedence over the
        spec's ``report:`` block. Use them to bind the same template to a
        different model at build time.

        Spec shape::

            report:
              name: AcmeSales
              theme: AcmeSales
              width: 1280
              height: 720
              model_id: <guid>                   # optional, may be overridden
              workspace_display_name: <name>     # optional
              initial_catalog: <name>            # optional
              theme_json: { ... }                # optional, inline theme JSON

            pages:
              - name: Overview
                background_color: "#FAFAFA"
                visuals:
                  - type: banner
                    title: "Acme Sales"
                    subtitle: "Overview — DirectLake on Fabric Lakehouse"
                    position: { x: 0, y: 0, width: 1280, height: 84 }
                    style: { background_color: "#1F4E79" }
                  - type: card
                    title: "Total Revenue"
                    value: { entity: fct_sales, property: "Total Revenue", _type: measure }
                    position: { x: 10, y: 110, width: 300, height: 80 }

        Supported visual types in MVP: ``banner``, ``card``, ``card_visual``,
        ``bar_chart`` (with ``horizontal: true|false`` + ``clustered`` flags),
        ``table``, ``textbox``.
        """
        import yaml

        spec_path = Path(spec_path)
        spec_text = spec_path.read_text(encoding="utf-8")
        spec = yaml.safe_load(spec_text)

        rcfg = spec.get("report") or {}
        builder = cls(
            report_name=rcfg["name"],
            model_id=model_id or rcfg.get("model_id"),
            model_name=rcfg.get("model_name"),
            workspace_display_name=workspace_display_name or rcfg.get("workspace_display_name"),
            initial_catalog=initial_catalog or rcfg.get("initial_catalog"),
            width=rcfg.get("width", 1280),
            height=rcfg.get("height", 720),
            theme=rcfg.get("theme", "CY25SU11"),
            theme_json=theme_json or rcfg.get("theme_json"),
        )

        for page_spec in spec.get("pages", []):
            page = builder.add_page(
                page_spec["name"],
                background_color=page_spec.get("background_color"),
            )
            for v_spec in page_spec.get("visuals", []):
                _add_visual_from_spec(page, v_spec)

        return builder

    # -- JSON tree generation ------------------------------------------------

    def _definition_pbir(self) -> dict:
        """Generate definition.pbir (model reference).

        Three forms:

        - ``model_id`` + ``workspace_display_name`` → full PBI service
          ``connectionString`` (matches Power BI Desktop emission;
          demo-claude ``build_and_deploy_report.py`` empirically validated)
        - ``model_id`` alone → short ``semanticModelId=…`` form (works for
          most deployments; verified via FabricConnector round-trip)
        - ``model_name`` only → ``byPath`` (sibling local folder)
        """
        base = {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definitionProperties/2.0.0/schema.json"
            ),
            "version": "4.0",
        }
        if self.model_id and self.workspace_display_name:
            catalog = self.initial_catalog or "model"
            base["datasetReference"] = {
                "byConnection": {
                    "connectionString": (
                        f"Data Source=powerbi://api.powerbi.com/v1.0/myorg/"
                        f"{self.workspace_display_name};"
                        f"initial catalog={catalog};"
                        f"integrated security=ClaimsToken;"
                        f"semanticmodelid={self.model_id}"
                    )
                }
            }
        elif self.model_id:
            base["datasetReference"] = {
                "byConnection": {
                    "connectionString": f"semanticModelId={self.model_id}",
                    "pbiServiceModelId": None,
                    "pbiModelVirtualServerName": "sobe_wowvirtualserver",
                    "pbiModelDatabaseName": None,
                    "name": "EntityDataSource",
                    "connectionType": "pbiServiceXmlaStyleLive",
                }
            }
        elif self.model_name:
            base["datasetReference"] = {
                "byPath": {"path": f"../{self.model_name}.SemanticModel"}
            }
        else:
            base["datasetReference"] = {
                "byConnection": {
                    "connectionString": None,
                    "pbiServiceModelId": None,
                    "pbiModelVirtualServerName": "sobe_wowvirtualserver",
                    "pbiModelDatabaseName": None,
                    "name": "EntityDataSource",
                    "connectionType": "pbiServiceXmlaStyleLive",
                }
            }
        return base

    #: Built-in Microsoft base theme every report rides on. Custom themes are
    #: layered on top as ``customTheme`` — see ``_report_json``.
    BASE_THEME = "CY26SU05"
    #: reportVersionAtImport blocks captured from a service-authored report
    #: (theme applied via the service Theme gallery, then getDefinition —
    #: 2026-07-09 ground truth). The service refuses to APPLY a customTheme
    #: whose versions are older than these, silently keeping the base theme.
    BASE_THEME_VERSIONS = {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"}
    CUSTOM_THEME_VERSIONS = {"visual": "2.10.0", "report": "3.4.0", "page": "2.3.1"}

    def _report_json(self) -> dict:
        """Generate report.json.

        Custom theme wiring (gotcha #10, discovered 2026-07-09): declaring a
        custom theme as ``themeCollection.baseTheme`` with an unknown name is
        SILENTLY ignored (classic-palette fallback), and a
        ``RegisteredResources`` package is accepted at import but the theme
        never renders. The shape the SERVICE ITSELF writes when a theme is
        applied through the UI — verified via getDefinition — is:

        - ``themeCollection.baseTheme`` = a Microsoft built-in
          (``CY26SU05``) with its version block;
        - ``themeCollection.customTheme`` = ``{name, reportVersionAtImport,
          type: SharedResources}``;
        - ONE ``resourcePackages`` entry ``SharedResources`` whose items
          include ``{name, path: "BuiltInThemes/{name}.json", type:
          "CustomTheme"}``;
        - the theme JSON at
          ``StaticResources/SharedResources/BuiltInThemes/{name}.json``.
        """
        base_theme_name = self.BASE_THEME if self.theme_json else self.theme
        base_versions = (
            self.BASE_THEME_VERSIONS
            if self.theme_json
            else {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"}
        )
        body = {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/report/3.2.0/schema.json"
            ),
            "themeCollection": {
                "baseTheme": {
                    "name": base_theme_name,
                    "reportVersionAtImport": dict(base_versions),
                    "type": "SharedResources",
                }
            },
            "settings": {
                "useStylableVisualContainerHeader": True,
                "exportDataMode": "AllowSummarized",
                "defaultDrillFilterOtherVisuals": True,
                "allowChangeFilterTypes": True,
                "useEnhancedTooltips": True,
            },
        }
        if self.theme_json:
            # Non-built-in custom themes ride in RegisteredResources with the
            # ``.json`` extension INCLUDED in both the customTheme name and
            # the package item name (Power BI Desktop emission form). The
            # SharedResources/BuiltInThemes slot only resolves Microsoft
            # gallery names — an arbitrary name there yields "Current theme
            # ()" and no dataColors.
            theme_ref = f"{self.theme}.json"
            body["themeCollection"]["customTheme"] = {
                "name": theme_ref,
                "reportVersionAtImport": dict(self.CUSTOM_THEME_VERSIONS),
                "type": "RegisteredResources",
            }
            body["resourcePackages"] = [{
                "name": "RegisteredResources",
                "type": "RegisteredResources",
                "items": [{
                    "name": theme_ref,
                    "path": theme_ref,
                    "type": "CustomTheme",
                }],
            }]
        return body

    def _version_json(self) -> dict:
        return {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/versionMetadata/1.0.0/schema.json"
            ),
            "version": "2.0.0",
        }

    def _pages_json(self) -> dict:
        return {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/item/report/"
                "definition/pagesMetadata/1.0.0/schema.json"
            ),
            "pageOrder": [p.page_id for p in self._pages],
            "activePageName": self._pages[0].page_id if self._pages else "",
        }

    def _platform_json(self) -> dict:
        logical_parts = [uuid.uuid4().hex[:8]] + [uuid.uuid4().hex[:4] for _ in range(3)] + [uuid.uuid4().hex[:12]]
        return {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                "platformProperties/2.0.0/schema.json"
            ),
            "metadata": {"type": "Report", "displayName": self.report_name},
            "config": {"version": "2.0", "logicalId": "-".join(logical_parts)},
        }

    # -- Output --------------------------------------------------------------

    def save(self, output_dir: str | Path) -> Path:
        """Write the complete PBIR folder structure to disk.

        Returns:
            Path to the created ``.Report`` folder.
        """
        output_dir = Path(output_dir)
        report_dir = output_dir / f"{self.report_name}.Report"
        def_dir = report_dir / "definition"
        pages_dir = def_dir / "pages"

        pages_dir.mkdir(parents=True, exist_ok=True)

        _write_json(report_dir / ".platform", self._platform_json())
        _write_json(report_dir / "definition.pbir", self._definition_pbir())
        _write_json(def_dir / "report.json", self._report_json())
        _write_json(def_dir / "version.json", self._version_json())
        _write_json(pages_dir / "pages.json", self._pages_json())

        # Embed the theme JSON in StaticResources when provided (custom theme
        # slot — RegisteredResources; see _report_json for the wiring rules).
        if self.theme_json:
            theme_path = (
                report_dir
                / "StaticResources"
                / "RegisteredResources"
                / f"{self.theme}.json"
            )
            _write_json(theme_path, self.theme_json)

        for page in self._pages:
            page_dir = pages_dir / page.page_id
            visuals_dir = page_dir / "visuals"
            visuals_dir.mkdir(parents=True, exist_ok=True)

            _write_json(page_dir / "page.json", page.page_json())

            for visual in page.visuals:
                visual_id = visual.get("name", uuid.uuid4().hex[:20])
                visual_dir = visuals_dir / visual_id
                visual_dir.mkdir(parents=True, exist_ok=True)
                _write_json(visual_dir / "visual.json", visual)

        return report_dir

    def summary(self) -> str:
        """Human-readable summary of the report structure."""
        lines = [
            f"Report: {self.report_name}",
            f"Model: {self.model_id or self.model_name or '(unbound)'}",
            f"Theme: {self.theme}",
            f"Pages: {len(self._pages)}",
        ]
        for page in self._pages:
            lines.append(f"  Page: {page.display_name} ({len(page.visuals)} visuals)")
            for v in page.visuals:
                vtype = v.get("visual", {}).get("visualType", "unknown")
                title_obj = (
                    v.get("visual", {}).get("visualContainerObjects", {}).get("title", [{}])
                )
                title = ""
                if title_obj:
                    props = title_obj[0].get("properties", {})
                    text_expr = (
                        props.get("text", {})
                        .get("expr", {})
                        .get("Literal", {})
                        .get("Value", "")
                    )
                    title = text_expr.strip("'")
                lines.append(f"    - {vtype}: {title}")
        return "\n".join(lines)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Spec → visual dispatch (used by ReportBuilder.from_spec)
# ---------------------------------------------------------------------------

def _field_from_spec(spec: dict | None) -> dict | None:
    """Convert a ``{entity, property, _type}`` spec dict to a field reference."""
    if not isinstance(spec, dict):
        return None
    from .fields import aggregation, column, measure  # local import to avoid cycle
    kind = spec.get("_type", "column")
    entity = spec["entity"]
    prop = spec["property"]
    if kind == "measure":
        return measure(entity, prop)
    if kind == "aggregation":
        return aggregation(entity, prop, function=spec.get("function", 0))
    return column(entity, prop, display_name=spec.get("display_name"))


def _flatten_visual_kwargs(v_spec: dict) -> dict:
    """Merge `position` + `style` blocks into flat kwargs for the visual helper."""
    kwargs: dict = {}
    pos = v_spec.get("position") or {}
    kwargs.update({k: pos[k] for k in ("x", "y", "width", "height", "z", "tab_order") if k in pos})
    style = v_spec.get("style") or {}
    kwargs.update(style)
    return kwargs


def _add_visual_from_spec(page: "PageBuilder", v_spec: dict) -> None:
    """Dispatch a YAML visual spec onto the right PageBuilder helper."""
    vtype = v_spec["type"]
    kwargs = _flatten_visual_kwargs(v_spec)

    if vtype == "banner":
        page.add_banner(
            v_spec["title"],
            v_spec.get("subtitle"),
            **kwargs,
        )
    elif vtype == "card":
        page.add_card(
            v_spec["title"],
            _field_from_spec(v_spec["value"]),
            **kwargs,
        )
    elif vtype == "card_visual" or vtype == "cardVisual":
        page.add_card_visual(
            v_spec["title"],
            _field_from_spec(v_spec["value"]),
            **kwargs,
        )
    elif vtype == "bar_chart" or vtype == "column_chart":
        # column_chart is bar_chart with horizontal=False
        horizontal = kwargs.pop("horizontal", vtype == "bar_chart" and v_spec.get("horizontal", False))
        if vtype == "column_chart":
            horizontal = False
        page.add_bar_chart(
            v_spec["title"],
            _field_from_spec(v_spec["category"]),
            [_field_from_spec(f) for f in v_spec["values"]],
            horizontal=horizontal,
            **kwargs,
        )
    elif vtype == "table":
        page.add_table(
            v_spec["title"],
            [_field_from_spec(f) for f in v_spec["fields"]],
            **kwargs,
        )
    elif vtype == "textbox":
        page.add_textbox(v_spec["text"], **kwargs)
    else:
        raise ValueError(f"Unsupported visual type in spec: {vtype!r}")
