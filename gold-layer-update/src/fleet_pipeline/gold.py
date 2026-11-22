"""Silver -> gold: business-level tables the Copilot's SQL tool queries.

Each table answers a family of ops questions:
  vehicle_daily            "How far did GOT-014 drive last week? Any warning lamps?"
  vehicle_monthly_fuel     "Why has fuel use on RTM-021 gone up?" (vs its own history and vs peers)
  vehicle_fault_status     "Which trucks have active faults nobody has repaired yet?"
  repeat_repairs           "Did the first repair on HAM-014 fix it?"
  vehicle_maintenance      "What did maintenance cost per truck? Who had breakdowns?"
  driver_monthly           "Which drivers use the most fuel compared to peers?"
  fleet_kpis_monthly       "How is each depot doing month by month?"
  vehicle_current_status   "What's the status of CHI-007 right now?"

All dates are local to the truck's depot. Costs stay in the depot's currency (EUR or USD), never summed across currencies.
"""
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

ACTIVE_WINDOW_DAYS = 14      # a fault seen in the last 14 days of data counts as active
REPEAT_WINDOW_DAYS = 90      # same system back in the workshop within 90 days = repeat repair
MIN_KM_FOR_RATE = 20         # don't compute L/100 km on days with almost no driving


def _local_date(ts_col: str):
    return F.to_date(F.from_utc_timestamp(F.col(ts_col), F.col("depot_timezone")))


def _l100(fuel, km, min_km=MIN_KM_FOR_RATE):
    return F.when(F.col(km) >= min_km, F.round(F.col(fuel) / F.col(km) * 100, 2))


# ------------------------------------------------------------------ daily
def vehicle_daily(telem: DataFrame, dtc: DataFrame, vehicles: DataFrame) -> DataFrame:
    v = vehicles.select("vin", "unit_no", "depot", "model", "duty_cycle", "depot_timezone")
    timer = F.col("trigger_type") == "TIMER"
    t = telem.join(F.broadcast(v), "vin").withColumn("local_date", _local_date("event_ts"))
    daily = (t.groupBy("vin", "unit_no", "depot", "model", "duty_cycle", "local_date")
             .agg(F.round(F.sum("interval_km"), 1).alias("km"),
                  F.round(F.sum("interval_fuel_l"), 1).alias("fuel_l"),
                  F.round(F.sum("interval_engine_h"), 2).alias("engine_hours"),
                  F.round(F.avg(F.when(timer, F.col("gross_weight_t"))), 1).alias("avg_gross_weight_t"),
                  F.round(F.avg(F.when(timer, F.col("ambient_temp_c"))), 1).alias("avg_ambient_temp_c"),
                  F.max(F.when(timer, F.col("coolant_temp_c"))).alias("max_coolant_temp_c"),
                  F.min(F.when(timer, F.col("battery_voltage_v"))).alias("min_running_voltage_v"),
                  F.max("dpf_soot_load_pct").alias("max_dpf_soot_pct"),
                  F.min("adblue_level_pct").alias("min_adblue_pct"),
                  F.max("odometer_km").alias("odometer_end_km"),
                  F.mode(F.when(timer, F.col("driver_id"))).alias("main_driver_id"),
                  F.count(F.when(F.col("trigger_type") == "TELL_TALE", 1)).alias("warning_lamp_events"))
             .withColumn("l_per_100km", _l100("fuel_l", "km")))

    d = (dtc.join(F.broadcast(v.select("vin", "depot_timezone")), "vin")
         .withColumn("local_date", _local_date("active_from"))
         .groupBy("vin", "local_date")
         .agg(F.count("*").alias("fault_events"),
              F.count(F.when(F.col("lamp") == "RED", 1)).alias("red_lamp_faults"),
              F.count(F.when(F.col("lamp") == "MIL", 1)).alias("emission_faults"),
              F.count(F.when(F.col("lamp") == "AMBER", 1)).alias("amber_faults"),
              F.sort_array(F.collect_set("dtc_code")).alias("fault_codes")))
    return (daily.join(d, ["vin", "local_date"], "left")
            .fillna(0, ["fault_events", "red_lamp_faults", "emission_faults", "amber_faults"]))


