---
name: pbir-clone-template
description: Clone a known-good report + retarget bindings (preview)
status: preview
since: 2026-05-24
related: pbir-create, <client>-pbi-loop, pbir-report, pbir-add-page
---

# /pbir-clone-template — Clone a known-good report + retarget bindings (preview)

You are cloning an existing `.Report` folder that already renders correctly, then rewriting its data bindings (entity, property, model, optionally page/visual titles) to produce a new report pointed at different data. The cloned report inherits the source's layout, theme embedding, and rendering quality — only what you explicitly change, changes.

This is the **empirical pattern Roberto used for years in production** to build new <client> reports reliably, now codified. Likely default for <client> steady-state work where a known-good template exists.

> **Status: `preview`**. The underlying engine (`core.platforms.powerbi.pbir_engine.clone.clone_report_template`) has a green synthetic smoke test (3 visual types, full rebind chain — entity + property + queryRef + filterConfig + page name + visual title + model). First production use IS the empirical validation. Watch for: complex visual types not in the smoke test (donut, line, pivot, slicer, treemap), filterConfig variants, theme-coupled visuals with hard-coded data colors that survive cloning unintentionally.

## When to use this skill

| Scenario | Use |
|---|---|
| You have a report that renders well, want a similar one for a different domain | **This skill** |
| Promote an existing report across envs (DEV→CERT→PROD, same shape) | `/ops-push --env {target}` (overlay handles env-specific naming) |
| Build a brand-new report with no template | `/pbir-create` (preview) — accepts the layout risk |
| Iterate on an existing report (no new report needed) | `/<client>-pbi-loop edit` (preview) |
| Add a single page to an existing report | manual + `/<client>-pbi-loop edit` today; `/pbir-add-page` (planned) |

## Prerequisites

- A source `.Report` folder (under `state/{env}/power_bi/Report/` after a prior pull, or `src/power_bi/`, or any local PBIR folder)
- Target Fabric workspace + semantic model already deployed (or pass `--no-deploy` to stop at the clone-folder step)
- `FabricConnector` credentials for the deploy phase
- For visual verification: Playwright MCP entry in `.mcp.json`

## Usage

```
# Mode 1: full rebind (entities + properties + model + cosmetic renames)
/pbir-clone-template {new-report-name} \
    --template {path/to/Source.Report} \
    --env {env} \
    --new-model-id {guid} \
    --rebind-entities OldTable1:NewTable1,OldTable2:NewTable2 \
    --rebind-properties NewTable1:OldProp1=NewProp1;OldProp2=NewProp2 \
    --rename-pages "Old Page Name:New Page Name" \
    --rename-visuals "Old Title:New Title"

# Mode 2: model-only rebind (same fields, different model — promote pattern)
/pbir-clone-template {new-report-name} \
    --template {path/to/Source.Report} \
    --env {env} \
    --new-model-id {guid}

# Mode 3: spec file (all options in YAML)
/pbir-clone-template --spec clone.yaml --env {env}

# Skip deploy (just produce the folder)
/pbir-clone-template ... --no-deploy
```

## Spec file format (`clone.yaml`)

```yaml
new_report_name: SpendChurn_QA
template: state/cert/power_bi/Report/Revenue_QA.Report
env: cert

# Rebind table references. Keys = current names in template (post template-build).
rebind_entities:
  FactSales: FactCategorySpend
  DimProduct: DimCategory

# Rebind columns/measures within entities. Outer key is the NEW entity name
# (after entity rebind). Inner keys are property names on that entity.
rebind_properties:
  FactCategorySpend:
    Total Revenue: Total Category Spend
    channel: category_channel
  DimCategory:
    category: category_name

# Optional model rebind. If omitted, the template's existing model binding is kept.
new_model_id: 12fd6e5e-d238-4340-a917-57e16f651016
new_workspace_display_name: <ENV>_<DOMAIN>_<AREA>_<PROJECT>
new_initial_catalog: ssp_qa

# Cosmetic — page display names.
rename_pages:
  Overview: Category Spend Overview

# Cosmetic — visual title text overrides. Match is exact-string on current title.
rename_visuals:
  Total Revenue: Total Category Spend
  Revenue by Channel: Spend by Category Channel
```

## Behavior

### Step 0: Resolve project + template + target

