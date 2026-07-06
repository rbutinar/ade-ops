---
description: Execute a Fabric Data Pipeline
name: fabric-pipeline-run
status: preview
since: 2026-05-28
related: fabric-pipeline-deploy, fabric-pipeline-poll, fabric-items-list
---

# /fabric-pipeline-run — Execute a Fabric Data Pipeline

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/pipeline_deploy_run.py`
> (DDF demo pipeline kick-off).

## What it does

Triggers an on-demand run of a Microsoft Fabric Data Pipeline. Returns the
`run_id` immediately; the run itself executes asynchronously. Use
`/fabric-pipeline-poll` to track the run to terminal state.

The Fabric counterpart of `/databricks-run` for pipelines.

## When to use

- After `/fabric-pipeline-deploy` to verify the pipeline works end-to-end
- Manual re-run after a failure (with corrected notebooks / definitions)
- CI / scheduled runs invoked via cron + this skill in `--yes` mode

## When NOT to use

- For scheduled execution at fixed cadence — configure a pipeline trigger
  (separate API not wrapped here)
- For running individual notebooks — use `/databricks-run` (Databricks
  Job) or call notebooks via pipeline activity

## Prerequisites

- `FabricConnector` credentials
- Pipeline already deployed (`fabric-pipeline-deploy` or pre-existing)
- The identity must be Member / Contributor / Admin on the workspace

## Usage

```
/fabric-pipeline-run --pipeline-id <id> --env dev
/fabric-pipeline-run --pipeline-name "acme_medallion" --env dev    # resolve id from name
/fabric-pipeline-run --pipeline-id <id> --env dev --wait            # kick off + auto-poll to terminal
/fabric-pipeline-run --pipeline-id <id> --env dev --parameters params.json   # parameterised run
```

## Pipeline summary

1. Resolve workspace id (from `--workspace-id` or overlay)
2. Resolve pipeline id (from `--pipeline-id` or `--pipeline-name` via
   `find_item_by_name(ws, name, "DataPipeline")`)
3. Load project + credentials, build connector
4. Optional: read parameters from `--parameters <file.json>` (key-value
   pairs passed to pipeline activities)
5. Echo plan + confirm (skip with `--yes`)
6. POST `/v1/workspaces/{ws}/items/{pipeline_id}/jobs/instances?jobType=Pipeline`
   with body `{"executionData": {"parameters": {...}}}` (empty if no params)
7. Capture `run_id` from response Location header / body
8. If `--wait`: invoke `/fabric-pipeline-poll --pipeline-id <id> --run-id <run_id>`
   inline and surface the terminal status
9. Surface: pipeline name + run_id + (status if --wait)
10. ops.log:
    - kick-off: `PIPELINE-RUN | <env or -> | fabric: ws=<id> pid=<id> run=<id> action=trigger | ok`
    - terminal (if --wait): `PIPELINE-RUN | <env or -> | fabric: ws=<id> pid=<id> run=<id> terminal=<status> | <ok|fail>`

## Preview tracking — known unknowns

1. **Parameter type coercion**: V1 passes parameter values as strings.
   Fabric pipelines may need typed params (int, bool). Caller responsible
   for serialisation today.
2. **Concurrent runs**: triggering a second run while the first is in
   progress is allowed by Fabric. V1 does not warn — future: add
   `--no-concurrent` flag that refuses if a run is already in flight.
3. **Failure surfacing without --wait**: kick-off returns immediately so
   you see only "triggered ok"; the actual failure (if any) shows up
   minutes later. The operator must remember to poll.

## Status — promotion to `stable`

1. 3+ runs kicked off across distinct pipelines / workspaces
2. The `--wait` flow tested end-to-end with both Succeeded and Failed
   terminal states (and ops.log lines correct for each)
3. ops.log entries capture the right correlation ids for audit

ARGUMENTS: $ARGUMENTS
