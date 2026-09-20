# Databricks notebook source
# MAGIC %md
# MAGIC # Silver Layer: Transform Sales
# MAGIC
# MAGIC **Pipeline**: AcmeSales - Medallion Architecture
# MAGIC **Layer**: Silver (cleaned & transformed)
# MAGIC **Source**: `bronze_sales`
# MAGIC **Target**: `silver_sales`
# MAGIC
# MAGIC Transformations:
# MAGIC - Parse dates
# MAGIC - Calculate derived fields
# MAGIC - Apply data quality rules
# MAGIC - Deduplicate

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

SOURCE_TABLE = "bronze_sales"
TARGET_TABLE = "silver_sales"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Bronze

# COMMAND ----------

from pyspark.sql import functions as F

df_bronze = spark.table(SOURCE_TABLE)
print(f"Read {df_bronze.count()} records from {SOURCE_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Transform

# COMMAND ----------

df_silver = (
    df_bronze
    .withColumn("sale_date", F.to_date("sale_date"))
    .withColumn("is_weekend", F.dayofweek("sale_date").isin([1, 7]))
    .withColumn("amount_bucket",
        F.when(F.col("total_amount") < 1000, "Small")
         .when(F.col("total_amount") < 10000, "Medium")
         .when(F.col("total_amount") < 50000, "Large")
         .otherwise("XLarge")
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Quality

# COMMAND ----------

df_clean = (
    df_silver
    .filter(F.col("quantity") > 0)
    .filter(F.col("unit_price") > 0)
    .filter(F.col("customer_id").isNotNull())
    .filter(F.col("product_id").isNotNull())
)

removed = df_silver.count() - df_clean.count()
print(f"Removed {removed} invalid records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deduplicate

# COMMAND ----------

from pyspark.sql.window import Window

window = Window.partitionBy("sale_id").orderBy(F.col("sale_date").desc())
df_deduped = (
    df_clean
    .withColumn("_row_num", F.row_number().over(window))
    .filter(F.col("_row_num") == 1)
    .drop("_row_num")
)
print(f"After dedup: {df_deduped.count()} records")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Metadata + Write

# COMMAND ----------

df_final = df_deduped.withColumn("_silver_timestamp", F.current_timestamp())

df_final.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Wrote {df_final.count()} records to {TARGET_TABLE}")

# COMMAND ----------

display(spark.table(TARGET_TABLE).limit(10))
