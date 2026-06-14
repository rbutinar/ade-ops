# databricks-fabric-migration

Reference end-to-end pipeline: bronze ingest from Databricks built-in
`samples.tpch.*` → silver clean / transform → gold fact + dimensions →
Power BI DirectLake semantic model → PBIR report.

## Source dataset

Databricks **built-in `samples.tpch.*` UC catalog**. Available on every
Databricks workspace (free-tier included) without provisioning. Zero CSV
shipped, zero adopter setup beyond pointing at a Databricks workspace.

Mapping TPC-H → AcmeSales:

| TPC-H source | Becomes |
|---|---|
| `samples.tpch.lineitem` JOIN `orders` | `bronze_sales` |
| `samples.tpch.part` | `bronze_products` |
| `samples.tpch.customer` | `bronze_customers` |

## First-run setup (every adopter)

Before the first synced run on a fresh environment:

1. **Copy credentials template**
   ```bash
   cp config/credentials.example.yaml config/credentials.yaml
   # Edit credentials.yaml with your Databricks PAT.
   ```

2. **Set environment variables** (PowerShell)
   ```powershell
   $env:DEMO_USER_EMAIL = "you@example.com"          # your Databricks workspace user
   $env:DATABRICKS_HOST = "https://<your-ws>.cloud.databricks.com"
   $env:FABRIC_TENANT_ID = "<your-azure-tenant-id>"
   $env:FABRIC_WORKSPACE_DEV = "<dev-fabric-workspace-id>"
   $env:FABRIC_WORKSPACE_CERT = "<cert-fabric-workspace-id>"
   $env:FABRIC_WORKSPACE_PROD = "<prod-fabric-workspace-id>"
   ```

3. **Run the bronze seeder once** — the `_setup` notebooks are excluded
   from the synced pipeline (overlay `exclude: ["_setup/*"]`). Trigger
   them manually via the Databricks UI or `dbutils.notebook.run` to
   seed `bronze_products`, `bronze_customers`, `bronze_sales` from
   `samples.tpch.*`:
   ```python
   dbutils.notebook.run("_setup/create_demo_tables", 600)
   ```

   This step is required because silver / gold notebooks assume the
   bronze tables already exist. The seeder is idempotent (overwrite).

## Environments

| Env | Databricks catalog | Fabric workspace | Notes |
|---|---|---|---|
| DEV | `workspace.default` + `/Users/${DEMO_USER_EMAIL}/acme_sales_demo` | `${FABRIC_WORKSPACE_DEV}` | Personal workspace folder, fastest iteration |
| CERT | `acme_cert.default` + `/Shared/AcmeSales/CERT/` | `${FABRIC_WORKSPACE_CERT}` | Promotion target |
| PROD | `acme_prod.default` + `/Shared/AcmeSales/PROD/` | `${FABRIC_WORKSPACE_PROD}` | Production promotion target |

## End-to-end workflow

After first-run setup:

```
python -m core.cli preflight                       # deps + creds check
python -m core.cli pull --env dev                  # mirror remote state
python -m core.cli push --env dev --dry-run        # see what would change
python -m core.cli push --env dev                  # deploy notebooks
# In Databricks: run silver/transform_sales, silver/transform_products,
#                gold/ft_sales, gold/dm_product, gold/dm_customer
# Hydrate the Fabric lakehouse from the Databricks gold layer (see below)
# In Fabric: open AcmeSales.SemanticModel, refresh DirectLake
python -m core.cli diff --env dev                  # confirm in sync
```

## Hydrating the Fabric lakehouse — two paths

The semantic model is DirectLake; the report queries the **Fabric lakehouse**,
not the Databricks gold layer directly. The lakehouse therefore needs to be
populated from the Databricks gold tables. Two paths, pick by source type:

### Path A — Fabric Mirrored Databricks Catalog (Azure Databricks source)

If your Databricks source is **Azure Databricks** (host pattern
`adb-*.azuredatabricks.net`), use Fabric Mirrored Databricks Catalog —
zero-copy, real-time, no notebook needed. Configure via Fabric workspace
UI → Mirrored Databricks Catalog. The DirectLake model then queries the
mirrored catalog directly.

### Path B — Fabric notebook + JDBC bridge (non-Azure Databricks source)

