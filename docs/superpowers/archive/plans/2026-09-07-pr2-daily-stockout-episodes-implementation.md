# PR2 Daily Stockout Episodes & Precise Route Cleaning — Implementation Plan

**Date:** 2026-09-07
**Scope:** PR2 only; no money, diagnostics redesign, optimizer, planning, runtime, API presentation, or frontend changes.

## Invariants

- Detect only per `SKU × destination`; origin routing never creates or changes destination demand.
- Build immutable, deterministically sorted Decimal locality data from the PR1 daily facts, materializing every calendar day from an identity's first known demand/fulfillment date through `as_of`.
- Preserve the weekly `detect_stockouts` and recommendation-distortion paths unchanged.
- Keep daily locality and episodes internal to `AnalysisResult`; serialize neither through snapshot/API.

## TDD sequence

1. Add RED locality/threshold tests covering zero-routing unknown shares, calendar gaps, immutability, validation, stable-local and SKU-mix controls.
2. Implement `DailyOriginShare`, `DailyLocalityPoint`, `DailyStockoutThresholds`, and `build_daily_locality_series` in focused `stockout_episodes.py`.
3. Add RED episode tests for one-day suppression, sustained collapse, demand collapse, donor switch/merge determinism, availability support/contradiction, and historical/current-week scope.
4. Implement fixed rolling candidates. For candidate end `T`, baseline is `T-13…T-7` and observed is `T-6…T`; require both fulfilled totals ≥10, baseline local share ≥0.60, local drop ≥0.30, destination-demand retention ≥0.60, an external rolling-share rise ≥0.20, and at least two distinct contaminated days. A day is contaminated only with positive fulfillment, local share ≤ baseline local share −0.30, and an external daily share rise ≥0.20. Boundaries are inclusive.
5. Merge candidates per `SKU × destination × scope` when actual affected-date sets overlap or touch. Union affected dates/origins deterministically, retain earliest baseline, minimum observed share/retention, maxima for donor shares/increases, and recompute donor quantities over unique affected dates.
6. Scope candidates ending no later than the Sunday before `as_of`'s ISO week as historical/high/cleanable; later candidates are operational/medium/not cleanable. Apply availability only after detection: positive days-without-stock supports; explicit zero plus positive local FBO stock contradicts; otherwise neutral. Support may raise operational display confidence, never cleaning eligibility.
7. Add RED precise-cleaning tests proving the completed-week daily universe exactly reaggregates to observed routes, only `affected_dates` are excluded for eligible episodes (all origins for that destination/day), current-week evidence is ignored, episode audit is bounded, demand is untouched, and full removal preserves observed fallback.
8. Implement `EpisodeExcludedRouteEvidence`, backward-compatible optional `excluded_episode_routes`, and `build_episode_clean_route_profile`; retain the legacy weekly cleaner.
9. Add RED application/API tests, then integrate daily locality/episodes and precise cleaner while keeping weekly signals as distortion input. Add internal `AnalysisResult` fields without adding snapshot/wire fields.
10. Run focused suites, full pytest, four Node syntax checks, diff checks, review `main...HEAD` against all PR2 gates, fix findings, commit, push, create one PR, and verify fresh final-HEAD CI including Windows portable smoke.

## Complexity

Use one grouping pass, per-identity calendar materialization, prefix/fixed-window aggregation, and deterministic sorting. Do not rescan all facts per identity or perform all-pairs joins; expected complexity is linear or near-linear in materialized daily points.
