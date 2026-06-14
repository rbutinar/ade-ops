---
name: fabric-pipeline-poll
status: preview
since: 2026-05-28
related: fabric-pipeline-run, fabric-pipeline-deploy
---

# /fabric-pipeline-poll — Poll a Fabric Pipeline Run to Terminal State

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/pipeline_poll.py`
> (DDF demo run monitor).

## What it does

Polls the status of a Fabric Data Pipeline run until it reaches a terminal
state (`Succeeded`, `Failed`, `Cancelled`, `Deduped`, `Completed`) or a
timeout expires. Surfaces the final status and, on `Failed`, the failure
reason and the failed activity if Fabric exposes it.

Companion to `/fabric-pipeline-run`. Use stand-alone when:
- You triggered the run elsewhere (UI, scheduled trigger, another script)
  and want to monitor from the agent
- A prior `--wait` invocation timed out and you want to resume polling

## When to use

- After a `/fabric-pipeline-run` without `--wait` to bring back the
  terminal status
- Picking up an in-flight run that started elsewhere
- Debugging: re-poll a known run_id to retrieve the failure detail

## Prerequisites

- `FabricConnector` credentials
- Workspace + pipeline + run_id known

## Usage

```
/fabric-pipeline-poll --pipeline-id <id> --run-id <id> --env dev
/fabric-pipeline-poll --pipeline-id <id> --run-id <id> --workspace-id <id>
/fabric-pipeline-poll --pipeline-id <id> --run-id <id> --env dev --timeout 1800   # max seconds, default 1800
/fabric-pipeline-poll --pipeline-id <id> --run-id <id> --env dev --interval 15    # poll every N seconds, default 15
/fabric-pipeline-poll --pipeline-id <id> --run-id <id> --env dev --once           # single status check, no loop
```

## Terminal states

| State | Treated as outcome |
|---|---|
| `Succeeded` | ok |
| `Completed` | ok (synonym; some Fabric stack versions return this) |
| `Failed` | fail (with failureReason surfaced) |
| `Cancelled` | fail |
| `Deduped` | fail (run was deduped because another identical was in flight) |

Non-terminal: `NotStarted`, `InProgress`, `Queued`. Loop continues.

## Pipeline summary

1. Resolve workspace id
2. Load project + credentials, build connector
3. Loop until terminal OR timeout:
   - GET `/v1/workspaces/{ws}/items/{pipeline_id}/jobs/instances/{run_id}`
   - Parse `status` field
   - If terminal: break
   - If `--once`: break after first check
   - Else: sleep `--interval` seconds
4. If terminal `Failed`: also fetch + surface `failureReason` / `error`
   field and (if available) the activity-level error from the run details
5. Surface: pipeline name + run_id + start time + duration + final status
6. ops.log: `PIPELINE-POLL | <env or -> | fabric: ws=<id> pid=<id> run=<id> terminal=<status> | <ok|fail>` (or `partial` for `--once` when not yet terminal)

## Output example

```
Polling pipeline acme_medallion run a1b2c3...
  [  0s] status=NotStarted
  [ 15s] status=InProgress
  [ 30s] status=InProgress
  [ 45s] status=Succeeded

FINAL: Succeeded
Duration: 45s
```

On failure:

```
  [ 60s] status=Failed
FINAL: Failed
failureReason: Activity 'run_silver' failed: AnalysisException: Table or view 'workspace.default.bronze_part' is not a valid identifier.
```

## Preview tracking — known unknowns

1. **Polling cost**: a 30-minute pipeline polled at 15s interval = 120 API
   calls. Per-tenant Fabric API quotas exist but are generous (~600/min
   on capacity-backed workspaces). Document this caveat.
2. **Activity-level error**: the top-level `failureReason` is sometimes
   opaque ("Activity X failed"). The full per-activity error requires a
   second call to `/jobs/instances/{run_id}/activityRuns`. V1 fetches it
   automatically on Failed only; V2 should surface it inline.
3. **Run completion vs. dataset refresh lag**: pipeline `Succeeded` does
   NOT guarantee downstream semantic-model refresh completed. Refresh is
   a separate async job. Caller must poll the dataset refresh status
   separately (different API).

## Status — promotion to `stable`

1. 3+ polls completed across Succeeded + Failed + Cancelled terminal states
2. Activity-level error retrieval tested on a real failure
3. Timeout behavior verified (does not hang indefinitely)
4. ops.log entries reviewed

ARGUMENTS: $ARGUMENTS
