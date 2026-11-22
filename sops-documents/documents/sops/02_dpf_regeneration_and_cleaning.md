# DPF regeneration failures and cleaning

Document: SOP-02 · Owner: Fleet Maintenance · Applies to: all Euro VI / EPA 2010+ trucks · Revision: 2

## Purpose
Keep the diesel particulate filter (DPF) healthy, recognise when automatic regeneration is failing, and decide between a parked regeneration and a DPF clean.

## When this applies
- DPF or soot filter tell-tale on the dashboard
- Fault code SPN 3719 (DPF Soot Load Percent) with FMI 16 or FMI 0
- Fault code SPN 3251 (DPF Differential Pressure) with FMI 0
- Telematics soot load above 85%, or frequent regeneration requests

## Symptoms and fault codes
| Code | Meaning | Lamp | Severity |
|---|---|---|---|
| SPN 3719 FMI 16 | Soot load high (about 85% and up) | MIL | Parked regeneration within 1 day |
| SPN 3719 FMI 0 | Soot load very high (about 95% and up) | MIL | Workshop before next shift |
| SPN 3251 FMI 0 | DPF pressure drop too high, filter blocked | MIL | Workshop, possible derate |

How regeneration works: soot builds up during driving. At motorway speed the exhaust is hot enough to burn soot off continuously (passive regeneration). When soot reaches about 60%, the engine runs an active regeneration, which uses a little extra fuel (typically 5-8% during the regeneration).

## What the driver should do
1. When the DPF lamp comes on, allow the regeneration to finish: keep driving at steady speed if safe, or start a parked regeneration as instructed on the display.
2. Do not switch off the engine during an active regeneration.
3. Report repeated DPF warnings (more than twice in a week) to dispatch.

## What the workshop should do
1. Check soot load and differential pressure in Tech Tool.
2. Run a parked (stationary) regeneration. If soot load drops below 20%, close the job and monitor.
3. If parked regeneration fails twice, or differential pressure stays high: remove the DPF and send it for thermal cleaning (exchange unit), fit new gaskets, reset the soot model, run a forced regeneration.
4. Check for causes of high soot production: leaking injectors, EGR faults, boost leaks, excessive idling.

## Escalation
- Two DPF cleanings within 12 months on the same truck: review the truck's duty cycle with the depot manager.
- Any DPF code together with an engine power derate: workshop the same day.

## Notes
Urban trucks (FL, FE) with short trips and low speeds rarely reach passive regeneration temperatures and are the most likely to clog. Consider a scheduled parked regeneration every week for these trucks. Expect fuel consumption to rise a few percent while regenerations keep failing.
