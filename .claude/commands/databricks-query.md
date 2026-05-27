# /databricks-query — Execute SQL on a Databricks SQL Warehouse

You are executing a **SQL query** on a Databricks SQL warehouse via MCP.

This skill is a thin wrapper around the `dde` MCP tools. Use it for ad-hoc queries, schema exploration, data profiling, and validation.

## Prerequisites

- Databricks MCP server `dde` configured in `.mcp.json`
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
3. `mcp__dde__get_best_warehouse()` — returns the best available (prefers RUNNING, then STARTING, smallest size)

### Step 3: Execute

```
mcp__dde__execute_sql(
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
mcp__dde__get_table_details(
  catalog={catalog},
  schema={schema},
  table_names=["{table}"],
  table_stat_level="SIMPLE"
)
```

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
