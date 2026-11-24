# Coolant overheating: driver and workshop response

Document: SOP-01 · Owner: Fleet Maintenance · Applies to: all depots, all models · Revision: 3

## Purpose
Prevent engine damage from overheating and make sure recurring high coolant temperature is traced to its root cause, not just topped up.

## When this applies
- Dashboard coolant temperature warning (yellow or red tell-tale)
- Fault code SPN 110 (Engine Coolant Temperature) with FMI 16 or FMI 0
- Fault code SPN 111 (Engine Coolant Level) with FMI 17 or FMI 1
- Telematics shows coolant temperature above 104 °C under load, or a rising trend over several weeks

## Symptoms and fault codes
| Code | Meaning | Lamp | Severity |
|---|---|---|---|
| SPN 110 FMI 16 | Coolant temperature above normal, moderately severe (about 104 °C and up) | Amber | Plan workshop visit within 3 days |
| SPN 110 FMI 0 | Coolant temperature above normal, most severe (about 111 °C and up) | Red | Stop safely now |
| SPN 111 FMI 17 | Coolant level low, least severe | Amber | Check level at next stop |
| SPN 111 FMI 1 | Coolant level critically low | Red | Stop safely now |

Normal coolant temperature is 85-95 °C under load. Temperatures that climb only on long climbs or hot days are an early sign of reduced cooling capacity.

## What the driver should do
1. Red lamp or SPN 110 FMI 0: pull over safely, let the engine idle for 2-3 minutes, then switch off. Do not open the expansion tank while hot.
2. Amber lamp: reduce load where possible, avoid long climbs at full power, and report the warning to dispatch the same day.
3. Never keep driving with a red coolant warning to "reach the depot".
4. Note in the defect report: outside temperature, load, road (climb, motorway, city) and how long the warning lasted.

## What the workshop should do
1. Read DM1 and DM2 fault lists, including occurrence counts, before clearing any code.
2. Check coolant level, then pressure test the system (1.0 bar) for external leaks.
3. If the level was low: inspect the water pump weep hole, hoses, radiator and EGR cooler for leaks. Dried coolant residue on the block around the pump points to a water pump seal leak.
4. If the level was correct: road test with Tech Tool logging. Check thermostat opening (coolant temperature should stabilise at 88-92 °C) and fan clutch engagement at high coolant temperature.
5. Common root causes in this fleet: thermostat stuck partially closed, viscous fan clutch slipping, water pump leaking.
6. Topping up coolant alone is not a repair. If no root cause is found, close the job as "monitor" and flag the truck for follow-up.

## Escalation
- A second coolant warning within 90 days of a "monitor" outcome must be escalated to the workshop lead for a full cooling system diagnosis.
- Any red coolant event goes to the fleet manager the same day.

## Notes
Cooling faults often only show in warm weather. A truck that overheated in summer may run normally in autumn and the fault returns next summer. Check the truck's coolant temperature history in telematics before closing a cooling job.
