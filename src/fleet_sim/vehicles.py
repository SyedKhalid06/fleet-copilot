"""Fleet master data: trucks and drivers."""
import numpy as np
import pandas as pd

from .config import SimConfig
from .reference import MODELS, DUTY

# VIN alphabet excludes I, O, Q (ISO 3779)
_VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
# World manufacturer identifiers used by Volvo trucks (EU builds / North American builds)
_WMI = {"EU": "YV2", "NA": "4V4"}


def _vin(rng, region: str, model_year: int) -> str:
    # 17 chars: WMI(3) + descriptor(5) + check(1) + year(1) + plant(1) + serial(6). Synthetic.
    year_code = "KLMNPRSTV"[model_year - 2019]  # 2019=K ... 2027=V
    body = "".join(rng.choice(list(_VIN_CHARS), 5))
    plant = rng.choice(list("ABC"))
    serial = "".join(rng.choice(list("0123456789"), 6))
    return f"{_WMI[region]}{body}X{year_code}{plant}{serial}"


def make_fleet(cfg: SimConfig, rng: np.random.Generator):
    depot_idx = rng.choice(len(cfg.depots), size=cfg.n_vehicles, p=np.array(cfg.depot_weights) / sum(cfg.depot_weights))
    vehicles, counters = [], {d.code: 0 for d in cfg.depots}

    for i in range(cfg.n_vehicles):
        depot = cfg.depots[depot_idx[i]]
        options = [m for m, spec in MODELS.items() if spec["region"] == depot.region]
        w = np.array([MODELS[m]["weight"] for m in options], dtype=float)
        model = rng.choice(options, p=w / w.sum())
        spec = MODELS[model]
        model_year = int(rng.choice(range(2019, 2026), p=[.08, .10, .14, .17, .18, .18, .15]))
        in_service = pd.Timestamp(f"{model_year}-01-01") + pd.Timedelta(days=int(rng.integers(0, 330)))
        age_years = (pd.Timestamp(cfg.start_date) - in_service).days / 365.25
        duty = spec["duty"]
        annual_km = {"long_haul": 140_000, "regional": 85_000, "urban": 45_000}[duty]
        odometer_start = int(max(0.0, age_years) * annual_km * rng.uniform(0.8, 1.15))

        counters[depot.code] += 1
        vehicles.append({
            "vin": _vin(rng, depot.region, model_year),
            "unit_no": f"{depot.code}-{counters[depot.code]:03d}",
            "depot": depot.code,
            "model": model,
            "model_year": model_year,
            "engine": rng.choice(spec["engines"]),
            "duty_cycle": duty,
            "in_service_date": in_service.date().isoformat(),
            "odometer_start_km": odometer_start,
            "service_interval_km": spec["service_km"],
            # hidden trait (not exported): how efficient this truck is vs its spec
            "hidden_efficiency": float(rng.normal(1.0, 0.025)),
        })

    vdf = pd.DataFrame(vehicles)

    drivers = []
    for depot in cfg.depots:
        n_trucks = int((vdf.depot == depot.code).sum())
        for j in range(max(1, int(np.ceil(n_trucks * cfg.drivers_per_depot_factor)))):
            card = f"{depot.country}{rng.integers(10**13, 10**14):014d}"
            drivers.append({
                "driver_id": card,
                "depot": depot.code,
                "driver_name": f"Driver {depot.code}-{j + 1:03d}",
                "hire_year": int(rng.integers(2008, 2026)),
                # hidden trait: driving style effect on fuel (eco driver < 1.0 < aggressive)
                "hidden_style": float(np.clip(rng.normal(1.0, 0.035), 0.92, 1.10)),
            })
    ddf = pd.DataFrame(drivers)

    # each truck gets a regular driver from its depot
    vdf["primary_driver_id"] = None
    for depot in cfg.depots:
        idx = vdf.index[vdf.depot == depot.code]
        pool = ddf[ddf.depot == depot.code].driver_id.tolist()
        rng.shuffle(pool)
        for k, i in enumerate(idx):
            vdf.at[i, "primary_driver_id"] = pool[k % len(pool)]
    return vdf, ddf


def public(df: pd.DataFrame) -> pd.DataFrame:
    """Drop hidden simulation traits (columns starting with hidden_) before export."""
    return df[[c for c in df.columns if not c.startswith("hidden_")]]
