"""Simulation settings. Change these, not the simulator code."""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Depot:
    code: str          # used in unit numbers, e.g. GOT-014
    city: str
    country: str       # ISO country code (also used on driver cards)
    lat: float
    lon: float
    temp_mean_c: float  # annual mean temperature
    temp_amp_c: float   # seasonal swing (+/-)
    currency: str
    labour_rate: float  # workshop labour rate per hour
    region: str         # "EU" or "NA" (decides which models the depot runs)
    tz: str             # IANA time zone (shifts start in local time)


DEFAULT_DEPOTS = [
    Depot("GOT", "Gothenburg", "SE", 57.708, 11.974, 8.0, 9.0, "EUR", 98.0, "EU", "Europe/Stockholm"),
    Depot("HAM", "Hamburg", "DE", 53.551, 9.993, 9.5, 8.5, "EUR", 95.0, "EU", "Europe/Berlin"),
    Depot("RTM", "Rotterdam", "NL", 51.924, 4.478, 10.5, 7.0, "EUR", 92.0, "EU", "Europe/Amsterdam"),
    Depot("CHI", "Chicago", "US", 41.878, -87.630, 10.0, 14.0, "USD", 135.0, "NA", "America/Chicago"),
]


@dataclass
class SimConfig:
    n_vehicles: int = 100
    start_date: date = date(2025, 11, 1)
    months: int = 12
    seed: int = 42

    depots: list = field(default_factory=lambda: list(DEFAULT_DEPOTS))
    # share of the fleet at each depot (same order as depots)
    depot_weights: tuple = (0.30, 0.25, 0.20, 0.25)

    # share of trucks that develop an injected fault during the period
    scenario_truck_share: float = 0.18

    # chance per operating day that a truck logs a random, unrelated fault code
    background_dtc_daily_rate: float = 0.012

    drivers_per_depot_factor: float = 1.25   # drivers per truck at each depot
