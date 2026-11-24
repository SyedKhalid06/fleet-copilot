# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Build the document collection
# MAGIC Goal: gather every piece of text the Copilot should be able to search and cite, into ONE table: `gold.documents`.
# MAGIC
# MAGIC | Source | Where it comes from | doc_type |
# MAGIC |---|---|---|
# MAGIC | Technician notes | `silver.work_orders` | `work_order` |
# MAGIC | Standard operating procedures | `documents/sops/*.md` in this repo | `sop` |
# MAGIC | Fault code guide | `silver.spn_reference` + `silver.fmi_reference` | `dtc_guide` |
# MAGIC
# MAGIC Output schema (one row per document):
# MAGIC `doc_id, doc_type, title, text, vin, unit_no, model, system_category, dtc_codes, doc_date, source_ref`

# COMMAND ----------

# MAGIC %md ## Step 1 · Setup (catalog widget, imports, sys.path to ../src)

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 2 · Work orders → documents
# MAGIC One document per work order. Text = complaint + technician notes + parts used.
# MAGIC Keep metadata (vin, unit_no, system_category, dtc_refs, opened_at) - we filter on it later.

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 3 · SOP markdown files → documents
# MAGIC Read each file in `../documents/sops/`. Title = first `# heading`. One document per file.

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 4 · Fault code guide → documents
# MAGIC One document per SPN: name, system, which FMIs we see in the fleet, and what the driver should do.

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 5 · Union all sources and save `gold.documents`

# COMMAND ----------

# TODO

# COMMAND ----------

# MAGIC %md ## Step 6 · Sanity checks
# MAGIC Count by doc_type, look at a few rows, check no empty text.

# COMMAND ----------

# TODO
