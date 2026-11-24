# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Build the document collection
# MAGIC Goal: gather every piece of text the Copilot should be able to search and cite, into ONE table: `gold.documents`.
# MAGIC
# MAGIC | Source | Where it comes from | doc_type |
# MAGIC |---|---|---|
# MAGIC | Technician notes | `silver.work_orders` | `work_order` |
# MAGIC | Standard operating procedures | `documents/sops/*.md` in this repo | `sop` |
# MAGIC | Fault code guide | `silver.spn_reference` + `silver.fmi_reference` | `dtc_guide` |
# MAGIC
# MAGIC Output schema (one row per document):
# MAGIC `doc_id, doc_type, title, text, vin, unit_no, model, system_category, dtc_codes, doc_date, source_ref`

# COMMAND ----------

# MAGIC %md ## Step 1 · Setup (catalog widget, imports, sys.path to ../src)

# COMMAND ----------

# TODO
dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

import os, sys, importlib
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

import fleet_rag.documents as D
importlib.reload(D)
# COMMAND ----------

# MAGIC %md ## Step 2 · Work orders → documents
# MAGIC One document per work order. Text = complaint + technician notes + parts used.
# MAGIC Keep metadata (vin, unit_no, system_category, dtc_refs, opened_at) - we filter on it later.

# COMMAND ----------

# TODO
wo_docs = D.work_order_documents(
    spark.table("silver.work_orders"),
    spark.table("silver.work_order_parts"),
    spark.table("silver.vehicles"),
)
print("documents:", wo_docs.count())
display(wo_docs.limit(5))
print(wo_docs.first().text)
# COMMAND ----------

# MAGIC %md ## Step 3 · SOP markdown files → documents
# MAGIC Read each file in `../documents/sops/`. Title = first `# heading`. One document per file.

# COMMAND ----------

# TODO
sop_folder = os.path.abspath(os.path.join(os.getcwd(), "..", "documents", "sops"))
sop_list = D.sop_documents(sop_folder)

print(len(sop_list), "SOPs")
for d in sop_list:
    print(d["doc_id"], "|", d["system_category"], "|", d["title"], "|", d["dtc_codes"])

sop_docs = spark.createDataFrame(sop_list, schema=D.DOC_SCHEMA)   # list of dicts -> Spark table
display(sop_docs)
# COMMAND ----------

# MAGIC %md ## Step 4 · Fault code guide → documents
# MAGIC One document per SPN: name, system, which FMIs we see in the fleet, and what the driver should do.

# COMMAND ----------

# TODO
dtc_docs = D.dtc_guide_documents(
    spark.table("silver.spn_reference"),
    spark.table("silver.fmi_reference"),
    spark.table("silver.dtc_events"),
)
print("guides:", dtc_docs.count())
print(dtc_docs.filter("doc_id = 'DTC-SPN-110'").first().text)
print()
print(dtc_docs.filter("doc_id = 'DTC-SPN-655'").first().text)

# COMMAND ----------

# MAGIC %md ## Step 5 · Union all sources and save `gold.documents`

# COMMAND ----------

# TODO
from pyspark.sql import functions as F

documents = (wo_docs
             .unionByName(sop_docs)
             .unionByName(dtc_docs)
             # some older work orders say "fuel", the rest say "fuel_system": use one name everywhere
             .withColumn("system_category",
                         F.when(F.col("system_category") == "fuel", "fuel_system").otherwise(F.col("system_category")))
             .withColumn("n_chars", F.length("text")))

documents.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("gold.documents")

spark.sql("""COMMENT ON TABLE gold.documents IS
  'All searchable text for the Copilot: work-order notes, SOPs and fault code guides. One row per document; chunked in notebook 06.'""")
print("gold.documents:", spark.table("gold.documents").count(), "rows")
# COMMAND ----------

# MAGIC %md ## Step 6 · Sanity checks
# MAGIC Count by doc_type, look at a few rows, check no empty text.

# COMMAND ----------

# TODO
docs = spark.table("gold.documents")

# 1. How many documents of each type, and how long they are
display(docs.groupBy("doc_type").agg(
    F.count("*").alias("docs"),
    F.round(F.avg("n_chars")).alias("avg_chars"),
    F.max("n_chars").alias("max_chars")))

# 2. No empty text, no duplicate ids
print("empty texts:", docs.filter(F.col("text").isNull() | (F.length(F.trim("text")) == 0)).count())
print("duplicate doc_ids:", docs.groupBy("doc_id").count().filter("count > 1").count())

# 3. Coverage: which systems have repairs, SOPs and guides
display(docs.groupBy("system_category").pivot("doc_type").count().orderBy("system_category"))