# ------------------------------------------------------------------ monthly fuel vs history and peers
def vehicle_monthly_fuel(daily: DataFrame) -> DataFrame:
    m = (daily.withColumn("month", F.trunc("local_date", "month"))
         .groupBy("vin", "unit_no", "depot", "model", "duty_cycle", "month")
         .agg(F.round(F.sum("km"), 0).alias("km"),
              F.round(F.sum("fuel_l"), 0).alias("fuel_l"),
              F.count(F.when(F.col("km") > 0, 1)).alias("days_driven"),
              F.round(F.avg("avg_gross_weight_t"), 1).alias("avg_gross_weight_t"),
              F.round(F.avg("avg_ambient_temp_c"), 1).alias("avg_ambient_temp_c"))
         .withColumn("l_per_100km", _l100("fuel_l", "km", min_km=500)))

    peers = (m.groupBy("model", "duty_cycle", "month")
             .agg(F.percentile_approx("l_per_100km", 0.5).alias("peer_median_l_per_100km"),
                  F.count("l_per_100km").alias("peer_trucks")))
    w_prev = Window.partitionBy("vin").orderBy("month").rowsBetween(-3, -1)
    return (m.join(peers, ["model", "duty_cycle", "month"], "left")
            .withColumn("pct_vs_peers", F.round((F.col("l_per_100km") / F.col("peer_median_l_per_100km") - 1) * 100, 1))
            .withColumn("prev_3m_l_per_100km", F.round(F.avg("l_per_100km").over(w_prev), 2))
            .withColumn("pct_vs_prev_3m", F.round((F.col("l_per_100km") / F.col("prev_3m_l_per_100km") - 1) * 100, 1)))


# ------------------------------------------------------------------ fault status
def vehicle_fault_status(dtc: DataFrame, work_orders: DataFrame, vehicles: DataFrame) -> DataFrame:
    """One row per truck per fault code: when seen, how often, and whether a workshop has dealt with it.

    status:
      active_unrepaired      seen in the last 14 days of data, no work order since
      monitoring             last work order for it ended with 'monitor' (may come back)
      repaired               a resolved work order referenced it after it was last seen
      cleared_without_repair stopped appearing on its own, no work order (often transient)
    """
    data_end = dtc.agg(F.max("active_from")).first()[0]
    codes = (dtc.groupBy("vin", "dtc_code", "spn", "fmi", "spn_name", "fmi_description", "system", "lamp")
             .agg(F.min("active_from").alias("first_seen"),
                  F.max("active_from").alias("last_seen"),
                  F.count("*").alias("events"),
                  F.countDistinct(F.to_date("active_from")).alias("days_seen"),
                  F.max("occurrence_count").alias("max_occurrence_count")))

    refs = (work_orders.select("vin", "wo_id", "opened_at", "outcome", F.explode("dtc_refs").alias("dtc_code")))
    after = (codes.alias("c").join(refs.alias("r"),
                                   (F.col("c.vin") == F.col("r.vin")) & (F.col("c.dtc_code") == F.col("r.dtc_code"))
                                   & (F.col("r.opened_at") >= F.col("c.last_seen")), "left")
             .select("c.*", F.col("r.wo_id"), F.col("r.opened_at"), F.col("r.outcome")))
    w = Window.partitionBy("vin", "dtc_code").orderBy(F.col("opened_at").desc_nulls_last())
    latest = after.withColumn("rn", F.row_number().over(w)).filter("rn = 1").drop("rn")

    days_since = F.datediff(F.lit(data_end), F.col("last_seen"))
    status = (F.when(F.col("outcome") == "resolved", "repaired")
              .when(F.col("outcome") == "monitor", "monitoring")
              .when(days_since <= ACTIVE_WINDOW_DAYS, "active_unrepaired")
              .otherwise("cleared_without_repair"))
    category = F.when((F.col("spn") == 1761) & (F.col("fmi") == 17), "operational").otherwise("fault")
    return (latest
            .withColumn("fault_category", category)
            .withColumnRenamed("wo_id", "addressed_by_wo")
            .withColumnRenamed("opened_at", "addressed_at")
            .withColumn("days_since_last_seen", days_since)
            .withColumn("status", status)
            .drop("outcome")
            .join(F.broadcast(vehicles.select("vin", "unit_no", "depot", "model")), "vin"))


