---
name: fabric-workspace-create
status: preview
since: 2026-05-28
related: fabric-capacity-list, fabric-workspace-delete, ops-init
---

# /fabric-workspace-create — Provision a New Fabric Workspace

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/_run_migration_dev.py`
> + `_rerun_migration_clean.py` (workspace provision step of DDF demo).

## What it does

Creates a new Microsoft Fabric workspace, optionally bound to a specific
capacity. Returns the new workspace id and assigns the configured identity
as an Admin role on it.

This is the "I need a workspace I don't have yet" skill. For existing
workspaces, use the overlay configuration in `overlays/{env}.yaml`.

## When to use

- Bootstrapping a new environment (DEV / CERT / PROD) on Fabric
- Setting up a sandbox workspace for testing
- The reference distribution onboarding flow (each operator may need their
  own dev workspace to avoid stepping on others)

## When NOT to use

- The workspace already exists — use the existing `workspace_id` in your
  overlay; no need to re-create
- You don't yet have a Fabric Capacity id — run `/fabric-capacity-list`
  first (without a capacity the workspace lands on Trial which has limits)

## Prerequisites

- `FabricConnector` credentials configured (`config/credentials.yaml`)
- `az login` or service principal credentials in scope
- The identity must have **Capacity Admin** or equivalent on the target
  capacity (to bind the new workspace to it)
- Decide name in advance — Fabric does not let you trivially rename
  workspaces afterwards via API

## Usage

```
/fabric-workspace-create --name "AcmeSales_DEV"
/fabric-workspace-create --name "AcmeSales_DEV" --capacity-id <id>
/fabric-workspace-create --name "AcmeSales_DEV" --capacity-id <id> --description "Dev workspace for AcmeSales medallion"
/fabric-workspace-create --name "AcmeSales_DEV" --dry-run   # preview only, no API call
```

## Safety

- **Confirmation required**: before issuing `POST /workspaces` the skill
  echoes the resolved name + capacity + description and asks
  "Proceed? (y/N)". A `y` is mandatory unless `--yes` is passed.
- **Name collision check**: pre-flight calls `find_workspace_by_name(name)`;
  if a workspace with that name already exists, the skill refuses to create
  a duplicate and surfaces the existing id instead.
- **Capacity state check**: if `--capacity-id` is provided, pre-flight
  verifies the capacity is `Active`. A `Paused`/`Suspended` capacity is
  refused with a clear error.

## Pipeline summary

1. Load project + credentials
2. Build `FabricConnector`
3. Pre-flight:
   - `find_workspace_by_name(name)` → refuse if exists
   - if `--capacity-id`: `list_capacities()` + verify state `Active`
4. Echo plan + confirm (skip with `--yes`)
5. Call `connector.client.create_workspace(name, description=..., capacity_id=...)`
6. New workspace id returned
7. Suggest next step: update overlay `overlays/{env}.yaml` with the new
   `workspace_id` so subsequent operations target it
8. ops.log: `WORKSPACE-CREATE | <env or -> | fabric: name=<name> id=<new_id> | ok`

## Preview tracking — known unknowns

1. **Default role assignments**: the API creates the workspace with the
   caller as Admin. Adding other principals as Member / Contributor / Viewer
   is a separate step (see `client.add_role_assignment()` — not wrapped in
   this skill yet).
2. **Region selection**: workspace inherits the region of the assigned
   capacity. Without `--capacity-id`, Trial picks an arbitrary region.
3. **Rate limits**: Fabric throttles workspace creation per tenant. The
   skill does not currently retry on 429 — caller waits and re-invokes.
4. **`--dry-run` semantics**: V1 just prints the plan without issuing the
   POST. Does not validate name uniqueness against the live tenant in
   dry-run mode (would require a real API call).

## Status — promotion to `stable`

1. 3+ workspaces successfully created across distinct identities + capacities
2. At least 1 case where the name-collision pre-flight prevented a duplicate
3. At least 1 case where the capacity state pre-flight caught a bad capacity
4. No silent failures on 403 (Insufficient permissions surfaced clearly)
5. ops.log entries reviewed and confirmed to capture the right fields for audit

ARGUMENTS: $ARGUMENTS
