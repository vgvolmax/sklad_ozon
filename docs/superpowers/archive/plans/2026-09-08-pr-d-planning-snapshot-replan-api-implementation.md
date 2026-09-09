# DEFERRED — former PR-D Planning Snapshot & Replan API

**Status:** deferred by the approved 2026-09-08 operational shipment-planner correction.

Do **not** implement this plan as part of the active roadmap.

The active PR-D is:

`docs/superpowers/plans/2026-09-08-pr-d-local-shipment-api-ozon-export-implementation.md`

Canonical current design:

`docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## What was removed from active scope

- selected-network `PlanningBasis` / `PlanningSnapshot` layer;
- `/api/replan` for alternate-origin coverage;
- applied-vs-draft selected supply network persistence;
- route reconstruction for future placement.

## What replaces it

The existing `AnalysisSnapshot` remains the analytical source of truth. The active roadmap appends a downstream whole-pack `ShippablePlan`, then uses local stateless `/api/shipment-plan` and `/api/shipment-export` for dates/methods/batching/manual Ozon XLSX generation.

No Ozon Seller API is introduced.

Git history preserves the full former plan for a future approved placement-optimization milestone.