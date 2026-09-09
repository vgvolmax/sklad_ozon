# DEFERRED — former PR-C Coverage-Aware MAX_MARGIN

**Status:** deferred by the approved 2026-09-08 operational shipment-planner correction.

Do **not** implement this plan as part of the active roadmap.

The active PR-C is:

`docs/superpowers/plans/2026-09-08-pr-c-shipment-batching-schedule-implementation.md`

Canonical current design:

`docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Why this plan is deferred

The former PR-C allocated seller stock over desired `origin → destination` coverage legs. Those legs no longer exist in the active milestone.

The existing per-SKU analytical allocation policy itself is **not removed**. Active PR-B reuses its deterministic eligibility/priority semantics when converting the already-calculated plan into complete supplier packs.

The current milestone adds no new global/portfolio optimizer and no user-selectable optimization objective.

Git history preserves the full former plan for a future approved placement-optimization milestone.