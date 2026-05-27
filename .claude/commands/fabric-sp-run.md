# /fabric-sp-run — Execute Stored Procedures on a Fabric Warehouse

You are executing a stored procedure (or a chain of them) on a Microsoft Fabric Warehouse, optionally monitoring the procedure's own log table for progress.

> Same prerequisites as `/fabric-sql-deploy` — both now ship inside ade-ops (``core.connectors.fabric_warehouse`` + ``core.platforms.fabric.auth.get_sql_token``). Not relevant for <client> <project> today.

## Prerequisites

- Stored procedures already deployed to the warehouse (`/fabric-sql-deploy procedures`)
- Optional: a log table the procedure writes to (e.g. `automation.Materialization_Execution_Log`) for live monitoring
- Same auth/connection setup as `/fabric-sql-deploy`

## Usage

```
/fabric-sp-run {target} --env {env}
```

Where `target` is:
- `sp_name` — execute a specific procedure
- `pipeline` — execute the master pipeline defined in `materialization_config.yaml`
- `cluster:{n}` — execute one cluster from the pipeline config
- `refresh` — execute named refresh procedures (e.g. `sp_refresh_all_cdc`)

Optional flags:
- `--param key=value` (repeatable) — bind procedure parameters
- `--no-monitor` — skip log-table polling

## Behavior

### Step 1: Resolve & Connect

Same as `/fabric-sql-deploy`: load warehouse from overlay, get SQL token, open pyodbc connection.

### Step 2: Resolve Target

- `sp_name` — direct, no config needed.
- `pipeline` / `cluster:{n}` — read `materialization_config.yaml` at the project root:

```yaml
materialization:
  master_sp: automation.sp_Materialize_All_Clusters_Master
  log_table: automation.Materialization_Execution_Log
schemas:
  automation:
    clusters:
      - id: 1
        name: "Demand & Supply"
        sp: automation.sp_Materialize_Cluster_1_DemandSupply
        depends_on: []
      - id: 2
        ...
```

For `cluster:{n}`, pick the matching `sp` from the cluster list.

### Step 3: Execute

```python
cursor = conn.cursor()
cursor.execute(f"EXEC {sp_name}{params_clause}")
# DO NOT call cursor.commit() until execute returns or raises
```

Capture the start time and (if available) the `ExecutionID` the procedure logs to its log table.

### Step 4: Monitor (if `log_table` configured and `--no-monitor` not set)

Every 5s, poll:

```sql
SELECT TOP 100 *
FROM {log_table}
WHERE ExecutionID = @current_execution
ORDER BY StartTime
```

Render rows incrementally — view name, row count, duration, status. Stop on a terminal status (`Completed` / `Failed`).

### Step 5: Final Report

```
=== FABRIC SP RUN ===
Warehouse: {server}/{warehouse_name}
Procedure: {sp_name}
Env:       {env}
Duration:  {seconds}s
ExecutionID: {id}

Per-cluster summary:
  Cluster 1 Demand & Supply: 11 views, 23.4s, all SUCCESS
  Cluster 2 BOM & Sourcing:  10 views, 29.1s, all SUCCESS
  ...

Totals: {n_views} views, {n_rows} rows, {ok_count} ok, {fail_count} fail
```

On failure: surface the failed view + error message, and offer the resume command:

> ❌ Cluster {N} failed at `{view}`: {error}
> Resume with: `/fabric-sp-run cluster:{N} --env {env}` (after fixing the underlying object)

### Step 6: Log

```
{ISO_timestamp} | {role} | FABRIC-SP-RUN | {env} | {sp_name}: {n} views ({ok} ok, {fail} fail), {duration}s | {ok|fail}
```

## Notes

- SPs execute server-side — no data transfer to the client.
- Materialization typically uses `SELECT INTO` (fast, no transaction log overhead).
- The log table is append-only — concurrent runs are supported with separate `ExecutionID`s.
- Procedure can call other procedures (the master SP invokes per-cluster SPs).

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `Invalid object name 'dbo.x'` | Referenced view/table missing | Deploy dependency first |
| 403 | User lacks EXECUTE on the procedure | Request grant from admin |
| Timeout | Query too slow | Check joins, source row counts; consider warehouse compute scale |
| Log table doesn't exist | SP doesn't log execution | Run with `--no-monitor` |
