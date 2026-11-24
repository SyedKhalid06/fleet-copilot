# Emissions warnings and SCR speed inducement

Document: SOP-03 · Owner: Fleet Maintenance · Applies to: all trucks with SCR (AdBlue/DEF) · Revision: 2

## Purpose
Respond to emissions system warnings before the truck is speed-limited by the SCR inducement strategy, and diagnose NOx sensor faults correctly.

## When this applies
- MIL (emissions) lamp on
- Fault codes SPN 3226 (Aftertreatment Outlet NOx), SPN 4364 (SCR Conversion Efficiency), SPN 5246 (SCR Operator Inducement Severity)
- Driver reports reduced top speed or a countdown message on the display

## Symptoms and fault codes
| Code | Meaning | Lamp | Severity |
|---|---|---|---|
| SPN 3226 FMI 2 | Outlet NOx sensor reading erratic | MIL | Workshop within 5 days |
| SPN 4364 FMI 18 | SCR efficiency below normal | MIL | Workshop within 2 days |
| SPN 5246 FMI 0 | Inducement active: truck is or will be speed-limited | MIL | Workshop now |

Inducement is a legal requirement: if the emissions system is not working, the engine progressively limits torque and speed until it is repaired.

## What the driver should do
1. Check the AdBlue level first. If the tank is low, refill (see SOP-08).
2. If the MIL stays on with a full AdBlue tank, report it the same day.
3. If the display shows an inducement countdown or the truck is speed-limited, inform dispatch immediately so loads can be re-planned.

## What the workshop should do
1. Read all aftertreatment codes and freeze-frame data.
2. Test AdBlue quality with a refractometer (target 32.5% urea). Contaminated or diluted AdBlue causes low SCR efficiency.
3. Compare inlet and outlet NOx sensor readings in Tech Tool. An outlet sensor that reads erratically or does not respond to load changes is the most common cause in this fleet.
4. Check NOx sensor connectors for moisture and corrosion. Cleaning a connector may clear the code temporarily; if SPN 3226 or SPN 4364 returns, replace the sensor.
5. After repair, run the SCR efficiency test and confirm inducement is cleared before releasing the truck.

## Escalation
- Inducement (SPN 5246) active: workshop lead informed immediately.
- Repeat emissions codes within 90 days of a "monitor" outcome: replace the outlet NOx sensor rather than cleaning again.

## Notes
A cleaned connector with codes cleared often buys a few weeks. Repeat visits for the same emissions code are a sign the sensor itself has failed.
