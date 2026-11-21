"""Bronze -> silver transformations as plain functions (DataFrame in, DataFrame out).

Keeping them out of the notebook makes them unit-testable on a laptop with local PySpark.
"""
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

STATUS_TRIGGERS = ["IGNITION_ON", "TIMER", "IGNITION_OFF"]


# ------------------------------------------------------------------ telematics
def flatten_rfms(bronze: DataFrame) -> DataFrame:
    """rFMS vehicle-status JSON -> one flat row per record, metric units, readable names."""
    tacho = F.col("driver1Id.tachoDriverIdentification")
    oem = F.col("driver1Id.oemDriverIdentification")
    return bronze.select(
        "vin",
        F.col("triggerType.type").alias("trigger_type"),
        F.to_timestamp("createdDateTime").alias("event_ts"),
        F.to_timestamp("receivedDateTime").alias("received_ts"),
        (F.col("hrTotalVehicleDistance") / 1000).alias("odometer_km"),
        F.col("totalEngineHours").alias("engine_hours_total"),
        (F.col("engineTotalFuelUsed") / 1000).alias("fuel_used_total_l"),
        (F.col("grossCombinationVehicleWeight") / 1000).alias("gross_weight_t"),
        F.coalesce(F.concat(tacho["cardIssuingMemberState"], tacho["driverIdentification"]),
                   oem["oemDriverIdentification"]).alias("driver_id"),
        F.col("snapshotData.gnssPosition.latitude").alias("latitude"),
        F.col("snapshotData.gnssPosition.longitude").alias("longitude"),
        F.col("snapshotData.gnssPosition.heading").alias("heading_deg"),
        F.col("snapshotData.wheelBasedSpeed").alias("speed_kmh"),
        F.col("snapshotData.engineSpeed").alias("engine_rpm"),
        F.col("snapshotData.fuelLevel1").alias("fuel_level_pct"),
        F.col("snapshotData.catalystFuelLevel").alias("adblue_level_pct"),
        F.col("snapshotData.ambientAirTemperature").alias("ambient_temp_c"),
        F.col("snapshotData.driver1WorkingState").alias("driver_working_state"),
        (F.col("uptimeData.serviceDistance") / 1000).alias("service_distance_km"),
        F.col("uptimeData.engineCoolantTemperature").alias("coolant_temp_c"),
        F.col("oemExtension.batteryVoltage").alias("battery_voltage_v"),
        F.col("oemExtension.dpfSootLoadPercent").alias("dpf_soot_load_pct"),
        F.col("oemExtension.engineOilPressureKpa").alias("oil_pressure_kpa"),
        F.col("triggerType.tellTaleInfo.tellTale").alias("tell_tale"),
        F.col("triggerType.tellTaleInfo.state").alias("tell_tale_state"),
        "_ingested_at",
    )


def add_intervals(flat: DataFrame) -> DataFrame:
    """Distance, fuel and engine hours since the previous status record of the same truck.

    Tell-tale records are event-driven and out of sequence, so they get no intervals.
    """
    is_status = F.col("trigger_type").isin(STATUS_TRIGGERS)
    w = Window.partitionBy("vin", is_status).orderBy("event_ts")
    out = (flat
           .withColumn("interval_km", F.when(is_status, F.round(F.col("odometer_km") - F.lag("odometer_km").over(w), 3)))
           .withColumn("interval_fuel_l", F.when(is_status, F.round(F.col("fuel_used_total_l") - F.lag("fuel_used_total_l").over(w), 3)))
           .withColumn("interval_engine_h", F.when(is_status, F.round(F.col("engine_hours_total") - F.lag("engine_hours_total").over(w), 2))))
    return out.withColumn(
        "interval_l_per_100km",
        F.when(F.col("interval_km") > 5, F.round(F.col("interval_fuel_l") / F.col("interval_km") * 100, 2)))


def quality_split(df: DataFrame):
    """Return (good, quarantined). Quarantined rows keep a reason so they can be inspected."""
    reason = (F.when(F.col("vin").isNull() | F.col("event_ts").isNull(), "missing key")
              .when(F.col("interval_km") < 0, "odometer went backwards")
              .when(F.col("interval_fuel_l") < 0, "fuel counter went backwards")
              .when(F.col("speed_kmh") > 130, "speed out of range")
              .when(F.col("coolant_temp_c") > 130, "coolant temp out of range")
              .when((F.col("latitude").isNotNull()) & (~F.col("latitude").between(-90, 90)), "bad latitude"))
    tagged = df.withColumn("dq_issue", reason)
    return tagged.filter("dq_issue IS NULL").drop("dq_issue"), tagged.filter("dq_issue IS NOT NULL")


def silver_telematics(bronze: DataFrame):
    flat = flatten_rfms(bronze).dropDuplicates(["vin", "event_ts", "trigger_type"])
    return quality_split(add_intervals(flat))


