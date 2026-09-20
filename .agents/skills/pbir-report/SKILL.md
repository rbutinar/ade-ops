---
name: pbir-report
description: Power BI Report (PBIR) Deploy Only
---

# /pbir-report — Power BI Report (PBIR) Deploy Only

You are deploying an existing PBIR `.Report` folder to a Fabric workspace.

> ⚠️ **Sub-modes `list` / `modify` / `extract` / `create` are BLOCKED** as of 2026-05-24 — they depended on the ADE-resident `pbir_engine` module which violates the framework autonomy principle (`core/` must be self-sufficient, no external repo dependencies).
>
> **Superseded by Phase B2**: a clean engine `core/platforms/powerbi/pbir_engine/` with native Playwright visual feedback loop. Use `/pbir-create` for build-from-scratch (when available) and `/<client>-pbi-loop edit` for iterative edits on existing reports.
>
> This skill retains only the `deploy` sub-mode, which uses `FabricConnector` (already in `core/`) and is fully autonomous.

## Prerequisites

- A `.Report` folder (PBIR format) — produced by Power BI Desktop's "Save as PBIP project", `/pbir-create`, or a prior pull
- `FabricConnector` credentials (az login or service principal)

## Usage

```
/pbir-report deploy {report_path} --env {env}         # deploy to Fabric workspace
```

For other operations:
- **List visuals / pages of an existing report**: read the folder structure directly (`state/{env}/power_bi/Report/{Name}.Report/definition/pages/*`)
- **Modify existing report** (<client>): `/<client>-pbi-loop edit {report-ref}` — iterative loop with Playwright snapshot per turn
- **Build new report from scratch**: `/pbir-create` (Phase B2 — coming)
- **Extract Python that recreates a report**: blocked, no clean replacement yet (low priority backlog)

## Behavior

### `deploy {report_path} --env {env}`

1. Resolve workspace_id from `overlay.power_bi.report_workspace_id` (or env_config `platforms.fabric.workspace_id`)
2. Resolve the bound semantic model id (`semanticModelId`) from overlay `power_bi.model_id`
3. Rewrite `definition.pbir` to use `byConnection` with `connectionString = "semanticModelId={guid}"`
4. Build inline-base64 parts (`.platform`, `definition.pbir`, all `report.json` / visuals / pages files)
5. Use `FabricConnector` to deploy:

```python
from core.connectors.fabric import FabricConnector
connector = FabricConnector.from_credentials(load_credentials(project_root))
# create or update Report item
existing = next((i for i in connector.client.list_items(workspace_id, item_type="Report") if i["displayName"] == name), None)
if existing:
    connector.client.update_item_definition(workspace_id, existing["id"], definition)
else:
    connector.client.create_item(workspace_id, display_name=name, item_type="Report", definition=definition)
```

6. Poll the LRO until terminal.

### Confirmation Gate

Before `deploy` to `cert` or `prod`, summarize and ask explicitly. `prod` requires double-confirm.

### Logging

```
{ISO_timestamp} | {role} | PBIR-{LIST|MODIFY|EXTRACT|CREATE|DEPLOY} | {env|--} | {report_path}: {detail} | {ok|fail}
```

## Notes

- **Round-trip is the primary use case** — load existing, modify, save. New JSON only where added.
- All visuals attach `filterConfig` automatically (measures → "Advanced", columns → "Categorical").
- **For Fabric deploy**: `definition.pbir` must use `byConnection` with `connectionString` containing `semanticModelId={guid}`.
- The PBI Modeling MCP is not required for this skill — it operates on files, not on a running PBI Desktop instance.

## Common silent-failure modes

Programmatic PBIR has a small set of silent-failure modes where Fabric accepts the input and renders something "almost right" instead of erroring. Read `core/playbooks/pbir-gotchas.md` before authoring new visuals — the 6 documented gotchas cover most real-world friction (`visualContainerObjects` vs `objects` styling slot, transparency `0D` for opaque fills, title text under container properties, theme JSON audit gap, "no-data" placeholder mistaken for layout bug, hex case irrelevant).

The fastest way to catch these is the visual-feedback loop documented in `core/playbooks/playwright-pbi-loop.md`: build → deploy → Playwright snapshot → diagnose → patch, with Claude self-screenshotting via MCP. For iterating on an existing <client> report, prefer `/<client>-pbi-loop edit {report-ref}` which wraps this skill's `deploy` step inside the loop.

## Backlog

The `pbir_engine` Python module is the major prerequisite. Once ported to `core/platforms/powerbi/pbir_engine/`, this skill will be fully self-contained inside ade-ops.