# ------------------------------------------------------------------ repeat repairs
def repeat_repairs(work_orders: DataFrame) -> DataFrame:
    """Pairs of non-scheduled jobs on the same truck and system within 90 days."""
    wo = work_orders.filter(F.col("wo_type") != "preventive")
    a, b = wo.alias("a"), wo.alias("b")
    return (a.join(b, (F.col("a.vin") == F.col("b.vin"))
                   & (F.col("a.system_category") == F.col("b.system_category"))
                   & (F.col("b.opened_at") > F.col("a.opened_at"))
                   & (F.col("b.opened_at") <= F.col("a.opened_at") + F.expr(f"INTERVAL {REPEAT_WINDOW_DAYS} DAYS")))
            .select(F.col("a.vin").alias("vin"), F.col("a.unit_no").alias("unit_no"),
                    F.col("a.system_category").alias("system_category"),
                    F.col("a.wo_id").alias("first_wo"), F.col("a.opened_at").alias("first_opened_at"),
                    F.col("a.outcome").alias("first_outcome"), F.col("a.technician_notes").alias("first_notes"),
                    F.col("b.wo_id").alias("repeat_wo"), F.col("b.opened_at").alias("repeat_opened_at"),
                    F.col("b.outcome").alias("repeat_outcome"), F.col("b.technician_notes").alias("repeat_notes"),
                    F.datediff("b.opened_at", "a.opened_at").alias("days_between"),
                    (F.col("a.total_cost") + F.col("b.total_cost")).alias("combined_cost"),
                    F.col("a.currency").alias("currency")))


# ------------------------------------------------------------------ maintenance per truck
def vehicle_maintenance(work_orders: DataFrame, daily: DataFrame, repeats: DataFrame, vehicles: DataFrame) -> DataFrame:
    wo = (work_orders.groupBy("vin")
          .agg(F.count(F.when(F.col("wo_type") == "corrective", 1)).alias("corrective_jobs"),
               F.count(F.when(F.col("wo_type") == "preventive", 1)).alias("scheduled_services"),
               F.count(F.when(F.col("wo_type") == "breakdown", 1)).alias("breakdowns"),
               F.round(F.sum("total_cost"), 0).alias("maintenance_cost"),
               F.first("currency").alias("currency"),
               F.round(F.sum("downtime_hours"), 1).alias("workshop_hours"),
               F.max(F.when(F.col("wo_type") == "preventive", F.col("opened_at"))).alias("last_service_at"),
               F.max(F.when(F.col("wo_type") == "preventive", F.col("odometer_km"))).alias("last_service_odometer_km")))
    km = daily.groupBy("vin").agg(F.round(F.sum("km"), 0).alias("km_in_period"))
    rep = repeats.groupBy("vin").agg(F.count("*").alias("repeat_repairs"))
    return (vehicles.select("vin", "unit_no", "depot", "model", "model_year", "duty_cycle")
            .join(km, "vin", "left").join(wo, "vin", "left").join(rep, "vin", "left")
            .fillna(0, ["corrective_jobs", "scheduled_services", "breakdowns", "maintenance_cost",
                        "workshop_hours", "repeat_repairs"])
            .withColumn("cost_per_1000km", F.round(F.col("maintenance_cost") / F.col("km_in_period") * 1000, 1)))


# ------------------------------------------------------------------ drivers
def driver_monthly(telem: DataFrame, vehicles: DataFrame, drivers: DataFrame) -> DataFrame:
    v = vehicles.select("vin", "model", "duty_cycle", "depot_timezone")
    m = (telem.filter(F.col("interval_km").isNotNull() & F.col("driver_id").isNotNull())
         .join(F.broadcast(v), "vin")
         .withColumn("month", F.trunc(_local_date("event_ts"), "month"))
         .groupBy("driver_id", "model", "duty_cycle", "month")
         .agg(F.round(F.sum("interval_km"), 0).alias("km"), F.round(F.sum("interval_fuel_l"), 0).alias("fuel_l"),
              F.countDistinct("vin").alias("trucks_driven"))
         .withColumn("l_per_100km", _l100("fuel_l", "km", min_km=500)))
    peers = (m.groupBy("model", "duty_cycle", "month")
             .agg(F.percentile_approx("l_per_100km", 0.5).alias("peer_median_l_per_100km")))
    return (m.join(peers, ["model", "duty_cycle", "month"], "left")
            .withColumn("pct_vs_peers", F.round((F.col("l_per_100km") / F.col("peer_median_l_per_100km") - 1) * 100, 1))
            .join(F.broadcast(drivers.select("driver_id", "driver_name", "depot")), "driver_id", "left"))


