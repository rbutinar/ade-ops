---
name: pbir-create
description: Build a New PBIR Report (preview)
status: preview
since: 2026-05-24
supersedes_in_part: pbir-report (create/modify/extract sub-modes)
related: pbir-clone-template (planned, higher-confidence pattern), <client>-pbi-loop, pbir-report
---

# /pbir-create — Build a New PBIR Report (preview)

You are building a **new** Power BI PBIR report from scratch using the framework-native engine at `core/platforms/powerbi/pbir_engine/`. The engine generates a `.Report` folder, then `FabricConnector` deploys to a Fabric workspace, then Playwright visually verifies the rendering. If the render shows known gotchas, the loop iterates.

> **Status: `preview`**. This is the first build-from-scratch capability autonomous from ADE workshop. The underlying engine is a clean port of `ade_app.platforms.powerbi.pbir_engine` with gotchas embedded as defaults (see `core/playbooks/pbir-gotchas.md`), but **has not been battle-tested in production**. Empirical observation across `<lab-root>/ade`: zero project usage of `ReportBuilder` for build-from-scratch — only synthetic tests. Expect rough edges. Use `/<client>-pbi-loop edit` instead if you're iterating an existing report. Future `/pbir-clone-template` (planned) may be the better default for enterprise-style work where a known-good template exists.

## When to use this skill

| Scenario | Use |
|---|---|
| Build a brand-new report with no existing template | **This skill** (`preview` — verify visually) |
| Iterate on an existing report (90% of <client> work) | `/<client>-pbi-loop edit {report-ref}` |
| Clone a known-working report and adapt fields | `/pbir-clone-template` (**planned**, not yet available) |
| Deploy an existing `.Report` folder | `/pbir-report deploy` |

## Prerequisites

- Project `config/project.yaml` with a Fabric workspace target (`environments.{env}.platforms.fabric.workspace_id` or `overlays/{env}.yaml power_bi.report_workspace_id`)
- A bound semantic model — either a Fabric workspace GUID (recommended) or a sibling `.SemanticModel` folder on disk
- `FabricConnector` credentials (az login or service principal)
- **For visual verification**: Playwright MCP entry in `.mcp.json` (see `core/playbooks/playwright-pbi-loop.md`)
- Spec for what to build (manifest YAML or interactive prompt)

## Usage

```
/pbir-create {ReportName} --env {env} --model-id {guid}                     # bind to deployed Fabric model
/pbir-create {ReportName} --env {env} --model-name {name}                   # bind to sibling local .SemanticModel
/pbir-create {ReportName} --env {env} --model-id {guid} --spec {file.yaml}  # non-interactive build from manifest
/pbir-create {ReportName} --env {env} --model-id {guid} --no-verify         # skip Playwright verify step
```

## Spec manifest format (when `--spec` is provided)

```yaml
report:
  name: AcmeSales
  theme: CY25SU11               # optional, default CY25SU11
  width: 1280
  height: 720

pages:
  - name: Overview
    visuals:
      - type: card
        title: Total Revenue
        value: { entity: FactSales, property: Total Revenue, _type: measure }
        position: { x: 10, y: 10, width: 300, height: 80 }
        style: { title_color: "#6990CA", shadow: true }

      - type: bar_chart
        title: Revenue by Channel
        category: { entity: FactSales, property: sales_channel, _type: column }
        values:
          - { entity: FactSales, property: Total Revenue, _type: measure }
        horizontal: true
        show_legend: false
        position: { x: 10, y: 100, width: 600, height: 300 }

      - type: table
        title: Category Breakdown
        fields:
          - { entity: DimProduct, property: category, _type: column }
          - { entity: FactSales, property: Total Revenue, _type: measure }
        position: { x: 620, y: 100, width: 600, height: 300 }
```

Supported visual types in MVP (preview): `card`, `card_visual`, `bar_chart` (with `horizontal` / `clustered` options → renders as `barChart` / `columnChart` / `clusteredBarChart` / `clusteredColumnChart`), `table`, `textbox`, **`banner`** (styled textbox with container background — header pattern). **Out of MVP**: `donut_chart`, `line_chart`, `pivot_table`, `slicer`, `treemap` — add on-demand to `core/platforms/powerbi/pbir_engine/visuals.py` if a real use case requires them.