# ------------------------------------------------------------------ fault codes
def silver_dtc(bronze: DataFrame, spn_ref: DataFrame, fmi_ref: DataFrame) -> DataFrame:
    lamp = (F.when(F.col("lamp_status.red_stop") == "ON", "RED")
            .when(F.col("lamp_status.mil") == "ON", "MIL")
            .otherwise("AMBER"))
    df = (bronze
          .select("event_id", "vin", "source_address", "spn", "fmi", "occurrence_count",
                  F.to_timestamp("active_from").alias("active_from"),
                  F.to_timestamp("active_to").alias("active_to"),
                  lamp.alias("lamp"), "_ingested_at")
          .dropDuplicates(["event_id"])
          .withColumn("dtc_code", F.concat(F.lit("SPN "), F.col("spn"), F.lit(" FMI "), F.col("fmi")))
          .withColumn("active_minutes",
                      F.round((F.unix_timestamp("active_to") - F.unix_timestamp("active_from")) / 60, 1)))
    return (df.join(F.broadcast(spn_ref.select("spn", "spn_name", "system")), "spn", "left")
              .join(F.broadcast(fmi_ref), "fmi", "left"))


# ------------------------------------------------------------------ work orders
def silver_work_orders(bronze: DataFrame):
    base = (bronze
            .withColumn("opened_at", F.to_timestamp("opened_at"))
            .withColumn("closed_at", F.to_timestamp("closed_at"))
            .dropDuplicates(["wo_id"]))
    wo = (base
          .withColumn("downtime_hours", F.round((F.unix_timestamp("closed_at") - F.unix_timestamp("opened_at")) / 3600, 1))
          .select("wo_id", "vin", "unit_no", "depot", "wo_type", "system_category", "opened_at", "closed_at",
                  "downtime_hours", "odometer_km", "complaint", "dtc_refs", "technician_notes", "labour_hours",
                  "labour_cost", "parts_cost", "total_cost", "currency", "outcome", "_ingested_at"))
    parts = (base.select("wo_id", "vin", F.explode_outer("parts").alias("p"))
             .filter(F.col("p").isNotNull())
             .select("wo_id", "vin", F.col("p.part_name").alias("part_name"),
                     F.col("p.quantity").alias("quantity"), F.col("p.unit_cost").alias("unit_cost"),
                     (F.col("p.quantity") * F.col("p.unit_cost")).alias("line_cost")))
    return wo, parts


# ------------------------------------------------------------------ master data
def silver_vehicles(vehicles: DataFrame, depots: DataFrame) -> DataFrame:
    d = depots.select(F.col("code").alias("depot"), "city", "country", F.col("tz").alias("depot_timezone"),
                      F.col("region").alias("market"), "currency")
    return (vehicles
            .withColumn("in_service_date", F.to_date("in_service_date"))
            .join(F.broadcast(d), "depot", "left"))


# column descriptions -> written as Unity Catalog comments (text-to-SQL agents read these)
COMMENTS = {
    "vehicles": ("One row per truck in the fleet.", {
        "vin": "Vehicle identification number (17 chars). Join key for all truck data.",
        "unit_no": "Fleet unit number used by the ops team, e.g. GOT-014 (depot code + number).",
        "duty_cycle": "long_haul, regional or urban. Drives typical speed, load and fuel use.",
        "odometer_start_km": "Odometer at the start of the data period.",
    }),
    "telematics": ("rFMS vehicle status records: hourly TIMER snapshots plus IGNITION_ON/OFF and TELL_TALE events.", {
        "trigger_type": "Why the record was sent: TIMER (hourly), IGNITION_ON, IGNITION_OFF, TELL_TALE (warning lamp).",
        "event_ts": "When the truck created the record (UTC).",
        "interval_km": "Distance since the truck's previous status record. Sum per day/month for distance driven.",
        "interval_fuel_l": "Fuel used since the previous status record (litres). Sum per period, then divide by km for L/100 km.",
        "interval_l_per_100km": "Fuel consumption for this interval. Noisy - aggregate over days before comparing trucks.",
        "coolant_temp_c": "Engine coolant temperature. Normal 85-95 C; above 104 C raises SPN 110.",
        "dpf_soot_load_pct": "Diesel particulate filter soot load. Regeneration normally starts near 60%.",
        "battery_voltage_v": "24 V system. ~28 V while charging, ~25 V at rest; below 26 V while running is low.",
    }),
    "dtc_events": ("J1939 fault code activations (DM1). One row per code per day it was active.", {
        "dtc_code": "Readable code, e.g. 'SPN 110 FMI 16'. SPN = which component, FMI = how it failed.",
        "lamp": "Dashboard lamp: RED (stop now), AMBER (warning), MIL (emissions).",
        "occurrence_count": "How many times the code has occurred since it was last cleared in the workshop.",
    }),
    "work_orders": ("Workshop work orders: repairs, breakdowns and scheduled services.", {
        "wo_type": "corrective, preventive (scheduled service) or breakdown.",
        "outcome": "resolved, or monitor (no clear fault found - may come back).",
        "technician_notes": "Free text written by the technician. Also indexed for RAG search.",
        "dtc_refs": "Fault codes the technician linked to the job.",
    }),
}
