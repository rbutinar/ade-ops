---
name: fabric-sql-deploy
description: Deploy SQL Scripts to a Fabric Warehouse
---

# /fabric-sql-deploy — Deploy SQL Scripts to a Fabric Warehouse

You are deploying SQL DDL (views, stored procedures, schemas) to a Microsoft Fabric Warehouse over a T-SQL endpoint (pyodbc + Azure AD).

> The required infra is now in place inside ade-ops:
> 1. ``core.connectors.fabric_warehouse.FabricWarehouseConnector`` (pyodbc + AAD).
> 2. ``core.platforms.fabric.auth.get_sql_token`` (MSAL cache, scope ``https://database.windows.net/.default``).
>
> For <client> <project> today this skill is **not relevant in practice** — <project> uses Power BI on Databricks, not a Fabric Warehouse. Kept here for parity with the ADE lab harness, ready when a <client> project starts deploying warehouse DDL.

## Prerequisites

- ODBC Driver 17 (or 18) for SQL Server installed
- `pyodbc`, `msal` Python packages
- Azure AD account with Contributor on the target warehouse
- Scripts in the project's `sql/` directory, alphabetically ordered (prefix with `01_`, `02_`, etc.)

## Usage

```
/fabric-sql-deploy {target} --env {env}
```

Where `target` is one of:
- `all` — schema + views + procedures (full deploy in order)
- `schema` — create schemas if missing
- `views` — deploy all `*view*.sql` (numeric order)
- `procedures` — deploy all `*procedure*.sql` (numeric order)
- `cleanup` — drop test/temporary objects
- `file:{path}` — deploy a single SQL file

## Behavior

### Step 1: Resolve Project & Warehouse

Read:
```yaml
overlay.fabric_warehouse.server          # e.g. abcd.datawarehouse.fabric.microsoft.com
overlay.fabric_warehouse.name            # e.g. wrh_SSP_PD
environments.{env}.platforms.fabric.workspace_id   # (for context)
```

(The overlay key `fabric_warehouse` is new — projects that need this skill add it.)

### Step 2: Authenticate (SQL scope)

Use the framework connector — it handles MSAL + pyodbc internally:

```python
from core.connectors.fabric_warehouse import FabricWarehouseConnector
connector = FabricWarehouseConnector.from_credentials(load_credentials(project_root))
conn = connector.client.connect()
```

Underneath: ``core.platforms.fabric.auth.get_sql_token_struct`` returns the AAD
token packed for the pyodbc ``ActiveDirectoryAccessToken`` attribute (1256).

### Step 3: Resolve Scripts

Locate under `{project_root}/sql/`. Expected naming:
```
sql/
  01_create_schema.sql
  02_view_*.sql
  03_procedure_*.sql
  99_cleanup.sql
```

For `target=views`, pick files matching `*view*.sql` in alphabetical order. Same logic for `procedures`.

For `target=file:{path}`, only that file.

### Step 4: Confirmation Gate

```
=== FABRIC SQL DEPLOY ===
Env:       {env}
Warehouse: {server}/{warehouse_name}
Target:    {target}
Scripts:   {n} files
  01_create_schema.sql
  02_view_material_plant.sql
  ...

⚠️ This executes DDL against the warehouse.
Proceed? (yes/no — prod double-confirm)
```

### Step 5: Execute

For each file (alphabetical order):
1. Read UTF-8
2. Split on `GO` (case-insensitive, line-anchored) — `GO` is **not** a T-SQL statement, it's a batch separator handled by SSMS / sqlcmd. pyodbc does not recognise it.
3. Execute each batch via `cursor.execute(batch)`, `conn.commit()`
4. On error: log batch + error, stop processing this file (no automatic rollback — DDL is auto-commit in Fabric Warehouse)

### Step 6: Verify

After deploy, query `INFORMATION_SCHEMA`:

```sql
SELECT TABLE_SCHEMA, TABLE_NAME
FROM INFORMATION_SCHEMA.VIEWS
WHERE TABLE_SCHEMA = '{target_schema}'
```

For each created view, run `SELECT TOP 10` to confirm it parses against the current data.

### Step 7: Log

```
{ISO_timestamp} | {role} | FABRIC-SQL-DEPLOY | {env} | {target} on {warehouse_name}: {ok_count} ok, {fail_count} fail | {ok|fail}
```

## Fabric Warehouse Compatibility

Fabric Warehouse is a DW engine, not OLTP. **Not supported**:

```sql
PRIMARY KEY                           -- declarative PKs (informational only)
IDENTITY(...)                         -- auto-increment
FOREIGN KEY                           -- referential integrity
CREATE INDEX                          -- explicit indexes
ALTER TABLE ... ADD CONSTRAINT        -- runtime constraints
```

**Supported**:
```sql
CREATE SCHEMA / DROP SCHEMA
CREATE VIEW / DROP VIEW
CREATE PROCEDURE / DROP PROCEDURE
CREATE TABLE (simple, no PK/IDENTITY/FK)
SELECT ... INTO new_table FROM source   -- materialization
```

## Script Conventions

```sql
-- 02_view_example.sql

DROP VIEW IF EXISTS automation.v_example;
GO

CREATE VIEW automation.v_example AS
SELECT col1, col2
FROM dbo.source_table;
GO
```

Use `DROP ... IF EXISTS` before `CREATE` so re-deploys are idempotent.

## Logging Details

Deployment log (one per run): `_data/analysis/deployment_log_{timestamp}.txt`.

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `Incorrect syntax near 'PRIMARY'` | DDL has PRIMARY KEY | Remove — Fabric Warehouse doesn't support it |
| 403 Forbidden | User lacks Contributor | Ask warehouse admin |
| `Invalid object name 'dbo.x'` | Referenced object missing | Deploy dependencies first |
| pyodbc `connection refused` | Network / firewall | Check VPN, Fabric endpoint reachable |
