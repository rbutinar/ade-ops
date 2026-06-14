# Databricks notebook source
# MAGIC %md
# MAGIC # Hydrate Fabric Lakehouse from external Databricks (Gold layer)
# MAGIC
# MAGIC This notebook runs **inside Fabric** (Spark notebook on the
# MAGIC lakehouse). It reads the gold tables from an external Databricks
# MAGIC workspace via JDBC and writes them as Delta tables into the Fabric
# MAGIC Lakehouse.
# MAGIC
# MAGIC ## When to use this notebook
# MAGIC
# MAGIC Use this **cross-tenant JDBC bridge** pattern when:
# MAGIC
# MAGIC - The source Databricks workspace is NOT Azure Databricks (e.g. AWS
# MAGIC   `dbc-*.cloud.databricks.com`, GCP, or community-tier free), so
# MAGIC   Fabric Mirrored Databricks Catalog is **not available** (Mirroring
# MAGIC   supports only Azure Databricks `adb-*.azuredatabricks.net`).
# MAGIC - You want a one-shot data hydration that copies gold layer rows
# MAGIC   into the lakehouse so Direct Lake semantic models can serve them.
# MAGIC - You need to demonstrate end-to-end integration without setting up
# MAGIC   Azure Databricks just for the demo.
# MAGIC
# MAGIC ## When NOT to use
# MAGIC
# MAGIC - Source is Azure Databricks → use **Fabric Mirrored Databricks
# MAGIC   Catalog** instead (zero-copy, real-time, no JDBC).
# MAGIC - Source data is already in OneLake / another Lakehouse → use
# MAGIC   shortcut, not JDBC.
# MAGIC - Production with PII / regulated data → JDBC + cross-tenant secret
# MAGIC   transfer needs hardening (use Azure Key Vault linked to Fabric
# MAGIC   workspace, never inline tokens).
# MAGIC
# MAGIC ## Setup before running
# MAGIC
# MAGIC 1. **Databricks side** — bronze / silver / gold layers must be built
# MAGIC    and accessible. Run `_setup/create_demo_tables.py` →
# MAGIC    `silver/*.py` → `gold/*.py` on the source Databricks first.
# MAGIC 2. **Databricks PAT** — generate a Personal Access Token on the
# MAGIC    source Databricks (User Settings → Developer → Access Tokens).
# MAGIC    SQL Warehouse compute permissions needed (or All-purpose cluster
# MAGIC    if you set `--cluster-id` below).
# MAGIC 3. **Token storage** — see "Token storage options" section below.
# MAGIC 4. **Fabric Lakehouse** — must exist and be attached to the notebook
# MAGIC    (right pane → "Add lakehouse"). The `default_lakehouse` becomes
# MAGIC    the target.
# MAGIC 5. **Network** — Fabric Spark must reach the source Databricks host.
# MAGIC    Default capacities allow outbound HTTPS to public Databricks
# MAGIC    workspaces. Behind VNet / Private Link this needs explicit egress.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration — parameters

# COMMAND ----------

# Parametrised so the same notebook works for any source workspace.
# When deployed via /fabric-notebook-deploy, the overlay can rewrite these
# defaults per environment (dev / cert / prod).

DATABRICKS_HOST = "https://<your-databricks-host>.cloud.databricks.com"
SQL_WAREHOUSE_ID = "<your-warehouse-id>"   # SQL Warehouse on the source; alt: cluster_id
SOURCE_CATALOG = "workspace"               # Source UC catalog (often 'workspace' on free-tier)
SOURCE_SCHEMA = "default"

# Tables to hydrate (gold layer)
GOLD_TABLES = ["gold_dm_product", "gold_dm_customer", "gold_ft_sales"]

# Target lakehouse table prefix (none = same name, optional prefix to namespace)
LAKEHOUSE_TARGET_PREFIX = ""               # e.g. "acme_" to land as acme_gold_dm_product

# COMMAND ----------