1. Find active project (`config/project.yaml` walking up from cwd)
2. Validate `--template` path: must be a `.Report` folder, must exist, must contain `definition/` subtree
3. Validate `--env` against `environments.{env}.platforms.fabric.auth`
4. Resolve target workspace from overlay (`overlays/{env}.yaml power_bi.report_workspace_id`)
5. Validate `--new-model-id` format (GUID); resolve the model exists in target workspace (sanity)
6. Resolve `new_report_name` — destination folder `src/power_bi/{name}.Report/` (default) or `--output` override
7. Refuse to overwrite if destination exists; require `--force` to overwrite (with explicit confirmation)

### Step 1: Pre-flight identity check

Same as the iterative PBI loop skill Step 1 (fail-fast on 404 with explicit hint — never silent PBIR-Legacy fallback).

### Step 2: Clone via engine

```python
from core.platforms.powerbi.pbir_engine import clone_report_template

cloned_dir = clone_report_template(
    template_path=template_path,
    output_path=output_parent,
    rebind_entities=rebind_entities,
    rebind_properties=rebind_properties,
    new_model_id=new_model_id,
    new_workspace_display_name=new_workspace_display_name,
    new_initial_catalog=new_initial_catalog,
    rename_pages=rename_pages,
    rename_visuals=rename_visuals,
    new_report_name=new_report_name,
    strip_sidecar=True,
)
```

What changes in the cloned folder vs the template:

| Element | Change |
|---|---|
| `.platform.metadata.displayName` | Set to `new_report_name` (if provided) |
| `.platform.config.logicalId` | Regenerated fresh UUID (avoid Fabric item collision) |
| `definition.pbir` `datasetReference` | Rewritten to new model (if `new_model_id`) |
| `visual.json` `Entity` / `entity` fields | Rewritten per `rebind_entities` |
| `visual.json` `Property` / `property` fields | Rewritten per `rebind_properties` (entity-scoped) |
| `visual.json` `queryRef` / `nativeQueryRef` | Rewritten per both rebinds |
| `visual.json` `filterConfig.filters[].field` | Rewritten (uses same entity / property recursion) |
| `page.json` `displayName` | Replaced per `rename_pages` |
| `visualContainerObjects.title[].properties.text` | Replaced per `rename_visuals` (exact-string match) |
| `.fabric.json` sidecar | **Deleted** (provenance is misleading post-clone) |
| Everything else | Verbatim copy |

### Step 3: Preview the diff (suggested)

Before deploy, show the user:

```
Cloned: SpendChurn_QA.Report (from Revenue_QA.Report)

Rebinds applied:
  Entity: FactSales -> FactCategorySpend
  Entity: DimProduct -> DimCategory
  Property: FactCategorySpend.Total Revenue -> FactCategorySpend.Total Category Spend
  Property: FactCategorySpend.channel -> FactCategorySpend.category_channel
  Property: DimCategory.category -> DimCategory.category_name
  Model: bound to 12fd6e5e... in <ENV>_<DOMAIN>_<AREA>_<PROJECT> (initial catalog: ssp_qa)
  Pages renamed: 1 ("Overview" -> "Category Spend Overview")
  Visual titles renamed: 2

Visuals: 7 (3 cards + 2 column charts + 1 table + 1 banner)
Output: src/power_bi/SpendChurn_QA.Report/
```

User confirms before deploy.

### Step 4: Deploy

Use `FabricConnector` (same flow as `/pbir-create` / `/pbir-report deploy`):

```python
from core.connectors.fabric import FabricConnector
connector = FabricConnector.from_credentials(...)

# Walk folder + base64 encode
parts = []
for fp in sorted(cloned_dir.rglob("*")):
    if not fp.is_file():
        continue
    rel = fp.relative_to(cloned_dir).as_posix()
    if rel == ".platform":
        continue
    parts.append({
        "path": rel,
        "payload": base64.b64encode(fp.read_bytes()).decode("ascii"),
        "payloadType": "InlineBase64",
    })

# create or update
existing = next((i for i in connector.client.list_items(ws_id, item_type="Report")
                 if i["displayName"] == new_report_name), None)
if existing:
    connector.client.update_item_definition(ws_id, existing["id"], {"parts": parts})
else:
    connector.client.create_item(ws_id, new_report_name, "Report", {"parts": parts})
```

Confirmation gates same as `/pbir-create`: dev no confirm, cert single, prod `i-mean-it-prod` token.

