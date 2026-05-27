# Quickstart: Databricks → Microsoft Fabric

> **Scenario:** You have Databricks + a Microsoft Fabric tenant. You want multi-platform pipelines with Fabric as the consumer layer (Lakehouses, Warehouses, semantic models, reports).

**Estimated time:** 30–45 minutes for first deploy (Fabric auth flows take more setup than Power BI alone).

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | Engine + CLI |
| Git | Clone + version control |
| Databricks workspace | Source compute / pipelines |
| Databricks personal access token (PAT) | Auth for the Databricks connector |
| Microsoft Fabric trial or capacity | Target tenant for Lakehouses + Warehouses + reports |
| Azure account in the Fabric tenant | Auth for Fabric REST API |
| Azure CLI installed | For `az login` against the Fabric tenant |
| At least **Member** role on the target Fabric workspace | Fabric returns 404 (not 403) when permissions are insufficient — silent failure mode |

## Step 1 — Clone and bootstrap

Same as the [Databricks → Power BI quickstart](databricks-to-powerbi.md#step-1--clone-and-bootstrap): clone, venv, install dependencies. Skip preflight here — it runs in step 6 after the project is scaffolded.

## Step 2 — Authenticate to Databricks

Same as [step 2 in the Databricks → Power BI quickstart](databricks-to-powerbi.md#step-2--authenticate-to-databricks). Set `DATABRICKS_TOKEN` as a user env var.

## Step 3 — Authenticate to Fabric (Azure AD)

Fabric REST API uses Azure AD. Sign in via the Azure CLI:

```bash
az login --tenant <fabric-tenant-id>
az account set --subscription <subscription-with-fabric>
```

Verify:

```bash
az account show
```

The output should list the Fabric tenant and a subscription. If you have Fabric access without an Azure subscription, use `--allow-no-subscriptions`:

```bash
az login --tenant <fabric-tenant-id> --allow-no-subscriptions
```

> **Advanced**: ade-ops supports per-environment identity isolation via the optional `auth.azure_config_dir` field in `project.yaml`, in case you need to operate against multiple tenants from the same machine. This is not part of the standard flow — open an issue tagged `setup-question` if your environment requires it.

## Step 4 — Scaffold the reference distribution

```
/ade-ops-onboarding
```

Choose **`databricks-to-fabric`**. The skill scaffolds:

- `distributions/reference/projects/<your-project-name>/`
- `config/project.yaml` with Databricks + Fabric platform blocks
- `overlays/{dev,cert,prod}.yaml` with per-env catalog, schema, workspace UUIDs
- `config/credentials.example.yaml`

Manual setup: copy from `core/templates/scenario-databricks-to-fabric/`.

## Step 5 — Configure workspace + identity

Edit `distributions/reference/projects/<project>/config/project.yaml`:

```yaml
project:
  name: <your-project-name>

platforms:
  databricks:
    host: https://<your-workspace>.cloud.databricks.com
  fabric:
    tenant_id: <fabric-tenant-uuid>

environments:
  dev:
    overlay: overlays/dev.yaml
    platforms:
      databricks:
        workspace_path: /Workspace/Users/<your-user>/<project>
        catalog: <bronze_dev>
        schema: <analytics>
      fabric:
        workspace_id: <fabric-workspace-uuid>
        auth:
          method: azure_cli
          tenant_id: <fabric-tenant-uuid>
```

The connector uses the system default Azure CLI profile (the one you signed into in step 3). Per-environment identity isolation via `auth.azure_config_dir` is available as an advanced option — see step 3 note above.

Copy credentials:

```bash
cp distributions/reference/projects/<project>/config/credentials.example.yaml \
   distributions/reference/projects/<project>/config/credentials.yaml
```

### Verify with preflight

Before pulling, validate the setup end-to-end:

```bash
python -m core.cli preflight --project distributions/reference/projects/<project>
```

You should see green ticks for Python, dependencies, project config, credentials, Databricks reachability, and Fabric reachability. If anything is red, the message explains what to set.

## Step 6 — First pull

Databricks scope:

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks
```

Fabric scope (Lakehouse + Warehouse + reports):

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope fabric_items
```

PBIR reports + semantic models materialize as Power BI Desktop project folders (`.Report/` + `.SemanticModel/`) under `state/dev/power_bi/`.

## Step 7 — Author + push

Databricks side: author under `src/notebooks/`, dry-run, push.

Fabric side: author or pulled PBIR / TMDL trees under `src/power_bi/` and `src/fabric/`. The push step repacks the folder as InlineBase64 parts and calls Fabric's `updateDefinition` LRO (long-running operation). Expect 5–30s per item for the update to complete.

```bash
python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope fabric_items \
  --dry-run

python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope fabric_items
```

## Step 8 — Promote dev → cert → prod

The Fabric workspace IDs are env-specific. Overlays handle the rebind:

```yaml
# overlays/cert.yaml
fabric:
  workspace_id: <cert-workspace-uuid>
  model_id: <cert-semantic-model-uuid>
power_bi:
  report_suffix: "_CERT"
  model_suffix: "_CERT"
```

The PBIR `byConnection` binding is auto-rewritten at push time using `overlay.power_bi.model_id`.

## Common gotchas

- **`404 Entity not found` on first Fabric pull**: the silent failure mode. Fabric returns 404 when your identity has list-read but not definition-read. Verify (a) you have **Member** role on the workspace, (b) `az account show` lists the Fabric tenant, (c) `AZURE_CONFIG_DIR` is set correctly. See [`core/docs/fabric_404_vs_403.md`](../../core/docs/fabric_404_vs_403.md) for the full matrix.
- **PBIR-Legacy reports**: workspaces bootstrapped pre-PBIR via Power BI Desktop "Publish" return reports in legacy format. The connector currently does not auto-convert. Workflow: open in Power BI Desktop, save-as `.pbip`, commit to `src/power_bi/`. The `/legacy-import` CLI is on the F2 backlog.
- **`az.cmd` not found on Windows**: the connector resolves the Azure CLI via `shutil.which("az")`. If your PATH doesn't include the Azure CLI install dir, add it explicitly.
- **Fabric `getDefinition?format=PBIR` returns 404 but the report exists in the UI**: identity issue, not format issue. Switch to the correct Azure CLI profile.
- **Notebook converter rewrites `default.X` → `<catalog>.<schema>.X`**: the Databricks→Fabric converter rewrites `IN default`, `dbutils.fs`, `notebook.exit`, `notebook.run` automatically. Tagged output: `compat` / `light` / `heavy` / `impossible`. The last two need your judgment.

## What's next

- Configure additional scopes (DLT pipelines, jobs, dashboards).
- Set up a `cert` environment with separate Fabric workspace.
- Explore the Fabric Lakehouse + Warehouse connectors under `core/connectors/`.
- Read [`core/playbooks/pbir-gotchas.md`](../../core/playbooks/pbir-gotchas.md) before authoring PBIR by hand.