# MAGIC %md
# MAGIC ## Token storage options
# MAGIC
# MAGIC Pick **one** based on your security posture:
# MAGIC
# MAGIC ### Option A (recommended for production-ish demos) — Azure Key Vault linked to Fabric workspace
# MAGIC
# MAGIC Link an Azure Key Vault to the Fabric workspace via
# MAGIC Workspace settings → Data engineering → Azure Key Vault. Store the
# MAGIC PAT under a secret name (e.g. `databricks-pat-demo`). Reference it
# MAGIC at runtime via `mssparkutils.credentials.getSecret`.
# MAGIC
# MAGIC ### Option B (demo-only, plain) — notebook session variable
# MAGIC
# MAGIC Paste the token directly below. Trade-off: token is visible in the
# MAGIC notebook source, anyone with notebook read access can see it.
# MAGIC **Never commit the resolved token to git**; the demo deploy pipeline
# MAGIC reads it from the operator-side overlay or env var at deploy time.
# MAGIC
# MAGIC ### Option C — Fabric workspace identity (only for Azure Databricks source)
# MAGIC
# MAGIC Configure the Databricks source to accept the Fabric workspace
# MAGIC managed identity. No token at all. Only works with Azure Databricks
# MAGIC + AAD passthrough enabled — same constraint as Mirroring, so if
# MAGIC you're already in Option A/B you don't have this choice.

# COMMAND ----------

# Resolve the token. Option A is the prod-ish path; Option B is the demo
# fallback. Try A first, fall back to B if not configured.

databricks_token = None
try:
    # Option A — Key Vault via Fabric workspace integration
    KEY_VAULT_NAME = "<your-key-vault-name>"
    SECRET_NAME = "databricks-pat-demo"
    databricks_token = mssparkutils.credentials.getSecret(KEY_VAULT_NAME, SECRET_NAME)  # noqa: F821
    print("Token resolved via Azure Key Vault.")
except Exception as exc:
    print(f"Key Vault path unavailable ({exc}); falling back to inline token.")
    # Option B — paste here for demo-only; rotate after the demo
    databricks_token = "<your-databricks-pat>"

if not databricks_token or databricks_token == "<your-databricks-pat>":
    raise RuntimeError(
        "DATABRICKS token not configured. Set either Key Vault secret "
        "or inline value above before running this notebook."
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## JDBC connection string

# COMMAND ----------

# Databricks JDBC URL format. The SQL Warehouse's HTTP path is the
# stable connection endpoint (versus all-purpose cluster paths which
# change per cluster).
#
# Reference: https://docs.databricks.com/integrations/jdbc/index.html

jdbc_url = (
    f"jdbc:databricks://{DATABRICKS_HOST.replace('https://', '')}:443;"
    f"transportMode=http;ssl=1;"
    f"AuthMech=3;UID=token;PWD={databricks_token};"
    f"httpPath=/sql/1.0/warehouses/{SQL_WAREHOUSE_ID};"
    f"ConnCatalog={SOURCE_CATALOG};ConnSchema={SOURCE_SCHEMA}"
)

# Spark read options shared across all tables
read_options = {
    "url": jdbc_url,
    "driver": "com.databricks.client.jdbc.Driver",
    "fetchsize": "10000",
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Hydrate each gold table

# COMMAND ----------

for table_name in GOLD_TABLES:
    source_fqn = f"{SOURCE_CATALOG}.{SOURCE_SCHEMA}.{table_name}"
    target_table = f"{LAKEHOUSE_TARGET_PREFIX}{table_name}"

    print(f"→ {source_fqn}  →  Lakehouse table `{target_table}` ...", end="", flush=True)

    df = (
        spark.read
        .format("jdbc")
        .options(**read_options, dbtable=source_fqn)
        .load()
    )

    row_count = df.count()

    (
        df.write
        .format("delta")
        .mode("overwrite")
        .saveAsTable(target_table)
    )

    print(f" {row_count} rows  ✓")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Smoke check — verify tables and row counts

# COMMAND ----------

for table_name in GOLD_TABLES:
    target_table = f"{LAKEHOUSE_TARGET_PREFIX}{table_name}"
    count = spark.sql(f"SELECT count(*) AS n FROM {target_table}").collect()[0]["n"]
    print(f"  {target_table}: {count:>10,} rows")

print("\nHydration complete. Direct Lake semantic models pointing to these tables should now serve real data.")