# ------------------------------------------------------------------ depot KPIs
def fleet_kpis_monthly(daily: DataFrame, work_orders: DataFrame, vehicles: DataFrame) -> DataFrame:
    ops = (daily.withColumn("month", F.trunc("local_date", "month"))
           .groupBy("depot", "month")
           .agg(F.countDistinct(F.when(F.col("km") > 0, F.col("vin"))).alias("trucks_active"),
                F.round(F.sum("km"), 0).alias("km"), F.round(F.sum("fuel_l"), 0).alias("fuel_l"),
                F.sum("fault_events").alias("fault_events"), F.sum("red_lamp_faults").alias("red_lamp_faults"))
           .withColumn("l_per_100km", _l100("fuel_l", "km", min_km=500))
           .withColumn("faults_per_10k_km", F.round(F.col("fault_events") / F.col("km") * 10_000, 2)))
    tz = vehicles.select("vin", "depot_timezone")
    ws = (work_orders.join(F.broadcast(tz), "vin")
          .withColumn("month", F.trunc(_local_date("opened_at"), "month"))
          .groupBy("depot", "month")
          .agg(F.count("*").alias("work_orders"),
               F.count(F.when(F.col("wo_type") == "breakdown", 1)).alias("breakdowns"),
               F.round(F.sum("downtime_hours"), 0).alias("workshop_hours"),
               F.round(F.sum("total_cost"), 0).alias("maintenance_cost"),
               F.first("currency").alias("currency")))
    return ops.join(ws, ["depot", "month"], "left").fillna(0, ["work_orders", "breakdowns", "workshop_hours", "maintenance_cost"])


# ------------------------------------------------------------------ current status snapshot
def vehicle_current_status(telem: DataFrame, daily: DataFrame, monthly: DataFrame, faults: DataFrame,
                           work_orders: DataFrame, vehicles: DataFrame) -> DataFrame:
    status_rows = telem.filter(F.col("trigger_type") != "TELL_TALE")
    w = Window.partitionBy("vin").orderBy(F.col("event_ts").desc())
    last = (status_rows.withColumn("rn", F.row_number().over(w)).filter("rn = 1")
            .select("vin", F.col("event_ts").alias("last_seen_at"), "odometer_km", "service_distance_km",
                    "latitude", "longitude", "fuel_level_pct", "adblue_level_pct"))

    end_date = daily.agg(F.max("local_date")).first()[0]
    recent = (daily.filter(F.col("local_date") > F.date_sub(F.lit(end_date), 7))
              .groupBy("vin")
              .agg(F.round(F.sum("km"), 0).alias("km_last_7d"),
                   F.max("max_coolant_temp_c").alias("max_coolant_temp_c_7d"),
                   F.min("min_running_voltage_v").alias("min_running_voltage_v_7d"),
                   F.max("max_dpf_soot_pct").alias("max_dpf_soot_pct_7d"),
                   F.sum("fault_events").alias("fault_events_7d")))
    w_m = Window.partitionBy("vin").orderBy(F.col("month").desc())
    fuel = (monthly.filter(F.col("l_per_100km").isNotNull())
            .withColumn("rn", F.row_number().over(w_m)).filter("rn = 1")
            .select("vin", F.col("l_per_100km").alias("latest_month_l_per_100km"),
                    F.col("pct_vs_peers").alias("latest_month_pct_vs_peers"),
                    F.col("pct_vs_prev_3m").alias("latest_month_pct_vs_prev_3m")))
    open_f = faults.filter(F.col("status").isin("active_unrepaired", "monitoring") & (F.col("fault_category") == "fault"))
    active = (open_f.groupBy("vin")
              .agg(F.count("*").alias("open_fault_codes"),
                   F.sort_array(F.collect_set("dtc_code")).alias("open_fault_list"),
                   F.max(F.col("lamp").isin("RED", "MIL").cast("int")).alias("_lamp"),
                   F.max("days_seen").alias("_days"),
                   F.max((F.col("status") == "monitoring").cast("int")).alias("_monitoring")))
    w_wo = Window.partitionBy("vin").orderBy(F.col("opened_at").desc())
    last_wo = (work_orders.withColumn("rn", F.row_number().over(w_wo)).filter("rn = 1")
               .select("vin", F.col("wo_id").alias("last_wo_id"), F.col("opened_at").alias("last_wo_at"),
                       F.col("wo_type").alias("last_wo_type"), F.col("outcome").alias("last_wo_outcome")))

    out = (vehicles.select("vin", "unit_no", "depot", "model", "model_year", "engine", "duty_cycle")
           .join(last, "vin", "left").join(recent, "vin", "left").join(fuel, "vin", "left")
           .join(active, "vin", "left").join(last_wo, "vin", "left")
           .fillna(0, ["open_fault_codes"]))
    flags = F.concat_ws(", ", F.array_compact(F.array(
        F.when(F.col("max_coolant_temp_c_7d") >= 104, F.lit("high coolant temp")),
        F.when(F.col("min_running_voltage_v_7d") < 26, F.lit("low charging voltage")),
        F.when(F.col("max_dpf_soot_pct_7d") >= 85, F.lit("high DPF soot")),
        F.when(F.col("latest_month_pct_vs_peers") >= 8, F.lit("fuel use above peers")),
        F.when(F.col("service_distance_km") <= 2000, F.lit("service due")),
        # a single one-off amber code is listed but not flagged; repeated, red/emission or multiple codes are
        F.when((F.col("_lamp") == 1) | (F.col("_days") >= 2) | (F.col("open_fault_codes") >= 2),
               F.lit("open fault codes")),
        F.when(F.col("_monitoring") == 1, F.lit("fault under monitoring after inconclusive repair")))))
    return (out.withColumn("attention_flags", F.when(flags == "", None).otherwise(flags))
            .drop("_lamp", "_days", "_monitoring"))


