# Databricks notebook source
# MAGIC %md
# MAGIC # AcmeSales - Demo Data Setup
# MAGIC
# MAGIC One-time seed that materialises the bronze layer from the Databricks
# MAGIC built-in `samples.tpch.*` catalog. Run once per environment before
# MAGIC executing the silver / gold notebooks for the first time.
# MAGIC
# MAGIC **Source**: `samples.tpch.{lineitem, part, customer}` (built-in UC
# MAGIC catalog, available on every Databricks workspace including free-tier)
# MAGIC
# MAGIC **Targets**:
# MAGIC - `bronze_sales` — derived from `samples.tpch.lineitem`
# MAGIC - `bronze_products` — derived from `samples.tpch.part`
# MAGIC - `bronze_customers` — derived from `samples.tpch.customer`
# MAGIC
# MAGIC `_setup/*` notebooks are excluded from the synced pipeline by overlay
# MAGIC (`exclude: ["_setup/*"]`). Run them via the Databricks UI or `dbutils`
# MAGIC explicitly when bootstrapping a new environment.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Use unqualified table names so Fabric and Databricks both resolve them
# inside the lakehouse / catalog default namespace.
DATABASE = ""

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: products (from samples.tpch.part)

# COMMAND ----------

from pyspark.sql import functions as F

df_products = (
    spark.table("samples.tpch.part")
    .select(
        F.concat(F.lit("PROD-"), F.format_string("%04d", F.col("p_partkey"))).alias("product_id"),
        F.col("p_name").alias("product_name"),
        F.col("p_mfgr").alias("manufacturer"),
        F.col("p_brand").alias("brand"),
        F.col("p_type").alias("category"),
        F.col("p_size").alias("size"),
        F.col("p_container").alias("container"),
        F.col("p_retailprice").alias("unit_price"),
    )
    .limit(2000)
)

df_products.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("bronze_products")
print(f"Created bronze_products with {df_products.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: customers (from samples.tpch.customer)

# COMMAND ----------

df_customers = (
    spark.table("samples.tpch.customer")
    .select(
        F.concat(F.lit("CUST-"), F.format_string("%05d", F.col("c_custkey"))).alias("customer_id"),
        F.col("c_name").alias("customer_name"),
        F.col("c_address").alias("address"),
        F.col("c_phone").alias("phone"),
        F.col("c_mktsegment").alias("segment"),
        F.col("c_acctbal").alias("account_balance"),
    )
    .limit(5000)
)

df_customers.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("bronze_customers")
print(f"Created bronze_customers with {df_customers.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Bronze: sales (from samples.tpch.lineitem JOIN orders)

# COMMAND ----------

df_sales = (
    spark.table("samples.tpch.lineitem").alias("l")
    .join(
        spark.table("samples.tpch.orders").alias("o"),
        F.col("l.l_orderkey") == F.col("o.o_orderkey"),
    )
    .select(
        F.concat(F.lit("SALE-"), F.format_string("%07d", F.col("l.l_orderkey"))).alias("sale_id"),
        F.col("o.o_orderdate").alias("sale_date"),
        F.concat(F.lit("PROD-"), F.format_string("%04d", F.col("l.l_partkey"))).alias("product_id"),
        F.concat(F.lit("CUST-"), F.format_string("%05d", F.col("o.o_custkey"))).alias("customer_id"),
        F.col("l.l_quantity").alias("quantity"),
        F.col("l.l_extendedprice").alias("unit_price"),
        (F.col("l.l_extendedprice") * (1 - F.col("l.l_discount"))).alias("total_amount"),
        (F.col("l.l_discount") * 100).alias("discount_pct"),
        F.col("o.o_orderpriority").alias("priority"),
        F.element_at(
            F.array(F.lit("Online"), F.lit("Retail Store"), F.lit("Wholesale"), F.lit("B2B")),
            (F.pmod(F.crc32(F.col("l.l_orderkey").cast("string")), F.lit(4)) + 1).cast("int"),
        ).alias("channel"),
        F.element_at(
            F.array(F.lit("EMEA"), F.lit("Americas"), F.lit("APAC"), F.lit("LATAM")),
            (F.pmod(F.crc32(F.col("o.o_custkey").cast("string")), F.lit(4)) + 1).cast("int"),
        ).alias("region"),
        F.col("l.l_returnflag").alias("status"),
    )
    .limit(20000)
)

df_sales.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("bronze_sales")
print(f"Created bronze_sales with {df_sales.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

print("Demo bronze tables ready:")
print(f"  bronze_products:  {spark.table('bronze_products').count()} rows")
print(f"  bronze_customers: {spark.table('bronze_customers').count()} rows")
print(f"  bronze_sales:     {spark.table('bronze_sales').count()} rows")

# COMMAND ----------

display(spark.table("bronze_sales").limit(5))
