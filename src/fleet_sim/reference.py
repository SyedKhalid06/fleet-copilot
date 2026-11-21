"""Static reference data: truck models, duty cycles and J1939 code definitions.

SPN names follow the SAE J1939-71 naming as it is commonly published. FMI meanings are
the standard J1939-73 failure modes. Verify against the official SAE documents before
using this in anything beyond a prototype.
"""

# ---------------------------------------------------------------- truck models
# fuel_base_l100: typical diesel use (L/100 km) at the duty cycle's reference weight.
MODELS = {
    # Europe
    "FH":   {"region": "EU", "duty": "long_haul", "engines": ["D13K460", "D13K500"], "fuel_base_l100": 30.5, "service_km": 90_000, "weight": 3},
    "FH16": {"region": "EU", "duty": "long_haul", "engines": ["D16K650"],            "fuel_base_l100": 33.5, "service_km": 90_000, "weight": 1},
    "FM":   {"region": "EU", "duty": "regional",  "engines": ["D11K390", "D13K420"], "fuel_base_l100": 32.0, "service_km": 60_000, "weight": 3},
    "FMX":  {"region": "EU", "duty": "regional",  "engines": ["D13K460"],            "fuel_base_l100": 35.0, "service_km": 60_000, "weight": 1},
    "FL":   {"region": "EU", "duty": "urban",     "engines": ["D8K250"],             "fuel_base_l100": 23.0, "service_km": 40_000, "weight": 2},
    "FE":   {"region": "EU", "duty": "urban",     "engines": ["D8K320"],             "fuel_base_l100": 26.0, "service_km": 40_000, "weight": 1},
    # North America
    "VNL":  {"region": "NA", "duty": "long_haul", "engines": ["D13TC455", "D13TC500"], "fuel_base_l100": 33.0, "service_km": 90_000, "weight": 3},
    "VNR":  {"region": "NA", "duty": "regional",  "engines": ["D11-405", "D13-455"],   "fuel_base_l100": 35.0, "service_km": 60_000, "weight": 2},
}

# ---------------------------------------------------------------- duty cycles
DUTY = {
    #             P(works on weekday/weekend)  shift hours  start hour   moving speed km/h  idle share  gross weight t   trip radius km
    "long_haul": {"p_weekday": 0.82, "p_weekend": 0.30, "hours": (9, 11), "start": (4, 7), "speed": (68, 78), "idle": 0.08, "gcw_t": (28, 40), "radius_km": 380},
    "regional":  {"p_weekday": 0.78, "p_weekend": 0.20, "hours": (8, 10), "start": (5, 8), "speed": (52, 64), "idle": 0.15, "gcw_t": (18, 34), "radius_km": 170},
    "urban":     {"p_weekday": 0.75, "p_weekend": 0.15, "hours": (7, 9),  "start": (5, 8), "speed": (22, 34), "idle": 0.26, "gcw_t": (9, 18),  "radius_km": 35},
}
REFERENCE_GCW_T = {"long_haul": 34, "regional": 26, "urban": 13}
IDLE_FUEL_L_PER_H = 2.4

# ---------------------------------------------------------------- J1939
# source addresses (ECU that reports the code)
SA_ENGINE = 0
SA_AFTERTREATMENT = 61

SPN = {
    91:   ("Accelerator Pedal Position 1", SA_ENGINE, "engine"),
    94:   ("Engine Fuel Delivery Pressure", SA_ENGINE, "fuel"),
    100:  ("Engine Oil Pressure", SA_ENGINE, "lubrication"),
    102:  ("Engine Intake Manifold #1 Pressure (boost)", SA_ENGINE, "air_intake"),
    105:  ("Engine Intake Manifold 1 Temperature", SA_ENGINE, "air_intake"),
    110:  ("Engine Coolant Temperature", SA_ENGINE, "cooling"),
    111:  ("Engine Coolant Level", SA_ENGINE, "cooling"),
    168:  ("Battery Potential / Power Input 1", SA_ENGINE, "electrical"),
    175:  ("Engine Oil Temperature 1", SA_ENGINE, "lubrication"),
    651:  ("Engine Injector Cylinder #1", SA_ENGINE, "fuel"),
    652:  ("Engine Injector Cylinder #2", SA_ENGINE, "fuel"),
    653:  ("Engine Injector Cylinder #3", SA_ENGINE, "fuel"),
    654:  ("Engine Injector Cylinder #4", SA_ENGINE, "fuel"),
    655:  ("Engine Injector Cylinder #5", SA_ENGINE, "fuel"),
    656:  ("Engine Injector Cylinder #6", SA_ENGINE, "fuel"),
    1761: ("Aftertreatment 1 Diesel Exhaust Fluid Tank Level", SA_AFTERTREATMENT, "aftertreatment"),
    3226: ("Aftertreatment 1 Outlet NOx 1", SA_AFTERTREATMENT, "aftertreatment"),
    3251: ("Aftertreatment 1 Diesel Particulate Filter Differential Pressure", SA_AFTERTREATMENT, "aftertreatment"),
    3719: ("Aftertreatment 1 Diesel Particulate Filter Soot Load Percent", SA_AFTERTREATMENT, "aftertreatment"),
    4364: ("Aftertreatment 1 SCR Conversion Efficiency", SA_AFTERTREATMENT, "aftertreatment"),
    5246: ("Aftertreatment SCR Operator Inducement Severity", SA_AFTERTREATMENT, "aftertreatment"),
}

