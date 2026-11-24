# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Chunk the documents and build the search index (FAISS + BM25)
# MAGIC ```
# MAGIC gold.documents ──▶ chunks (with contextual headers) ──▶ OpenAI embeddings ──▶ FAISS index (semantic)
# MAGIC                                                     └──────────────────────▶ BM25 index  (keywords)
# MAGIC                                                        both saved to /Volumes/<catalog>/gold/rag_index/
# MAGIC ```
# MAGIC Why both? FAISS finds meaning ("engine running hot" ≈ "coolant temperature high").
# MAGIC BM25 finds exact tokens (part numbers, "SPN 110", "WO-26-00325") that embeddings blur.

# COMMAND ----------

# MAGIC %md ## Step 1 · Install libraries and restart Python
# MAGIC `faiss-cpu`, `rank-bm25`, `openai`, `tiktoken`

# COMMAND ----------

# TODO
%pip install faiss-cpu rank-bm25 openai tiktoken -q
dbutils.library.restartPython()
# COMMAND ----------

# MAGIC %md ## Step 2 · Setup + OpenAI key from a Databricks secret (never paste the key in a notebook)

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
import fleet_rag.chunking as C
importlib.reload(D); importlib.reload(C)

OPENAI_KEY = dbutils.secrets.get(scope="fleet", key="openai_api_key")   # used in step 6
# COMMAND ----------

# MAGIC %md ## Step 3 · Load `gold.documents` into pandas

# COMMAND ----------

# TODO
docs = [row.asDict() for row in spark.table("gold.documents").collect()]
print(len(docs), "documents")
# COMMAND ----------

# MAGIC %md ## Step 4 · Chunk
# MAGIC Short docs (work orders) stay whole. Long docs (SOPs) split on headings, then by size (~400 tokens, ~12% overlap).
# MAGIC Every chunk gets a contextual header, e.g. `[Work order | GOT-028 | FM | cooling]`.

# COMMAND ----------

# TODO
chunks = C.chunk_documents(docs, max_tokens=400, overlap_tokens=50)
print(len(chunks), "chunks")

from collections import Counter
print(Counter(c["doc_type"] for c in chunks))
print("max tokens:", max(c["n_tokens"] for c in chunks))

for c in chunks:
    if c["doc_id"] == "SOP-01":
        print("\n-----", c["chunk_id"], c["n_tokens"], "tokens -----")
        print(c["chunk_text"])
# COMMAND ----------

# MAGIC %md ## Step 5 · Save chunks as `gold.document_chunks`

# COMMAND ----------

# TODO
from pyspark.sql import types as T

chunk_schema = T.StructType(
    [f for f in D.DOC_SCHEMA.fields if f.name != "text"] + [
        T.StructField("chunk_id", T.StringType()),
        T.StructField("chunk_index", T.IntegerType()),
        T.StructField("chunk_text", T.StringType()),
        T.StructField("n_tokens", T.IntegerType()),
    ])

(spark.createDataFrame(chunks, schema=chunk_schema)
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("gold.document_chunks"))
print("gold.document_chunks:", spark.table("gold.document_chunks").count())
# COMMAND ----------

# MAGIC %md ## Step 6 · Embed chunks with OpenAI (batched) and build the FAISS index

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 7 · Build the BM25 index

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 8 · Save both indexes + chunk metadata to the volume

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 9 · Test: hybrid search (FAISS + BM25 fused with Reciprocal Rank Fusion)
# MAGIC Try: "coolant temperature keeps rising on long climbs", "SPN 3719 FMI 16", "truck would not start in the cold"

# COMMAND ----------

# TODO
