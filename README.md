# Fleet Copilot: data foundation on Azure Databricks

Synthetic but standards-based data for a mixed **Volvo truck fleet**, landed in a Unity Catalog medallion architecture.
It is the data layer for Fleet Copilot, a RAG + SQL agent for fleet operations.

* **Telematics** shaped like the **rFMS** vehicle-status API (the ACEA standard Volvo uses for fleet data access)
* **Fault codes** in **SAE J1939** SPN/FMI form (DM1 events)
* **Workshop work orders** with free-text technician notes (the RAG corpus for repair history)
* **Injected faults with ground truth**, so you can measure whether the Copilot finds the real root cause

> **Be clear about what's real.** The fleet, telematics, fault events and work orders are simulated. The formats
> follow public standards (rFMS, J1939), and the fleet uses real Volvo model names and engine families. Real Volvo
> data can be added alongside: the Volvo Discovery Challenge dataset (see notebook 02).

---

## Layout

```
fleet-copilot-data/
├── notebooks/
│   ├── 00_setup_unity_catalog.py   catalog, schemas (bronze/silver/gold/eval), landing volume
│   ├── 01_generate_raw_data.py     runs the simulator, writes raw files to the volume
│   ├── 02_bronze_ingest.py         Auto Loader -> bronze Delta tables (+ optional real Volvo PdM CSVs)
│   └── 03_silver_transform.py      flatten, de-duplicate, data-quality quarantine, UC comments
├── src/
│   ├── fleet_sim/                  the simulator (pure Python: numpy + pandas)
│   │   ├── config.py               fleet size, depots, period, fault rates  <- tune here
│   │   ├── reference.py            models, duty cycles, J1939 SPN/FMI tables
│   │   ├── vehicles.py             trucks + drivers
│   │   ├── scenarios.py            injected faults + work-order text
│   │   ├── simulator.py            hour-by-hour truck simulation
│   │   └── generate.py             orchestration, file layout, ground truth, golden questions
│   └── fleet_pipeline/silver.py    bronze -> silver transforms (testable with local PySpark)
├── tests/test_simulator.py         pytest sanity checks
└── run_local.py                    generate the data on a laptop
```

## Run it on Azure Databricks

1. **Workspace**: Azure Databricks with Unity Catalog enabled (all new workspaces have it).
2. **Get the code in**: push this folder to a GitHub repo, then *Workspace → Create → Git folder*.
   (Or use the Databricks CLI: `databricks workspace import-dir . /Workspace/Users/<you>/fleet-copilot-data`.)
3. **Compute**: serverless notebooks, or a cluster on **DBR 15.4 LTS or newer** in *Dedicated (single user)* access mode.
   No extra libraries needed.
4. **Run the notebooks in order**: `00` → `01` → `02` → `03`. Every notebook has a `catalog` widget (default `fleet_copilot`).
   If you can't create catalogs, point the widget at one you own.

Default run: 100 trucks × 12 months (Nov 2025 – Oct 2026) ≈ 256k telematics records, ~2k fault events, ~400 work orders,
about 220 MB raw. Generation takes ~20 seconds.

### Locally (optional)
```bash
pip install numpy pandas pytest
python run_local.py --out ./raw
pytest -q
```

## The fleet

| Depot | Region | Models | Duty cycles |
|---|---|---|---|
| Gothenburg (GOT), Hamburg (HAM), Rotterdam (RTM) | EU | FH, FH16, FM, FMX, FL, FE | long haul, regional, urban |
| Chicago (CHI) | NA | VNL, VNR | long haul, regional |

The fuel model accounts for load, ambient temperature, idle time, truck-to-truck variation, driver style and DPF regenerations.
Results land in realistic ranges: FH ≈ 31 L/100 km, FL ≈ 27, VNR ≈ 37.

## Injected faults (the hidden stories)

About 18% of trucks develop one of these faults. Each changes the signals, raises J1939 codes and ends in work orders.

| Fault | What shows up in the data | Codes |
|---|---|---|
| Injector wear | Fuel use climbs 8–15% *before* any code appears, then injector codes | SPN 651–656 FMI 7, SPN 94 |
| Cooling degradation (thermostat / water pump / fan clutch) | Coolant temperature rises under load and on hot days, so a fault starting in winter may only show in summer | SPN 110 FMI 16/0, SPN 111 |
| DPF clogging | Soot load climbs, regenerations fail, fuel up ~5% | SPN 3719, SPN 3251 |
| NOx sensor failure | Erratic NOx, low SCR efficiency, then speed-limiting inducement | SPN 3226, 4364, 5246 |
| Charging fault (batteries / alternator) | Low voltage, cold-morning no-start breakdowns | SPN 168 FMI 18/1 |

Realism built in:
* **Wrong first repairs.** Some faults get a first visit that only treats the symptom (outcome `monitor`). The fault comes
  back and a later work order fixes it ("Repeat visit, see WO-…").
* **Open issues.** Faults that start late in the period are still unrepaired when the data ends.
* **Noise.** Unrelated sensor faults, AdBlue warnings, scheduled services, tyres and brakes.

Ground truth lands in `eval.scenarios`. `eval.golden_questions` holds questions such as
*"What is causing the high coolant temperature warnings on truck HAM-014?"*, each with the expected root cause and the
work orders that prove it. **Never give the Copilot access to the `eval` schema.**

## Tables

| Schema.table | Grain |
|---|---|
| `silver.vehicles` | one row per truck (VIN, unit no, model, engine, depot, duty cycle) |
| `silver.drivers` | one row per driver |
| `silver.telematics` | one row per rFMS record; hourly snapshots + interval km / fuel |
| `silver.telematics_quarantine` | rows that failed data-quality rules, with `dq_issue` |
| `silver.dtc_events` | one row per fault code per day active, with SPN/FMI descriptions and lamp |
| `silver.work_orders` / `silver.work_order_parts` | one row per job / per part line |
| `silver.spn_reference`, `silver.fmi_reference` | J1939 code tables |

## Caveats

* rFMS field names follow the rFMS v4 naming conventions, and `oemExtension` stands in for an OEM's extended data set.
  Check against the official ACEA rFMS specification before swapping in a real feed.
* SPN names follow the commonly published SAE J1939-71 naming; FMI meanings are the standard J1939-73 list.
* Volvo manuals and Driver Guide PDFs are copyrighted. Use them only inside your own project; don't republish them.

## Next steps

1. **Gold layer**: daily vehicle KPIs, fuel benchmarks by model/duty cycle, open-fault list, cost per km.
2. **Documents**: Driver Guide PDFs, NHTSA recall records for VNL/VNR, your own SOPs → chunk → Databricks Vector Search.
3. **Real Volvo data**: upload the Volvo Discovery Challenge CSVs, then model them and link them to the fleet.
4. **Copilot**: LangGraph agent with a SQL tool over gold and retrieval over documents + work-order notes, evaluated
   against `eval.golden_questions` with MLflow.
