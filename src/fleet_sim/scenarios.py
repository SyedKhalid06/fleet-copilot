"""Injected faults: the 'hidden stories' in the data.

Each scenario is a real-world failure pattern. It changes the truck's sensor signals and
fuel use, raises J1939 codes, and ends with a work order. The ground truth is exported
separately, so the Copilot can be evaluated on whether it finds the real root cause.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

SCENARIOS = {
    # type: (variants, ramp days (min, max), chance the first repair misses the real cause, eligible duty cycles)
    "injector_wear":       (["cyl1", "cyl2", "cyl3", "cyl4", "cyl5", "cyl6"], (70, 110), 0.0, {"long_haul", "regional"}),
    "cooling_degradation": (["thermostat", "water_pump_leak", "fan_clutch"], (30, 60), 0.5, {"long_haul", "regional", "urban"}),
    "dpf_clogging":        (["dpf"], (25, 45), 0.0, {"urban", "regional"}),
    "nox_sensor_failure":  (["outlet_nox_sensor"], (20, 40), 0.4, {"long_haul", "regional", "urban"}),
    "charging_fault":      (["batteries", "alternator"], (15, 30), 0.3, {"long_haul", "regional", "urban"}),
}


@dataclass
class ScenarioState:
    scenario_id: str
    vin: str
    unit_no: str
    type: str
    variant: str
    onset: date
    ramp_days: int
    false_fix_planned: bool
    sev_offset: float = 0.0
    n_codes: int = 0
    first_code_date: Optional[date] = None
    false_fix_wo: Optional[str] = None
    fix_wo: Optional[str] = None
    fixed_on: Optional[date] = None
    wo_history: list = field(default_factory=list)

    def severity(self, day: date) -> float:
        if self.fixed_on is not None or day < self.onset:
            return 0.0
        raw = (day - self.onset).days / self.ramp_days
        return float(np.clip(raw - self.sev_offset, 0.0, 1.0))

    @property
    def cylinder(self) -> int:
        return int(self.variant[-1]) if self.type == "injector_wear" else 0


def assign_scenarios(vehicles, cfg, rng, total_days: int):
    """Pick which trucks develop which fault, and when."""
    n = int(round(cfg.scenario_truck_share * len(vehicles)))
    chosen = rng.choice(vehicles.index, size=n, replace=False)
    states = []
    for k, idx in enumerate(chosen):
        v = vehicles.loc[idx]
        eligible = [t for t, s in SCENARIOS.items() if v.duty_cycle in s[3]]
        # older trucks are more likely to get charging faults
        w = np.array([(1.3 if v.model_year <= 2021 else 0.5) if t == "charging_fault" else 1.0 for t in eligible])
        stype = rng.choice(eligible, p=w / w.sum())
        variants, (rmin, rmax), p_false, _ = SCENARIOS[stype]

        if stype == "charging_fault":
            # cold-weather fault: starts in the first 4 months (Nov-Feb if the run starts in Nov)
            onset_day = int(rng.integers(5, min(110, total_days - 30)))
        else:
            # some faults start late enough that they are still open when the data ends
            onset_day = int(rng.integers(15, max(16, total_days - 20)))

        states.append(ScenarioState(
            scenario_id=f"SCN-{k + 1:03d}",
            vin=v.vin, unit_no=v.unit_no, type=stype,
            variant=str(rng.choice(variants)),
            onset=cfg.start_date + timedelta(days=onset_day),
            ramp_days=int(rng.integers(rmin, rmax + 1)),
            false_fix_planned=bool(rng.random() < p_false),
        ))
    return states


# --------------------------------------------------------------- work order text
COMPLAINTS = {
    "injector_wear": ["Driver reports loss of power on hills and higher fuel use.",
                      "Fleet office flagged fuel consumption up vs last quarter.",
                      "Engine running rough at idle, driver noticed smoke on start-up."],
    "cooling_degradation": ["Coolant temperature warning on dash during long climbs.",
                            "Driver reports temp gauge running high, engine fan very loud.",
                            "Red coolant warning, driver stopped and called in."],
    "dpf_clogging": ["DPF warning lamp on, regeneration not completing.",
                     "Driver reports frequent regen requests and reduced power.",
                     "MIL lamp on, dash message: particulate filter needs service."],
    "nox_sensor_failure": ["MIL lamp on with emissions warning.",
                           "Truck speed-limited, dash shows emission system fault.",
                           "Driver reports AdBlue warning although tank is full."],
    "charging_fault": ["Truck would not start this morning, jump start required.",
                       "Battery warning lamp on, slow cranking in cold weather.",
                       "Voltage warning on dash, headlights dim at idle."],
}

FALSE_FIX = {
    "cooling_degradation": ("Coolant level low, topped up 4 L. Pressure tested cooling system at 1.0 bar, "
                            "no external leaks found. Codes cleared, monitor.", [("Coolant VCS (5 L)", 1, 38.0)], 1.2),
    "nox_sensor_failure": ("NOx sensor connector showed signs of moisture, cleaned and resealed. "
                           "AdBlue quality tested OK (32.5%). Codes cleared, monitor.", [], 1.0),
    "charging_fault": ("Batteries recharged overnight. Load test borderline on battery 2. "
                       "Charging voltage 27.9 V at idle. Customer advised to monitor.", [], 0.8),
}

REAL_FIX = {
    ("injector_wear", None): (
        "DM1 shows SPN {spn} FMI 7 (injector cyl {cyl}), occurrence count {oc}. Cylinder balance test in "
        "Tech Tool: cyl {cyl} contribution well below the others. Removed and replaced injector cyl {cyl}, "
        "programmed new trim code. Road test OK, fuel trim back to normal, codes cleared.",
        [("Unit injector", 1, 1150.0), ("Injector seal kit", 1, 42.0)], 4.5),
    ("cooling_degradation", "thermostat"): (
        "Repeat overheat complaint. Coolant temp reached 112 C on road test with fan engaged. Thermostat "
        "found stuck partially closed. Replaced thermostat and gasket, refilled and bled system. "
        "Temperatures stable at 88-92 C under load.", [("Thermostat with seal", 1, 165.0), ("Coolant VCS (20 L)", 1, 120.0)], 3.0),
    ("cooling_degradation", "water_pump_leak"): (
        "Coolant loss traced to water pump weep hole, dried coolant residue on block. Replaced water pump "
        "and gasket, refilled and bled system. Pressure test OK, no further loss after 50 km test run.",
        [("Water pump", 1, 640.0), ("Coolant VCS (20 L)", 1, 120.0)], 5.5),
    ("cooling_degradation", "fan_clutch"): (
        "Fan clutch not engaging fully at high coolant temp (slip measured in Tech Tool). Replaced viscous "
        "fan clutch. Coolant temps now controlled under load.", [("Viscous fan clutch", 1, 890.0)], 3.5),
    ("dpf_clogging", None): (
        "Soot load {soot}% and DPF differential pressure high. Parked regen failed twice. Removed DPF and "
        "sent for thermal cleaning, refitted cleaned unit, reset soot model and ran forced regen. "
        "Advised customer that urban low-speed cycle limits passive regeneration.",
        [("DPF cleaning service (exchange)", 1, 520.0), ("DPF gasket set", 1, 36.0)], 3.0),
    ("nox_sensor_failure", None): (
        "Outlet NOx readings erratic vs inlet sensor, SCR efficiency calculated low (SPN 4364 FMI 18). "
        "Replaced outlet NOx sensor, ran SCR efficiency test: passed. Inducement cleared, speed limit removed.",
        [("NOx sensor outlet", 1, 780.0)], 2.0),
    ("charging_fault", "batteries"): (
        "Both batteries failed load test (CCA < 50% of rating). Replaced both batteries, cleaned terminals. "
        "Resting voltage 25.4 V, cranking normal.", [("Battery 12 V 225 Ah", 2, 285.0)], 1.2),
    ("charging_fault", "alternator"): (
        "Charging voltage only 25.6 V at 1200 rpm, alternator output low. Replaced alternator, "
        "charging voltage now 28.2 V. Batteries tested OK after recharge.", [("Alternator 28 V 150 A", 1, 720.0)], 2.5),
}


def real_fix_template(stype: str, variant: str):
    return REAL_FIX.get((stype, variant)) or REAL_FIX[(stype, None)]
