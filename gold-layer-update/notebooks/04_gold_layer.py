# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Gold: business tables for the Copilot
# MAGIC These are the tables the Copilot's **SQL tool** queries. Each one answers a family of ops questions:
# MAGIC
# MAGIC | Gold table | Grain | Answers questions like |
# MAGIC |---|---|---|
# MAGIC | `vehicle_current_status` | 1 row per truck | "What's the status of CHI-007?" "Which trucks need attention?" |
# MAGIC | `vehicle_daily` | truck × day | "How far did GOT-014 drive last week? Any warning lamps?" |
# MAGIC | `vehicle_monthly_fuel` | truck × month | "Why has fuel use on RTM-021 gone up?" (vs own history and vs peers) |
# MAGIC | `vehicle_fault_status` | truck × fault code | "Which faults are active and unrepaired?" |
# MAGIC | `repeat_repairs` | pair of jobs | "Did the first repair on HAM-014 fix it?" |
# MAGIC | `vehicle_maintenance` | 1 row per truck | "Which trucks cost most to maintain per km? Who broke down?" |
# MAGIC | `driver_monthly` | driver × truck type × month | "Which drivers use more fuel than peers?" |
# MAGIC | `fleet_kpis_monthly` | depot × month | "How is each depot doing?" |
# MAGIC
# MAGIC Logic lives in `src/fleet_pipeline/gold.py`. Dates are local to each depot; costs stay in the depot currency.

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")
spark.conf.set("spark.sql.session.timeZone", "UTC")   # timestamps are UTC; local dates come from each depot's time zone

import os, sys
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

from fleet_pipeline import gold as G


def save(df, table):
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"gold.{table}")
    print(f"gold.{table}: {spark.table(f'gold.{table}').count():,} rows")
    return spark.table(f"gold.{table}")

# COMMAND ----------

telem = spark.table("silver.telematics")
dtc = spark.table("silver.dtc_events")
wo = spark.table("silver.work_orders")
veh = spark.table("silver.vehicles")
drv = spark.table("silver.drivers")

# COMMAND ----------

daily = save(G.vehicle_daily(telem, dtc, veh), "vehicle_daily")
monthly = save(G.vehicle_monthly_fuel(daily), "vehicle_monthly_fuel")
faults = save(G.vehicle_fault_status(dtc, wo, veh), "vehicle_fault_status")
repeats = save(G.repeat_repairs(wo), "repeat_repairs")
save(G.vehicle_maintenance(wo, daily, repeats, veh), "vehicle_maintenance")
save(G.driver_monthly(telem, veh, drv), "driver_monthly")
save(G.fleet_kpis_monthly(daily, wo, veh), "fleet_kpis_monthly")
save(G.vehicle_current_status(telem, daily, monthly, faults, wo, veh), "vehicle_current_status")

# COMMAND ----------

# Unity Catalog comments: the text-to-SQL step reads these to pick the right table and column
def q(text):
    return text.replace("'", "\\'")

for table, (table_comment, columns) in G.COMMENTS.items():
    spark.sql(f"COMMENT ON TABLE gold.{table} IS '{q(table_comment)}'")
    for col, comment in columns.items():
        spark.sql(f"ALTER TABLE gold.{table} ALTER COLUMN {col} COMMENT '{q(comment)}'")
print("Comments applied.")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check 1: which trucks need attention right now?
# MAGIC Compare with `eval.scenarios`: trucks with an unrepaired injected fault should be near the top.

# COMMAND ----------

display(spark.sql("""
  SELECT unit_no, model, duty_cycle, attention_flags, open_fault_list,
         latest_month_l_per_100km, latest_month_pct_vs_peers, service_distance_km, last_wo_id, last_wo_outcome
  FROM gold.vehicle_current_status
  WHERE attention_flags IS NOT NULL
  ORDER BY open_fault_codes DESC, latest_month_pct_vs_peers DESC
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check 2: can the fuel table see the injector faults?
# MAGIC `pct_vs_peers` and `pct_vs_prev_3m` should rise in the months before the repair and fall after it.

# COMMAND ----------

display(spark.sql("""
  SELECT s.unit_no, s.type, s.onset_date, s.fixed_on, m.month, m.l_per_100km, m.pct_vs_peers, m.pct_vs_prev_3m
  FROM gold.vehicle_monthly_fuel m JOIN eval.scenarios s USING (vin)
  WHERE s.type = 'injector_wear'
  ORDER BY s.unit_no, m.month
"""))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check 3: repeat repairs after an inconclusive first visit

# COMMAND ----------

display(spark.sql("""
  SELECT unit_no, system_category, first_wo, first_outcome, repeat_wo, days_between, first_notes, repeat_notes
  FROM gold.repeat_repairs
  WHERE first_outcome = 'monitor'
  ORDER BY unit_no
"""))
