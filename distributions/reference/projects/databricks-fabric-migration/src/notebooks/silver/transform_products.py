# Databricks notebook source
# MAGIC %md
# MAGIC # Silver Layer: Transform Products
# MAGIC
# MAGIC **Pipeline**: AcmeSales - Medallion Architecture
# MAGIC **Layer**: Silver (cleaned & enriched)
# MAGIC **Source**: `bronze_products`
# MAGIC **Target**: `silver_products`

# COMMAND ----------

SOURCE_TABLE = "bronze_products"
TARGET_TABLE = "silver_products"

# COMMAND ----------

from pyspark.sql import functions as F

df_bronze = spark.table(SOURCE_TABLE)
print(f"Read {df_bronze.count()} records from {SOURCE_TABLE}")

# COMMAND ----------

# Normalise category from p_type ("STANDARD POLISHED BRASS", etc.)
# into a simpler bucket for slicer-friendly grouping.
df_silver = (
    df_bronze
    .withColumn("category_top",
        F.when(F.col("category").contains("STANDARD"), "Standard")
         .when(F.col("category").contains("PROMO"), "Promo")
         .when(F.col("category").contains("ECONOMY"), "Economy")
         .when(F.col("category").contains("MEDIUM"), "Medium")
         .when(F.col("category").contains("LARGE"), "Large")
         .otherwise("Other")
    )
    .withColumn("material",
        F.when(F.col("category").contains("BRASS"), "Brass")
         .when(F.col("category").contains("COPPER"), "Copper")
         .when(F.col("category").contains("STEEL"), "Steel")
         .when(F.col("category").contains("NICKEL"), "Nickel")
         .when(F.col("category").contains("TIN"), "Tin")
         .otherwise("Other")
    )
    .withColumn("price_bucket",
        F.when(F.col("unit_price") < 500, "Budget")
         .when(F.col("unit_price") < 1500, "Standard")
         .otherwise("Premium")
    )
)

# COMMAND ----------

df_clean = df_silver.filter(F.col("product_id").isNotNull())
df_final = df_clean.withColumn("_silver_timestamp", F.current_timestamp())

df_final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Wrote {df_final.count()} records to {TARGET_TABLE}")

# COMMAND ----------

display(spark.table(TARGET_TABLE).limit(10))
