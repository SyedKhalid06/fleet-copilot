# Cold starts, batteries and charging faults

Document: SOP-04 · Owner: Fleet Maintenance · Applies to: all 24 V trucks · Revision: 4

## Purpose
Avoid no-start breakdowns in cold weather and tell battery faults apart from alternator (charging) faults.

## When this applies
- Slow cranking, failed start, or a jump start was needed
- Battery or charging tell-tale on the dashboard
- Fault code SPN 168 (Battery Potential) with FMI 17, 18 or 1
- Winter months (November to March), especially below 0 °C

## Symptoms and fault codes
| Code | Meaning | Lamp | Severity |
|---|---|---|---|
| SPN 168 FMI 17 | Voltage slightly low | Amber | Check at next service |
| SPN 168 FMI 18 | Voltage low (resting under ~24.3 V, or charging under 26 V) | Amber | Workshop within 3 days |
| SPN 168 FMI 1 | Voltage critically low | Amber | Workshop now; risk of no-start |

Reference voltages (24 V system): resting, engine off: about 25.2-25.6 V. Charging, engine running: 27.6-28.4 V.

## What the driver should do
1. If the truck cranks slowly in the morning, report it the same day. It will get worse as temperatures drop.
2. If a jump start was needed, do not switch the engine off until the truck is at the workshop.
3. Switch off cab heaters and lights when parked without engine running.

## What the workshop should do
1. Measure charging voltage at 1,200 rpm.
   - Below 26 V: alternator output is low. Check belt and connections, then replace the alternator.
   - 27.6-28.4 V: charging is fine; test the batteries.
2. Load test both batteries (check cold cranking amps against rating). Replace both batteries together if either fails; never mix old and new.
3. Clean and re-torque battery terminals and earth connections.
4. Recharging a weak battery is not a repair. If a battery tests borderline, replace it before winter.

## Escalation
- Any roadside no-start: logged as a breakdown and reviewed by the fleet manager.
- Repeat battery complaint within 90 days of a "monitor" outcome: replace the batteries.

## Notes
Older trucks (4+ years) are most at risk. Check battery condition on all trucks during the October service before winter.
