"""Day-by-day fleet simulator.

For every truck and every day it decides whether the truck works, simulates each hour of the
shift (distance, fuel, temperatures, soot, voltage, position), and emits:
  * rFMS-style vehicle status records (IGNITION_ON, hourly TIMER, TELL_TALE, IGNITION_OFF)
  * J1939 DM1-style fault events, raised from the simulated signals or from fault scenarios
  * workshop work orders (scenario repairs, scheduled services, minor and routine jobs)
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from .reference import (
    BACKGROUND_CODES, BACKGROUND_FIXES, DUTY, IDLE_FUEL_L_PER_H, MODELS, PM_NOTE, PM_PARTS,
    REFERENCE_GCW_T, ROUTINE_JOBS, SPN, lamp_for,
)
from .scenarios import COMPLAINTS, FALSE_FIX, real_fix_template

TANK_L = {"long_haul": 600, "regional": 450, "urban": 250}
ADBLUE_L = {"long_haul": 80, "regional": 60, "urban": 35}
SOOT_RATE = {"long_haul": 0.9, "regional": 1.5, "urban": 2.3}   # % per operating hour

SCENARIO_SPNS = {
    "injector_wear": {94, 651, 652, 653, 654, 655, 656},
    "cooling_degradation": {110, 111},
    "dpf_clogging": {3251, 3719},
    "nox_sensor_failure": {3226, 4364, 5246},
    "charging_fault": {168},
}

TELL_TALE = {
    110: "ENGINE_COOLANT_TEMPERATURE", 111: "ENGINE_COOLANT_LEVEL", 168: "BATTERY_CHARGING_CONDITION",
    3719: "ENGINE_EMISSION_FILTER_SOOT_FILTER", 3251: "ENGINE_EMISSION_FILTER_SOOT_FILTER",
    4364: "ENGINE_EMISSION_FAILURE", 5246: "ENGINE_EMISSION_FAILURE", 3226: "ENGINE_EMISSION_FAILURE",
    1761: "ADBLUE_LEVEL",
}


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class TruckState:
    odometer_m: float
    service_remaining_m: float
    engine_h: float
    fuel_ml: float
    fuel_level: float = 80.0
    adblue: float = 80.0
    soot: float = 20.0
    downtime_until: date = date.min
    pm_due: date | None = None
    occ: dict = field(default_factory=dict)           # (spn, fmi) -> occurrence count since last clear
    recent_codes: list = field(default_factory=list)  # (date, spn, fmi)


class FleetSim:
    def __init__(self, cfg, vehicles, drivers, scenarios, rng):
        self.cfg, self.rng = cfg, rng
        self.vehicles = vehicles
        self.depots = {d.code: d for d in cfg.depots}
        self.tz = {d.code: ZoneInfo(d.tz) for d in cfg.depots}
        self.drivers_by_depot = {c: g for c, g in drivers.groupby("depot")}
        self.style = dict(zip(drivers.driver_id, drivers.hidden_style))
        self.scen = {s.vin: s for s in scenarios}
        self.state = {}
        for v in vehicles.itertuples():
            km = v.odometer_start_km
            done = km % v.service_interval_km
            self.state[v.vin] = TruckState(
                odometer_m=km * 1000.0,
                service_remaining_m=(v.service_interval_km - done) * 1000.0,
                engine_h=km / 55.0,
                fuel_ml=km * MODELS[v.model]["fuel_base_l100"] * 10.0,   # L/100km * km / 100 * 1000 ml
                fuel_level=float(rng.uniform(40, 95)),
                adblue=float(rng.uniform(40, 95)),
                soot=float(rng.uniform(10, 40)),
            )
        self.rfms, self.dtc, self.work_orders = [], [], []
        self._wo_seq = 0
        self._dtc_seq = 0

    # ------------------------------------------------------------------ weather
    def _ambient(self, depot, day: date, hour: float, day_noise: float) -> float:
        doy = day.timetuple().tm_yday
        seasonal = depot.temp_mean_c - depot.temp_amp_c * math.cos(2 * math.pi * (doy - 15) / 365.25)
        diurnal = 4.0 * math.sin(2 * math.pi * (hour - 9) / 24)
        return seasonal + diurnal + day_noise

    # ------------------------------------------------------------------ main loop
    def simulate_day(self, day: date):
        noise = {c: float(self.rng.normal(0, 2.5)) for c in self.depots}
        for v in self.vehicles.itertuples():
            self._truck_day(v, self.state[v.vin], day, noise[v.depot])

    def _truck_day(self, v, st: TruckState, day: date, day_noise: float):
        rng, depot, duty = self.rng, self.depots[v.depot], DUTY[v.duty_cycle]
        if day < st.downtime_until:
            return
        if st.pm_due and day >= st.pm_due:
            self._pm_work_order(v, st, day)
            return
        p_work = duty["p_weekday"] if day.weekday() < 5 else duty["p_weekend"]
        if rng.random() > p_work:
            return

        scen = self.scen.get(v.vin)
        sev = scen.severity(day) if scen else 0.0
        stype = scen.type if (scen and sev > 0) else None

        # ---- shift plan
        tz = self.tz[v.depot]
        start_h = float(rng.uniform(*duty["start"]))
        n_hours = int(rng.integers(duty["hours"][0], duty["hours"][1] + 1))
        t0 = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(hours=start_h)
        driver = v.primary_driver_id
        if rng.random() > 0.85:
            driver = str(rng.choice(self.drivers_by_depot[v.depot].driver_id.values))
        gcw_t = float(rng.uniform(*duty["gcw_t"]))
        speed_avg = float(rng.uniform(*duty["speed"]))
        inducement = stype == "nox_sensor_failure" and sev > 0.85
        if inducement:
            speed_avg *= 0.6
        bearing = float(rng.uniform(0, 360))
        radius = duty["radius_km"] * float(rng.uniform(0.4, 1.0))
        today_codes = {}   # (spn, fmi) -> datetime first seen today

        # ---- ignition on: battery resting voltage (cold + weak batteries -> no start)
        amb0 = self._ambient(depot, day, start_h, day_noise)
        resting_v = 25.3 + rng.normal(0, 0.1) - 0.02 * max(0.0, -amb0)
        if stype == "charging_fault" and scen.variant == "batteries":
            resting_v -= sev * (1.4 + 0.05 * max(0.0, -amb0))
        if resting_v < 23.7 and amb0 < 3:
            self._raise(v, st, today_codes, 168, 1, t0)
            self._flush_codes(v, st, today_codes, t0 + timedelta(minutes=20))
            self._scenario_work_order(v, st, scen, day, breakdown=True)
            return
        if resting_v < 24.3:
            self._raise(v, st, today_codes, 168, 18, t0)

        self._emit(v, st, t0, "IGNITION_ON", depot.lat, depot.lon, 0, 0.0, amb0, amb0 + rng.uniform(2, 8),
                   driver, 600, gcw_t, resting_v, 180.0)

        # ---- each hour of the shift
        spec = MODELS[v.model]
        lat, lon = depot.lat, depot.lon
        for h in range(n_hours):
            ts = t0 + timedelta(hours=h + 1)
            frac = (h + 0.5) / n_hours
            amb = self._ambient(depot, day, start_h + h + 0.5, day_noise)
            idle = float(np.clip(duty["idle"] * rng.uniform(0.7, 1.3), 0.02, 0.6))
            hour_speed = speed_avg * float(rng.uniform(0.85, 1.10))
            dist_km = hour_speed * (1 - idle)
            load = gcw_t / 40.0

            # soot accumulates, regeneration burns it off (fails more often with a clogged DPF)
            rate = SOOT_RATE[v.duty_cycle] * (1 + 1.6 * sev if stype == "dpf_clogging" else 1.0)
            passive = 1.2 if hour_speed > 60 else 0.0
            st.soot = float(np.clip(st.soot + rate * rng.uniform(0.8, 1.2) - passive, rng.uniform(3, 8), 100))
            regen = False
            if st.soot > 60:
                p_ok = 0.95 - (0.9 * sev if stype == "dpf_clogging" else 0.0)
                if rng.random() < p_ok:
                    st.soot, regen = float(rng.uniform(10, 20)), True

            # fuel
            fuel_mult = 1.0
            if stype == "injector_wear":
                fuel_mult += 0.16 * sev
            elif stype == "dpf_clogging":
                fuel_mult += 0.05 * sev
            l100 = (spec["fuel_base_l100"]
                    * (1 + 0.012 * (gcw_t - REFERENCE_GCW_T[v.duty_cycle]))
                    * v.hidden_efficiency * self.style.get(driver, 1.0)
                    * (1 + 0.004 * max(0.0, 10 - amb))
                    * fuel_mult * (1.07 if regen else 1.0)
                    * float(rng.normal(1.0, 0.025)))
            fuel_l = dist_km * l100 / 100 + idle * IDLE_FUEL_L_PER_H

            # coolant temperature
            coolant = 86 + 4 * load + 0.06 * (amb - 10) + rng.normal(0, 1.2)
            if stype == "cooling_degradation":
                coolant += sev * (14 + 0.35 * max(0.0, amb - 12)) * (0.6 + 0.5 * load)

            # charging voltage
            volts = 28.1 + rng.normal(0, 0.1)
            if stype == "charging_fault" and scen.variant == "alternator":
                volts -= 2.8 * sev

            # position: out-and-back trip from the depot
            d_km = radius * (1 - abs(2 * frac - 1))
            lat = depot.lat + d_km * math.cos(math.radians(bearing)) / 111.0
            lon = depot.lon + d_km * math.sin(math.radians(bearing)) / (111.0 * math.cos(math.radians(depot.lat)))
            heading = int(bearing if frac < 0.5 else (bearing + 180) % 360)
            moving = rng.random() > idle
            inst_speed = max(0.0, float(rng.normal(hour_speed, 6))) if moving else 0.0
            rpm = int(rng.normal(1250, 120)) if moving else int(rng.normal(620, 20))
            oil_kpa = float(rng.normal(390, 25) if moving else rng.normal(180, 15))

            # counters
            st.odometer_m += dist_km * 1000
            st.service_remaining_m -= dist_km * 1000
            st.engine_h += 1.0
            st.fuel_ml += fuel_l * 1000
            st.fuel_level = max(2.0, st.fuel_level - fuel_l / TANK_L[v.duty_cycle] * 100)
            st.adblue = max(0.0, st.adblue - fuel_l * 0.055 / ADBLUE_L[v.duty_cycle] * 100)

            self._emit(v, st, ts, "TIMER", lat, lon, heading, inst_speed, amb, coolant,
                       driver, rpm, gcw_t, volts, oil_kpa)

            # ECU threshold checks -> fault codes
            if coolant >= 111:
                self._raise(v, st, today_codes, 110, 0, ts)
            elif coolant >= 104:
                self._raise(v, st, today_codes, 110, 16, ts)
            if st.soot >= 95:
                self._raise(v, st, today_codes, 3719, 0, ts)
                self._raise(v, st, today_codes, 3251, 0, ts)
            elif st.soot >= 85:
                self._raise(v, st, today_codes, 3719, 16, ts)
            if volts < 24.8:
                self._raise(v, st, today_codes, 168, 1, ts)
            elif volts < 26.0:
                self._raise(v, st, today_codes, 168, 18, ts)
            if st.adblue < 10:
                self._raise(v, st, today_codes, 1761, 17, ts)

        t_end = t0 + timedelta(hours=n_hours, minutes=int(rng.integers(5, 40)))

        # ---- probabilistic scenario codes (no simple threshold in the data)
        def rand_ts():
            return t0 + timedelta(minutes=int(rng.integers(10, n_hours * 60)))
        if stype == "injector_wear":
            if sev > 0.45 and rng.random() < 0.35 * (sev - 0.45) / 0.55:
                self._raise(v, st, today_codes, 650 + scen.cylinder, 7, rand_ts())
            if rng.random() < 0.05 * sev:
                self._raise(v, st, today_codes, 94, 18, rand_ts())
        if stype == "cooling_degradation" and scen.variant == "water_pump_leak" and sev > 0.5 and rng.random() < 0.3:
            self._raise(v, st, today_codes, 111, 17 if sev < 0.9 else 1, rand_ts())
        if stype == "nox_sensor_failure":
            if rng.random() < 0.25 * sev:
                self._raise(v, st, today_codes, 3226, 2, rand_ts())
            if sev > 0.5 and rng.random() < 0.8 * (sev - 0.5):
                self._raise(v, st, today_codes, 4364, 18, rand_ts())
            if inducement:
                self._raise(v, st, today_codes, 5246, 0, t0 + timedelta(minutes=5))

        # ---- random unrelated faults
        bg_today = []
        age = max(0, day.year - v.model_year)
        if rng.random() < self.cfg.background_dtc_daily_rate * (1 + 0.15 * age):
            codes, w = zip(*[((s, f), wt) for s, f, wt in BACKGROUND_CODES if s != 1761])
            spn, fmi = codes[rng.choice(len(codes), p=np.array(w) / sum(w))]
            self._raise(v, st, today_codes, spn, fmi, rand_ts())
            bg_today.append(spn)

        self._flush_codes(v, st, today_codes, t_end)
        self._emit(v, st, t_end, "IGNITION_OFF", lat, lon, 0, 0.0,
                   self._ambient(depot, day, start_h + n_hours, day_noise), 80.0, driver, 0, gcw_t, 25.2, 0.0)

        # ---- end of day: refuel, refill AdBlue, plan service
        if st.fuel_level < 25:
            st.fuel_level = float(rng.uniform(92, 100))
        # drivers top up AdBlue well before empty; now and then someone forgets
        refill_at = rng.uniform(5, 10) if rng.random() < 0.03 else rng.uniform(18, 35)
        if st.adblue < refill_at:
            st.adblue = float(rng.uniform(90, 100))
        if st.service_remaining_m <= 2_000_000 and st.pm_due is None:
            st.pm_due = day + timedelta(days=int(rng.integers(2, 8)))

        # ---- workshop decisions
        if scen and scen.fixed_on is None and any(k[0] in SCENARIO_SPNS[scen.type] for k in today_codes):
            red = any(lamp_for(s, f) == "RED" or s == 5246 for s, f in today_codes)
            p_open = 0.7 if red else 0.08 + 0.035 * min(scen.n_codes, 10)
            if rng.random() < p_open:
                self._scenario_work_order(v, st, scen, day + timedelta(days=1))
        for spn in bg_today:
            if rng.random() < 0.35 and st.downtime_until <= day:
                self._minor_work_order(v, st, day + timedelta(days=1), spn)
        if rng.random() < 0.0035 and st.downtime_until <= day:
            self._routine_work_order(v, st, day + timedelta(days=1))

    # ------------------------------------------------------------------ records
    def _emit(self, v, st, ts, trigger, lat, lon, heading, speed, amb, coolant, driver, rpm, gcw_t, volts, oil_kpa):
        rng = self.rng
        if self.depots[v.depot].region == "EU":
            driver_block = {"tachoDriverIdentification": {"driverIdentification": driver[2:],
                                                          "cardIssuingMemberState": driver[:2]}}
        else:
            driver_block = {"oemDriverIdentification": {"idType": "FLEET_ID", "oemDriverIdentification": driver}}
        working = "DRIVE" if speed > 0 else ("WORK" if trigger == "TIMER" else "REST")
        rec = {
            "vin": v.vin,
            "triggerType": {"context": "RFMS", "type": trigger},
            "createdDateTime": _iso(ts),
            "receivedDateTime": _iso(ts + timedelta(seconds=int(rng.integers(3, 120)))),
            "hrTotalVehicleDistance": int(st.odometer_m),
            "totalEngineHours": round(st.engine_h, 2),
            "engineTotalFuelUsed": int(st.fuel_ml),
            "grossCombinationVehicleWeight": int(gcw_t * 1000),
            "driver1Id": driver_block,
            "snapshotData": {
                "gnssPosition": {"latitude": round(lat, 5), "longitude": round(lon, 5), "heading": heading,
                                 "altitude": int(rng.normal(40, 15)), "speed": round(speed, 1),
                                 "positionDateTime": _iso(ts)},
                "wheelBasedSpeed": round(speed, 1),
                "tachographSpeed": round(speed, 1),
                "engineSpeed": rpm,
                "fuelLevel1": round(st.fuel_level, 1),
                "catalystFuelLevel": round(st.adblue, 1),
                "ambientAirTemperature": round(amb, 1),
                "driver1WorkingState": working,
            },
            "uptimeData": {
                "serviceDistance": int(st.service_remaining_m),
                "engineCoolantTemperature": round(coolant, 1),
            },
            # OEM extended data set (synthetic): extra signals beyond the rFMS core
            "oemExtension": {
                "batteryVoltage": round(volts, 2),
                "dpfSootLoadPercent": round(st.soot, 1),
                "engineOilPressureKpa": round(oil_kpa, 0),
            },
        }
        self.rfms.append(rec)

    def _tell_tale(self, v, st, ts, name, state):
        """Event-triggered rFMS record sent when a dashboard warning lamp switches on."""
        depot = self.depots[v.depot]
        self.rfms.append({
            "vin": v.vin,
            "triggerType": {"context": "RFMS", "type": "TELL_TALE", "tellTaleInfo": {"tellTale": name, "state": state}},
            "createdDateTime": _iso(ts),
            "receivedDateTime": _iso(ts + timedelta(seconds=int(self.rng.integers(3, 60)))),
            "hrTotalVehicleDistance": int(st.odometer_m),
            "totalEngineHours": round(st.engine_h, 2),
            "engineTotalFuelUsed": int(st.fuel_ml),
            "uptimeData": {"serviceDistance": int(st.service_remaining_m),
                           "tellTaleInfo": [{"tellTale": name, "state": state}]},
        })

    def _raise(self, v, st, today_codes, spn, fmi, ts):
        """Code becomes active. Recorded once per day per code (first time seen)."""
        today_codes.setdefault((spn, fmi), ts)

    def _flush_codes(self, v, st, today_codes, t_end):
        scen = self.scen.get(v.vin)
        for (spn, fmi), ts in sorted(today_codes.items(), key=lambda kv: kv[1]):
            st.occ[(spn, fmi)] = min(126, st.occ.get((spn, fmi), 0) + 1)
            lamp = lamp_for(spn, fmi)
            self._dtc_seq += 1
            self.dtc.append({
                "event_id": f"DTC-{self._dtc_seq:07d}",
                "vin": v.vin,
                "source_address": SPN[spn][1],
                "spn": spn,
                "fmi": fmi,
                "occurrence_count": st.occ[(spn, fmi)],
                "active_from": _iso(ts),
                "active_to": _iso(min(t_end, ts + timedelta(minutes=int(self.rng.integers(5, 240))))),
                "lamp_status": {"mil": "ON" if lamp == "MIL" else "OFF",
                                "red_stop": "ON" if lamp == "RED" else "OFF",
                                "amber_warning": "ON" if lamp == "AMBER" else "OFF"},
            })
            st.recent_codes.append((ts.date(), spn, fmi))
            if (spn in TELL_TALE and lamp in ("RED", "MIL")) or spn in (168, 1761):
                self._tell_tale(v, st, ts, TELL_TALE[spn], "RED" if lamp == "RED" else "YELLOW")
            if scen and spn in SCENARIO_SPNS[scen.type] and scen.severity(ts.date()) > 0:
                scen.n_codes += 1
                scen.first_code_date = scen.first_code_date or ts.date()

    # ------------------------------------------------------------------ work orders
    def _new_wo(self, v, st, opened: datetime, days: float, wo_type, category, complaint, notes,
                parts, labour_h, outcome, dtc_refs):
        depot = self.depots[v.depot]
        self._wo_seq += 1
        mult = 1.1 if depot.currency == "USD" else 1.0
        parts_out = [{"part_name": n, "quantity": q, "unit_cost": round(c * mult, 2)} for n, q, c in parts]
        parts_cost = sum(p["quantity"] * p["unit_cost"] for p in parts_out)
        labour_cost = labour_h * depot.labour_rate
        closed = opened + timedelta(days=days)
        wo = {
            "wo_id": f"WO-{opened.year % 100:02d}-{self._wo_seq:05d}",
            "vin": v.vin,
            "unit_no": v.unit_no,
            "depot": v.depot,
            "wo_type": wo_type,
            "system_category": category,
            "opened_at": _iso(opened),
            "closed_at": _iso(closed),
            "odometer_km": int(st.odometer_m / 1000),
            "complaint": complaint,
            "dtc_refs": dtc_refs,
            "technician_notes": notes,
            "parts": parts_out,
            "labour_hours": labour_h,
            "labour_cost": round(labour_cost, 2),
            "parts_cost": round(parts_cost, 2),
            "total_cost": round(labour_cost + parts_cost, 2),
            "currency": depot.currency,
            "outcome": outcome,
        }
        self.work_orders.append(wo)
        st.downtime_until = max(st.downtime_until, (closed + timedelta(hours=12)).date())
        return wo

    def _open_time(self, v, day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=self.tz[v.depot]) + timedelta(hours=float(self.rng.uniform(7, 10)))

    def _recent_refs(self, st, spns, day, window=21):
        seen = []
        for d, s, f in st.recent_codes:
            if s in spns and (day - d).days <= window and f"SPN {s} FMI {f}" not in seen:
                seen.append(f"SPN {s} FMI {f}")
        return seen

    def _clear_codes(self, st, spns):
        for k in [k for k in st.occ if k[0] in spns]:
            del st.occ[k]

    def _scenario_work_order(self, v, st, scen, day, breakdown=False):
        if scen is None:
            return
        rng = self.rng
        spns = SCENARIO_SPNS[scen.type]
        refs = self._recent_refs(st, spns, day)
        complaint = str(rng.choice(COMPLAINTS[scen.type]))
        if breakdown:
            complaint = "Roadside: truck would not start, battery voltage very low. Jump started and driven to workshop."
        opened = self._open_time(v, day)
        category = {"injector_wear": "fuel_system", "cooling_degradation": "cooling", "dpf_clogging": "aftertreatment",
                    "nox_sensor_failure": "aftertreatment", "charging_fault": "electrical"}[scen.type]
        wo_type = "breakdown" if breakdown else "corrective"

        if scen.false_fix_planned and scen.false_fix_wo is None:
            notes, parts, labour = FALSE_FIX[scen.type]
            wo = self._new_wo(v, st, opened, 0.3, wo_type, category, complaint, notes, parts, labour,
                              "monitor", refs)
            scen.false_fix_wo = wo["wo_id"]
            scen.sev_offset += 0.35          # problem seems to go away for a while ...
            scen.wo_history.append(wo["wo_id"])
            self._clear_codes(st, spns)
            return

        template, parts, labour = real_fix_template(scen.type, scen.variant)
        oc = max([n for (s, f), n in st.occ.items() if s in spns] or [1])
        notes = template.format(spn=650 + scen.cylinder, cyl=scen.cylinder, oc=oc, soot=int(st.soot))
        if scen.false_fix_wo:
            notes = f"Repeat visit, see {scen.false_fix_wo}. " + notes
        days = {"injector_wear": 1.5, "cooling_degradation": 1.2, "dpf_clogging": 1.0,
                "nox_sensor_failure": 0.4, "charging_fault": 0.3}[scen.type]
        wo = self._new_wo(v, st, opened, days, wo_type, category, complaint, notes, parts, labour, "resolved", refs)
        scen.fix_wo = wo["wo_id"]
        scen.fixed_on = day
        scen.wo_history.append(wo["wo_id"])
        self._clear_codes(st, spns)
        if scen.type == "dpf_clogging":
            st.soot = 12.0

    def _pm_work_order(self, v, st, day):
        km = int(st.odometer_m / 1000)
        self._new_wo(v, st, self._open_time(v, day), 0.4, "preventive", "scheduled_service",
                     "Scheduled maintenance due (service distance reached).", PM_NOTE.format(km=km),
                     [(n, 1, c) for n, c in PM_PARTS], 3.5, "resolved", [])
        st.service_remaining_m = v.service_interval_km * 1000.0
        st.pm_due = None

    def _minor_work_order(self, v, st, day, spn):
        note, part, labour = BACKGROUND_FIXES[spn]
        refs = self._recent_refs(st, {spn}, day, window=3)
        parts = [(part, 1, float(self.rng.uniform(25, 180)))] if part else []
        self._new_wo(v, st, self._open_time(v, day), 0.2, "corrective", SPN[spn][2],
                     f"Dash warning reported by driver ({', '.join(refs) or f'SPN {spn}'}).", note, parts, labour,
                     "resolved", refs)
        self._clear_codes(st, {spn})

    def _routine_work_order(self, v, st, day):
        cat, note, part, labour, cost = ROUTINE_JOBS[int(self.rng.integers(len(ROUTINE_JOBS)))]
        self._new_wo(v, st, self._open_time(v, day), 0.3, "corrective", cat, "Defect reported on daily walk-around check.",
                     note, [(part, 1, cost)], labour, "resolved", [])
