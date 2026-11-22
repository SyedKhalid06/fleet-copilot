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

# COMMAND ----------

# MAGIC %md ## Step 2 · Setup + OpenAI key from a Databricks secret (never paste the key in a notebook)

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 3 · Load `gold.documents` into pandas

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 4 · Chunk
# MAGIC Short docs (work orders) stay whole. Long docs (SOPs) split on headings, then by size (~400 tokens, ~12% overlap).
# MAGIC Every chunk gets a contextual header, e.g. `[Work order | GOT-028 | FM | cooling]`.

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 5 · Save chunks as `gold.document_chunks`

# COMMAND ----------

# TODO

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
