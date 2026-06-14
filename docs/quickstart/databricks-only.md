# Quickstart: Databricks-only

> **Scenario:** You have only Databricks. No Microsoft Fabric, no Power BI publishing for now. You want notebook + job deployment per environment with reproducible promotions.

This is the simplest scenario — pick it if you're not on Fabric yet, or if you're focused on data engineering rather than the BI consumer layer.

**Estimated time:** 15–20 minutes for first deploy.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python 3.10+ | Engine + CLI |
| Git | Clone + version control |
| Databricks workspace | Target (Community Edition works for trial) |
| Databricks personal access token (PAT) | Auth |

That's it. No Azure CLI, no Fabric tenant, no Power BI licence.

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

> The preflight check needs a scaffolded project — we run it in step 5 after `/ade-ops-onboarding` creates `config/project.yaml`. Running it now on a fresh clone exits with "No project.yaml found"; that's expected pre-scaffold.

## Step 2 — Authenticate to Databricks

Create a PAT in your Databricks workspace (avatar → **Settings** → **Developer** → **Access tokens**). Set as user env var:

```powershell
# Windows
[System.Environment]::SetEnvironmentVariable("DATABRICKS_TOKEN", "dapi...", "User")
```

```bash
# macOS/Linux
export DATABRICKS_TOKEN="dapi..."
```

Reopen your terminal to load the variable.

## Step 3 — Scaffold the reference distribution

```
/ade-ops-onboarding
```

Choose **`databricks-only`**. The skill scaffolds:

- `distributions/reference/projects/<your-project-name>/`
- `config/project.yaml` with only the Databricks platform block
- `overlays/{dev,cert,prod}.yaml` with per-env workspace path / catalog / schema
- `config/credentials.example.yaml`

Manual setup: copy from `core/templates/scenario-databricks-only/`.

## Step 4 — Configure workspace

Edit `distributions/reference/projects/<project>/config/project.yaml`:

```yaml
project:
  name: <your-project-name>

platforms:
  databricks:
    host: https://<your-workspace>.cloud.databricks.com

environments:
  dev:
    overlay: overlays/dev.yaml
    platforms:
      databricks:
        workspace_path: /Workspace/Users/<your-user>/<project>
        catalog: <bronze_dev>
        schema: <analytics>

scopes:
  notebooks:
    path: src/notebooks
    connector: databricks
  jobs:
    path: src/jobs
    connector: databricks
```

Copy credentials:

```bash
cp distributions/reference/projects/<project>/config/credentials.example.yaml \
   distributions/reference/projects/<project>/config/credentials.yaml
```

> ⚠️ **If this machine also does client work, use literal demo values — not `${VAR}` references.** If `credentials.yaml`/`project.yaml` leave `host`/`token` as `${DATABRICKS_HOST}`/`${DATABRICKS_TOKEN}` and you already have those env vars set for a client workspace, this demo will silently point at **your client's workspace**. Put the demo's own (or a Databricks Free Edition) host + token as literals here, and set `platforms.databricks.host` to a literal in `project.yaml`. See `core/conventions/credentials.md` → "Scenario C".

### Verify with preflight

Before pulling, validate the setup end-to-end:

```bash
python -m core.cli preflight --project distributions/reference/projects/<project> --env dev
```

You should see green ticks for Python, dependencies, project config, credentials, and Databricks reachability. With `--env`, preflight also prints the **token identity** it authenticates as and where `host`/`token` were resolved from (project literal vs ambient env var) — **confirm the identity is the workspace you intend before any push.** A mismatch between the token identity and the target (your `DEMO_USER_EMAIL` or the `/Users/<email>/` workspace path) is flagged as a hard failure. If anything is red, the message explains what to set.

## Step 5 — First pull

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks
```

Notebooks land under `state/dev/notebooks/`. Jobs (if configured):

```bash
python -m core.cli pull \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope jobs
```

## Step 6 — Author + push

Author under `src/notebooks/`. Use overlay placeholders for env-specific values (`${catalog}`, `${schema}`).

```bash
python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks \
  --dry-run

python -m core.cli push \
  --project distributions/reference/projects/<project> \
  --env dev \
  --scope notebooks
```

Confirmation prompt fires before each remote write. Production envs prompt twice.

## Step 7 — Promote dev → cert → prod

```bash
python -m core.cli push --env cert --scope notebooks
python -m core.cli push --env prod --scope notebooks
```

Refresh local `state/` with `pull` after each push.

## Common gotchas

- **`401 Unauthorized`**: token expired. Regenerate, reset env var, reopen terminal.
- **`Workspace path does not exist`**: the `workspace_path` in your overlay points at a folder that hasn't been created. Either create it via the Databricks UI or let the engine create it on first push (depends on the connector version).
- **Pull writes nothing**: the scope is empty in the remote workspace. `python -m core.cli status` confirms which scopes have files locally vs remotely.

## What's next

- Add a `cert` environment overlay when you have a staging workspace.
- Configure `jobs` and `dlt_pipelines` scopes in `project.yaml` if you use them.
- When you're ready to add Power BI or Fabric, you can extend the same project — just add the platform block to `project.yaml` and the relevant overlay fields. The scenario isn't locked in.
- File feedback via GitHub Issues (`feedback.yml` template).
