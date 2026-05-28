# /fabric-notebook-deploy — Deploy a Notebook to a Fabric Workspace

You are deploying a Python notebook (Databricks-style `.py` or plain `.ipynb`) to a Microsoft Fabric workspace.

This skill is the Fabric counterpart of `/databricks-deploy`. It uses the `FabricConnector` in `core/connectors/fabric.py` for the REST part. The `.py → .ipynb` conversion still depends on a module from the ADE lab — see backlog item #18.

## Prerequisites

- `FabricConnector` credentials configured in `credentials.yaml` (see `core/connectors/fabric.py` docstring)
- `az login --allow-no-subscriptions` to the target tenant, **or** service principal in `credentials.yaml` under `fabric.{client_id, client_secret, tenant_id}`
- For `.py` Databricks-style sources: `ade_app.platforms.fabric.notebooks.converter` available (backlog: port to `core/platforms/fabric/notebooks/`)
- Contributor access on the target workspace

## Usage

```
/fabric-notebook-deploy {local_path} --env {env}               # deploy to env's workspace
/fabric-notebook-deploy {local_path} --workspace {ws_id}       # explicit workspace override
/fabric-notebook-deploy {local_path} --env {env} --folder {f}  # place under a workspace folder
/fabric-notebook-deploy --list --env {env}                     # list notebooks in workspace
```

Arguments via `$ARGUMENTS`:
- positional `local_path` — `.py` (Databricks-style or plain) or `.ipynb`
- `--env {env}` — resolves workspace from `overlay.power_bi.workspace_id` or env_config
- `--workspace {ws_id}` — override workspace
- `--folder {name}` — place under a workspace folder (Fabric requires create-in-root-then-move)
- `--list` — read-only listing of notebooks already in the workspace
- `--name {display_name}` — override display name (defaults to source filename)

## Behavior

### Step 1: Resolve Project & Workspace

Same pattern as `/powerbi-publish`:

```yaml
overlay.power_bi.workspace_id            # preferred
environments.{env}.platforms.fabric.workspace_id  # fallback
```

### Step 2: Read & Convert Source

For `.ipynb`:
```python
import json
notebook_content = json.loads(Path(local_path).read_text(encoding="utf-8"))
```

For `.py`:
```python
# Until ade_app.platforms.fabric.notebooks.converter is ported to core/:
from ade_app.platforms.fabric.notebooks.converter import read_and_convert
notebook_content = read_and_convert(local_path, format="auto")
```

The converter handles Databricks-style sources:
- `# Databricks notebook source` header → notebook metadata
- `# COMMAND ----------` → cell boundary
- `# MAGIC %md` → markdown cell
- `# MAGIC %pip` / `# MAGIC %sql` → preserved magic commands
- Plain `.py` → comments become markdown, code becomes code cells (split on triple newlines)

### Step 3: Check Existing

```python
from core.connectors.fabric import FabricConnector
connector = FabricConnector.from_credentials(load_credentials(project_root))
items = connector.client.list_items(workspace_id, item_type="Notebook")
existing = next((i for i in items if i["displayName"] == display_name), None)
```

### Step 4: Build Fabric Definition

```python
import base64, json
parts = [
    {
        "path": "notebook-content.ipynb",
        "payload": base64.b64encode(json.dumps(notebook_content).encode()).decode(),
        "payloadType": "InlineBase64",
    },
    # Fabric Notebook items also require .platform metadata:
    {
        "path": ".platform",
        "payload": base64.b64encode(json.dumps({
            "$schema": ".../platformProperties/2.0.0/schema.json",
            "metadata": {"type": "Notebook", "displayName": display_name},
            "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"},
        }).encode()).decode(),
        "payloadType": "InlineBase64",
    },
]
definition = {"format": "ipynb", "parts": parts}
```

### Step 5: Confirmation Gate

Before pushing to `cert` or `prod`, show:

> **Notebook deploy — {env}**:
> - Source: {local_path}
> - Target: {workspace_id}{/folder}
> - Action: {Create | Update existing {item_id}}
>
> **Proceed?** (yes/no — `prod` requires double-confirm)

### Step 6: Deploy

**Create**:
```python
result = connector.client.create_item(
    workspace_id, display_name=display_name, item_type="Notebook", definition=definition,
)
notebook_id = result["id"]
```

**Update**:
```python
connector.client.update_item_definition(workspace_id, existing["id"], definition)
notebook_id = existing["id"]
```

Poll the LRO on 202.

### Step 7: Move to Folder (Optional)

Fabric API doesn't support creating items directly inside folders with a definition — must create in root, then move:

```
POST /v1/workspaces/{ws_id}/items/{notebook_id}/move
{"folderId": "{folder_id}"}
```

Resolve `folder_id` via `GET /v1/workspaces/{ws_id}/folders` (filter by displayName).

### Step 8: Log

```
{ISO_timestamp} | {role} | FABRIC-NB-DEPLOY | {env} | {local_path} -> {workspace_id}/{folder}: {created|updated} {notebook_id} | {ok|fail}
```

## Error Handling

| Error | Cause | Fix |
|---|---|---|
| 401 after `az login` | Token cache stale | Force-refresh via `connector.auth.get_token(force_refresh=True)` |
| 403 on workspace | Lacks Contributor role | Request access from workspace admin |
| 409 LockConflict | Concurrent operation on the notebook | Wait 30s and retry |
| `Invalid notebook format` | Source doesn't match expected format | Use Databricks-style or `.ipynb` |
| `Folder not found` | Folder hasn't been created yet | Create via Fabric portal or extend skill to create folders |

## Notes

- Fabric Notebook items support `format: ipynb` (canonical) and `format: py` (Spark Python). The converter currently always produces `ipynb`.
- Token cache (when using MSAL device-code) lives at `~/.ade/fabric_token_cache.json` once `msal_cache` is ported.
- For Git-integrated workspaces, deployed notebooks will also sync to the Git repo on the next sync cycle.
- Large notebooks may take longer (base64 encoding overhead). The Fabric API timeout is 100s — for very large notebooks consider splitting cells.
