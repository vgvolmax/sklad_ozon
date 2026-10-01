# Economics buyer price implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Recover historical price evidence, show daily average SPP and buyer price, and distinguish actual values above plan/targets in Economics.

**Architecture:** Normalize explicit historical prices by SKU, migrate each cached order channel once during normal refresh, and calculate daily averages in the backend. Extend the existing lazy daily panel and existing Economics cells; no new framework or endpoint.

**Tech Stack:** Python 3.12, vanilla JavaScript/CSS/SVG, pytest and existing Playwright smoke checks.

**Spec:** User request of 2026-10-01; root DESIGN.md and UX-CONTRACT.md; active 2026-09-09 API-first architecture and UI specs.

## Global Constraints

- New branch and PR from current main; never merge.
- Existing DemandEstimate, stockout, Flow, route economics and advertising denominator stay unchanged.
- Prices are historical, RUB and joined by canonical SKU; absent evidence never becomes zero or today's catalogue price.
- Backend owns averages. Quantity weights represent ordered units, including existing order lifecycle semantics.
- Preserve lazy loading, snapshot isolation, focus, keyboard/touch controls and optional advertising batch uploads.
- No runtime dependencies or raw customer data; keep Windows portable checks.

## Review Focus

- Financial products arrive reordered or contain duplicate SKU identities: never join by position.
- Null/blank canonical prices can have usable explicit financial evidence; malformed/non-RUB prices remain unknown.
- Old cache refresh must recover older prices once, without repeatedly refetching history for genuine missing prices.
- Different prices and quantities on one day must give unit-weighted means, with honest partial coverage.
- A new buyer-price plot must retain independent scaling, missing-day gaps, bounded tooltips and accessible date selection.

### Task 1: Historical evidence and daily averages

**Files:** adapters/orders.py, source_contracts.py, source_persistence.py, sync.py, domain/economics_daily.py and economics/daily_series.py under backend; corresponding adapter, persistence, sync, daily and API tests.

**Interfaces:** Daily series adds `buyer_price_mean`, `spp_priced_qty`, `buyer_priced_qty`, and observed buyer-price bounds. EndpointEvidence adds optional `order_prices_version=0`; successfully normalized order fetches mark version 1.

- [x] Write regression tests for financial price fallback, different same-day prices, independent buyer-price means, partial coverage and one-time per-channel cache refresh.
- [x] Run targeted pytest; expect failures on missing values/incorrect existing aggregates.
- [x] Implement strict historical price selection, versioned refresh and unit-weighted daily means.
- [x] Run adapter/persistence/sync/daily/API tests; expect all passing.
- [x] Commit this independently testable change.

### Task 2: Buyer-price panel and actual/plan presentation

**Files:** frontend/assets/js/economics_daily.js, economics_workspace.js, frontend/assets/css/workspace.css, frontend tests, tests/browser/economics_advertising_smoke.py, DESIGN.md, UX-CONTRACT.md, README.md and acceptance record.

**Interfaces:** Consume Task 1 daily means and coverage only; existing Economics financial values remain backend-owned.

- [ ] Write geometry tests and browser assertions for three synchronized plots, daily mean hover and actual-above-plan colors.
- [ ] Run the targeted tests/check; expect failure for absent buyer-price plot/presentation.
- [ ] Add independently scaled buyer-price line and hover mean/coverage; stack labeled actual and plan values using teal/purple.
- [ ] Run frontend tests, both production browser smoke checks and strict design audit; inspect screenshots.
- [ ] Run complete pytest, JavaScript syntax checks and git diff --check; expect passing.
- [ ] Commit, obtain independent review, resolve blocking findings, publish new PR and verify CI/head/mergeability without merging.
