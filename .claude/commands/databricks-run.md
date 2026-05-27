# /databricks-run — Execute Databricks Notebooks / Jobs

You are executing a **notebook run** on a Databricks cluster via MCP.

This skill is a thin wrapper around the `dde` MCP tools.

## Prerequisites

- Databricks MCP server `dde` configured in `.mcp.json` (see ONBOARDING.md step 7)
- Cluster RUNNING or startable
- Notebooks already deployed to the workspace (via `/ops-push` or `/databricks-deploy`)

## Usage

```
/databricks-run --env {env} --notebook {workspace_path}        # single notebook
/databricks-run --env {env} --layer bronze                     # all notebooks under {workspace_path}/bronze
/databricks-run --env {env} --pipeline                         # all notebooks in order (project-defined sequence)
```

Arguments via `$ARGUMENTS`:
- `--env {env}` — required: resolves workspace_path, cluster_id from project.yaml + overlay
- `--notebook {path}` — workspace path (absolute or relative to env workspace_path)
- `--layer {bronze|silver|gold|...}` — subfolder under workspace_path
- `--pipeline` — run all notebooks under workspace_path in order
- `--cluster {cluster_id}` — override cluster (default from overlay or interactive prompt)
- `--timeout {seconds}` — per-notebook timeout, default 3600

## Behavior

### Step 1: Resolve Project & Env

Find the active project (nearest ancestor of cwd with `config/project.yaml`). Read:

```yaml
environments.{env}.platforms.databricks.workspace_path
```

Apply env-var expansion (e.g. `${DATABRICKS_USER_PATH}`).

### Step 2: Resolve Cluster

Look for `cluster_id` in this order:
1. `--cluster` flag
2. Overlay key `databricks.cluster_id` in `overlays/{env}.yaml`
3. MCP `mcp__dde__list_clusters()` — prompt user to pick

Cache the resolved cluster_id for the session.

### Step 3: Pre-flight cluster state

```
mcp__dde__get_cluster_status(cluster_id="{cluster_id}")
```

If state is `TERMINATED`:
- Ask user: "Cluster {name} is terminated. Start it? (yes/no)"
- On yes: `mcp__dde__start_cluster(cluster_id=...)` then poll `get_cluster_status` every 30s until `RUNNING`
- On no: abort

### Step 4: Execute

**Single notebook** — use the Jobs API for proper tracking:

```
# Create one-time job
job = mcp__dde__manage_jobs(
  action="create",
  name=f"ade-ops run: {notebook_name}",
  tasks=[{
    "task_key": notebook_name,
    "existing_cluster_id": cluster_id,
    "notebook_task": {"notebook_path": full_workspace_path}
  }]
)

# Trigger
run = mcp__dde__manage_job_runs(action="run_now", job_id=job.job_id)

# Wait
result = mcp__dde__manage_job_runs(
  action="wait",
  run_id=run.run_id,
  timeout={timeout},
  poll_interval=10
)
```

**Pipeline / layer** — sequential execution with fail-fast:

For each notebook in order:
1. Submit and wait
2. On failure → stop, report which notebook failed and the error
3. On success → next

### Step 5: Report & Log

Output a summary table:

```
=== Databricks Run ===
Env:       {env}
Cluster:   {cluster_name} ({cluster_id})
Notebooks: {n}

[1/N] {notebook} ... SUCCESS ({duration}s)
[2/N] {notebook} ... FAILED — {error}

=== SUMMARY ===
Succeeded: X
Failed:    Y
Skipped:   Z
Duration:  {seconds}
```

Append to project `ops.log`:

```
{ISO_timestamp} | {role} | RUN | {env} | {scope}: {n} notebooks ({succeeded} ok, {failed} fail) | {ok|fail}
```

## Error Handling

| Error | Action |
|---|---|
| MCP `dde` not available | Verify `.mcp.json`, restart Claude Code |
| Cluster TERMINATED | Offer to start |
| `PERMISSION_DENIED` | Cluster owned by another user — pick a different one |
| `Notebook not found` | Notebook not deployed — suggest `/ops-push` or `/databricks-deploy` first |
| `ModuleNotFoundError` in notebook | Library missing — install via `%pip install` in notebook |

## Notes

- For SQL-only workloads, prefer `/databricks-query` (uses SQL warehouse, no cluster needed)
- The Jobs API path produces tracked runs visible in the Databricks UI Jobs section — easier to debug than `execute_databricks_command`
- Pipeline order: today it's "alphabetical within layer" — define an explicit order in `overlays/{env}.yaml` under `databricks.pipeline_order` (list of relative paths) to control execution sequence
