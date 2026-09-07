# PR5 — Real-Scale Flow & Stockout Impact UI — Implementation Plan

**Date:** 2026-09-07  
**Branch:** `codex/pr5-real-scale-flow-ui`  
**Base:** `a94c3e5908c62097ec4c1b03de6608301e7b2491`

## Guardrails

Preserve destination-owned demand, all PR1–PR4 analytical formulas, immutable Project JSON contracts, the PII boundary, and the portable vanilla-JS runtime. The backend prepares every demand, routing, ranking, stockout, and economics value; the frontend only selects, filters, paginates, and renders.

## Task 1 — Bounded backend Flow presentation

1. **RED:** add contract/presentation tests for Moscow's 500 own demand versus 1,000 dispatch, externally fulfilled Kazan demand, clean/observed demand invariance, route keys, Top 8 reconciliation, complete-before-incomplete ranking, and signed absolute-value economics ranking.
2. **GREEN:** add immutable `FlowContextSummary` and `FlowMetricOverview`; add `route_key`; assemble summaries from the completed daily destination-demand period and deterministic metric overviews from exact links.
3. **REFACTOR:** isolate ranking and summary assembly in focused pure helpers; keep snapshot orchestration thin.

## Task 2 — Selected-context screen model and state

1. **RED:** add Node-backed tests for the complete Flow state, mode/evidence transitions, 250-context selector pagination, 80/120/180-route bounds, exact route identity, and non-selectable `Прочие`.
2. **GREEN:** build one indexed screen model (`routeByKey`, destination series, episodes, product identity, contextual quality), bounded selector/overview/full-route/SKU tables, and exact backend-key selection.
3. **REFACTOR:** centralize filtering/pagination/copy formatting and remove route-count-dependent topology rendering.

## Task 3 — Backend-driven locality timeline and episodes

1. **RED:** test fixed-height 90-day output, gaps for null local share, 50-row daily pages, 20-row episode pages, context rules, and backend-only episode boundaries/values.
2. **GREEN:** add `SkladOzon.FlowTimeline`, rendering only `stockout_impact.destination_daily_series` and `episodes` into a fixed-height SVG plus bounded exact tables and episode drill-down.
3. **REFACTOR:** keep timeline geometry presentation-only and expose pure model functions for deterministic testing.

## Task 4 — Economics, quality, accessibility, and portable assets

1. **RED:** test positive/negative Russian economics copy, `None → Не рассчитано`, contextual PR4 blocker selection, PII absence, script ordering, CI checks, and Windows asset probing.
2. **GREEN:** render route counterfactuals and episode donors from backend values, contextual Data action, native controls, labelled searches, focus styles, stacked zoom layout, reduced motion, and forced-colors markers.
3. **REFACTOR:** ensure no raw diagnostic code is primary UI and no global listeners are added by Flow renders.

## Task 5 — Deterministic real-scale acceptance fixture

1. **RED:** specify structural assertions for 250 contexts, 80 destination routes, 120 SKU routes, 150 product identities, 90 daily points, 20 episodes, and mixed signed/incomplete economics.
2. **GREEN:** create `tests/manual/flow_stress.html` using production CSS/JS with an in-memory snapshot only.
3. **REFACTOR:** expose deterministic counters in the harness without shipping fixture data in production.

## Task 6 — Documentation and verification

1. Update `DESIGN.md` and `UX-CONTRACT.md` with selected-context-first Flow, bounded selectors/lists, Top 8 + `Прочие`, exact route search, locality timeline, contextual quality, and fixed canvas height.
2. Run focused tests, full `python -m pytest -q`, compileall, every JS syntax check, forbidden-height search, diff check, and status check.
3. Run real Chromium acceptance at 1440×900, 1024×768, 200% zoom, keyboard-only, reduced motion, and forced colors; capture evidence.
4. Review `main...HEAD`, fix every Critical/Important finding, commit, push the one branch, open one PR, and require fresh final-head Linux and Windows CI before describing it as merge-ready.
