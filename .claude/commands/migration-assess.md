# /migration-assess — Databricks → Fabric migration assessment + execute

You are running a Databricks → Fabric migration assessment, and optionally
executing the migration (provisioning lakehouse + deploying notebooks +
creating orchestration pipeline) in the target Fabric workspace.

This skill backs the public-facing demo `distributions/demo-claude/projects/databricks-fabric-migration/`
but is generic — it works on any project whose `project.yaml` declares both
a Databricks and a Fabric platform with an environment overlay.

## Usage

```
/migration-assess                          # assess only (governed mode, default)
/migration-assess --env cert               # target a specific env (default: dev)
/migration-assess --execute                # assess + provision + deploy + create pipeline
/migration-assess --execute --run          # same + trigger the pipeline at the end
/migration-assess --auto-approve           # big-bang: --execute --run with no confirmations
/migration-assess --output ./reports/      # custom report path (default: local/reports/)
```

## Behavior

### Step 1 — Resolve project + env

Use `core.engine.config.load_project()` to read `project.yaml` and resolve the
env. The skill auto-discovers the nearest project root from the current
working directory (same pattern as the other `/ops-*` skills).

### Step 2 — Pull source notebooks

If `state/{env}/notebooks/.state.yaml` is missing or stale, run:
```
python -m core.cli pull --project <project> --env {env} --scope notebooks
```
Otherwise use the existing state as the source of truth. The assessment
reads from `state/{env}/notebooks/` (mirror of remote, not `src/`).

### Step 3 — Assess

```python
from core.parsers.databricks_migration_assess import run_assessment
report = run_assessment(
    notebooks_root=project_root / "state" / env / "notebooks",
    output_dir=output_path,
)
```

This emits:
- `{output_dir}/assessment_report.md` — human-readable summary table per notebook
- `{output_dir}/assessment_report.json` — machine-readable for downstream tools
- `{output_dir}/converted/<rel_path>.ipynb` — pre-converted Jupyter notebooks for every non-`impossible` source

Each notebook is classified into:
- `compat` — direct port, zero effort
- `refactor_light` — trivial rename (`dbutils.fs` → `mssparkutils.fs`) or UC three-part name
- `refactor_heavy` — secrets, widgets, DLT, hardcoded `dbfs:/`
- `impossible` — `%scala` / `%r` magics, can't be auto-ported

Print the summary table to the user. Highlight `refactor_heavy` and `impossible`
counts — those drive the conversation about manual effort.

### Step 4 — Execute (if `--execute` or `--auto-approve`)

In governed mode (default), STOP here and ask the user to review the report.

In execute mode, perform these in order on the target Fabric workspace
(resolved from `env_config.platforms.fabric.workspace_id`):

1. **Provision Lakehouse** — `FabricLakehouseManager.ensure_lakehouse(name)`. Poll for SQL endpoint.
2. **Deploy notebooks** — for each notebook with `classification != "impossible"`:
   - Read the converted ipynb from `{output_dir}/converted/<rel_path>.ipynb`
   - Inject default lakehouse metadata via `FabricLakehouseManager.inject_default_lakehouse`
   - `FabricNotebookManager.deploy(name, content)`
3. **Build orchestration pipeline** — order activities by folder (bronze → silver → gold), each calling the corresponding deployed notebook via `FabricPipelineManager.build_notebook_activity`.
4. **Deploy pipeline** — `FabricPipelineManager.deploy("acme_medallion", definition)`.

In governed mode within `--execute`, ask for one [y/N] before each of the
4 sub-steps. In `--auto-approve`, skip all confirmations and stream the
operations sequentially.

### Step 5 — Run (if `--run` or `--auto-approve`)

```python
job = pipeline_mgr.run(pipeline_id)
result = pipeline_mgr.poll_run(job, timeout_seconds=1800)
```

Print final status (Succeeded / Failed / Timeout) and the pipeline run URL
in the Fabric UI for inspection.

### Step 6 — Summary

Print a final block with:
- What was assessed (count by classification)
- What was provisioned (lakehouse id, SQL endpoint connection string)
- What was deployed (notebook ids in target workspace)
- What was orchestrated (pipeline id)
- Run status (if `--run`)

