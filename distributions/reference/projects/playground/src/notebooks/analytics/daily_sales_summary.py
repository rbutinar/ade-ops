# Databricks notebook source
# MAGIC %md
# MAGIC # Playground — daily sales summary
# MAGIC
# MAGIC The one analytics step of the playground pipeline. Reads the synthetic
# MAGIC `pg_sales` / `pg_products` / `pg_customers` tables (seeded by
# MAGIC `_setup/generate_synthetic_data`) and writes `pg_daily_sales_summary` —
# MAGIC revenue + quantity + transaction count per day, category and region.
# MAGIC
# MAGIC This is the notebook ade-ops deploys (`push`) and runs (`/databricks-run`).
# MAGIC Keep it small: the playground is the "operational in 5 minutes" path.

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

sales = spark.table("pg_sales")
products = spark.table("pg_products").select("product_id", "category")
customers = spark.table("pg_customers").select("customer_id", "region")

summary = (
    sales
    .join(products, "product_id", "left")
    .join(customers, "customer_id", "left")
    .groupBy("sale_date", "category", "region", "channel")
    .agg(
        F.round(F.sum("amount"), 2).alias("total_revenue"),
        F.sum("quantity").alias("total_quantity"),
        F.count("*").alias("transaction_count"),
    )
    .orderBy("sale_date", "category", "region")
)

summary.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    "pg_daily_sales_summary"
)
print(f"pg_daily_sales_summary: {summary.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC Inspect the result:
# MAGIC `/databricks-query "SELECT * FROM pg_daily_sales_summary ORDER BY total_revenue DESC LIMIT 20"`

# COMMAND ----------

display(
    summary.groupBy("category")
    .agg(F.round(F.sum("total_revenue"), 2).alias("revenue"))
    .orderBy(F.desc("revenue"))
)
