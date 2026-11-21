"""Run the whole simulation and write raw files, laid out the way source systems would deliver them.

<out_dir>/
  reference/  vehicles.csv, drivers.csv, depots.csv, spn_reference.csv, fmi_reference.csv
  rfms/vehicle_status/year=YYYY/month=MM/part-00000.jsonl   (telematics, rFMS-style JSON)
  dtc/year=YYYY/month=MM/part-00000.jsonl                   (J1939 DM1 fault events)
  work_orders/year=YYYY/month=MM/part-00000.jsonl           (workshop system export)
  eval/scenarios.csv, eval/golden_questions.jsonl           (ground truth - keep away from the Copilot)
"""
import json
import os
from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta

import numpy as np
import pandas as pd

from .config import SimConfig
from .reference import FMI, SPN
from .scenarios import assign_scenarios
from .simulator import FleetSim
from .vehicles import make_fleet, public


def _write_jsonl(path: str, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def _month_path(out_dir, folder, ym):
    return os.path.join(out_dir, folder, f"year={ym[0]}", f"month={ym[1]:02d}", "part-00000.jsonl")


def generate_all(cfg: SimConfig = None, out_dir: str = "./raw", progress=print) -> dict:
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    end = (pd.Timestamp(cfg.start_date) + pd.DateOffset(months=cfg.months)).date()
    total_days = (end - cfg.start_date).days

    vehicles, drivers = make_fleet(cfg, rng)
    scenarios = assign_scenarios(vehicles, cfg, rng, total_days)
    sim = FleetSim(cfg, vehicles, drivers, scenarios, rng)

    # ---- reference data
    ref = os.path.join(out_dir, "reference")
    os.makedirs(ref, exist_ok=True)
    public(vehicles).to_csv(os.path.join(ref, "vehicles.csv"), index=False)
    public(drivers).to_csv(os.path.join(ref, "drivers.csv"), index=False)
    pd.DataFrame([asdict(d) for d in cfg.depots]).to_csv(os.path.join(ref, "depots.csv"), index=False)
    pd.DataFrame([{"spn": k, "spn_name": n, "source_address": sa, "system": sys_} for k, (n, sa, sys_) in SPN.items()]) \
        .to_csv(os.path.join(ref, "spn_reference.csv"), index=False)
    pd.DataFrame([{"fmi": k, "fmi_description": d} for k, d in FMI.items()]) \
        .to_csv(os.path.join(ref, "fmi_reference.csv"), index=False)

    # ---- simulate day by day, flushing telematics each month to keep memory flat
    n_rfms = 0
    day, current = cfg.start_date, (cfg.start_date.year, cfg.start_date.month)
    while day < end:
        ym = (day.year, day.month)
        if ym != current:
            _write_jsonl(_month_path(out_dir, "rfms/vehicle_status", current), sim.rfms)
            progress(f"  {current[0]}-{current[1]:02d}: {len(sim.rfms):,} telematics records")
            n_rfms += len(sim.rfms)
            sim.rfms, current = [], ym
        sim.simulate_day(day)
        day += timedelta(days=1)
    _write_jsonl(_month_path(out_dir, "rfms/vehicle_status", current), sim.rfms)
    progress(f"  {current[0]}-{current[1]:02d}: {len(sim.rfms):,} telematics records")
    n_rfms += len(sim.rfms)

    # ---- fault events and work orders, partitioned by month
    for folder, rows, key in (("dtc", sim.dtc, "active_from"), ("work_orders", sim.work_orders, "opened_at")):
        by_month = defaultdict(list)
        for r in rows:
            by_month[(int(r[key][:4]), int(r[key][5:7]))].append(r)
        for ym, chunk in sorted(by_month.items()):
            _write_jsonl(_month_path(out_dir, folder, ym), chunk)

    # ---- ground truth for evaluation
    gt = _ground_truth(scenarios, end)
    os.makedirs(os.path.join(out_dir, "eval"), exist_ok=True)
    pd.DataFrame(gt).to_csv(os.path.join(out_dir, "eval", "scenarios.csv"), index=False)
    _write_jsonl(os.path.join(out_dir, "eval", "golden_questions.jsonl"), _golden_questions(gt))

    summary = {
        "vehicles": len(vehicles), "drivers": len(drivers), "telematics_records": n_rfms,
        "dtc_events": len(sim.dtc), "work_orders": len(sim.work_orders), "scenarios": len(scenarios),
        "period": f"{cfg.start_date} to {end - timedelta(days=1)}",
    }
    progress(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------- evaluation set
ROOT_CAUSE = {
    ("injector_wear", None): "Worn injector on cylinder {cyl} (SPN {spn} FMI 7) causing poor combustion and higher fuel use",
    ("cooling_degradation", "thermostat"): "Thermostat stuck partially closed, restricting coolant flow",
    ("cooling_degradation", "water_pump_leak"): "Water pump leaking at the weep hole, causing coolant loss",
    ("cooling_degradation", "fan_clutch"): "Viscous fan clutch slipping, not cooling enough under load",
    ("dpf_clogging", None): "DPF clogged with soot; active regenerations failing (low-speed duty cycle)",
    ("nox_sensor_failure", None): "Failed outlet NOx sensor giving erratic readings, low calculated SCR efficiency",
    ("charging_fault", "batteries"): "Both batteries worn out (failed load test), worse in cold weather",
    ("charging_fault", "alternator"): "Alternator with low output, charging voltage too low",
}

QUESTION = {
    "injector_wear": "Why has fuel consumption on truck {unit} gone up since {month}?",
    "cooling_degradation": "What is causing the high coolant temperature warnings on truck {unit}?",
    "dpf_clogging": "Why does truck {unit} keep getting particulate filter warnings?",
    "nox_sensor_failure": "Why is the emissions warning lamp on for truck {unit}, and is it speed-limited?",
    "charging_fault": "Why did truck {unit} have battery or starting problems in {month}?",
}


def _ground_truth(scenarios, end):
    rows = []
    for s in scenarios:
        key = (s.type, s.variant) if (s.type, s.variant) in ROOT_CAUSE else (s.type, None)
        status = "resolved" if s.fixed_on else ("symptomatic" if s.first_code_date else "latent")
        rows.append({
            "scenario_id": s.scenario_id, "vin": s.vin, "unit_no": s.unit_no, "type": s.type, "variant": s.variant,
            "onset_date": s.onset.isoformat(),
            "first_code_date": s.first_code_date.isoformat() if s.first_code_date else None,
            "n_scenario_codes": s.n_codes,
            "false_fix_wo": s.false_fix_wo, "fix_wo": s.fix_wo,
            "fixed_on": s.fixed_on.isoformat() if s.fixed_on else None,
            "status_at_end": status,
            "root_cause": ROOT_CAUSE[key].format(cyl=s.cylinder, spn=650 + s.cylinder),
        })
    return rows


def _golden_questions(gt):
    out = []
    for g in gt:
        if g["status_at_end"] == "latent":
            continue   # never showed symptoms - nothing for the Copilot to find
        month = pd.Timestamp(g["first_code_date"] or g["onset_date"]).strftime("%B %Y")
        if g["status_at_end"] == "resolved":
            resolution = f"Fixed in work order {g['fix_wo']} on {g['fixed_on']}."
        else:
            resolution = "Not yet repaired at the end of the data period."
        if g["false_fix_wo"]:
            resolution += f" The first visit ({g['false_fix_wo']}) did not find the real cause."
        out.append({
            "question_id": f"Q-{g['scenario_id']}",
            "question": QUESTION[g["type"]].format(unit=g["unit_no"], month=month),
            "expected_root_cause": g["root_cause"],
            "expected_resolution": resolution,
            "evidence": {"vin": g["vin"], "work_orders": [w for w in (g["false_fix_wo"], g["fix_wo"]) if w]},
            "needs": ["sql", "rag"],
            "scenario_id": g["scenario_id"],
        })
        if g["false_fix_wo"] and g["fix_wo"]:
            out.append({
                "question_id": f"Q-{g['scenario_id']}-repeat",
                "question": f"Did the first repair on truck {g['unit_no']} fix the problem?",
                "expected_root_cause": g["root_cause"],
                "expected_resolution": (f"No. {g['false_fix_wo']} only treated the symptom; the fault came back "
                                        f"and was fixed in {g['fix_wo']}."),
                "evidence": {"vin": g["vin"], "work_orders": [g["false_fix_wo"], g["fix_wo"]]},
                "needs": ["sql", "rag"],
                "scenario_id": g["scenario_id"],
            })
    return out