# ------------------------------------------------------------------ Unity Catalog comments
COMMENTS = {
    "vehicle_daily": ("One row per truck per local day it was used: distance, fuel, sensor extremes and fault counts.", {
        "local_date": "Calendar date in the depot's time zone.",
        "l_per_100km": "Fuel consumption for the day; NULL if under 20 km driven.",
        "max_coolant_temp_c": "Highest coolant temperature that day. Normal under 100 C; 104+ raises SPN 110.",
        "min_running_voltage_v": "Lowest charging voltage while driving (24 V system, normal ~28 V; under 26 V is low).",
        "fault_codes": "Distinct J1939 codes active that day, e.g. ['SPN 110 FMI 16'].",
    }),
    "vehicle_monthly_fuel": ("Monthly fuel use per truck compared with its own last 3 months and with peers (same model and duty cycle).", {
        "pct_vs_peers": "Percent above (+) or below (-) the median truck of the same model and duty cycle that month.",
        "pct_vs_prev_3m": "Percent change versus this truck's own average of the previous 3 months. A sustained rise suggests a fault.",
        "peer_trucks": "How many trucks are in the peer group. Treat comparisons with fewer than 3 peers with caution.",
    }),
    "vehicle_fault_status": ("One row per truck per fault code, with whether a workshop has dealt with it.", {
        "status": "active_unrepaired, monitoring (last repair inconclusive), repaired, or cleared_without_repair.",
        "fault_category": "fault, or operational (e.g. AdBlue tank low - a refill issue, not a defect).",
        "addressed_by_wo": "Work order that referenced this code after it was last seen, if any.",
        "days_since_last_seen": "Days between the code's last appearance and the end of the data.",
    }),
    "repeat_repairs": ("Pairs of unscheduled jobs on the same truck and system within 90 days - the first repair may not have fixed the root cause.", {
        "first_outcome": "Outcome of the first job; 'monitor' means no clear fault was found.",
        "days_between": "Days between the first and the repeat job.",
    }),
    "vehicle_maintenance": ("Maintenance totals per truck over the data period. Costs are in the depot currency (see currency).", {
        "cost_per_1000km": "Maintenance cost per 1,000 km driven, in the truck's currency.",
        "repeat_repairs": "Number of repeat-repair pairs (see gold.repeat_repairs).",
    }),
    "driver_monthly": ("Monthly fuel efficiency per driver per truck type, compared with peers. Use for coaching, not blame - load and route also matter.", {
        "pct_vs_peers": "Percent above (+) or below (-) the median for the same model and duty cycle that month.",
    }),
    "fleet_kpis_monthly": ("Monthly KPIs per depot: activity, fuel, faults, workshop time and cost (depot currency).", {
        "faults_per_10k_km": "Fault-code events per 10,000 km driven.",
    }),
    "vehicle_current_status": ("Latest snapshot per truck: position, odometer, service due, last-7-day health, open faults, last work order. Start here for 'what is the status of truck X'.", {
        "attention_flags": "Comma-separated reasons this truck needs attention, or NULL if none.",
        "open_fault_list": "Fault codes (not operational alerts) that are active and unrepaired, or under monitoring after an inconclusive repair.",
        "service_distance_km": "Kilometres left until the next scheduled service.",
    }),
}
