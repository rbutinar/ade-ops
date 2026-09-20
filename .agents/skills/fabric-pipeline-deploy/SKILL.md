---
description: Deploy a Data Pipeline to Fabric
name: fabric-pipeline-deploy
status: preview
since: 2026-05-28
related: fabric-pipeline-run, fabric-pipeline-poll, fabric-notebook-deploy, fabric-items-list
---

# /fabric-pipeline-deploy — Deploy a Data Pipeline to Fabric

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/pipeline_deploy_run.py`
> + `redeploy_pipeline_corrected_dag.py` (DDF demo pipeline build).

## What it does

Deploys a Microsoft Fabric Data Pipeline (DAG of notebook / copy / dataflow
activities) into a target workspace. Pipeline definition is supplied as a
JSON / YAML file matching Fabric's `dataPipelines` item-definition schema.

This is the orchestration counterpart of `/fabric-notebook-deploy`: notebooks
are individual units; pipelines wire them into a DAG that Fabric schedules
and runs end-to-end.

## When to use

- After deploying notebooks via `/fabric-notebook-deploy`, when you need
  to chain them into a pipeline that executes them in order
- Migrating a Databricks Job to a Fabric Data Pipeline (DBR Job DAG →
  Fabric Pipeline activities)
- Updating an existing pipeline DAG (e.g. adding a new notebook activity)

## Prerequisites

- `FabricConnector` credentials
- Target workspace already exists with the notebooks referenced by the
  pipeline already deployed (use `/fabric-items-list` to confirm)
- Pipeline definition file in the expected Fabric schema (see "Definition
  format" below)

## Usage

```
/fabric-pipeline-deploy <path-to-pipeline.json> --env dev --name "acme_medallion"
/fabric-pipeline-deploy <path-to-pipeline.json> --workspace-id <id> --name "..."
/fabric-pipeline-deploy <path-to-pipeline.json> --env dev --name "..." --update     # update if exists, error otherwise
/fabric-pipeline-deploy <path-to-pipeline.json> --env dev --name "..." --dry-run
```

## Definition format

The JSON file follows Fabric's Data Pipeline schema:

```json
{
  "properties": {
    "activities": [
      {
        "name": "run_setup",
        "type": "TridentNotebook",
        "typeProperties": {
          "notebookId": "<notebook-id-resolved-by-name>",
          "workspaceId": "<ws-id>"
        }
      },
      {
        "name": "run_silver",
        "type": "TridentNotebook",
        "dependsOn": [{ "activity": "run_setup", "dependencyConditions": ["Succeeded"] }],
        "typeProperties": { "notebookId": "...", "workspaceId": "..." }
      }
    ]
  }
}
```

V1 supports `TridentNotebook` activities (the DDF demo pattern). Future
versions: Copy, Dataflow, Lookup, ForEach, etc.

## Pipeline summary

1. Resolve workspace id (from `--workspace-id` or overlay)
2. Load project + credentials, build connector
3. Read pipeline definition file → parse JSON
4. Resolve any `<notebook-name>` references in the definition to real
   notebook ids via `find_item_by_name(ws, name, "Notebook")` (caller-
   supplied helper if the definition file uses names not ids)
5. Pre-flight: `find_item_by_name(ws, name, "DataPipeline")`:
   - If exists and `--update`: proceed with `update_item_definition`
   - If exists and no `--update`: refuse
   - If not exists: proceed with `create_item`
6. Encode the definition as Fabric expects (base64 part wrapper)
7. Echo plan + confirm
8. `create_item(ws, display_name=name, item_type="DataPipeline", definition=...)`
   (handles 202 LRO) OR `update_item_definition(ws, item_id, definition=...)`
9. Surface the pipeline id
10. Suggest next step: `/fabric-pipeline-run --pipeline-id <id>` to execute
11. ops.log: `PIPELINE-DEPLOY | <env or -> | fabric: ws=<id> name=<name> pid=<id> action=<create|update> | ok`

## Preview tracking — known unknowns

1. **Name resolution helper**: V1 assumes the definition file already
   contains notebook ids. Resolving by name requires a pre-pass — should
   live in this skill or as a utility script? Decide at first real use.
2. **Schema validation**: V1 trusts the input JSON. A malformed definition
   gets rejected by Fabric with a 400 + opaque error. Future: light schema
   validation client-side.
3. **Update conflict**: if two operators update the same pipeline
   concurrently, Fabric returns 412 Precondition Failed. V1 surfaces as
   `fail`; no auto-retry or merge.
4. **Trigger config**: V1 deploys the pipeline definition only. Scheduling
   triggers (cron, blob trigger, etc.) are a separate API not yet wrapped.

## Status — promotion to `stable`

1. 3+ pipelines deployed across distinct workspaces (DEV / CERT / PROD)
2. At least 1 update-in-place scenario tested without losing prior history
3. The name-resolution helper (if needed) is in stable shape
4. ops.log entries reviewed for audit

ARGUMENTS: $ARGUMENTS
