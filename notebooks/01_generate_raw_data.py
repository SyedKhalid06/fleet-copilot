# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Generate raw fleet data
# MAGIC Simulates a mixed Volvo fleet (FH, FM, FMX, FL, FE in Europe; VNL, VNR in North America) and writes files to the
# MAGIC landing volume in the formats real source systems deliver:
# MAGIC
# MAGIC | Folder | Format | Mimics |
# MAGIC |---|---|---|
# MAGIC | `rfms/vehicle_status/` | JSON lines, monthly partitions | rFMS vehicle status API (telematics) |
# MAGIC | `dtc/` | JSON lines | J1939 DM1 fault code events |
# MAGIC | `work_orders/` | JSON lines | Workshop management system export |
# MAGIC | `reference/` | CSV | Fleet master data + SPN/FMI code tables |
# MAGIC | `eval/` | CSV + JSON lines | Ground truth of injected faults + golden questions |
# MAGIC
# MAGIC Default run: 100 trucks × 12 months ≈ 250k telematics records, ~2k fault events, ~400 work orders. Takes about 30 seconds.

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
dbutils.widgets.text("n_vehicles", "100", "Trucks")
dbutils.widgets.text("months", "12", "Months")
dbutils.widgets.text("start_date", "2025-11-01", "Start date")
dbutils.widgets.text("seed", "42", "Random seed")

CATALOG = dbutils.widgets.get("catalog")
RAW = f"/Volumes/{CATALOG}/bronze/raw"

# COMMAND ----------

import os, sys
from datetime import date

src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

from fleet_sim import SimConfig, generate_all

cfg = SimConfig(
    n_vehicles=int(dbutils.widgets.get("n_vehicles")),
    months=int(dbutils.widgets.get("months")),
    start_date=date.fromisoformat(dbutils.widgets.get("start_date")),
    seed=int(dbutils.widgets.get("seed")),
)

# COMMAND ----------

# MAGIC %md
# MAGIC Re-running replaces the generated files. If you already loaded bronze tables, run notebook 02 with
# MAGIC `reset = yes` afterwards, because Auto Loader skips files it has already seen.

# COMMAND ----------

for folder in ["rfms", "dtc", "work_orders", "reference", "eval"]:
    dbutils.fs.rm(f"{RAW}/{folder}", recurse=True)

summary = generate_all(cfg, out_dir=RAW)

# COMMAND ----------

display(spark.read.option("header", True).csv(f"{RAW}/eval/scenarios.csv"))
