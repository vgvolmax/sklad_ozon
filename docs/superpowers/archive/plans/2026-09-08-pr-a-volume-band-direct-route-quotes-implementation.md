# DEFERRED — former PR-A Volume-Band Direct Route Quotes

**Status:** deferred by the approved 2026-09-08 operational shipment-planner correction.

Do **not** implement this plan as part of the active roadmap.

The active PR-A is:

`docs/superpowers/plans/2026-09-08-pr-a-supply-facts-pack-multiplicity-implementation.md`

Canonical current product design:

`docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Why this plan is deferred

The former plan built direct customer-delivery route quotes and RouteCostIndex support for a selected-network future-placement optimizer. The current milestone does not redistribute one destination's future demand into alternate physical origin clusters. It operationalizes the already-calculated plan into whole-pack shipments, dates/methods and manual Ozon XLSX exports.

Existing historical route economics/Flow analysis remains in the product under the Product Completion and real-data designs. Only this future-placement implementation sequence is deferred.

Git history preserves the full former plan if a later approved milestone revives it.