### Step 5: Visual verification (default; skip with `--no-verify`)

Open the new report in Playwright + compare against the template. Loop integrated:

```
mcp__playwright__browser_navigate(
    url=f"https://app.powerbi.com/groups/{ws_id}/reports/{new_report_id}/ReportSection?ctid={tenant_id}&experience=power-bi"
)
mcp__playwright__browser_wait_for(textGone="Loading your report")
mcp__playwright__browser_take_screenshot(filename=f".playwright-mcp/{new_report_name}_clone.png")
```

Diagnostic comparison:
- Banner / page background / theme survived the clone? (should be: nothing changed there)
- Card values populate from the new model? (if "Error fetching data" placeholders — model binding wrong; check `new_model_id`)
- Visual titles show the renamed text? (validate `rename_visuals` worked)
- Cross-page navigation still works?

### Step 6: Log

```
{ISO_timestamp} | pbir-clone-template | {env} | {new_report_name} <- {template_base}: {n_rebinds} rebinds, {n_renames} renames | {ok|fail}
```

## Anti-goals (current MVP, may relax in future)

- **No structural rewrite**: clone preserves visual count, types, and positions. Adding/removing visuals = separate concern (`/<client>-pbi-loop edit` after clone).
- **No theme rebrand**: cloned report keeps the template's embedded theme. To change theme, edit the cloned `StaticResources/SharedResources/BaseThemes/{theme}.json` post-clone.
- **No automatic field-existence validation**: skill does NOT verify that `NewTable.NewProp` exists on the new model before deploy. If it doesn't, visuals render with "Cannot find" placeholders. Future: optional pre-deploy DAX `EVALUATE INFO.MEASURES()` validation (data plane).
- **No `--clone-from-page`**: cloning a single page from one report into another is `/pbir-add-page` territory (backlog).
- **No PBIR-Legacy template support**: clone assumes modern PBIR shape. Legacy reports must be republished as PBIR first (via Power BI Desktop save-as).

## Preview tracking — known unknowns

- [ ] Visual types beyond card / cardVisual / bar/column chart / table / textbox / banner: untested. donut, line, pivot, slicer, treemap may have additional `query.queryState` shapes (e.g. `Series`, `Group`, `Columns`) the rebind walker handles uniformly today via recursion, but specific edge cases not validated.
- [ ] Reports with `StaticResources/SharedResources/` beyond `BaseThemes/`: clone copies verbatim; if there's a binding inside those (e.g. a custom visual referenced by path) the rebind doesn't touch it.
- [ ] Templates with `byPath` model reference: clone with `--new-model-id` rewrites to `byConnection`; templates that intentionally stayed `byPath` (sibling SemanticModel folder) get a behaviour change. Acceptable for the common case but watch on first byPath template.
- [ ] Cross-env promotion via clone: today the canonical promotion path is `/ops-push --env {target}` (overlay-driven). This skill's clone with `--new-model-id` is functionally close but uses a different mechanism. Watch for divergence on first cross-env clone.
- [ ] FilterConfig variants: smoke test covers basic `filterConfig.filters[].field.{Measure|Column}.Expression.SourceRef.Entity`. Top-N filters, relative-date filters, hierarchy filters may carry references in different shapes — recursion walks them but specifically untested.

## Status — promotion to `stable`

This skill graduates from `preview` → `stable` when:

1. **3+ distinct production clones** end-to-end (clone + deploy + Playwright verify) without manual JSON patching post-clone.
2. **At least 2 different visual types beyond the smoke-tested 6** exercised (e.g. donut, slicer).
3. **At least one cross-env clone** (e.g. CERT template → PROD clone with model rebind) validated.

Track on a future `docs/backlog/pbir-clone-template-promotion.md` as criteria meet evidence.

## Related skills

- `/pbir-create` (preview) — build-from-scratch when no template exists
- `/<client>-pbi-loop edit` (preview) — iterate on the cloned report after deploy
- `/pbir-report deploy` (stable) — deploy a `.Report` folder (legacy skill, retained)
- `/pbir-add-page` (planned, backlog) — incremental page addition
- `/ops-push --env {target}` (stable) — overlay-driven env promotion (different mechanism, same goal for the cross-env case)

## Maturity convention

Same `status:` framework as `/pbir-create`. Honest disclosure principle applies — known unknowns listed above, not vague.
