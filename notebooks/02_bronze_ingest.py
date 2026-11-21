# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Bronze: ingest raw files into Delta tables
# MAGIC * **Telematics, fault codes, work orders** → Auto Loader (`cloudFiles`) with schema inference and evolution.
# MAGIC   It only picks up files it hasn't seen, so the same code works for a one-off load and for daily increments.
# MAGIC * **Reference CSVs** → full overwrite (small, slowly changing).
# MAGIC * **Ground truth** → `eval` schema, kept apart from anything the Copilot can query.
# MAGIC * **Volvo Discovery Challenge data** (optional) → one bronze table per CSV you upload.
# MAGIC
# MAGIC Bronze keeps data as received, plus `_ingested_at`, `_source_file` and `_rescued_data` (fields that didn't match the schema).

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
dbutils.widgets.dropdown("reset", "no", ["no", "yes"], "Reset bronze (drop tables + checkpoints)")
CATALOG = dbutils.widgets.get("catalog")
RAW = f"/Volumes/{CATALOG}/bronze/raw"
CHECKPOINTS = f"{RAW}/_checkpoints"
spark.sql(f"USE CATALOG {CATALOG}")

# COMMAND ----------

STREAM_TABLES = {
    # bronze table           source folder            schema hints (keep timestamps as raw strings in bronze)
    "rfms_vehicle_status": ("rfms/vehicle_status", "createdDateTime STRING, receivedDateTime STRING"),
    "dtc_events":          ("dtc",                 "active_from STRING, active_to STRING"),
    "work_orders":         ("work_orders",         "opened_at STRING, closed_at STRING"),
}

if dbutils.widgets.get("reset") == "yes":
    for table in STREAM_TABLES:
        spark.sql(f"DROP TABLE IF EXISTS bronze.{table}")
        dbutils.fs.rm(f"{CHECKPOINTS}/{table}", recurse=True)
    print("Bronze streaming tables and checkpoints removed.")

# COMMAND ----------

from pyspark.sql import functions as F


def autoload(table: str, folder: str, hints: str):
    chk = f"{CHECKPOINTS}/{table}"
    stream = (spark.readStream.format("cloudFiles")
              .option("cloudFiles.format", "json")
              .option("cloudFiles.schemaLocation", f"{chk}/schema")
              .option("cloudFiles.inferColumnTypes", "true")
              .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
              .option("cloudFiles.partitionColumns", "year,month")
              .option("cloudFiles.schemaHints", hints)
              .load(f"{RAW}/{folder}")
              .withColumn("_ingested_at", F.current_timestamp())
              .withColumn("_source_file", F.col("_metadata.file_path")))
    query = (stream.writeStream
             .option("checkpointLocation", chk)
             .option("mergeSchema", "true")
             .trigger(availableNow=True)          # process everything new, then stop
             .toTable(f"bronze.{table}"))
    query.awaitTermination()
    print(f"bronze.{table}: {spark.table(f'bronze.{table}').count():,} rows")


for table, (folder, hints) in STREAM_TABLES.items():
    autoload(table, folder, hints)

# COMMAND ----------

# MAGIC %md
# MAGIC If the first run stops with `UnknownFieldException`, that is Auto Loader recording a newly discovered column
# MAGIC in its schema. Run the cell again and it continues.

# COMMAND ----------

def load_csv(path: str, table: str):
    (spark.read.option("header", True).option("inferSchema", True).csv(path)
     .withColumn("_ingested_at", F.current_timestamp())
     .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    print(f"{table}: {spark.table(table).count():,} rows")


for name in ["vehicles", "drivers", "depots", "spn_reference", "fmi_reference"]:
    load_csv(f"{RAW}/reference/{name}.csv", f"bronze.ref_{name}")

load_csv(f"{RAW}/eval/scenarios.csv", "eval.scenarios")
(spark.read.json(f"{RAW}/eval/golden_questions.jsonl")
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("eval.golden_questions"))
print(f"eval.golden_questions: {spark.table('eval.golden_questions').count()} questions")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Optional: real Volvo data
# MAGIC Download the **Volvo Discovery Challenge (ECML PKDD 2024)** dataset, published by Volvo Group Trucks Technology
# MAGIC and Halmstad University, and upload its CSV files to `/Volumes/<catalog>/bronze/raw/volvo_pdm/`.
# MAGIC Each CSV becomes a bronze table `bronze.volvo_pdm_<file name>`, loaded as-is. We will model it in a later step,
# MAGIC once we've looked at its columns.

# COMMAND ----------

import re

pdm_files = [f for f in dbutils.fs.ls(f"{RAW}/volvo_pdm") if f.name.lower().endswith(".csv")]
if not pdm_files:
    print("No Volvo PdM CSVs uploaded yet - skipping.")
for f in pdm_files:
    stem = re.sub(r"[^a-z0-9_]", "_", f.name.lower().rsplit(".", 1)[0])
    load_csv(f.path, f"bronze.volvo_pdm_{stem}")
