# Databricks notebook source
# MAGIC %md
# MAGIC # Gold Layer: Fact Sales
# MAGIC
# MAGIC **Pipeline**: AcmeSales - Medallion Architecture
# MAGIC **Layer**: Gold (business-ready)
# MAGIC **Source**: `silver_sales`
# MAGIC **Target**: `gold_ft_sales`
# MAGIC
# MAGIC Aggregate to daily grain + product + customer + priority. Adds business
# MAGIC metrics and surrogate key. Consumed by the AcmeSales DirectLake
# MAGIC semantic model.

# COMMAND ----------

SOURCE_TABLE = "silver_sales"
TARGET_TABLE = "gold_ft_sales"

# COMMAND ----------

from pyspark.sql import functions as F

df_silver = spark.table(SOURCE_TABLE)
print(f"Read {df_silver.count()} records from {SOURCE_TABLE}")

# COMMAND ----------

df_fact = (
    df_silver
    .groupBy("sale_date", "product_id", "customer_id", "priority", "channel", "region")
    .agg(
        F.sum("quantity").alias("total_quantity"),
        F.sum("total_amount").alias("total_revenue"),
        F.count("sale_id").alias("transaction_count"),
        F.avg("unit_price").alias("avg_unit_price"),
        F.min("unit_price").alias("min_unit_price"),
        F.max("unit_price").alias("max_unit_price"),
    )
)

# COMMAND ----------

df_enriched = (
    df_fact
    .withColumn("revenue_per_transaction",
        F.round(F.col("total_revenue") / F.col("transaction_count"), 2)
    )
    .withColumn("avg_quantity_per_transaction",
        F.round(F.col("total_quantity") / F.col("transaction_count"), 2)
    )
    .withColumn("fiscal_year", F.year("sale_date"))
    .withColumn("fiscal_quarter", F.quarter("sale_date"))
    .withColumn("fiscal_month", F.month("sale_date"))
)

# COMMAND ----------

df_final = (
    df_enriched
    .withColumn("fact_key",
        F.sha2(
            F.concat_ws("_",
                F.col("sale_date"),
                F.col("product_id"),
                F.col("customer_id"),
                F.col("priority"),
            ), 256
        )
    )
    .withColumn("_gold_timestamp", F.current_timestamp())
)

df_final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Wrote {df_final.count()} records to {TARGET_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary checks

# COMMAND ----------

display(
    spark.table(TARGET_TABLE)
    .groupBy("priority")
    .agg(
        F.sum("total_revenue").alias("revenue"),
        F.sum("total_quantity").alias("units"),
        F.sum("transaction_count").alias("transactions"),
    )
    .orderBy(F.col("revenue").desc())
)

# COMMAND ----------

display(
    spark.table(TARGET_TABLE)
    .groupBy("fiscal_year", "fiscal_month")
    .agg(F.sum("total_revenue").alias("monthly_revenue"))
    .orderBy("fiscal_year", "fiscal_month")
)
