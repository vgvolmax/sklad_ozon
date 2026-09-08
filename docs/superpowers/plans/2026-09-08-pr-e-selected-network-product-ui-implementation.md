# DEFERRED — former PR-E Selected-Network Product UI

**Status:** deferred by the approved 2026-09-08 operational shipment-planner correction.

Do **not** implement this plan as part of the active roadmap.

The active PR-E is:

`docs/superpowers/plans/2026-09-08-pr-e-article-first-plan-shipment-ui-implementation.md`

Canonical current UI amendment:

`docs/superpowers/specs/2026-09-08-article-first-plan-ui-amendment.md`

Canonical current product design:

`docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## What was removed from active scope

- selected supply-network draft/applied editor;
- network-only `/api/replan` UX;
- wide `SKU × cluster` table as the primary Plan workspace;
- planned alternate-origin coverage view.

## What replaces it

`План` becomes article-first master/detail using the interaction grammar of `Потоки спроса → По артикулу`, with `Товары | Отгрузки` subviews. The operational view edits dates/methods/cluster scope and downloads Ozon templates for manual upload.

Existing Flow, Economics, Data, visual tokens and shared frontend primitives remain.

Git history preserves the full former plan for a future approved placement-optimization milestone.