**Branded report support** (engine v2, 2026-05-24 patch absorbed from demo-claude hand-crafted reference):

- **Theme JSON embedding**: pass `theme_json={...}` to `ReportBuilder` to embed a full theme content (dataColors, textClasses, visualStyles, etc.). The engine writes `StaticResources/SharedResources/BaseThemes/{theme}.json` AND declares `resourcePackages` in `report.json`. Mitigates gotcha #4 (theme deployed but invisible to `getItemDefinition`) by ensuring the theme content is in the deploy bundle.
- **Page background**: `report.add_page(name, background_color="#FAFAFA")` emits `page.objects.background` with explicit `transparency: 0D`. Required for branded look — without it the page renders with default theme bg.
- **dataPoint default color**: `add_bar_chart(..., data_point_color="#5B9BD5")` overrides the theme accent for a specific chart. Useful for visual consistency in a multi-chart layout.
- **Full `connectionString` form**: pass `workspace_display_name="MyWorkspace"` + `initial_catalog="MyModel"` to `ReportBuilder` to emit the full Power BI service `connectionString` (`Data Source=powerbi://...`) instead of the short `semanticModelId=...` form. The full form mirrors what Power BI Desktop emits and what the demo-claude hand-crafted script validated empirically.

## Behavior

### Step 0: Project + env + model resolution

1. Find active project (walk up from cwd to `config/project.yaml`)
2. Validate `--env` against `environments.{env}.platforms.fabric.auth`
3. Resolve workspace target (`overlays/{env}.yaml power_bi.report_workspace_id` or `platforms.fabric.workspace_id` fallback)
4. Validate `--model-id` (GUID format) or `--model-name` (local folder must exist) — exactly one required

### Step 1: Pre-flight identity check

```python
from core.connectors.fabric import FabricConnector
connector = FabricConnector.from_credentials(
    credentials, env_platform_auth=env_cfg.platforms.fabric.auth
)
ws = connector.client.get_workspace(report_workspace_id)
```

Hard-fail with explicit hint if 404 (identity / PBI Pro). Mirror the iterative PBI loop skill pattern — never silent PBIR-Legacy fallback.

### Step 2: Build the report

**With `--spec` (canonical path)** — use `ReportBuilder.from_spec()` so the YAML is parsed with explicit `encoding="utf-8"`, eliminating the Windows cp1252 mangling that broke em-dash / middle-dot / accented titles before the F5 fix (2026-05-24):

```python
from core.platforms.powerbi.pbir_engine import ReportBuilder

report = ReportBuilder.from_spec(
    spec_path,
    model_id=model_id,                     # optional override
    workspace_display_name=ws_display,     # optional override
)
```

The spec dispatch supports MVP visual types: `banner`, `card`, `card_visual`, `bar_chart` / `column_chart`, `table`, `textbox`. See `core/platforms/powerbi/pbir_engine/builder.py` `_add_visual_from_spec` for the exact field mapping.

**Without `--spec` (interactive)** — drive `ReportBuilder` directly:

```python
from core.platforms.powerbi.pbir_engine import ReportBuilder, measure, column

report = ReportBuilder(
    report_name=name,
    model_id=model_id,        # byConnection — recommended
    width=1280, height=720,
    theme="CY25SU11",
)
page = report.add_page("Overview", background_color="#FAFAFA")
page.add_banner("My Report", "Subtitle here", background_color="#1F4E79")
page.add_card("Total Revenue", measure("FactSales", "Total Revenue"),
              x=10, y=110, width=300, height=80,
              display_units=1000)  # NOTE: int, not str (F2 fix 2026-05-24)
# ... ask user for next visual and iterate
```

Output: save the report folder to a temp dir (default) or `--output` path. Print `report.summary()`.

**Anti-pattern (avoid)** — do NOT write a local script that uses `Path.read_text()` without `encoding=` to parse the spec YAML. That was the F5 footgun: cp1252 default on Windows silently mangles UTF-8 multi-byte sequences. `ReportBuilder.from_spec()` exists precisely to eliminate this footgun from the canonical path.

### Step 3: Deploy

Use the existing `FabricConnector` lifecycle (same path as `/pbir-report deploy`):

