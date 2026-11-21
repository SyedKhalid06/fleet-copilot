# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Silver: clean, flatten and enrich
# MAGIC | Silver table | From | What changes |
# MAGIC |---|---|---|
# MAGIC | `vehicles` | ref_vehicles + ref_depots | typed dates, depot city / time zone / currency |
# MAGIC | `drivers`, `spn_reference`, `fmi_reference` | reference CSVs | copied, typed |
# MAGIC | `telematics` | rfms_vehicle_status | nested rFMS JSON flattened to metric columns, de-duplicated, distance/fuel per interval |
# MAGIC | `telematics_quarantine` | rfms_vehicle_status | rows that failed data-quality rules, with the reason |
# MAGIC | `dtc_events` | dtc_events | readable code, lamp, SPN/FMI descriptions joined in |
# MAGIC | `work_orders`, `work_order_parts` | work_orders | parts array exploded into its own table, downtime hours |
# MAGIC
# MAGIC Every table and key column gets a Unity Catalog comment. The Copilot's text-to-SQL step reads these
# MAGIC to understand the schema, so they matter as much as the data.
# MAGIC
# MAGIC The transformation logic lives in `src/fleet_pipeline/silver.py`, so it can be unit-tested outside Databricks.

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

import os, sys
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

from pyspark.sql import functions as F
from fleet_pipeline import silver as S


def save(df, table):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"silver.{table}")
    print(f"silver.{table}: {spark.table(f'silver.{table}').count():,} rows")

# COMMAND ----------

# master + reference data
save(S.silver_vehicles(spark.table("bronze.ref_vehicles").drop("_ingested_at"),
                       spark.table("bronze.ref_depots")), "vehicles")
save(spark.table("bronze.ref_drivers").drop("_ingested_at"), "drivers")
spn_ref = spark.table("bronze.ref_spn_reference").drop("_ingested_at")
fmi_ref = spark.table("bronze.ref_fmi_reference").drop("_ingested_at")
save(spn_ref, "spn_reference")
save(fmi_ref, "fmi_reference")

# COMMAND ----------

# telematics
good, quarantined = S.silver_telematics(spark.table("bronze.rfms_vehicle_status"))
save(good, "telematics")
save(quarantined, "telematics_quarantine")
spark.sql("OPTIMIZE silver.telematics ZORDER BY (vin, event_ts)")

# COMMAND ----------

# fault codes and work orders
save(S.silver_dtc(spark.table("bronze.dtc_events"), spn_ref, fmi_ref), "dtc_events")
wo, parts = S.silver_work_orders(spark.table("bronze.work_orders"))
save(wo, "work_orders")
save(parts, "work_order_parts")

# COMMAND ----------

# Unity Catalog comments (read by text-to-SQL agents)
def q(text):
    return text.replace("'", "\\'")

for table, (table_comment, columns) in S.COMMENTS.items():
    spark.sql(f"COMMENT ON TABLE silver.{table} IS '{q(table_comment)}'")
    for col, comment in columns.items():
        spark.sql(f"ALTER TABLE silver.{table} ALTER COLUMN {col} COMMENT '{q(comment)}'")
print("Comments applied.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Sanity check: are the injected faults visible in silver?
# MAGIC Monthly fuel use (L/100 km) for trucks with an injected fuel-system fault. You should see consumption climb
# MAGIC for a few months, then drop back after the repair month. This is the signal the Copilot has to find.

# COMMAND ----------

display(spark.sql("""
  WITH monthly AS (
    SELECT vin, date_trunc('month', event_ts) AS month,
           round(sum(interval_fuel_l) / sum(interval_km) * 100, 1) AS l_per_100km
    FROM silver.telematics
    WHERE interval_km IS NOT NULL
    GROUP BY ALL
  )
  SELECT s.unit_no, s.type, s.onset_date, s.fixed_on, m.month, m.l_per_100km
  FROM monthly m JOIN eval.scenarios s USING (vin)
  WHERE s.type IN ('injector_wear', 'dpf_clogging')
  ORDER BY s.unit_no, m.month
"""))

# COMMAND ----------

display(spark.sql("""
  SELECT d.dtc_code, d.spn_name, d.lamp, count(*) AS events, count(DISTINCT vin) AS trucks
  FROM silver.dtc_events d
  GROUP BY ALL ORDER BY events DESC
"""))
