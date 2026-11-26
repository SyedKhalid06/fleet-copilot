# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Retriever tool
# MAGIC Entity extraction + query expansion + filtered searches on top of the hybrid index.

# COMMAND ----------

%pip install -U "mlflow[databricks]>=3.1" faiss-cpu rank-bm25 openai tiktoken -q
dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "fleet_copilot", "Catalog")
CATALOG = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG {CATALOG}")

import os, sys, importlib
src = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if src not in sys.path:
    sys.path.insert(0, src)

import fleet_rag.retrieval as R
import fleet_agent.retriever_tool as T
importlib.reload(R); importlib.reload(T)

import mlflow
from openai import OpenAI
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/fleet-copilot-traces")

client = OpenAI(api_key=dbutils.secrets.get(scope="fleet", key="openai_api_key"))
index = R.HybridIndex.load(f"/Volumes/{CATALOG}/gold/rag_index/v1")      # built in notebook 06
spn_names = {r.spn: r.spn_name for r in spark.table("silver.spn_reference").collect()}
print(len(index.chunks), "chunks loaded |", len(spn_names), "SPN names")

# COMMAND ----------

# MAGIC %md ## Entity extraction and query expansion

# COMMAND ----------

for q in ["SPN 3719 FMI 16", "Why is GOT-028 overheating? It shows SPN 110 FMI 16", "What does SPN 168 mean?"]:
    e = T.extract_entities(q)
    print(q, "\n   ", e, "\n   ", T.expand_query(q, e["spns"], spn_names), "\n")

# COMMAND ----------

# MAGIC %md ## Before vs after: plain search vs retriever tool

# COMMAND ----------

def compare(question):
    print("\n" + "=" * 100 + f"\nQ: {question}")
    print("-- plain index.search --")
    for r in index.search(question, client, k=5):
        print(f"   {r['chunk_id']:<18} {r['title'][:60]}")
    print("-- retriever tool --")
    for r in T.retrieve(question, index, client, spn_names, k=5):
        print(f"   {r['chunk_id']:<18} {r['title'][:60]}")

compare("SPN 3719 FMI 16")
compare("What does SPN 168 FMI 18 mean and what should the workshop do?")
compare("What happened with HAM-014's cooling system?")
compare("GOT-028 shows SPN 110 FMI 16 and SPN 111 FMI 17, what should we check?")

# COMMAND ----------

# MAGIC %md ## What the LLM will receive

# COMMAND ----------

hits = T.retrieve("GOT-028 shows SPN 110 FMI 16, what should the workshop check?", index, client, spn_names, k=5)
print(T.format_context(hits))