```python
import base64

# Build inline-base64 parts from the folder. Each part is a dict with
# path / payload / payloadType — the shape the Fabric items API expects.
files = {rel_path: file_bytes for rel_path, file_bytes in walk_folder(report_dir)}
parts = [
    {
        "path": rel_path,
        "payload": base64.b64encode(file_bytes).decode("ascii"),
        "payloadType": "InlineBase64",
    }
    for rel_path, file_bytes in files.items()
]
definition = {"parts": parts}

# Resolve target: existing or new
# NOTE: find_item_by_name signature is (workspace_id, item_type, display_name)
# — item_type before display_name, NOT the other way around.
existing = connector.client.find_item_by_name(workspace_id, "Report", name)
if existing:
    connector.client.update_item_definition(
        workspace_id, existing["id"], definition
    )
else:
    # create_item is keyword-only after workspace_id; pass definition as a dict
    # with the wrapped parts list (NOT the bare parts list)
    connector.client.create_item(
        workspace_id,
        display_name=name,
        item_type="Report",
        definition=definition,
    )
```

Poll the LRO 202 → Succeeded. Confirmation gate on `cert`/`prod` (`prod` double-confirm).

### Step 4: Visual verification (default; skip with `--no-verify`)

This is the differentiating step from the legacy ADE engine. After deploy, the agent self-screenshots the rendered report and diagnoses against the gotcha catalog.

```
mcp__playwright__browser_navigate(
    url=f"https://app.powerbi.com/groups/{workspace_id}/reports/{report_id}/ReportSection"
)
mcp__playwright__browser_wait_for(textGone="Loading your report", timeout=30000)
mcp__playwright__browser_take_screenshot(filename=f".playwright-mcp/{name}_create_0.png")
mcp__playwright__browser_snapshot()
```

Now compare the screenshot to the spec. The 6 gotchas in `core/playbooks/pbir-gotchas.md` are the **diagnostic checklist** — the engine fixes #1, #2, #3 by default, but render-time issues #4 (theme audit gap), #5 (card data placeholder = pipeline not run), and #6 (hex case red herring) can still surface. Plus new gotchas may appear — record them.

