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

# Which SOP covers each fault code
SPN_SOP = {110: "SOP-01", 111: "SOP-01",
           3719: "SOP-02", 3251: "SOP-02",
           3226: "SOP-03", 4364: "SOP-03", 5246: "SOP-03",
           168: "SOP-04",
           94: "SOP-05", 102: "SOP-05", 651: "SOP-05", 652: "SOP-05", 653: "SOP-05",
           654: "SOP-05", 655: "SOP-05", 656: "SOP-05",
           1761: "SOP-08"}

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


def dtc_guide_documents(spn_ref, fmi_ref, dtc_events):
    """SPN/FMI reference tables + fleet fault history -> one guide document per SPN."""

    # 1. How often each failure mode (SPN + FMI) actually happened in the fleet
    seen = (dtc_events.groupBy("spn", "fmi", "lamp")
            .agg(F.count("*").alias("events"), F.countDistinct("vin").alias("trucks"))
            .join(fmi_ref, "fmi", "left")
            .withColumn("line", F.format_string("- FMI %d: %s. Lamp: %s. Seen %d times on %d trucks.",
                                                "fmi", "fmi_description", "lamp", "events", "trucks"))
            .withColumn("code", F.concat(F.lit("SPN "), F.col("spn"), F.lit(" FMI "), F.col("fmi"))))

    # 2. One row per SPN: its lines sorted by FMI, and its list of codes
    per_spn = (seen.groupBy("spn")
               .agg(F.transform(F.sort_array(F.collect_list(F.struct("fmi", "line"))), lambda x: x["line"]).alias("lines"),
                    F.sort_array(F.collect_set("code")).alias("codes")))

    # 3. Look up the SOP for each SPN (python dict -> Spark map)
    sop_map = F.create_map([F.lit(x) for pair in SPN_SOP.items() for x in pair])
    ecu = F.when(F.col("source_address") == 61, "aftertreatment ECU").otherwise("engine ECU")
    system = F.when(F.col("system") == "fuel", "fuel_system").otherwise(F.col("system"))

    g = spn_ref.join(per_spn, "spn", "left")
    text = F.concat_ws("\n",
        F.format_string("Fault code guide: SPN %d - %s", "spn", "spn_name"),
        F.concat(F.lit("System: "), system, F.lit(" | Reported by: "), ecu,
                 F.lit(" (source address "), F.col("source_address").cast("string"), F.lit(")")),
        F.when(F.size("lines") > 0,
               F.concat(F.lit("Failure modes seen in this fleet:\n"), F.concat_ws("\n", "lines")))
         .otherwise(F.lit("Not seen in this fleet during the data period.")),
        F.concat(F.lit("What to do: follow "), F.coalesce(sop_map[F.col("spn")], F.lit("SOP-06")), F.lit(".")))

    # 4. Standard document columns
    return g.select(
        F.concat(F.lit("DTC-SPN-"), F.col("spn")).alias("doc_id"),
        F.lit("dtc_guide").alias("doc_type"),
        F.format_string("SPN %d - %s", "spn", "spn_name").alias("title"),
        text.alias("text"),
        F.lit(None).cast("string").alias("vin"),
        F.lit(None).cast("string").alias("unit_no"),
        F.lit(None).cast("string").alias("model"),
        system.alias("system_category"),
        F.coalesce("codes", F.array().cast("array<string>")).alias("dtc_codes"),
        F.lit(None).cast("date").alias("doc_date"),
        F.concat(F.lit("silver.spn_reference/"), F.col("spn")).alias("source_ref"),
    )
