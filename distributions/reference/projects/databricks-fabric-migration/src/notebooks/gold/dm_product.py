# Databricks notebook source
# MAGIC %md
# MAGIC # Gold Layer: Dimension Product
# MAGIC
# MAGIC **Pipeline**: AcmeSales - Medallion Architecture
# MAGIC **Layer**: Gold (business-ready)
# MAGIC **Source**: `silver_products`
# MAGIC **Target**: `gold_dm_product`
# MAGIC
# MAGIC Slowly-changing dimension type 1 (overwrite). Adds surrogate key.

# COMMAND ----------

SOURCE_TABLE = "silver_products"
TARGET_TABLE = "gold_dm_product"

# COMMAND ----------

from pyspark.sql import functions as F

df_silver = spark.table(SOURCE_TABLE)
print(f"Read {df_silver.count()} records from {SOURCE_TABLE}")

# COMMAND ----------

df_final = (
    df_silver
    .select(
        "product_id",
        "product_name",
        "manufacturer",
        "brand",
        F.col("category_top").alias("category"),
        "material",
        "size",
        "container",
        "unit_price",
        "price_bucket",
    )
    .withColumn("product_key",
        F.sha2(F.col("product_id"), 256)
    )
    .withColumn("_gold_timestamp", F.current_timestamp())
)

df_final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Wrote {df_final.count()} records to {TARGET_TABLE}")

# COMMAND ----------

display(spark.table(TARGET_TABLE).limit(10))
