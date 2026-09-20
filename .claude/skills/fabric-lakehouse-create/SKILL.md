---
description: Create a Lakehouse in a Fabric Workspace
name: fabric-lakehouse-create
status: preview
since: 2026-05-28
related: fabric-workspace-create, fabric-items-list, fabric-notebook-deploy
---

# /fabric-lakehouse-create — Create a Lakehouse in a Fabric Workspace

> **Status**: preview. F2 Fabric workspace lifecycle suite, 2026-05-28.
> Source pattern from `distributions/demo-claude/.../local/_run_migration_dev.py`
> (lakehouse provisioning step of the DDF medallion demo).

## What it does

Creates a Lakehouse in a target Fabric workspace. Returns the lakehouse id +
SQL endpoint connection string (useful for Power BI Direct Lake + external
clients).

Lakehouses are the storage primitive for the DBR→Fabric migration scenario:
they receive the converted notebooks' Delta tables (`bronze_*`, `silver_*`,
`gold_*`).

## When to use

- Bootstrapping a new environment that has no Lakehouse yet
- The reference distribution onboarding flow: each env (DEV / CERT / PROD)
  needs at least one Lakehouse to host medallion tables
- Setting up a sandbox for testing notebook conversion output

## When NOT to use

- The Lakehouse already exists — check via `/fabric-items-list --type Lakehouse`
- You want a Warehouse (different item type) — Fabric distinguishes
  Lakehouse (Delta + Spark) vs Warehouse (T-SQL)

## Prerequisites

- `FabricConnector` credentials
- Target workspace already exists (use `/fabric-workspace-create` first)
- The identity must be Member / Contributor / Admin on the workspace

## Usage

```
/fabric-lakehouse-create --workspace-id <id> --name "Acme_DEV_LH"
/fabric-lakehouse-create --env dev --name "Acme_DEV_LH"               # resolve workspace from overlay
/fabric-lakehouse-create --workspace-id <id> --name "Acme_DEV_LH" --description "..."
/fabric-lakehouse-create --workspace-id <id> --name "Acme_DEV_LH" --dry-run
```

## Safety

- **Name collision check**: pre-flight calls `find_item_by_name(workspace_id, name, item_type="Lakehouse")`;
  if exists, surfaces the existing id and refuses to create a duplicate
- **Echo plan + confirm** before issuing the POST (skip with `--yes`)

## Pipeline summary

1. Resolve workspace id (from `--workspace-id` or `overlays/{env}.yaml`)
2. Load project + credentials, build connector
3. Pre-flight: `find_item_by_name(ws, name, "Lakehouse")` → refuse if exists
4. Echo plan + confirm
5. `connector.client.create_item(ws, display_name=name, item_type="Lakehouse")`
   — handles 202 Accepted LRO automatically (lakehouse provisioning is async)
6. Fetch the lakehouse details: `get_item(ws, lakehouse_id)` → includes
   `properties.sqlEndpointProperties.connectionString`
7. Surface: lakehouse_id + SQL connection string + workspace + name
8. Suggest next step: update overlay `overlays/{env}.yaml` with the
   `lakehouse_id` so notebook deploys / Direct Lake models target it
9. ops.log: `LAKEHOUSE-CREATE | <env or -> | fabric: ws=<id> name=<name> lh=<id> | ok`

## Preview tracking — known unknowns

1. **SQL endpoint provisioning lag**: the lakehouse appears immediately
   but the SQL endpoint takes 30-90 seconds to materialise. V1 returns
   the connection string from the get_item response (which may be empty
   on fresh lakehouse) — caller may need to poll. V2 should auto-poll
   until endpoint is ready (default 120s timeout).
2. **Schema-level Lakehouses**: Fabric introduced "schema-enabled"
   Lakehouses in 2025. V1 creates the default (single schema). Add
   `--schema-enabled` flag in V2.
3. **Default tables**: a new lakehouse has no tables. Loading bronze
   data is a separate step (`/fabric-notebook-deploy` + run a setup notebook).

## Status — promotion to `stable`

1. 3+ lakehouses created across distinct workspaces / distributions
2. The SQL endpoint string is reliably fetched (or the poll-until-ready
   logic landed in V2)
3. At least 1 case where the name collision pre-flight prevented duplicates
4. ops.log entries reviewed for audit completeness

ARGUMENTS: $ARGUMENTS
