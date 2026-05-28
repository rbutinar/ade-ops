# /fabric-warehouse-extract — Extract Warehouse DDL & Metadata

You are extracting DDL (views, procedures), object lists, and dependencies from a Microsoft Fabric Warehouse for analysis, documentation, or backup.

> Same prerequisites as `/fabric-sql-deploy` — both now ship inside ade-ops (``core.connectors.fabric_warehouse`` + ``core.platforms.fabric.auth``). Not relevant for <client> <project> today; kept for parity.

## Prerequisites

- `pyodbc`, `msal`, `pyyaml` installed
- ODBC Driver 17/18 for SQL Server
- Read access on the warehouse (Viewer role sufficient for read-only extraction)
- `materialization_config.yaml` at the project root **optional** — used to compare extracted objects against a target list

## Usage

```
/fabric-warehouse-extract {target} --env {env}
```

Where `target` is optional:
- `all` (default) — extract all configured schemas
- `{schema_name}` — extract a specific schema (e.g. `dbo`, `automation`)
- `system` — system catalog only (INFORMATION_SCHEMA, sys.objects)

## Behavior

### Step 1: Resolve & Connect

Same as `/fabric-sql-deploy`. Read `overlay.fabric_warehouse.{server,name}` and schemas list.

### Step 2: Extract

For each target schema:

**Views**:
```sql
SELECT
    SCHEMA_NAME(v.schema_id) AS schema_name,
    v.name,
    v.create_date,
    v.modify_date,
    m.definition
FROM sys.views v
JOIN sys.sql_modules m ON v.object_id = m.object_id
WHERE SCHEMA_NAME(v.schema_id) = '{schema}'
```

**Procedures**: same pattern via `sys.procedures`.

**Tables**: name, schema, row counts (via `sys.partitions` or a fallback `COUNT(*)` per-table query).

**Dependencies** (light): parse view definitions for `FROM`/`JOIN` clauses with regex; flag dynamic SQL as low-confidence.

### Step 3: Save Outputs

Under `{project_root}/_data/extractions/`:

```
_data/extractions/{schema}/{schema}_extraction_{timestamp}.json
_data/extractions/{schema}/ddl/{timestamp}/*.sql       # one file per view/procedure
_data/snapshots/{timestamp}/full_extraction.json       # combined
```

If `materialization_config.yaml` exists, also write:
```
_data/analysis/comparison_{timestamp}.json
```

That comparison tells the user which targeted objects are missing / found.

### Step 4: Report

```
=== FABRIC WAREHOUSE EXTRACT ===
Env:       {env}
Warehouse: {server}/{warehouse_name}
Target:    {target}

Schema summary:
  dbo:        52 views, 0 procs, 0 tables
  automation:  6 views, 6 procs, 3 tables
  ...

Extraction vs config (if present):
  Found:   {n}/{N}
  Missing: {list}

Outputs:
  _data/extractions/...
  _data/snapshots/{timestamp}/
```

### Step 5: Log

```
{ISO_timestamp} | {role} | FABRIC-WH-EXTRACT | {env} | {target} on {warehouse_name}: {n_objects} extracted | {ok|fail}
```

## Output Schema

`{schema}_extraction_{timestamp}.json` shape:
```json
{
  "extraction_info": {"timestamp": "...", "database": "...", "schema": "..."},
  "summary": {"views": N, "procedures": N, "tables": N},
  "objects": {
    "views": [{"name": "...", "definition": "CREATE VIEW...", "created": "...", "modified": "..."}],
    "procedures": [...],
    "tables": [{"name": "...", "rowcount": N}]
  }
}
```

## Notes

- Read-only — no warehouse mutation.
- `_data/` is gitignored — extracted DDL may contain sensitive identifiers.
- For very large schemas (SAPECC-style with thousands of tables), only metadata is extracted, not row data.
- DDL output is UTF-8 — encoding matters for non-ASCII identifiers.