FMI = {
    0: "Data valid but above normal operational range - most severe level",
    1: "Data valid but below normal operational range - most severe level",
    2: "Data erratic, intermittent or incorrect",
    3: "Voltage above normal, or shorted to high source",
    4: "Voltage below normal, or shorted to low source",
    5: "Current below normal or open circuit",
    6: "Current above normal or grounded circuit",
    7: "Mechanical system not responding or out of adjustment",
    8: "Abnormal frequency or pulse width or period",
    9: "Abnormal update rate",
    10: "Abnormal rate of change",
    11: "Root cause not known",
    12: "Bad intelligent device or component",
    13: "Out of calibration",
    14: "Special instructions",
    15: "Data valid but above normal operating range - least severe level",
    16: "Data valid but above normal operating range - moderately severe level",
    17: "Data valid but below normal operating range - least severe level",
    18: "Data valid but below normal operating range - moderately severe level",
    19: "Received network data in error",
    31: "Condition exists",
}

EMISSION_SPNS = {1761, 3226, 3251, 3719, 4364, 5246}


def lamp_for(spn: int, fmi: int) -> str:
    """Which dashboard lamp a code lights. RED = stop, AMBER = warning, MIL = emissions."""
    if spn in EMISSION_SPNS:
        return "MIL"
    if fmi in (0, 1) and spn in (100, 110, 111):
        return "RED"
    return "AMBER"


# random codes that happen to any truck now and then (spn, fmi, relative weight)
BACKGROUND_CODES = [
    (91, 2, 3), (100, 17, 2), (175, 3, 2), (1761, 17, 5), (102, 18, 2),
    (105, 16, 2), (168, 17, 3), (94, 17, 1),
]

# what a technician does about a background code: (action note, part or None, labour hours)
BACKGROUND_FIXES = {
    91:   ("Pedal sensor connector corroded, cleaned and applied contact grease.", None, 0.8),
    100:  ("Oil level checked and topped up 2 L. Pressure readings normal on test.", "Engine oil 5W-30 (2 L)", 0.5),
    175:  ("Oil temp sensor reading implausible, sensor replaced.", "Oil temperature sensor", 1.0),
    1761: ("AdBlue tank refilled. Level sensor checked, OK.", None, 0.3),
    102:  ("Boost hose clamp loose at intercooler, re-tightened. Boost OK on road test.", None, 1.2),
    105:  ("Charge air cooler fins blocked with debris, cleaned.", None, 1.5),
    168:  ("Battery terminals cleaned and re-torqued. Charging voltage 28.1 V OK.", None, 0.6),
    94:   ("Fuel prefilter changed, water drained from separator.", "Fuel prefilter", 0.8),
}

# routine work without a fault code: (type, note, part, labour hours, part cost)
ROUTINE_JOBS = [
    ("tyres", "Steer axle tyres worn to 3 mm, both replaced and aligned.", "Steer tyre 385/55R22.5 (x2)", 1.5, 980.0),
    ("tyres", "Drive axle tyre sidewall damage, single tyre replaced.", "Drive tyre 315/70R22.5", 1.0, 520.0),
    ("brakes", "Front brake pads at wear limit, pads replaced both sides.", "Brake pad set front axle", 2.0, 310.0),
    ("body", "Windscreen chip in driver's line of sight, windscreen replaced.", "Windscreen", 2.5, 640.0),
    ("lights", "Nearside rear marker lamp inoperative, lamp unit replaced.", "Marker lamp LED", 0.4, 45.0),
]

PM_NOTE = ("Scheduled service at {km:,} km: engine oil and filters changed, fuel filters changed, "
           "chassis lubricated, brakes and tyres inspected. No defects found.")
PM_PARTS = [("Engine oil 5W-30 (38 L)", 260.0), ("Oil filter kit", 85.0), ("Fuel filter kit", 95.0)]
