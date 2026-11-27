# Databricks notebook source
# MAGIC %md
# MAGIC # 09 · Fleet Copilot agent (LangGraph)
# MAGIC Step A: router. Step B: tools + answer. Step C: grading, retry, citations, memory.

# COMMAND ----------

# MAGIC %md ## Step 1 · Install

# COMMAND ----------

%pip install -U "mlflow[databricks]>=3.1" langgraph langchain-openai faiss-cpu rank-bm25 openai tiktoken -q
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

import fleet_agent.retriever_tool as T
import fleet_agent.graph as A
importlib.reload(T); importlib.reload(A)

import mlflow
user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/fleet-copilot-traces")
mlflow.langchain.autolog()          # traces every graph node and LLM call automatically

from langchain_openai import ChatOpenAI
OPENAI_KEY = dbutils.secrets.get(scope="fleet", key="openai_api_key")
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_KEY)

# COMMAND ----------

# MAGIC %md ## Step 3 · Build the router-only graph

# COMMAND ----------

graph = A.build_router_only_graph(llm)
print(graph.get_graph().draw_mermaid())

# COMMAND ----------

# MAGIC %md ## Step 4 · Does each question go to the right route?

# COMMAND ----------

from langchain_core.messages import HumanMessage

tests = [
    ("Which trucks need attention right now?", "sql"),
    ("How many breakdowns did each depot have?", "sql"),
    ("What does SPN 3719 FMI 16 mean?", "docs"),
    ("What should a driver do when the coolant warning turns red?", "docs"),
    ("Why has RTM-021's fuel consumption gone up?", "both"),
    ("What's wrong with GOT-028 and what should the workshop check?", "both"),
    ("Is it fixed now?", "clarify"),
    ("What's the weather in Gothenburg?", "out_of_scope"),
]

correct = 0
for q, expected in tests:
    out = graph.invoke({"messages": [HumanMessage(q)]})
    ok = out["route"] == expected
    correct += ok
    print(f"{'PASS' if ok else 'MISS':4}  {out['route']:12} (expected {expected:12})  {q}")
    print(f"      reason: {out['route_reason']}  | entities: {out['entities']}")
print(f"\n{correct}/{len(tests)} routed as expected")

# COMMAND ----------

# MAGIC %md ## Step 5 · Follow-up questions (history -> standalone question)

# COMMAND ----------

from langchain_core.messages import AIMessage

history = [
    HumanMessage("What's wrong with GOT-028?"),
    AIMessage("GOT-028 has open coolant codes SPN 110 FMI 16 and SPN 111 FMI 17 and no cooling repair on record."),
    HumanMessage("And what should the workshop do about it?"),
]
out = graph.invoke({"messages": history})
print("route:     ", out["route"])
print("standalone:", out["question"])
print("entities:  ", out["entities"])

# COMMAND ----------

# MAGIC %md ## Step 6 · Build the tools and the full agent

# COMMAND ----------

import fleet_agent.sql_tool as S
import fleet_rag.retrieval as R
importlib.reload(S); importlib.reload(R); importlib.reload(A)
from openai import OpenAI

client = OpenAI(api_key=OPENAI_KEY)
tools = A.FleetTools(
    spark=spark,
    client=client,
    schema_context=S.get_schema_context(spark, CATALOG),
    index=R.HybridIndex.load(f"/Volumes/{CATALOG}/gold/rag_index/v1"),
    spn_names={r.spn: r.spn_name for r in spark.table("silver.spn_reference").collect()},
)
agent = A.build_agent(llm, tools)
print(agent.get_graph().draw_mermaid())

# COMMAND ----------

# MAGIC %md ## Step 7 · First real answers

# COMMAND ----------

def ask(question):
    out = agent.invoke({"messages": [HumanMessage(question)]})
    print("\n" + "=" * 100)
    print(f"Q: {question}")
    print(f"route: {out['route']}  | standalone: {out['question']}")
    if out.get("sql_result"):
        r = out["sql_result"]
        print(f"SQL ok={r.get('ok')} rows={r.get('row_count')} attempts={r.get('attempts')}")
    if out.get("docs"):
        print("docs:", [d["doc_id"] for d in out["docs"]])
    print("citations:", out.get("citations"))
    print("-" * 100)
    print(out["answer"])

ask("Which trucks need attention right now and why?")
ask("What does SPN 3719 FMI 16 mean and what should the driver do?")
ask("Why has RTM-021's fuel consumption gone up, and was it fixed?")
ask("What's wrong with GOT-028 and what should the workshop check?")
ask("Did the first repair on HAM-014's cooling system fix the problem?")
ask("Is it fixed now?")
ask("What's the weather today?")


# COMMAND ----------

# MAGIC %md ## Step 8 · Agent with grading, citation check and memory

# COMMAND ----------

from langgraph.checkpoint.memory import InMemorySaver
importlib.reload(A)

agent = A.build_agent(llm, tools, checkpointer=InMemorySaver())
print(agent.get_graph().draw_mermaid())

# COMMAND ----------

# MAGIC %md ## Step 9 · Rerun the 7 questions

# COMMAND ----------

import uuid

def ask(question, thread_id=None):
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())},   # one thread = one conversation
              "recursion_limit": 25}                                            # safety net against loops
    out = agent.invoke({"messages": [HumanMessage(question)]}, config)
    print("\n" + "=" * 100)
    print(f"Q: {question}")
    print(f"route: {out['route']} | standalone: {out['question']}")
    if out.get("sql_result"):
        r = out["sql_result"]
        print(f"SQL ok={r.get('ok')} rows={r.get('row_count')}")
    if out.get("docs"):
        print(f"docs: {[d['doc_id'] for d in out['docs']]}")
        print(f"grade: relevant={out.get('relevant')} retries={out.get('attempts')} note={out.get('grade_note')!r}")
    print(f"citations: {out.get('citations')} | invalid: {out.get('invalid_citations')}")
    print("-" * 100)
    print(out["answer"])
    return out

ask("Which trucks need attention right now and why?")
ask("What does SPN 3719 FMI 16 mean and what should the driver do?")
ask("Why has RTM-021's fuel consumption gone up, and was it fixed?")
ask("What's wrong with GOT-028 and what should the workshop check?")
ask("Did the first repair on HAM-014's cooling system fix the problem?")
ask("Is it fixed now?")
ask("What's the weather today?")

# COMMAND ----------

# MAGIC %md ## Step 10 · A conversation (memory across turns)

# COMMAND ----------

thread = "demo-conversation-1"
ask("What's wrong with GOT-028?", thread)
ask("What should the workshop check?", thread)
ask("Has it had any cooling repairs before?", thread)