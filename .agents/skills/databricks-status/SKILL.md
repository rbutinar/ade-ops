---
name: databricks-status
description: Databricks Workspace Status
---

# /databricks-status — Databricks Workspace Status

You are checking the **operational status** of a Databricks workspace: clusters, recent job runs, SQL warehouses, current user.

This skill is a thin wrapper around the `databricks` MCP tools.

## Prerequisites

- Databricks MCP server `databricks` configured in `.mcp.json`

## Usage

```
/databricks-status                          # default: clusters + warehouses + user
/databricks-status clusters                 # only clusters
/databricks-status runs [--limit N]         # recent job runs (default 10)
/databricks-status warehouse                # SQL warehouses only
/databricks-status user                     # whoami
```

Arguments via `$ARGUMENTS`:
- positional `what` — one of `clusters` | `runs` | `warehouse` | `user` (default: all)
- `--limit N` — for `runs`, how many to show (default 10)

## Behavior

### Step 1: Resolve User (always)

```
mcp__databricks__get_current_user()
```

Show the authenticated user and home workspace path — verifies that the MCP profile is bound to the expected workspace.

### Step 2: Clusters

```
mcp__databricks__list_clusters()
```

Render as a table:

| Cluster | State | DBR | Driver Type | Notes |
|---|---|---|---|---|

Highlight in bold the cluster_id matching `overlays/{env}.yaml` `databricks.cluster_id` if defined (when an `--env` is supplied or guessed from the active project).

States to display: `RUNNING`, `TERMINATED`, `PENDING`, `RESIZING`, `RESTARTING`, `ERROR`, `UNKNOWN`.

### Step 3: SQL Warehouses

```
mcp__databricks__list_warehouses()
```

Render:

| Warehouse | State | Size | Auto-stop |
|---|---|---|---|

If `databricks.sql_warehouse_id` is defined in any overlay, mark the matching warehouse with `[configured]`.

### Step 4: Recent Runs

```
mcp__databricks__manage_job_runs(action="list", limit={N}, completed_only=False)
```

Render:

| Run | Status | Duration | Run page |
|---|---|---|---|

Status values: `SUCCESS`, `FAILED`, `RUNNING`, `PENDING`, `CANCELED`, `TIMEDOUT`, `INTERNAL_ERROR`.

The run page URL helps the user jump to the Databricks UI for log inspection.

## Logging

Status checks are **read-only**. Do NOT append to `ops.log` for status calls (would create noise).

## Notes

- `list_clusters()` returns all clusters visible to the user (may include shared/other-user clusters). Use overlay highlighting to disambiguate the "right" one for this project.
- `list_warehouses()` lists all warehouses the user can access.
- For lineage queries, use `/databricks-lineage` (separate skill).
- For SQL exec, use `/databricks-query`.