## Code skeleton

```python
from pathlib import Path
from core.engine.config import load_project, find_project_root
from core.parsers.databricks_migration_assess import run_assessment
from core.connectors.fabric import FabricConnector
from core.connectors.databricks import DatabricksConnector
from core.platforms.fabric.lakehouse_manager import FabricLakehouseManager
from core.platforms.fabric.notebook_manager import FabricNotebookManager
from core.platforms.fabric.pipeline_manager import FabricPipelineManager

# Resolve project
project_root = find_project_root(Path.cwd())
config = load_project(project_root, env=env)
env_cfg = config.environments[env]

# Step 3 — assess
state_dir = project_root / "state" / env / "notebooks"
output_dir = project_root / "local" / "reports"
report = run_assessment(state_dir, output_dir)

# Step 4 — execute (if --execute)
# Build through from_credentials so the env-auth override in project.yaml
# (environments.{env}.platforms.fabric.auth — azure_config_dir, az_tenant_id)
# wins over the credentials.yaml base AND ${ENV_VAR} is resolved. Constructing
# FabricAuthenticator straight from credentials["fabric"] BYPASSES the override
# and can resolve the WRONG identity.
fabric_conn = FabricConnector.from_credentials(
    config.credentials,
    env_platform_auth=env_cfg.platforms["fabric"].get("auth"),
)
client = fabric_conn.client
ws_id = env_cfg.platforms["fabric"]["workspace_id"]
lakehouse_name = env_cfg.platforms["fabric"]["lakehouse_name"]

lh_mgr = FabricLakehouseManager(client, ws_id)
lh = lh_mgr.ensure_lakehouse(lakehouse_name)
sql_ep = lh_mgr.get_sql_endpoint(lh["id"])

nb_mgr = FabricNotebookManager(client, ws_id)
deployed = {}
for nb in report.notebooks:
    if nb.classification == "impossible":
        continue
    converted_path = output_dir / "converted" / Path(nb.relative_path).with_suffix(".ipynb")
    content = json.loads(converted_path.read_text(encoding="utf-8"))
    content = lh_mgr.inject_default_lakehouse(
        content,
        lakehouse_id=lh["id"],
        lakehouse_name=lakehouse_name,
        workspace_id=ws_id,
    )
    result = nb_mgr.deploy(nb.name, content)
    deployed[nb.name] = result["id"]

# Step 4.3 — pipeline (bronze → silver → gold by folder convention)
pl_mgr = FabricPipelineManager(client, ws_id)
bronze_acts = [pl_mgr.build_notebook_activity(name=n, notebook_id=deployed[n], workspace_id=ws_id)
               for n in deployed if Path(report.notebooks_by_name[n].relative_path).parent.name == "bronze"]
# ... silver/gold with depends_on chain ...
definition = pl_mgr.build_pipeline_definition(bronze_acts + silver_acts + gold_acts)
pipeline = pl_mgr.deploy("acme_medallion", definition)

# Step 5 — run (if --run)
if args.run:
    job = pl_mgr.run(pipeline["id"])
    result = pl_mgr.poll_run(job)
    print(f"Pipeline run: {result['status']}")
```

## Safety

- **Never** deploy to `prod` env without explicit confirmation, even with `--auto-approve` (require a literal `--i-mean-it-prod` flag instead).
- Empty `state/{env}/notebooks/` is a hard stop — instruct user to pull first.
- When the report has 0 notebooks classified as anything but `impossible`, refuse to execute (nothing to do).
- Log every operation to the project's `ops.log` (use `_append_ops_log` helper from `core.cli.main`).

## Mode summary

| Mode | Pull | Assess | Provision Lakehouse | Deploy notebooks | Create pipeline | Run pipeline | Confirmations |
|---|---|---|---|---|---|---|---|
| default (governed) | y | y | n | n | n | n | n/a |
| `--execute` | y | y | y | y | y | n | one per sub-step |
| `--execute --run` | y | y | y | y | y | y | one per sub-step |
| `--auto-approve` | y | y | y | y | y | y | none (big-bang) |

ARGUMENTS: $ARGUMENTS
