# acme-powerbi

Reference end-to-end pipeline, **Import-mode variant**: bronze ingest from
Databricks built-in `samples.tpch.*` → silver clean / transform → gold fact +
dimensions → **Power BI Import-mode semantic model reading the Databricks gold
layer directly** → PBIR report built from a spec.

This is the `databricks-to-powerbi` scenario — the "fewer pieces" sibling of
`databricks-fabric-migration`. **A Power BI Pro workspace is enough**: no Fabric
capacity, no lakehouse, no DirectLake, no hydration step.

## How it differs from `databricks-fabric-migration`

| | databricks-fabric-migration (default) | acme-powerbi (this project) |
|---|---|---|
| BI binding | DirectLake on a Fabric lakehouse | Import-mode, M `Databricks.Catalogs(...)` |
| Fabric capacity | required | **not** required (PBI Pro is enough) |
| Lakehouse + hydration | yes (`fabric/hydrate_lakehouse_from_databricks.py`) | **dropped** — model reads Databricks gold directly |
| Pieces to stand up | Databricks + Fabric workspace + lakehouse + capacity | Databricks + a Power BI workspace |
| Refresh | DirectLake (near-real-time over the lakehouse) | scheduled / on-demand Import refresh |

Everything upstream of the BI layer (the medallion notebooks) is **identical** —
the notebooks are reused verbatim; only `fabric/` is omitted.

> **Dual purpose**: this project is also the starter template for a
> Databricks + Power BI (no Fabric) client distribution.

## Source dataset

Databricks **built-in `samples.tpch.*` UC catalog** — available on every
Databricks workspace (free-tier included), zero CSV shipped. Mapping TPC-H →
AcmeSales:

| TPC-H source | Becomes |
|---|---|
| `samples.tpch.lineitem` JOIN `orders` | `bronze_sales` |
| `samples.tpch.part` | `bronze_products` |
| `samples.tpch.customer` | `bronze_customers` |

## First-run setup (every adopter)

1. **Copy credentials template**
   ```bash
   cp config/credentials.example.yaml config/credentials.yaml
   # Edit credentials.yaml with your Databricks PAT.
   ```

2. **Set environment variables** (PowerShell)
   ```powershell
   $env:DEMO_USER_EMAIL       = "you@example.com"        # your Databricks workspace user
   $env:DATABRICKS_HOST       = "https://<your-ws>.cloud.databricks.com"
   $env:DATABRICKS_TOKEN      = "dapi..."                # PAT (or put it in credentials.yaml)
   # --- for the Import-mode semantic model M expression ---
   $env:DATABRICKS_SQL_HOST   = "<your-ws>.cloud.databricks.com"   # bare host, NO https://
   $env:DATABRICKS_WAREHOUSE_ID = "<sql-warehouse-id>"  # from the warehouse connection details
   # --- for publishing to Power BI ---
   $env:FABRIC_TENANT_ID      = "<your-azure-tenant-id>"
   $env:PBI_WORKSPACE_DEV     = "<dev-powerbi-workspace-id>"
   $env:PBI_WORKSPACE_CERT    = "<cert-powerbi-workspace-id>"
   $env:PBI_WORKSPACE_PROD    = "<prod-powerbi-workspace-id>"
   ```

   `DATABRICKS_SQL_HOST` + `DATABRICKS_WAREHOUSE_ID` + the per-env catalog are
   substituted into `src/power_bi/AcmeSales.SemanticModel/definition/expressions.tmdl`
   by the overlay `transforms` at push time, so the deployed model points at the
   adopter's own warehouse.

3. **Run the bronze seeder once** — the `_setup` notebooks are excluded from the
   synced pipeline (overlay `exclude: ["_setup/*"]`). Trigger manually via the
   Databricks UI or `dbutils.notebook.run` to seed `bronze_*` from `samples.tpch.*`:
   ```python
   dbutils.notebook.run("_setup/create_demo_tables", 600)
   ```
   Idempotent (overwrite). Silver / gold notebooks assume the bronze tables exist.

## Environments

| Env | Databricks catalog | Databricks workspace path | Power BI workspace |
|---|---|---|---|
| DEV | `workspace.default` | `/Users/${DEMO_USER_EMAIL}/acme_powerbi_demo` | `${PBI_WORKSPACE_DEV}` |
| CERT | `acme_cert.default` | `/Shared/AcmePowerBI/CERT/` | `${PBI_WORKSPACE_CERT}` |
| PROD | `acme_prod.default` | `/Shared/AcmePowerBI/PROD/` | `${PBI_WORKSPACE_PROD}` |

## End-to-end workflow

After first-run setup:

```
python -m core.cli preflight                       # deps + creds check
python -m core.cli push --env dev --dry-run        # see what would change
python -m core.cli push --env dev --scope notebooks  # deploy bronze/silver/gold
# In Databricks: run _setup/create_demo_tables, then silver/*, then gold/*
/powerbi-publish --env dev                          # publish AcmeSales.SemanticModel
                                                    # (M placeholders resolved by overlay)
# Refresh the model in Power BI so Import pulls the Databricks gold layer
python -m core.cli diff --env dev                   # confirm in sync
```

### The report — built from a spec, not shipped pre-built

The project ships `reports/AcmeSales_Overview.spec.yaml` (the *recipe*), not a
pre-built `.Report`. The agent turns it into a PBIR report on the fly — the
build is reasoned and reproducible, and the spec doubles as a reusable starter
template:

```
/pbir-create AcmeSales_Overview --env dev --model-id {guid} \
    --spec reports/AcmeSales_Overview.spec.yaml
```

`{guid}` is the semantic model id returned by `/powerbi-publish`; alternatively
`--model-name AcmeSales` binds the sibling local `.SemanticModel` folder. The
spec's entities/properties match the model (`fct_sales`, `dim_product`,
`dim_customer`).

## Validate the semantic model

The TMDL is authored by hand here (DirectLake → Import conversion). Before the
first publish, open `src/power_bi/AcmeSales.SemanticModel/` in **Power BI
Desktop** (or Tabular Editor) once to validate syntax and let it normalize on
save — same posture as the parent reference model.

## Skills you'll typically invoke

| Stage | Skill |
|---|---|
| First-run | `/ops-onboarding`, `/ops-init` (if scaffolding a new project) |
| Audit | `/databricks-status`, `/databricks-lineage` |
| Deploy notebooks | `/ops-push`, `/databricks-deploy` |
| Run | `/databricks-run` |
| PBI authoring | `/powerbi-model-create`, `/powerbi-model-edit`, `/pbir-create` |
| PBI deploy | `/powerbi-publish`, `/pbir-report` |
| State | `/ops-pull`, `/ops-diff`, `/ops-status` |
| Promote | `/ops-push --env cert`, `/ops-push --env prod` |

## Pipeline graph

```
samples.tpch.part      → bronze_products      → silver_products     → gold_dm_product
samples.tpch.customer  → bronze_customers     ──────────────────────────────────┐
samples.tpch.lineitem  → bronze_sales         → silver_sales        → gold_ft_sales
samples.tpch.orders    ↗                                                  │      │
                                            (dim_customer ← bronze_customers)    │
                                                                                 ↓
                              AcmeSales.SemanticModel (Import, Databricks.Catalogs)
                                                                                 ↓
                              AcmeSales_Overview.Report (PBIR, from spec)
```
