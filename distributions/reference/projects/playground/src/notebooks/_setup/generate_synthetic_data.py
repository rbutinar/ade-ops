# Databricks notebook source
# MAGIC %md
# MAGIC # Playground — generate synthetic data
# MAGIC
# MAGIC Self-contained synthetic dataset for the ade-ops zero-friction playground.
# MAGIC Creates three tables — `pg_products`, `pg_customers`, `pg_sales` — using
# MAGIC pure Spark (no external catalog, no CSV, no `samples.*` dependency), so it
# MAGIC runs on **any** Databricks workspace including free-tier / Community Edition.
# MAGIC
# MAGIC Idempotent: re-run any time, it overwrites. This notebook is a `_setup`
# MAGIC seeder — excluded from the synced pipeline (overlay `exclude: ["_setup/*"]`),
# MAGIC run it once manually before the analytics notebook.

# COMMAND ----------

from pyspark.sql import functions as F

# Tunable size — keep small so a free-tier cluster finishes in seconds.
N_PRODUCTS = 50
N_CUSTOMERS = 200
N_SALES = 5000
SEED = 42

CATEGORIES = ["Electronics", "Home", "Sports", "Apparel", "Grocery"]
REGIONS = ["North", "South", "East", "West"]
SEGMENTS = ["Consumer", "SMB", "Enterprise"]
CHANNELS = ["Online", "Retail", "Partner"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Dimensions

# COMMAND ----------

products = (
    spark.range(1, N_PRODUCTS + 1)
    .withColumnRenamed("id", "product_id")
    .withColumn("product_name", F.concat(F.lit("Product "), F.col("product_id")))
    .withColumn("category",
                F.element_at(F.array([F.lit(c) for c in CATEGORIES]),
                             (F.col("product_id") % len(CATEGORIES) + 1).cast("int")))
    .withColumn("unit_price", F.round(F.rand(SEED) * 480 + 20, 2))
)
products.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pg_products")
print(f"pg_products: {products.count()} rows")

# COMMAND ----------

customers = (
    spark.range(1, N_CUSTOMERS + 1)
    .withColumnRenamed("id", "customer_id")
    .withColumn("customer_name", F.concat(F.lit("Customer "), F.col("customer_id")))
    .withColumn("region",
                F.element_at(F.array([F.lit(r) for r in REGIONS]),
                             (F.col("customer_id") % len(REGIONS) + 1).cast("int")))
    .withColumn("segment",
                F.element_at(F.array([F.lit(s) for s in SEGMENTS]),
                             (F.col("customer_id") % len(SEGMENTS) + 1).cast("int")))
)
customers.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pg_customers")
print(f"pg_customers: {customers.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fact — synthetic sales over the last 90 days

# COMMAND ----------

sales = (
    spark.range(1, N_SALES + 1)
    .withColumnRenamed("id", "sale_id")
    .withColumn("product_id", (F.rand(SEED + 1) * N_PRODUCTS + 1).cast("int"))
    .withColumn("customer_id", (F.rand(SEED + 2) * N_CUSTOMERS + 1).cast("int"))
    .withColumn("quantity", (F.rand(SEED + 3) * 9 + 1).cast("int"))
    .withColumn("sale_date",
                F.date_sub(F.current_date(), (F.rand(SEED + 4) * 90).cast("int")))
    .withColumn("channel",
                F.element_at(F.array([F.lit(c) for c in CHANNELS]),
                             (F.col("sale_id") % len(CHANNELS) + 1).cast("int")))
)
# Join unit_price to derive a realistic amount.
sales = (
    sales.join(products.select("product_id", "unit_price"), "product_id", "left")
    .withColumn("amount", F.round(F.col("quantity") * F.col("unit_price"), 2))
    .drop("unit_price")
)
sales.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pg_sales")
print(f"pg_sales: {sales.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC Done. Next: run `analytics/daily_sales_summary`, or query directly with
# MAGIC `/databricks-query "SELECT * FROM pg_sales LIMIT 10"`.
