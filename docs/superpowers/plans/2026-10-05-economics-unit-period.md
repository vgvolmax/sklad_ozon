# Economics unit pricing and period profit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Calculate SKU prices without sales and compare the same unit-profit basis on orders/buyouts with one period expense ledger, inside PR #206.

**Architecture:** Pure Python pricing and period aggregators consume immutable normalized snapshot facts. The existing Economics workspace retains SKU state; the finance component mounts only its own summary panel. Existing financial reads and portable runtime remain owners.

**Tech Stack:** Python/FastAPI/Decimal/openpyxl; committed vanilla JS/CSS; Playwright 1.55.0.

**Spec:** `docs/superpowers/specs/2026-10-05-economics-unit-period-design.md`

## Global constraints

- Work on `codex/economics-buyouts-expenses`; update open PR #206; do not merge or enable auto-merge.
- No new runtime dependency/framework/database; preserve Plan/Flow and SKU identity.
- Common expense ledger belongs to the store, and only quantity changes between summary modes.
- Current upload costs take precedence; no monthly cost history; backend-only normalized evidence.
- Unknown data stays unknown; valid zero and signed returns stay distinct.
- Frontend owns presentation/state; Python owns finance; Moscow UTC+03:00 dates.

## Review focus

- In-progress orders with unknown origin still count while their unit basis remains explicitly incomplete.
- A negative net return quantity must not be clamped or yield a misleading margin.
- Finance cache must not survive a credential change, even with the same FILES analysis.
- Unsaved SKU fields and focused cluster scroll must survive panel mode/progress changes.
- A tariff boundary may make price-profit nonmonotonic; currency-grid minimality must hold.

### Task 1: Independent pricing and DRR policy

**Files:** Create `backend/economics/pricing.py`, `tests/economics/test_pricing.py`; modify `workspace.py`.
**Interfaces:** `calculate_pricing(product, tariffs, settings, routes, *, drr, margin, roi, goal)` returns current unit components, before-ad profit, target price and limiting route; `resolve_drr(real, planned, fallback, *, report_present=False)` returns rate/source/readiness.

- [x] Write behavioral tests for no current price/no sales, zero cost, missing/ambiguous tariffs, lower prices, tier boundaries and real/plan zero.
- [x] Run `python -m pytest tests/economics/test_pricing.py -q`; expected RED for missing implementation.
- [x] Implement using canonical `expected_logistics`/`calculate_unit_economics`, splitting target search by tariff price intervals.
- [x] Run pricing/unit/tariff/workspace tests; expected PASS. Commit domain changes.

### Task 2: Snapshot inputs and period aggregate API

**Files:** Modify `backend/decision/contracts.py`, `backend/api.py`; create `backend/economics/period_profit.py`, `backend/economics/period_api.py`; extend finance normalization; test `tests/economics/test_period_profit.py`, `tests/api/test_economics_period_profit.py`.
**Interfaces:** Pricing inputs/tariffs and net-order daily quantities remain private snapshot fields. `build_period_profit(basis, period, quantities, finance, mode)` returns totals, coverage and classified common expense ledger. `/api/economics/period/workspace` and `/export` share this aggregate and current credential/snapshot guards; finance `/sync` remains the reader.

- [x] Write tests for 12000/5900 example, duplicate costs, signed/unknown quantities, filtered store totals, private snapshot evidence and cost precedence.
- [x] Run new domain/API tests; expected RED for missing behavior.
- [x] Build unit basis independent of mode; classify advertising across all SKUs, exclude modeled services, flag unknown types. Keep legacy buyout endpoints explicitly compatible, never use them for the new panel.
- [x] Run domain/API/full pytest suite; expected PASS. Commit API/aggregate changes.

### Task 3: Local panel, no-sales UI and XLSX

**Files:** Modify `frontend/assets/js/economics_workspace.js`, `economics_buyouts.js`, app stylesheet, `backend/economics/export.py`; extend browser/API export tests.
**Interfaces:** `EconomicsBuyouts.render(panel, snapshot, fetch, {scenario, report})` receives only its panel container and stable scenario; panel changes do not call outer `draw`. Routes for new SKUs are transient per snapshot/SKU; export consumes the same server aggregate.

- [x] Write/run production browser regression for local switch, input/focus/cluster preservation, source/cost failure, no-sales controls and actual XLSX; expected RED against whole-tab switch.
- [x] Mount finance panel inside persistent workspace; add DRR fallback checkbox and compact scenario cards with native controls and reusable copy feedback.
- [x] Add source/coverage exports without altering the original order columns; period workbook has store summary, filtered products and whole-store expenses.
- [x] Run browser scenarios plus domain/API/full pytest suite; expected PASS. Update canonical contracts/acceptance and commit.

### Task 4: Review, final verification and publication

**Files:** Existing CI/browser tests, active contracts and acceptance records.
**Interfaces:** Final reviewer reads base `e8c030a` to tested HEAD plus spec/plan; immutable GitHub tree publication must match the tested local tree.

- [x] Run full pytest, JS syntax, all five production browser scenarios, premium audit, diff checks and spec acceptance matrix.
- [x] Request one fresh whole-change review per requesting-code-review; resolve material findings with RED→GREEN and full suite.
- [ ] Commit verified changes, update PR #206 without force/merge, and wait for exact-head push/PR CI including Windows portable smoke.
- [ ] Update PR description with whole scope, actual checks and live-finance limitations; verify PR stays open/unmerged/no auto-merge.
