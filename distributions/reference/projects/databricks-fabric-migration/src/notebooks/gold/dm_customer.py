# Databricks notebook source
# MAGIC %md
# MAGIC # Gold Layer: Dimension Customer
# MAGIC
# MAGIC **Pipeline**: AcmeSales - Medallion Architecture
# MAGIC **Layer**: Gold (business-ready)
# MAGIC **Source**: `bronze_customers` (direct — no silver layer needed for this dim)
# MAGIC **Target**: `gold_dm_customer`

# COMMAND ----------

SOURCE_TABLE = "bronze_customers"
TARGET_TABLE = "gold_dm_customer"

# COMMAND ----------

from pyspark.sql import functions as F

df_bronze = spark.table(SOURCE_TABLE)
print(f"Read {df_bronze.count()} records from {SOURCE_TABLE}")

# COMMAND ----------

df_final = (
    df_bronze
    .select(
        "customer_id",
        "customer_name",
        "segment",
        "account_balance",
    )
    .withColumn("balance_bucket",
        F.when(F.col("account_balance") < 0, "Overdraft")
         .when(F.col("account_balance") < 1000, "Low")
         .when(F.col("account_balance") < 5000, "Medium")
         .otherwise("High")
    )
    .withColumn("customer_key",
        F.sha2(F.col("customer_id"), 256)
    )
    .withColumn("_gold_timestamp", F.current_timestamp())
)

df_final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Wrote {df_final.count()} records to {TARGET_TABLE}")

# COMMAND ----------

display(spark.table(TARGET_TABLE).limit(10))
