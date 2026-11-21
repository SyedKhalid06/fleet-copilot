# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Set up Unity Catalog
# MAGIC Creates the catalog, the medallion schemas (bronze → silver → gold), an `eval` schema for ground truth,
# MAGIC and a Unity Catalog **volume** where raw files land.
# MAGIC
# MAGIC Run once. Safe to re-run.

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")

# COMMAND ----------

try:
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG} "
              "COMMENT 'Fleet Copilot: Volvo-style fleet data (synthetic rFMS/J1939 + public datasets)'")
except Exception as e:
    print("Could not create the catalog. You need CREATE CATALOG permission, and some metastores also need a "
          "MANAGED LOCATION. Create it in Catalog Explorer, or set the widget to a catalog you already own.\n\n", e)
    raise

spark.sql(f"USE CATALOG {CATALOG}")

schemas = {
    "bronze": "Raw data exactly as received from source systems",
    "silver": "Cleaned, flattened, de-duplicated, joined with reference data",
    "gold":   "Business-level tables the Copilot's SQL tool queries",
    "eval":   "Ground truth and golden questions for evaluation. Never exposed to the Copilot.",
}
for name, comment in schemas.items():
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {name} COMMENT '{comment}'")

spark.sql("CREATE VOLUME IF NOT EXISTS bronze.raw COMMENT 'Landing zone: files as delivered by source systems'")

# COMMAND ----------

RAW = f"/Volumes/{CATALOG}/bronze/raw"
for folder in ["rfms", "dtc", "work_orders", "reference", "eval", "volvo_pdm", "documents", "_checkpoints"]:
    dbutils.fs.mkdirs(f"{RAW}/{folder}")

display(dbutils.fs.ls(RAW))
