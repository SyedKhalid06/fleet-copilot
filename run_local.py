"""Generate the raw data on your laptop (no Databricks needed):

    python run_local.py                 # 100 trucks, 12 months -> ./raw
    python run_local.py --trucks 20 --months 3 --out ./raw_small
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from fleet_sim import SimConfig, generate_all  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--trucks", type=int, default=100)
p.add_argument("--months", type=int, default=12)
p.add_argument("--start", default="2025-11-01")
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default="./raw")
a = p.parse_args()

generate_all(SimConfig(n_vehicles=a.trucks, months=a.months, start_date=date.fromisoformat(a.start), seed=a.seed), a.out)
