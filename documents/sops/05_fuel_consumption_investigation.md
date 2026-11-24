# Investigating abnormal fuel consumption

Document: SOP-05 · Owner: Fleet Operations · Applies to: all trucks · Revision: 2

## Purpose
Find out why a truck uses more fuel than expected, separating vehicle faults from load, route, weather and driving style.

## When this applies
- A truck's monthly fuel consumption (L/100 km) is 8% or more above its peer group (same model and duty cycle)
- Or 5% or more above its own average of the previous 3 months for two months in a row
- Or a driver reports loss of power, rough running or smoke

## Symptoms and fault codes
A rise in fuel consumption often comes before any fault code. Typical vehicle causes:
| Cause | What you see | Related codes |
|---|---|---|
| Injector wear | Gradual rise over 2-3 months (10-15%), later rough idle | SPN 651-656 FMI 7 (injector cylinder 1-6), SPN 94 |
| DPF regeneration failing | Rise of a few percent, frequent DPF warnings | SPN 3719, SPN 3251 |
| Boost leak | Loss of power on climbs | SPN 102 FMI 18 |
| Tyres under-inflated | Small steady rise | none |

Non-vehicle causes: heavier loads, colder weather (more fuel below 10 °C), more idling, a different driver or route.

## What the operations team should do
1. Compare the truck against peers and against its own history (gold.vehicle_monthly_fuel).
2. Check whether load (average gross weight), ambient temperature or the main driver changed in the same period.
3. If those do not explain the rise, book a workshop check.

## What the workshop should do
1. Read fault codes, including inactive (DM2) codes.
2. Run a cylinder balance test in Tech Tool. A cylinder with low contribution points to a worn injector.
3. Check boost pressure, air filter restriction and charge air hoses.
4. Check DPF soot load and regeneration history.
5. After repair, the truck's fuel consumption should return to its normal level within one month. Check this.

## Escalation
- Fuel 15% or more above peers for a full month: workshop within one week.
- Driver-related differences (same truck, different drivers) go to driver coaching, not the workshop.

## Notes
Compare like with like: an urban FL and a long-haul FH have very different normal consumption. Always use the peer group of the same model and duty cycle.
