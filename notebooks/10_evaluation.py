# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · Evaluate the agent on the golden questions
# MAGIC Every answer is scored by an LLM judge (root cause correct?) and code checks (evidence found, cited, valid).
# MAGIC Results land in MLflow: Experiments -> fleet-copilot-traces -> Evaluation runs.

# COMMAND ----------

%pip install -U "mlflow[databricks]>=3.1" langgraph langchain-openai faiss-cpu rank-bm25 openai tiktoken -q
dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

import os, sys, importlib
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

import fleet_agent.graph as A, fleet_agent.factory as F, fleet_agent.evaluation as E
importlib.reload(A); importlib.reload(F); importlib.reload(E)

import mlflow
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/fleet-copilot-traces")
mlflow.langchain.autolog()

os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "2"     # answer 2 questions at a time (avoids API rate limits)

# COMMAND ----------

# MAGIC %md ## Build the agent and load the golden questions

# COMMAND ----------

OPENAI_KEY = dbutils.secrets.get(scope="fleet", key="openai_api_key")
agent, client = F.create_agent(spark, CATALOG, OPENAI_KEY)

data = E.load_eval_set(spark)
print(len(data), "golden questions")
for d in data[:3]:
    print("-", d["inputs"]["question"], "->", d["expectations"]["work_orders"])

# COMMAND ----------

# MAGIC %md ## Dry run on 3 questions (check everything works before the full run)

# COMMAND ----------

trial = mlflow.genai.evaluate(data=data[:3], predict_fn=E.make_predict_fn(agent), scorers=E.make_scorers(client))
print(trial.metrics)

# COMMAND ----------

# MAGIC %md ## Full evaluation

# COMMAND ----------

with mlflow.start_run(run_name="baseline-gpt-4o-mini"):
    results = mlflow.genai.evaluate(data=data, predict_fn=E.make_predict_fn(agent), scorers=E.make_scorers(client))

for name, value in sorted(results.metrics.items()):
    print(f"{name:40} {value:.2f}")