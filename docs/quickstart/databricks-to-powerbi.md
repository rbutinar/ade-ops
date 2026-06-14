# Quickstart: Databricks → Power BI

> **Scenario:** You have Databricks (any tier) + Power BI Pro or Premium. You want to manage notebooks + PBIR reports + semantic models end-to-end across `dev` / `cert` / `prod` environments.

This is the default scenario — pick this if you're not sure which one fits.

**Estimated time:** 20–30 minutes for first deploy.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | Engine + CLI |
| Git | Clone + version control |
| Databricks workspace | Target for notebooks/jobs (Community Edition works for trial) |
| Databricks personal access token (PAT) | Auth for the Databricks connector |
| Power BI Pro or Premium licence | Required to publish + manage semantic models / PBIR reports |
| Azure account with Power BI permissions | Auth flows through Azure AD (`az login`) |
| Azure CLI installed | For `az login` (`winget install Microsoft.AzureCLI` on Windows, `brew install azure-cli` on macOS) |

## Step 1 — Clone and bootstrap

```bash
git clone https://github.com/rbutinar/ade-ops.git
cd ade-ops
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

> The preflight check (`python -m core.cli preflight`) needs a scaffolded project to verify, so we run it later in step 5 after `/ade-ops-onboarding` (or manual scaffolding) creates `config/project.yaml`. If you run it now on a fresh clone, it'll exit with "No project.yaml found" — that's expected pre-scaffold.

## Step 2 — Authenticate to Databricks

Create a personal access token in your Databricks workspace:

1. Open the workspace UI
2. Click your avatar → **Settings** → **Developer** → **Access tokens**
3. **Generate new token** — set a meaningful comment (`ade-ops dev`) and a lifetime (90 days is reasonable)
4. Copy the token value (`dapi...`) — it's shown only once

Set the token as an environment variable. On Windows (persistent across sessions):

```powershell
[System.Environment]::SetEnvironmentVariable("DATABRICKS_TOKEN", "dapi...", "User")
```

On macOS/Linux, add to your shell profile:

```bash
export DATABRICKS_TOKEN="dapi..."
```

Reopen your terminal so the variable is loaded.

## Step 3 — Authenticate to Power BI / Azure

Power BI publishing uses Azure AD. Sign in via Azure CLI:

```bash
az login --tenant <your-tenant-id-or-domain>
```

If you're a guest in multiple tenants, specify the one that hosts your Power BI workspace explicitly. To verify:

```bash
az account show
```

The output should list the correct tenant and a Power BI–enabled subscription (or no subscription if you only have Power BI without an Azure resource group — that's also fine).

## Step 4 — Scaffold the reference distribution

The reference distribution ships with the project skeleton but no notebooks/reports yet — you bring those.

If you use Claude Code:

```
/ade-ops-onboarding
```

When prompted, choose **`databricks-to-powerbi`**. The skill scaffolds:

- `distributions/reference/projects/<your-project-name>/`
- `config/project.yaml` with placeholders for your workspace URL + token env var
- `overlays/dev.yaml` / `overlays/cert.yaml` / `overlays/prod.yaml` with environment-specific transforms
- `config/credentials.example.yaml` (you'll copy to `credentials.yaml` and the engine reads from there)

Manual setup (no Claude Code) is the same: copy the `core/templates/scenario-databricks-to-powerbi/` tree to `distributions/reference/projects/<project>/` and edit the placeholders. Documentation in the `core/templates/` directory.

## Step 5 — Configure your workspace

Edit `distributions/reference/projects/<project>/config/project.yaml`:

```yaml
project:
  name: <your-project-name>

platforms:
  databricks:
    host: https://<your-workspace>.cloud.databricks.com
  powerbi:
    tenant_id: <your-tenant-uuid>

environments:
  dev:
    overlay: overlays/dev.yaml
    platforms:
      databricks:
        workspace_path: /Workspace/Users/<your-user>/<project>
      powerbi:
        workspace_id: <your-pbi-workspace-uuid>
```

Repeat the per-environment block for `cert` and `prod` as needed. Workspace UUIDs are in the Power BI service URL when you open the workspace (`app.powerbi.com/groups/<uuid>/...`).

Copy the credentials example:

```bash
cp distributions/reference/projects/<project>/config/credentials.example.yaml \
   distributions/reference/projects/<project>/config/credentials.yaml
```

The default `credentials.yaml` references `${DATABRICKS_TOKEN}` and Azure CLI auth — no edits needed if step 2 + 3 are done.

> ⚠️ **If this machine also does client work, override the demo's Databricks `host`/`token` with literal demo values.** Leaving them as `${DATABRICKS_HOST}`/`${DATABRICKS_TOKEN}` when you already have those env vars set for a client workspace makes this demo silently target **your client's workspace**. See `core/conventions/credentials.md` → "Scenario C".

### Verify with preflight

Before pulling, validate the setup end-to-end:

```bash
python -m core.cli preflight --project distributions/reference/projects/<project> --env dev
```

You should see green ticks for Python, dependencies, project config, credentials, and Databricks reachability. With `--env`, preflight also prints the **token identity** it authenticates as and flags a mismatch against the intended target — confirm it is the demo workspace before any push. If anything is red, the message explains what to set.

## Step 6 — First pull

Pull the current Databricks state into `state/dev/`:

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks
```

You should see notebooks downloaded under `state/dev/notebooks/`. If you have no notebooks yet, the pull completes with zero files — that's expected.

Similarly for Power BI semantic models / reports (once a Power BI scope is configured in `project.yaml`):

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope power_bi
```

## Step 7 — Author + push

Author your notebooks under `src/notebooks/`. Use environment placeholders (e.g. `${catalog}`) that overlays will substitute at push time.

Dry-run first:

```bash
python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks \
  --dry-run
```

The dry-run shows the assembled output (src + overlay applied) without writing to the remote. Once you're satisfied:

```bash
python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks
```

You'll be prompted to confirm. Production environments require double confirmation.

## Step 8 — Promote dev → cert → prod

Same `push` command, different `--env`. The overlay handles environment-specific values (catalog, schema, workspace path, identity).

```bash
python -m core.cli push --env cert --scope notebooks
python -m core.cli push --env prod --scope notebooks
```

Always run `pull` after a `push` to refresh local `state/`.

## Common gotchas

- **`401 Unauthorized` on Databricks**: token expired or wrong workspace. Regenerate via UI, reset env var, reopen terminal.
- **`404 Entity not found` on Power BI**: identity has list-read but not definition-read. Verify Azure CLI is logged into the correct tenant (`az account show`), and that the identity has at least **Member** role on the target workspace.
- **`MissingSchemaError` on PBIR pull**: the workspace was bootstrapped via legacy Power BI Desktop "Publish" before PBIR. See `core/docs/fabric_404_vs_403.md` for the diagnostic flow.
- **Notebook converter tagging output as `heavy` or `impossible`**: the converter flagged constructs it can't safely auto-rewrite. Inspect the converter output — these are your call. Tagging is documented in `core/parsers/databricks_migration_assess.py`.
- **`pull` writes nothing**: the scope is empty in the remote workspace, or your identity has no read access. `python -m core.cli status` will show which scopes are configured.

## What's next

- Configure additional scopes in `project.yaml` (jobs, DLT pipelines, dashboards).
- Set up a `cert` environment overlay pointing at your staging workspace.
- Read `core/conventions/sanitization-patterns.md` before contributing back — sample data and examples must use generic placeholders.
- File feedback via GitHub Issues (`feedback.yml` template) or `/ops-feedback` in Claude Code.
