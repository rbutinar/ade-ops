---
name: fabric-items-list
status: preview
since: 2026-05-28
related: fabric-workspace-delete, fabric-extract-v2, fabric-lineage
---

# /fabric-items-list — Inventory Items in a Fabric Workspace

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/_list_all_items.py`
> + `list_pipelines.py` (DDF demo inventory utilities).

## What it does

Lists items in a Fabric workspace, optionally filtered by type. Returns id +
displayName + type + (where applicable) workspace path / folder.

Lightweight read-only utility — distinct from `/fabric-extract-v2` (which
fetches full definitions for migration / extraction) and `/fabric-lineage`
(which traverses dependency graphs). This is just "what's there".

## When to use

- Pre-flight before `/fabric-workspace-delete` (audit what gets deleted)
- Pre-flight before `/fabric-pipeline-deploy` to check name collision
- Verifying a deploy landed (does the item exist after the operation?)
- Quick inventory for documentation / status report

## Prerequisites

- `FabricConnector` credentials
- The identity must have at least *Viewer* on the workspace

## Usage

```
/fabric-items-list --workspace-id <id>
/fabric-items-list --workspace-id <id> --type Notebook         # filter by type
/fabric-items-list --workspace-id <id> --type DataPipeline
/fabric-items-list --workspace-id <id> --json                   # raw JSON
/fabric-items-list --env dev                                    # resolve workspace from overlay
```

## Supported item types

`Notebook`, `DataPipeline`, `Lakehouse`, `Warehouse`, `SemanticModel`,
`Report`, `Dashboard`, `KQLDatabase`, `Eventstream`, `MLModel`, `Environment`.

Filter is case-sensitive (Fabric API convention).

## Pipeline summary

1. Resolve workspace id (from `--workspace-id` or from `overlays/{env}.yaml`)
2. Load project + credentials, build connector
3. `connector.client.list_items(workspace_id, item_type=type)`
4. Render table or JSON per flags
5. ops.log: `ITEMS-LIST | <env or -> | fabric: ws=<id> type=<type or all> count=<n> | ok`

## Example output

```
id                                    type           displayName              folder
6f8b...                               Notebook       _setup_seed_bronze       /
a1b2...                               Notebook       silver_transform_sales   /
c3d4...                               DataPipeline   acme_medallion           /
e5f6...                               Lakehouse      Acme_DEV_LH              /
g7h8...                               SemanticModel  AcmeSales                /
i9j0...                               Report         AcmeSales Overview       /
```

## Preview tracking — known unknowns

1. **Folder field**: Fabric introduced workspace folders mid-2025; older
   items may have `folder: null`. V1 renders as `/`.
2. **Paging**: workspace with > 100 items requires paging (continuation
   token). V1 fetches first page only; for large workspaces add
   `--all-pages` flag in V2.
3. **Item type unknown to API**: new Fabric item types may appear over time.
   V1 lists them with `type` as Fabric returns it (no whitelist).

## Status — promotion to `stable`

1. 3+ workspaces inspected across distinct distributions / scenarios
2. Output format stable across at least 3 Fabric API minor versions
3. No silent failures on permission errors

ARGUMENTS: $ARGUMENTS
