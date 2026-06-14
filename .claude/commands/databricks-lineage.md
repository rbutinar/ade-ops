# /databricks-lineage — Databricks Job & Notebook Lineage (Lite)

You are extracting **orchestration lineage** from Databricks: which jobs contain which tasks, which tasks execute which notebooks, and the task dependency DAG.

> ⚠️ **Lite version**: this skill ports the *job-structure* half of the ADE lab `databricks-lineage` skill. The full *data-lineage* half (notebook code → input/output tables) depends on the `NotebookIOParser` from `ade_app.platforms.databricks.parsers`, which is not yet ported to ade-ops. Full lineage will arrive in a follow-up task (see `docs/backlog/` — port `NotebookIOParser` to `core/`).
>
> For data lineage against Unity Catalog, prefer the native UC lineage views (`system.access.table_lineage`) via `/databricks-query`.

## Prerequisites

- Databricks MCP server `databricks` configured in `.mcp.json`
- Read access to Workspace + Jobs API

## Usage

```
/databricks-lineage                                  # list available jobs for selection
/databricks-lineage --job {id_or_name}               # job structure (tasks + dependencies)
/databricks-lineage --job {id} --export {file.json}  # also write lineage to JSON
```

Arguments via `$ARGUMENTS`:
- `--job {id_or_name}` — job id (numeric) or job name (string)
- `--export {path}` — write JSON output to the given file
- `--env {env}` — optional, used for context display only

## Behavior

### Step 1: Discover

If no `--job` given:

```
mcp__databricks__manage_jobs(action="list", expand_tasks=True)
```

Render a table of jobs (name, id, task count, last run state) and ask the user to pick one.

### Step 2: Get Job Definition

```
mcp__databricks__manage_jobs(action="get", job_id={id})
```

Returns the full job spec including `tasks[]` and each task's `depends_on[]`.

### Step 3: Build the DAG

For each task, extract:
- `task_key`
- `notebook_task.notebook_path` (the notebook executed)
- `existing_cluster_id` or `new_cluster` (where it runs)
- `depends_on[].task_key` (upstream tasks)

Render as:

```
JOB: {job_name} ({job_id})

DAG:
  Task: bronze_eds_gpp           [no deps]            -> /Workspace/.../bronze/bronze_eds_gpp
  Task: bronze_eds_mpv           [no deps]            -> /Workspace/.../bronze/bronze_eds_mpv
  Task: silver_gpp_cost          [bronze_eds_gpp]     -> /Workspace/.../silver/silver_gpp_cost
  Task: gold_fact_spend          [silver_gpp_cost]    -> /Workspace/.../gold/gold_fact_spend

Notebooks involved: 4
Tasks: 4 (3 with deps)
Clusters: 1 (single cluster: {cluster_id})
```

If `--export {path}` given, write the structure as JSON:

```json
{
  "job_id": 12345,
  "job_name": "...",
  "tasks": [
    {"task_key": "...", "notebook_path": "...", "depends_on": [...]}
  ],
  "edges": [
    {"from": "task_a", "to": "task_b", "type": "triggers"},
    {"from": "task_a", "to": "/notebook/path", "type": "executes"}
  ]
}
```

## Deposit into the KB

After `--export`, deposit the orchestration DAG into the knowledge base so it
becomes queryable structural lineage instead of being re-derived each session:

```bash
python -m core.knowledge deposit-lineage --from-databricks-export {file.json}
python -m core.knowledge lineage {object}        # upstream / downstream
```

This deposits the **orchestration** half only (jobs/tasks/notebooks — Jobs API,
not parsing). The **data-lineage** half (table-level reads/writes) is NOT included:
get it from Unity Catalog (`system.access.table_lineage` via `/databricks-query`)
or, once ported, `NotebookIOParser` — an ADE library **not yet present in this
repo**. See `core/conventions/knowledge-base.md` → *Structural deposit*.

## What This Skill Does NOT Cover (Yet)

- **Notebook → table lineage** (which tables a notebook reads/writes). Requires porting `NotebookIOParser` from ADE.
- **Cross-job lineage** (table produced by job A consumed by job B). Same dependency.
- **Unity Catalog lineage**. Use `/databricks-query` against `system.access.table_lineage` directly — UC tracks reads/writes at runtime and is more reliable than static parsing.

## Logging

Read-only operation. Not logged to `ops.log`.

## Future Extension

When `NotebookIOParser` lands in `core/`:
- Add `--full` flag to enable code-parsing pass
- Add `--query {table}` to query upstream/downstream for a specific table
- Add table-level nodes to the exported graph
