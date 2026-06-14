# /powerbi-publish — Publish a Power BI Semantic Model to Fabric

You are publishing a Power BI semantic model from Power BI Desktop to a Fabric workspace via the REST API.

This skill combines two halves:
1. **TMDL export** from the local PBI Desktop instance via MCP `powerbi`.
2. **REST deploy** to the Fabric workspace via the `FabricConnector` in `core/connectors/fabric.py`.

## Why REST API (not MCP ConnectFabric)

ADOMD.NET/XMLA endpoints are blocked by corporate SSL/proxy and fail cross-tenant. The REST API path with `az login` (or service principal) tokens works universally — same auth flow used by `FabricConnector`.

## Prerequisites

- Power BI Desktop running with the target model open
- `powerbi` MCP server configured in `.mcp.json` (see ONBOARDING.md Step 7)
- `az login --allow-no-subscriptions` to the correct tenant (e.g. `contoso.com`) **or** service principal configured in `credentials.yaml` under `fabric.{client_id, client_secret, tenant_id}`
- Target workspace must be on Fabric/Premium capacity (Pro workspaces require device-code auth)
- Project `config/project.yaml` with `environments.{env}.platforms.fabric.workspace_id` (or overlay `power_bi.model_workspace_id`)

## Usage

```
/powerbi-publish --env {env}                            # publish, model name from PBI Desktop window
/powerbi-publish --env {env} --name {model_name}        # explicit display name
/powerbi-publish --env {env} --update                   # update existing model (preserve creds/refresh)
/powerbi-publish --env {env} --workspace {ws_id}        # override workspace
```

Arguments via `$ARGUMENTS`:
- `--env {env}` — required
- `--name {model_name}` — defaults to PBI Desktop window title
- `--workspace {ws_id}` — override `overlay.power_bi.model_workspace_id`
- `--update` — call `updateDefinition` on the existing item with the same display name
- `--set-credentials` — after publish, set datasource credentials
- `--refresh` — after publish, trigger a refresh

## Behavior

### Step 1: Resolve Project & Workspace

Find the active project (nearest ancestor of cwd with `config/project.yaml`). Read:

```yaml
environments.{env}.platforms.fabric.workspace_id    # fallback
overlay.power_bi.model_workspace_id                 # preferred when present
```

Apply env-var expansion as needed.

### Step 2: Connect to PBI Desktop

```
mcp__powerbi__connection_operations(operation="ListLocalInstances")
```

If multiple instances: ask the user. Connect:

```
mcp__powerbi__connection_operations(operation="Connect", dataSource="localhost:{port}")
```

### Step 3: Export TMDL

```
mcp__powerbi__model_operations(
  operation="ExportTMDL",
  tmdlExportOptions={
    filePath: "{tmp_dir}/{model}_tmdl",
    maxReturnCharacters: -1,
    serializationOptions: {includeChildren: true}
  }
)
```

Then per-table for partition/M expressions:

```
mcp__powerbi__table_operations(operation="List")
# for each table:
mcp__powerbi__table_operations(
  operation="ExportTMDL",
  references=[{name: "{table}"}],
  tmdlExportOptions={filePath: "{tmp_dir}/{model}_tmdl/definition/tables/{table}.tmdl"}
)
```

### Step 4: Build Fabric Definition

Assemble the inline-base64 parts the Fabric API expects:

| Path | Content |
|---|---|
| `.platform` | JSON: `{"$schema": "...platformProperties/2.0.0/schema.json", "metadata": {"type": "SemanticModel", "displayName": "{name}"}, "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"}}` |
| `definition.pbism` | JSON: `{"$schema": "...definitionProperties/1.0.0/schema.json", "version": "4.2", "settings": {}}` |
| `definition/model.tmdl` | from TMDL export |
| `definition/tables/{name}.tmdl` | one per table |
| `definition/relationships.tmdl` | if present |
| `definition/cultures/{culture}.tmdl` | if present |

Each part is base64-encoded:

```python
parts = [
    {"path": p, "payload": base64(content), "payloadType": "InlineBase64"}
    for p, content in files.items()
]
definition = {"format": "TMDL", "parts": parts}
```

### Step 5: Check for Existing Model

Use the framework's `FabricConnector` to look up items in the workspace:

```python
from core.connectors.fabric import FabricConnector
connector = FabricConnector.from_credentials(load_credentials(project_root))
items = connector.client.list_items(workspace_id, item_type="SemanticModel")
existing = next((i for i in items if i["displayName"] == model_name), None)
```

If `existing` and not `--update`: warn and ask whether to update or pick a different name.

### Step 6: Deploy

**Create new**:
```python
connector.client.create_item(
    workspace_id,
    display_name=model_name,
    item_type="SemanticModel",
    definition=definition,
)
```

**Update existing**:
```python
connector.client.update_item_definition(workspace_id, existing["id"], definition)
```

Both return 200 or 202 (LRO). For 202, poll `/v1/operations/{operation_id}` with the `Retry-After` interval until `Succeeded` or `Failed`.

### Step 7: Confirmation Gate

Before deploying to `cert` or `prod`, show:

> **Publish summary — {env}**:
> - Model: {name} ({n} tables, {n} measures)
> - Workspace: {workspace_id}
> - Action: {Create | Update existing item {item_id}}
>
> **Proceed?** (yes/no — `prod` requires double-confirm)

### Step 8: Optional Follow-ups

**Set credentials** (`--set-credentials`):
```
GET https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}/datasources
PATCH https://api.powerbi.com/v1.0/myorg/gateways/{gateway_id}/datasources/{datasource_id}
```

**Refresh** (`--refresh`):
```
POST https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}/refreshes
GET  https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}/refreshes?$top=1
```

### Step 9: Log

Append to the project's `ops.log`:

```
{ISO_timestamp} | {role} | PBI-PUBLISH | {env} | {model_name} -> {workspace_id}: {created|updated} | {ok|fail}
```

## Post-publish visual verification

A semantic-model publish that returns 200/Succeeded only guarantees that Fabric accepted the parts. It does NOT guarantee that downstream **reports** bound to this model render correctly — especially when the model carries a custom theme (see `core/playbooks/pbir-gotchas.md` § "gotcha #4: theme audit gap") or when measures changed format.

After publishing, verify visually that at least one consuming report still renders as expected. Two paths:

- **For <client> reports**: `/<client>-pbi-loop verify {report-ref} --env {env}` — one-shot Playwright snapshot, read-only, no deploy. Surfaces broken bindings, missing measures, theme regressions in seconds.
- **For demo / other distributions**: invoke the Playwright loop pattern directly per `core/playbooks/playwright-pbi-loop.md`.

This is a strong recommendation, not a hard gate. Skip only for trivial measure-only updates with no theme or relationship changes.

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `Workload_FailedToParseFile` (pbism) | Wrong schema | Use `version: "4.2"` |
| `Missing required artifact 'model.bim'` | Missing `.platform` | Include `.platform` in parts |
| 403 on workspace | Wrong tenant / Pro workspace | `az account show`; switch token method |
| Model created but empty | TMDL parse error | Tabs not spaces; check syntax |
| 202 then silent fail | Async error | Always poll the operation |