If your source is **AWS Databricks**, **free-tier Community Edition** (`dbc-*.cloud.databricks.com`),
or any non-Azure workspace, Mirroring is not available. Use the Fabric
notebook `src/notebooks/fabric/hydrate_lakehouse_from_databricks.py`:

```
# 1. Deploy the hydrate notebook to the Fabric workspace
python -m core.cli push --env dev --scope notebooks --filter fabric/

# 2. Open the notebook in the Fabric workspace, attach the target lakehouse
#    (right pane → Add lakehouse → AcmeSales_Lakehouse_DEV).

# 3. Configure the notebook (one-time):
#    - DATABRICKS_HOST  — your source workspace URL
#    - SQL_WAREHOUSE_ID — your SQL Warehouse id (gold-layer-capable)
#    - Token storage: see notebook header for Key Vault vs inline options

# 4. Run the notebook (Fabric UI or via /fabric-pipeline-run if wrapped
#    in a pipeline). Reads gold tables via JDBC, writes Delta to the
#    lakehouse with overwrite semantics.

# 5. Refresh the AcmeSales DirectLake semantic model in the Fabric
#    workspace. The report now serves real data.
```

This path was the original demo pattern (DDF 2026-05-23) — the JDBC bridge
is the same primitive used to chain non-Azure Databricks sources into Fabric.
It demonstrates cross-tenant integration and the visible Fabric Spark
notebook operating on real workloads.

**Trade-off**: the source Databricks PAT must reach the Fabric notebook
runtime. Production-ish posture uses Azure Key Vault linked to the Fabric
workspace; demo-only posture pastes the token into a notebook session
variable. The notebook header documents both options + how to switch.

## Demo runbook (clone vergine → working report)

For a clean public-preview clone:

1. `git clone https://github.com/rbutinar/ade-ops.git` (post go-public)
2. Follow the "First-run setup" section above (credentials + env vars)
3. **Source bootstrap (Databricks side)**:
   - `python -m core.cli push --env dev --scope notebooks` (deploys bronze/silver/gold notebooks)
   - In Databricks UI: run `_setup/create_demo_tables`, then `silver/*`,
     then `gold/*` in order
4. **Fabric side**:
   - Create / reference a Fabric workspace (use `/fabric-workspace-create`
     if needed)
   - Create a Lakehouse (`/fabric-lakehouse-create`)
   - Choose hydration path:
     - **Azure Databricks source** → set up Mirrored Catalog via Fabric UI
     - **Non-Azure source** → deploy + run the JDBC bridge notebook (Path B
       above)
5. **Semantic model + report**:
   - `/powerbi-publish` — push AcmeSales TMDL to Fabric workspace
   - `/pbir-report` — deploy the AcmeSales_Overview report
6. **Verify**:
   - Open report in Power BI service / Fabric UI → visuals populated
   - `python -m core.cli diff --env dev` → "OK: In sync"

Total time clone vergine → working report: ~30 minutes (most of which is
Databricks-side notebook execution; the ade-ops steps are seconds).

## Skills you'll typically invoke

| Stage | Skill |
|---|---|
| First-run | `/ops-onboarding`, `/ops-init` (if scaffolding new project) |
| Audit | `/databricks-status`, `/databricks-lineage`, `/migration-assess` |
| Deploy | `/ops-push`, `/databricks-deploy`, `/fabric-notebook-deploy` |
| Run | `/databricks-run`, `/fabric-sp-run` |
| PBI authoring | `/powerbi-model-create`, `/powerbi-model-edit`, `/pbir-create`, `/pbir-add-page` |
| PBI deploy | `/powerbi-publish`, `/pbir-report` |
| State | `/ops-pull`, `/ops-diff`, `/ops-status` |
| Promote | `/ops-push --env cert`, `/ops-push --env prod` |

## Pipeline graph

```
samples.tpch.part      → bronze_products      → silver_products     → gold_dm_product
samples.tpch.customer  → bronze_customers     ────────────────────→ gold_dm_customer
samples.tpch.lineitem  → bronze_sales         → silver_sales        → gold_ft_sales
samples.tpch.orders    ↗                                                  ↓
                                                                  AcmeSales.SemanticModel (DirectLake)
                                                                          ↓
                                                                  AcmeSales_Overview.Report (PBIR)
```
