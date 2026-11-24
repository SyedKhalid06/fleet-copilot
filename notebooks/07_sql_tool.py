# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · SQL tool
# MAGIC Task 1: schema context, safety guard, safe runner (no LLM yet).
# MAGIC Task 2 (next): question -> SQL with an LLM, retry on error.

# COMMAND ----------

# MAGIC %md ## Step 1 · Install

# COMMAND ----------

%pip install -U "mlflow[databricks]>=3.1" openai -q
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md ## Step 2 · Setup

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

import os, sys, importlib
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

import fleet_agent.sql_tool as S
importlib.reload(S)

import mlflow
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/fleet-copilot-traces")

# COMMAND ----------

# MAGIC %md ## Step 3 · Schema context (what the LLM will read)

# COMMAND ----------

schema_context = S.get_schema_context(spark, CATALOG)
print(f"{len(schema_context):,} characters")
print(schema_context)

# COMMAND ----------

# MAGIC %md ## Step 4 · Safety guard tests

# COMMAND ----------

tests = [
    ("SELECT unit_no, attention_flags FROM gold.vehicle_current_status WHERE attention_flags IS NOT NULL", True),
    ("WITH m AS (SELECT * FROM gold.vehicle_monthly_fuel) SELECT unit_no, max(pct_vs_peers) FROM m GROUP BY unit_no", True),
    ("SELECT unit_no, extract(MONTH FROM first_opened_at) AS m FROM gold.repeat_repairs", True),
    ("DELETE FROM gold.vehicle_daily", False),
    ("SELECT * FROM eval.scenarios", False),
    ("SELECT * FROM silver.work_orders", False),
    ("SELECT * FROM gold.vehicle_daily; DROP TABLE gold.vehicle_daily", False),
    ("SELECT * FROM gold.document_chunks", False),
]
for sql, expected in tests:
    ok, reason = S.is_safe_sql(sql)
    flag = "PASS" if ok == expected else "UNEXPECTED"
    print(f"{flag:10} allowed={str(ok):5}  {reason:48}  {sql[:60]}")

# COMMAND ----------

# MAGIC %md ## Step 5 · Run queries safely

# COMMAND ----------

import pandas as pd

r = S.run_sql(spark, """
    SELECT unit_no, model, attention_flags, open_fault_list, latest_month_pct_vs_peers
    FROM gold.vehicle_current_status
    WHERE attention_flags IS NOT NULL
    ORDER BY open_fault_codes DESC""")
print("ok:", r["ok"], "| rows:", r["row_count"], "| truncated:", r["truncated"])
display(pd.DataFrame(r["rows"]))

# a broken query comes back as an error message, not a crash
print(S.run_sql(spark, "SELECT no_such_column FROM gold.vehicle_daily"))

# a blocked query never reaches Spark
print(S.run_sql(spark, "SELECT * FROM eval.scenarios"))

# COMMAND ----------

# MAGIC %md ## Step 6 · LLM client + automatic tracing of LLM calls

# COMMAND ----------

from openai import OpenAI
importlib.reload(S)

client = OpenAI(api_key=dbutils.secrets.get(scope="fleet", key="openai_api_key"))
mlflow.openai.autolog()        # every chat call (prompt, SQL answer, tokens, cost) appears in the trace

# COMMAND ----------

# MAGIC %md ## Step 7 · Ask questions

# COMMAND ----------

import pandas as pd

def ask(question):
    r = S.ask_sql(question, spark, client, schema_context)
    print("\n" + "=" * 100)
    print(f"Q: {question}")
    print(f"attempts: {r['attempts']} | ok: {r['ok']} | rows: {r.get('row_count')}")
    print(r["sql"] or "")
    if r["ok"]:
        display(pd.DataFrame(r["rows"]).head(10))
    else:
        print("ERROR:", r["error"])

ask("Which trucks need attention right now and why?")
ask("What was RTM-021's fuel consumption per month compared with its peers?")
ask("Which depot had the most breakdowns, and how many workshop hours did each depot use?")
ask("Which 5 drivers used the most fuel compared to their peers in September 2026?")
ask("Show open faults that nobody has repaired yet.")
ask("What was the maintenance cost per 1000 km for trucks in Gothenburg?")
ask("What is the weather in Gothenburg today?")