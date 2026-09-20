---
name: databricks-query
description: Execute SQL on a Databricks SQL Warehouse
---

# /databricks-query — Execute SQL on a Databricks SQL Warehouse

You are executing a **SQL query** on a Databricks SQL warehouse. Use it for
ad-hoc queries, schema exploration, data profiling, and validation.

## Command (start here)

The framework ships this as a runnable command — it is the path of least
resistance and works with no MCP server (plain REST from `credentials.yaml`):

```
python -m core.cli databricks-query "SELECT * FROM t LIMIT 10"
python -m core.cli databricks-query --env dev "SHOW TABLES IN {catalog}.{schema}"
python -m core.cli databricks-query --warehouse {wh_id} "SELECT 1"
```

It resolves the warehouse (`--warehouse` > overlay `databricks.sql_warehouse_id`
> auto-pick the best running one), applies the env's catalog/schema as defaults,
runs the statement to completion, and prints a markdown table. DDL/DML is logged
to `ops.log`; read-only queries are not.

**When the `databricks` MCP server is loaded, prefer it** — richer table introspection
(`get_table_details`), warehouse picking (`get_best_warehouse`), and multi-statement
helpers. The MCP path is documented below; the CLI is the dependable fallback and
the recommended default when no MCP is configured.

## Prerequisites

- Databricks MCP server `databricks` configured in `.mcp.json`
- A SQL warehouse accessible to the authenticated user (auto-discovered if not configured)

## Usage

```
/databricks-query {SQL}                              # execute against default warehouse
/databricks-query --env {env} {SQL}                  # use env's catalog/schema as defaults
/databricks-query --warehouse {wh_id} {SQL}          # explicit warehouse
/databricks-query --explain {SQL}                    # show explain plan instead of executing
```

Arguments via `$ARGUMENTS`:
- positional — the SQL query (multiline supported with quotes)
- `--env {env}` — pulls catalog/schema defaults from `project.yaml` + overlay
- `--warehouse {wh_id}` — override warehouse
- `--catalog {name}` — override default catalog for unqualified table names
- `--schema {name}` — override default schema for unqualified table names

## Behavior

### Step 1: Resolve Project & Env (if `--env` given)

Read:
```yaml
environments.{env}.platforms.databricks.catalog
environments.{env}.platforms.databricks.schema
```

Use as defaults for `catalog`/`schema` so unqualified table names resolve correctly.

### Step 2: Resolve Warehouse

In order:
1. `--warehouse` flag
2. Overlay key `databricks.sql_warehouse_id` in `overlays/{env}.yaml`
3. `mcp__databricks__get_best_warehouse()` — returns the best available (prefers RUNNING, then STARTING, smallest size)

### Step 3: Execute

```
mcp__databricks__execute_sql(
  sql_query={query},
  warehouse_id={warehouse_id},
  catalog={catalog},     # if --env or --catalog
  schema={schema}        # if --env or --schema
)
```

For multi-statement scripts, use `execute_sql_multi`.

### Step 4: Render Results

- Display column headers + rows in a markdown table
- Truncate large result sets at 50 rows; show row count
- For wide schemas (many columns), pivot or summarize on request
- Print warehouse used + duration

### Step 5: --explain mode

If `--explain` is set, run `EXPLAIN {query}` and pretty-print the plan instead of executing.

### MCP signature gotchas

- `execute_sql` takes **`sql_query`**, not `query` — passing `query` (a natural
  first guess) fails with a pydantic `ValidationError`.
- Warehouse discovery: `manage_sql_warehouse` has **no `list` action**
  (create/modify/delete only). Use `mcp__databricks__get_best_warehouse()` to pick one,
  or the REST endpoint `GET /api/2.0/sql/warehouses` to enumerate.

## Common Patterns

| Goal | Query |
|---|---|
| List tables in schema | `SHOW TABLES IN {catalog}.{schema}` |
| Describe table | `DESCRIBE EXTENDED {catalog}.{schema}.{table}` |
| Row count | `SELECT COUNT(*) FROM {table}` |
| Sample | `SELECT * FROM {table} LIMIT 10` |
| Top values | `SELECT col, COUNT(*) FROM {table} GROUP BY col ORDER BY 2 DESC LIMIT 20` |
| Find duplicates | `SELECT key, COUNT(*) c FROM {table} GROUP BY key HAVING c > 1` |
| DQ check | `SELECT _dq_*, COUNT(*) FROM {table} GROUP BY ALL` |

For richer table introspection (DDL, statistics, value distributions), use:

```
mcp__databricks__get_table_details(
  catalog={catalog},
  schema={schema},
  table_names=["{table}"],
  table_stat_level="SIMPLE"
)
```

## REST fallback (no MCP)

If the `databricks` MCP server is not configured, use the **command above**
(`python -m core.cli databricks-query …`) — it wraps exactly this REST path.
The lower-level connector call it builds on (SQL Statement Execution API
`/api/2.0/sql/statements`, submit + poll) is shown here for when you need to
drive it from your own script:

```python
from core.engine.config import load_credentials
from core.connectors.databricks import DatabricksConnector

conn = DatabricksConnector.from_credentials(
    load_credentials(project_root), host=db_host  # from project.yaml platforms.databricks.host
)
out = conn.run_query(sql, warehouse_id, catalog=catalog, schema=schema)
# out = {"columns": [...], "rows": [[...]], "row_count": int, "truncated": bool}
```

Render `out["columns"]` + `out["rows"]` as in Step 4. The connector blocks until
the statement terminates and raises RuntimeError on FAILED/CANCELED. Warehouse
discovery without MCP: REST `GET /api/2.0/sql/warehouses` (see *MCP signature
gotchas*). Use this whenever the `mcp__databricks__*` tools are not loaded.

## Logging

Read-only queries (`SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`) are **not logged** to `ops.log` — would create noise.

DDL/DML queries (`CREATE`, `DROP`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `ALTER`):

```
{ISO_timestamp} | {role} | SQL-WRITE | {env|--} | {warehouse}: {first 80 chars of query} | {ok|fail}
```

**Always confirm with the user before executing a write query** that targets `{env} == cert | prod`.

## Notes

- No cluster needed — SQL warehouses are independent compute
- A stopped warehouse auto-starts (~10-30s) on first query
- Results are returned as structured JSON; large result sets should use `LIMIT`
- For schema exploration `/databricks-query --env {env} "SHOW SCHEMAS IN {catalog}"` is a good starting point
