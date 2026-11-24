"""Turn each source into document rows with the same columns.

Output columns: doc_id, doc_type, title, text, vin, unit_no, model, system_category,
                dtc_codes, doc_date, source_ref
"""
from pyspark.sql import functions as F
import os
import re
from pyspark.sql import types as T

# Every document source returns these columns, so they can be unioned into one table
DOC_SCHEMA = T.StructType([
    T.StructField("doc_id", T.StringType()),
    T.StructField("doc_type", T.StringType()),
    T.StructField("title", T.StringType()),
    T.StructField("text", T.StringType()),
    T.StructField("vin", T.StringType()),
    T.StructField("unit_no", T.StringType()),
    T.StructField("model", T.StringType()),
    T.StructField("system_category", T.StringType()),
    T.StructField("dtc_codes", T.ArrayType(T.StringType())),
    T.StructField("doc_date", T.DateType()),
    T.StructField("source_ref", T.StringType()),
])

# Which truck system each SOP covers (by file number), same names as work_orders.system_category
SOP_SYSTEM = {"01": "cooling", "02": "aftertreatment", "03": "aftertreatment", "04": "electrical",
              "05": "fuel_system", "06": "general", "07": "scheduled_service", "08": "aftertreatment"}

CODE_PATTERN = re.compile(r"SPN \d+ FMI \d+")   # finds codes like "SPN 110 FMI 16"

def work_order_documents(work_orders, parts, vehicles):
    """Work orders -> one searchable document per job (scheduled services excluded)."""

    # 1. Parts used per work order, as one line: "Water pump x1; Coolant VCS (20 L) x1"
    parts_text = (parts.groupBy("wo_id")
                  .agg(F.concat_ws("; ", F.collect_list(
                        F.concat_ws(" x", "part_name", F.col("quantity").cast("string")))).alias("parts_text")))

    # 2. Keep repairs only, and add the parts line and the truck model
    wo = (work_orders.filter(F.col("wo_type") != "preventive")
          .join(parts_text, "wo_id", "left")
          .join(vehicles.select("vin", "model", "duty_cycle"), "vin", "left"))

    # 3. Build the readable text, one line per fact
    text = F.concat_ws("\n",
        F.format_string("Work order %s | %s (%s, %s) | %s | %s | outcome: %s",
                        "wo_id", "unit_no", "model", "duty_cycle", "system_category", "wo_type", "outcome"),
        F.concat(F.lit("Opened: "), F.date_format("opened_at", "yyyy-MM-dd"),
                 F.lit(" | Odometer: "), F.format_number("odometer_km", 0), F.lit(" km")),
        F.concat(F.lit("Fault codes: "),
                 F.when(F.size("dtc_refs") > 0, F.concat_ws(", ", "dtc_refs")).otherwise(F.lit("none"))),
        F.concat(F.lit("Complaint: "), "complaint"),
        F.concat(F.lit("Technician notes: "), "technician_notes"),
        F.concat(F.lit("Parts: "), F.coalesce("parts_text", F.lit("none"))))

    # 4. Shape into the standard document columns
    return wo.select(
        F.col("wo_id").alias("doc_id"),
        F.lit("work_order").alias("doc_type"),
        F.concat_ws(" ", F.lit("Work order"), "wo_id", F.lit("-"), "unit_no", F.lit("-"), "system_category").alias("title"),
        text.alias("text"),
        "vin", "unit_no", "model", "system_category",
        F.col("dtc_refs").alias("dtc_codes"),
        F.to_date("opened_at").alias("doc_date"),
        F.concat(F.lit("silver.work_orders/"), F.col("wo_id")).alias("source_ref"),
    )


def sop_documents(sop_folder: str):
    """Markdown SOP files -> list of document dicts. One per file."""
    docs = []
    for name in sorted(os.listdir(sop_folder)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(sop_folder, name), encoding="utf-8") as f:
            text = f.read()

        # title = first line that starts with "# "
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name)
        number = name[:2]                                   # "01_coolant..." -> "01"

        docs.append({
            "doc_id": f"SOP-{number}",
            "doc_type": "sop",
            "title": title,
            "text": text,
            "vin": None, "unit_no": None, "model": None,   # SOPs apply to the whole fleet
            "system_category": SOP_SYSTEM.get(number, "general"),
            "dtc_codes": sorted(set(CODE_PATTERN.findall(text))),
            "doc_date": None,
            "source_ref": f"documents/sops/{name}",
        })
    return docs


def dtc_guide_documents(spn_ref_df, fmi_ref_df, dtc_events_df):
    """SPN/FMI reference tables -> one guide document per SPN."""
    # TODO
    raise NotImplementedError
