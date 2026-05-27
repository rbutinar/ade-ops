# /fabric-extract-v2 — Parallel Fabric Workspace Metadata Extraction

You are extracting **metadata** (workspaces, semantic models, notebooks, pipelines, report visuals) from one or more Microsoft Fabric workspaces into a structured catalog.

> ⚠️ **Heavy skill**: this is a port of the ADE lab `fabric-extract-v2` workflow. It depends on the `ade_app.platforms.fabric.*` modules and on a SQL Server backend (`fabric_infra` + `powerbi_meta` schemas). **Not yet self-contained** inside ade-ops — see backlog tasks for porting `msal_cache` (auth), `TokenManager`/`CheckpointManager` (extraction infra), and the metadata schema.
>
> For <client> <project> today this skill is **optional** — it's used to populate a corporate-wide Fabric catalog, not for <project>-specific operations. Keep it documented so the porting path is clear.

## Prerequisites

- Python: `msal`, `httpx`, `pyodbc`
- `core.platforms.fabric.auth.get_fabric_token` (or the framework's `FabricConnector` once `msal_cache` is ported)
- SQL Server with `fabric_infra` and `powerbi_meta` schemas (DB+schema bootstrap is out of scope for ade-ops today — backlog item)
- Contributor access on the workspaces being extracted

## Usage

```
/fabric-extract-v2 [phase] [--workspace-filter {substring}]
```

Phases:
- `inventory` (~1-2 min for 75 workspaces) — workspace + item catalog via REST (no item content)
- `content` — parallel extraction of SemanticModel TMDL, Notebook source, Pipeline + activity definitions, Report (PBIR) pages/visuals
- `enrich` — post-extraction lineage (M partitions → data sources, DAX → dependencies); operates on already-extracted TMDL files
- `both` (default) — inventory + content
- `all` — inventory + content + enrich

## Behavior

### Phase 1 — Inventory

For each workspace matching `--workspace-filter`:

1. `mcp__dde__...` is **not** used here — we go through `FabricConnector.client.list_workspaces()` / `list_items()` directly.
2. Persist `workspaces`, item counts by type, last-modified to `fabric_infra.workspaces` + `fabric_infra.items`.
3. Snapshot to `_data/extractions/_inventory_{timestamp}.json` for offline review.

### Phase 2 — Content (parallel)

For each item discovered in Phase 1, call `connector.client.get_item_definition(workspace_id, item_id)` to get the inline-base64 parts, then:

- **SemanticModel** — decode TMDL parts → parse tables, columns, measures, relationships; persist to `powerbi_meta.{datasets,tables,columns,measures,relationships}`.
- **Notebook** — decode `notebook-content.py` (Spark) or `notebook.ipynb`; store source code.
- **Pipeline** — decode `pipeline-content.json`; parse activities into `fabric_infra.pipelines` + `pipeline_activities`.
- **Report** — decode PBIR parts (`pages.json`, visuals); persist `powerbi_meta.{reports,report_pages,visuals}` with measure bindings.

**LRO pattern** (critical):
```
POST .../getDefinition → 202 + Location header
poll Location until status == "Succeeded"
GET /v1/operations/{operationId}/result → actual definition
```
Do **not** rely on `resourceLocation` — it's null for `getDefinition`.

Use a `CheckpointManager` for resume-after-interruption. Force-refresh tokens on 401 (the `FabricConnector` already does this; if calling REST directly, replicate the pattern from `core/connectors/fabric.py`).

### Phase 3 — Enrich

Operate on already-extracted TMDL/PBIR files:
- **M partition parsing** — extract source connections (`lakehouse → table`, `warehouse → table`).
- **DAX dependency parsing** — extract referenced tables/measures from DAX expressions.
- Populate `powerbi_meta.data_sources`, `powerbi_meta.depends_on_tables`, `powerbi_meta.depends_on_measures`.

### Output

Imports directly to SQL Server (default backend):
- `fabric_infra.workspaces / items / lakehouses / warehouses / pipelines / notebooks / pipeline_activities`
- `powerbi_meta.reports / datasets / tables / columns / measures / relationships / report_pages / visuals / data_sources`

Snapshots to `_data/extractions/` for offline review (gitignored).

## Logging

```
{ISO_timestamp} | {role} | FABRIC-EXTRACT | -- | phase={phase} workspaces={n}: items={n} | {ok|fail}
```

## Port Status / Backlog

- `msal_cache` (token cache) → planned in `core/platforms/fabric/auth/`
- `TokenManager` / `CheckpointManager` → planned in `core/platforms/fabric/extract/`
- Metadata catalog schema (SQL Server) → out of scope for ade-ops today; users must bootstrap their own

## Notes

- Token scope: `analysis.windows.net/powerbi/api/.default` (PBI Service) works on ALL workspaces; `https://api.fabric.microsoft.com` (Fabric API) works only on Premium/Fabric capacity.
- Windows: use `\\?\` prefix for paths > 260 chars (common with long workspace + TMDL filenames).
- Excel export: `python tasks/generate_pbi_excel.py` produces 6 sheets (Summary, Reports, Measures, Tables, Relationships, Visuals).
