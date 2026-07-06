---
name: fabric-lineage
description: Extract Lineage from Fabric Artifacts
---

# /fabric-lineage — Extract Lineage from Fabric Artifacts

You are extracting **lineage relationships** from Fabric artifacts (views, stored procedures, pipelines) and persisting them into a metadata catalog (`lineage_meta` schema).

> ⚠️ **Heavy skill — large prerequisites**:
> - Needs the Fabric Warehouse SQL connector (for `sys.sql_expression_dependencies` native method) and/or extracted DDL from `/fabric-warehouse-extract`.
> - Needs the lineage metadata catalog (`lineage_meta.nodes`, `lineage_meta.edges`) — out of scope for ade-ops today.
> - Pipeline invocation lineage needs the inventory JSON produced by `/fabric-extract-v2`.
>
> For <client> <project> today this skill is **optional**. The full data-lineage story will mature alongside the corresponding `NotebookIOParser` port (see backlog).

## Prerequisites

- One or more of:
  - Active connection to the warehouse (for native method)
  - Output of `/fabric-warehouse-extract` (for regex method)
  - Output of `/fabric-extract-v2` (for pipeline invocation method)
- `lineage_meta.nodes` + `lineage_meta.edges` tables (own bootstrap; out of ade-ops scope)

## Usage

```
/fabric-lineage {target} {method} --env {env}
```

Where:
- `target`:
  - `all` (default) — views + procedures + pipelines
  - `views` — table/view dependencies
  - `procedures` — SP materialization patterns (`SELECT INTO`, `INSERT SELECT`, dynamic SQL)
  - `pipelines` — `ExecutePipeline` / `InvokePipeline` calling other pipelines
- `method`:
  - `auto` (default) — native first, regex fallback
  - `native` — `sys.sql_expression_dependencies` (requires warehouse connection)
  - `regex` — parse stored DDL (works offline against extractions)

## What This Skill Extracts

### View lineage

| Edge | Example |
|---|---|
| Table → View | `dbo.Parts` feeds `dbo.v_PartDetails` |
| View → View | `dbo.v_BaseData` feeds `dbo.v_Summary` |
| Lakehouse → View | `lkh_SOP.Tables.SAP_Parts` feeds `dbo.v_Parts` |

### SP materialization lineage

Detect these patterns in procedure code:

```sql
-- SELECT INTO
SELECT col1, col2 INTO dbo.mat_Summary FROM dbo.v_Source

-- INSERT SELECT
INSERT INTO dbo.mat_Target SELECT * FROM dbo.v_Source

-- Dynamic SQL (detected, NOT resolved — flagged for review)
SET @sql = 'SELECT * INTO ' + @target + ' FROM ' + @source
EXEC(@sql)
```

Create edges:
- `dbo.v_Source` → `sp_Materialize` (feeds)
- `sp_Materialize` → `dbo.mat_Summary` (produces)

### Pipeline invocation lineage

Detect both formats:

```json
// Format 1: ExecutePipeline (ADF-style)
{"typeProperties": {"pipeline": {"referenceName": "{guid}", "type": "PipelineReference"}}}

// Format 2: InvokePipeline / InvokeFabricPipeline
{"typeProperties": {"pipelineId": "{guid}", "workspaceId": "{guid}"}}
```

GUIDs are resolved to display names using `inventory.json` produced by `/fabric-extract-v2`.

Edges:
- `activity.Load_L3` → `pipeline.Master_L3` (invokes)
- Edge category: `orchestration`

## Behavior

### Step 1: Resolve Sources

- Native: connect to warehouse via pyodbc + SQL token (same as `/fabric-sql-deploy`).
- Regex: locate latest extraction under `{project_root}/_data/extractions/`.
- Pipelines: locate latest inventory under `{project_root}/_data/extractions/_inventory_*.json` plus pipeline definitions.

### Step 2: Build Node + Edge Sets

For each target, collect nodes (tables, views, procedures, pipelines, activities) and edges (`feeds`, `produces`, `depends_on`, `invokes`).

Each node carries:
```json
{"key": "schema.name", "type": "view|table|procedure|pipeline|activity", "platform": "fabric", "workspace": "{ws_id}"}
```

Each edge:
```json
{"from": "node_key", "to": "node_key", "type": "feeds|produces|invokes|depends_on", "confidence": "high|medium|low"}
```

### Step 3: Persist

Upsert into `lineage_meta.nodes` and `lineage_meta.edges`. Idempotent — re-running over the same extraction must not duplicate edges.

### Step 4: Report

```
=== FABRIC LINEAGE — {env} ===

Views:       42 nodes, 87 edges
Procedures:  6 nodes, 18 materialization edges
Pipelines:   12 nodes, 25 invocation edges

Confidence:
  high:   105 edges (literal references)
  medium: 19 edges (parameterised but resolvable)
  low:    6 edges (dynamic SQL — flagged for human review)

Persisted to lineage_meta.{nodes,edges}.
```

### Step 5: Log

```
{ISO_timestamp} | {role} | FABRIC-LINEAGE | {env} | {target}/{method}: {n_nodes} nodes, {n_edges} edges | {ok|fail}
```

## Deposit into the KB

The KB's structural feed normalizes any lineage source to one record
(`nodes`/`edges`, a subset of `lineage_meta`) and deposits it under
`docs/knowledge/lineage/` (query via `/knowledge lineage <object>`). A Fabric
adapter — normalizing the nodes/edges this skill computes into that record — is
the integration point. Until it exists, this skill targets
`lineage_meta.{nodes,edges}` directly, which (together with the ade-catalog graph)
remains an **external capability not yet present in this repo**. See
`core/conventions/knowledge-base.md` → *Structural deposit*.

## Known Limitations

| Pattern | Impact | Workaround |
|---|---|---|
| Dynamic SQL (`EXEC(@sql)`) | Edge marked low-confidence, target unresolved | Use `sys.dm_*` runtime lineage if accessible |
| Cross-warehouse references | Not auto-resolved across warehouses | Pass both extractions in the same run |
| 3-part vs 2-part names | Naming inconsistency | Normalise via overlay default schema |

## Notes

- Native method (`sys.sql_expression_dependencies`) is more reliable than regex but only sees objects the user can access.
- Regex method works offline — useful for batch processing extractions from many environments.
- Pipeline lineage requires `/fabric-extract-v2` to have run first (provides GUID → name mapping).
