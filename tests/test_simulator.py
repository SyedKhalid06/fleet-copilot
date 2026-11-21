"""Fast checks on the generated data. Run with:  pytest -q"""
import glob
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from fleet_sim import SimConfig, generate_all  # noqa: E402


@pytest.fixture(scope="module")
def raw(tmp_path_factory):
    out = tmp_path_factory.mktemp("raw")
    generate_all(SimConfig(n_vehicles=30, months=4, seed=7), str(out), progress=lambda *_: None)
    return str(out)


def _jsonl(raw, folder):
    rows = []
    for f in glob.glob(f"{raw}/{folder}/*/*/*.jsonl"):
        rows += [json.loads(line) for line in open(f)]
    return rows


def test_no_hidden_traits_exported(raw):
    for name in ("vehicles", "drivers"):
        cols = pd.read_csv(f"{raw}/reference/{name}.csv").columns
        assert not [c for c in cols if c.startswith("hidden_")]


def test_counters_never_go_backwards(raw):
    status = [r for r in _jsonl(raw, "rfms/vehicle_status") if r["triggerType"]["type"] != "TELL_TALE"]
    df = pd.DataFrame([(r["vin"], r["createdDateTime"], r["hrTotalVehicleDistance"], r["engineTotalFuelUsed"])
                       for r in status], columns=["vin", "ts", "odo", "fuel"]).sort_values(["vin", "ts"])
    assert (df.groupby("vin").odo.diff().dropna() >= 0).all()
    assert (df.groupby("vin").fuel.diff().dropna() >= 0).all()


def test_fuel_consumption_is_plausible(raw):
    status = [r for r in _jsonl(raw, "rfms/vehicle_status") if r["triggerType"]["type"] != "TELL_TALE"]
    df = pd.DataFrame([(r["vin"], r["hrTotalVehicleDistance"], r["engineTotalFuelUsed"]) for r in status],
                      columns=["vin", "odo", "fuel"])
    g = df.groupby("vin").agg(km=("odo", lambda s: (s.max() - s.min()) / 1000),
                              l=("fuel", lambda s: (s.max() - s.min()) / 1000))
    l100 = g.l / g.km * 100
    assert l100.between(18, 45).all(), l100.describe()


def test_work_orders_reference_known_trucks(raw):
    vins = set(pd.read_csv(f"{raw}/reference/vehicles.csv").vin)
    wos = _jsonl(raw, "work_orders")
    assert wos and all(w["vin"] in vins for w in wos)
    assert len({w["wo_id"] for w in wos}) == len(wos)


def test_ground_truth_points_at_real_work_orders(raw):
    wo_ids = {w["wo_id"] for w in _jsonl(raw, "work_orders")}
    sc = pd.read_csv(f"{raw}/eval/scenarios.csv")
    for col in ("fix_wo", "false_fix_wo"):
        assert set(sc[col].dropna()) <= wo_ids
