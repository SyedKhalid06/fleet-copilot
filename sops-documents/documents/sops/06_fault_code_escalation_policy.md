# Fault code escalation policy (red, amber, MIL)

Document: SOP-06 · Owner: Fleet Manager · Applies to: all trucks, all depots · Revision: 5

## Purpose
Give drivers, dispatchers and workshops one clear rule for how fast to act on each kind of dashboard warning and J1939 fault code.

## When this applies
Any active fault code (DM1) or dashboard tell-tale reported by the driver or by telematics.

## Symptoms and fault codes
Fault codes are reported as SPN + FMI:
- SPN (Suspect Parameter Number): which component or signal, e.g. SPN 110 = coolant temperature.
- FMI (Failure Mode Identifier): how it failed, e.g. FMI 0 = above normal, most severe; FMI 16 = above normal, moderately severe; FMI 2 = erratic signal; FMI 7 = mechanical system not responding.
- Occurrence count: how many times the code has occurred since it was last cleared. A rising count means a recurring fault.

| Lamp | Meaning | Response time |
|---|---|---|
| RED (stop) | Risk of engine damage or safety risk | Stop safely now; tow or workshop |
| MIL (emissions) | Emissions system fault; may lead to speed inducement | Workshop within 2 days |
| AMBER (warning) | Fault needs attention | Workshop within 3 days, or at next planned visit if within 7 days |

## What the driver should do
1. Red lamp: stop safely, switch off, call dispatch.
2. MIL or amber lamp: finish the trip if the truck drives normally, report it the same day.
3. Always report: the code shown on the display, when it appeared and what you were doing.

## What the workshop should do
1. Record all active and inactive codes with occurrence counts before clearing anything.
2. Link the codes to the work order (DTC references), so repeat faults can be tracked.
3. Outcome "resolved" only when a root cause was found and fixed. Otherwise use "monitor".

## Escalation
- Same code returning within 90 days after a "monitor" job: escalate to the workshop lead.
- A one-off amber code that clears on its own and does not return within 14 days needs no action, but stays on record.
- AdBlue-low warnings (SPN 1761 FMI 17) are operational alerts, not defects: handled by refilling (SOP-08).

## Notes
Never clear codes without recording them. Clearing codes destroys the evidence the next technician needs.
