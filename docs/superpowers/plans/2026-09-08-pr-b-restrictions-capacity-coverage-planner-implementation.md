# DEFERRED — former PR-B Restrictions Capacity & Coverage Planner

**Status:** deferred by the approved 2026-09-08 operational shipment-planner correction.

Do **not** implement this plan as part of the active roadmap.

The active PR-B is:

`docs/superpowers/plans/2026-09-08-pr-b-multiplicity-aware-shippable-plan-implementation.md`

The restriction/capacity facts that remain useful were moved into active PR-A:

`docs/superpowers/plans/2026-09-08-pr-a-supply-facts-pack-multiplicity-implementation.md`

Canonical current design:

`docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## What was removed from active scope

- alternate-origin `SKU × origin × destination` Coverage Planner;
- hard LOCAL-first route assignment;
- constrained-destination greedy fill;
- customer-delivery tariff ranking for future placement;
- desired coverage legs.

## What was preserved

- restrictions remain the physical eligibility/capacity source;
- FINITE / UNLIMITED / UNKNOWN capacity remains explicit;
- warehouse maxima inside one cluster are not summed;
- placement-zone evidence is now preserved for operational shipment rules;
- `Да + 0` remains unusable for positive shipment quantity.

Git history preserves the full former plan if a later approved placement-optimization milestone revives it.