---
name: fabric-workspace-delete
status: preview
since: 2026-05-28
related: fabric-workspace-create, fabric-items-list
---

# /fabric-workspace-delete — Delete a Fabric Workspace (with safety hook)

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/_cleanup_fabric_dev.py`
> + `_cleanup_cert_prod.py` (DDF demo cleanup scripts).
>
> ⚠️ **Critical safety hook** encoded after the lesson in memory note
> "cleanup-deletes-workspace": the underlying API deletes the workspace
> AND all its items in one shot. The pre-flight inventory is mandatory.

## What it does

Deletes a Microsoft Fabric workspace and all its items (Notebooks, Pipelines,
Lakehouses, Reports, Semantic Models, …). Irreversible — there is no
recycle bin.

## When to use

- Tearing down a sandbox after a demo
- Cleaning up a failed onboarding attempt
- Decommissioning a deprecated environment

## When NOT to use

- Anywhere near PROD without triple confirmation
- When you're not sure what's in the workspace — use `/fabric-items-list`
  first
- When the workspace contains items you cannot recreate from source — full
  audit via `/fabric-items-list --json` first, archive any non-recreateable
  artefact

## Prerequisites

- `FabricConnector` credentials
- The identity must be **Admin** on the target workspace (Member /
  Contributor is not enough to delete)

## Usage

```
/fabric-workspace-delete --workspace-id <id>                # interactive
/fabric-workspace-delete --workspace-id <id> --confirm-name "AcmeSales_DEV"  # name double-check
/fabric-workspace-delete --workspace-id <id> --confirm-name "AcmeSales_DEV" --yes  # non-interactive (CI)
/fabric-workspace-delete --workspace-id <id> --dry-run      # inventory only, no DELETE
```

## Safety hook (mandatory, encoded by design)

The skill **always** performs these steps before issuing `DELETE`:

1. **Pre-flight inventory**: call `connector.client.list_items(workspace_id)`
   to enumerate ALL items in the workspace. Group by type. Render counts
   per type (Notebook, Pipeline, Lakehouse, Report, SemanticModel, …).
2. **Name double-check**: require `--confirm-name "<exact workspace name>"`.
   The skill fetches the workspace via `get_workspace(id)` and compares
   the displayName field; mismatch → refuse.
3. **Echo plan**: "About to delete workspace `<name>` (id `<id>`) and its
   N items: <breakdown>. This is irreversible. Type the workspace name
   again to confirm: ___".
4. **Final confirmation**: operator types name a second time (unless `--yes`).
   The skill compares character-by-character. Any mismatch → abort.

`--dry-run` performs steps 1-3 without 4 (no DELETE issued).

## Pipeline summary

1. Load project + credentials, build connector
2. Pre-flight inventory + name double-check (see Safety hook above)
3. Echo plan + final confirmation prompt (skip only with `--yes`)
4. `connector.client.delete_workspace(workspace_id)` → DELETE
5. Confirm 200/204 response
6. ops.log: `WORKSPACE-DELETE | <env or -> | fabric: name=<name> id=<id> items=<n> | ok` (always log even on dry-run, with detail `dry-run`)
7. Suggest cleanup of stale `overlays/*.yaml` entries that referenced the deleted workspace_id

## Preview tracking — known unknowns

1. **No recovery**: there is no soft-delete or undo. Repeat the warning.
2. **Capacity unbinding**: deleting a workspace unbinds it from its
   capacity. No special action required, but be aware of capacity billing
   implications.
3. **Linked datasets**: reports and semantic models referenced by external
   workspaces (cross-workspace lineage) will silently break after delete.
   V1 does not detect this — future enhancement: `--check-external-refs`.
4. **Idempotent re-runs**: if the workspace is already deleted, the API
   returns 404. V1 surfaces as `fail`; should consider as `ok` (already
   in desired state) — defer to first real use.

## Status — promotion to `stable`

1. 3+ deletes executed correctly across different workspaces, with the
   inventory + name-confirmation flow followed and validated.
2. At least 1 case where the name-confirmation aborted a wrong-workspace
   delete attempt.
3. ops.log entries reviewed and confirmed to capture workspace name + id +
   item count for post-hoc audit.
4. No silent destructive paths — refuse on any uncertainty.

ARGUMENTS: $ARGUMENTS