For each rendered visual:
- Title text matches the spec? (gotcha #3 fix verification)
- Background renders crisp (not pastel)? (gotcha #2 fix verification)
- Container styling applied (border, shadow if specified)? (gotcha #1 fix verification)
- Theme colors look right? (gotcha #4 detection — if not, the deploy didn't fail but theme wasn't applied; check `StaticResources` upload)
- Card values populated, not error placeholders? (gotcha #5 — if placeholders, the bound model/pipeline isn't ready, NOT a layout bug)

### Step 5: Iterate or accept

For each diagnostic finding:
- **Known gotcha** with engine fix → escalate as engine bug (write `/ops-feedback`); user decides whether to retry deploy with manual patch or accept as-is
- **New gotcha** (not in catalog) → propose appending to `core/playbooks/pbir-gotchas.md` after diagnosis; user confirms
- **Rendering correct** → done

If the user wants iterative adjustments (move visual, change color, add visual), suggest switching to `/<client>-pbi-loop edit {name} --env {env}` for the iteration phase — `/pbir-create` is one-shot build, not iterative edit.

### Step 6: Log

```
{ISO_timestamp} | pbir-create | {env} | {name}: {n_pages}p/{n_visuals}v build+deploy+verify | {ok|gotcha-N|fail}
```

If gotchas detected during verify, include the gotcha IDs in the outcome field.

## Safety

- PBIR-Legacy 404 fallback: never; surface identity issue
- `prod` deploy: double-confirm with `i-mean-it-prod` literal token
- `cert` deploy: single confirm
- `dev` deploy: no confirm
- Playwright snapshots: gitignored under `.playwright-mcp/`
- New gotchas suggested: never auto-write to canonical doc; always propose + user confirms

## Preview tracking — known unknowns

Honesty checklist for this `preview` skill, **updated post engine v2 patch (2026-05-24)**:

- [x] **Theme handling**: engine v2 supports `theme_json=...` parameter — embeds full theme content in `StaticResources` + declares `resourcePackages`. Validated by ddf-operator round 2026-05-24 — 3 reports deployed end-to-end with embedded themes, zero patch.
- [x] **Page background**: engine v2 supports `page.add_page(..., background_color=...)` → emits `page.objects.background` with `transparency: 0D`. Validated empirically.
- [x] **Banner / header textbox**: engine v2 adds `page.add_banner(...)` with multi-paragraph + container background. Validated.
- [x] **`connectionString` full form**: engine v2 supports `workspace_display_name=` + `initial_catalog=` → emits Power BI Desktop-style full connection string. Validated.
- [x] **UTF-8 in spec → engine path**: F5 fix (2026-05-24) — `ReportBuilder.from_spec()` reads YAML with explicit `encoding="utf-8"`. Previously Windows cp1252 default mangled em-dash / middle-dot / accents.
- [x] **Card `display_units` numeric**: F2 fix (2026-05-24) — `_literal(int(display_units))` cast to int, emits `1000L` not `'1000'`. "Display units = Thousands" selector now applies.
- [x] **cardVisual title duplication suppressed by default**: F1 fix (2026-05-24) — `show_container_title=None` auto-detects (suppress when title==measure name, show when different). Override via explicit kwarg.
- [ ] **Build-from-scratch battle-tested in different identity**: ddf-operator did 3 deploys on demo tenant. <seat> dogfooding on <client> tenant in flight via CR. Promotion criteria #1 (3+ real-world builds) met on demo seat — need 1+ on <seat> seat for cross-identity confirmation.
- [ ] **5+1 visual types only**: card, card_visual, bar_chart (+ variants), table, textbox, banner. Real reports usually need line_chart, donut_chart, pivot_table, slicer — port from `ade_app.platforms.powerbi.pbir_engine.visuals` on first concrete use case.
- [ ] **Field reference round-trip**: `measure()`/`column()`/`aggregation()` helpers tested in synthetic case + the engine v2 smoke test. Field names with spaces, special chars, or non-ASCII tested via F5 spec — passing on em-dash/middle-dot. Unicode in field names themselves (entity / property identifiers) TBD on first concrete case.
- [ ] **Layout helpers** (`auto_layout`, `grid_layout`): used in ADE tests + not in any production report. Manual `x/y/width/height` positioning is the safe default.
- [ ] **Schema URLs bumped to 2.8.0 / 3.2.0 / 2.1.0**: demo tenant accepted them on 3 deploys 2026-05-24. Multi-tenant compat (<client> tenant + others) TBD on first cross-tenant push.

When a finding falsifies one of the above bullets, move it to `core/playbooks/pbir-gotchas.md` (or to skill body if it's a using-this-skill rule rather than a rendering gotcha).

## Status — promotion to `stable`

This skill graduates from `preview` → `stable` when:

1. **3+ distinct real-world reports** (not synthetic) have been built end-to-end (build + deploy + verified-rendering) without manual JSON patching post-deploy.
2. **All 6 documented gotchas** are either fixed-by-default OR explicitly surfaced by the engine with remediation suggestion (not silent).
3. **At least one team member other than the author** has used the skill successfully without coaching from ops-manager / Roberto.

Track promotion progress at the bottom of `docs/backlog/2026-05-24-b2-pbir-engine-rewrite.md` (planned). On graduation, edit this skill's frontmatter `status: preview` → `status: stable`.

## Related skills

- `/<client>-pbi-loop edit` — iterative edit on existing reports (Phase B1, `preview`)
- `/pbir-report deploy` — deploy an existing `.Report` folder (legacy skill, retained `stable` for deploy only)
- `/pbir-clone-template` — clone an existing report + retarget bindings (**planned**, likely higher-confidence than this skill for <client> steady-state)
- `/powerbi-publish` — deploy semantic models (sibling concern)
- `/powerbi-directlake-create` — scaffold new DirectLake semantic model (sibling concern)

## Maturity convention

This skill is the **first** to use the explicit `status:` frontmatter field. Convention: any new skill or skill capability that hasn't been battle-tested in production carries `status: preview`. When the skill matures (criteria above), update to `status: stable`. When a successor emerges, mark `status: deprecated` with `deprecated_by:` pointer. See `core/CLAUDE.md` § "Skill maturity convention" (codified concurrently).
