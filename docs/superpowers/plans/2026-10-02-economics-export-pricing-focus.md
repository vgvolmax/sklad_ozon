# Economics export, target prices and focused clusters implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Repair filtered downloads, allow lower target prices, summarize period profit and uploaded advertising, and keep article exploration focused with SKU copying.

**Architecture:** Python owns scenario calculations, product selection, totals and XLSX. Extend the existing Economics workspace and immutable selected-period evidence; vanilla UI owns focus, display limits and clipboard feedback.

**Tech Stack:** Existing Python/FastAPI/Decimal/openpyxl and committed vanilla JavaScript/CSS; no new runtime dependency.

**Spec:** User-approved five-point design in this conversation (2026-10-02), together with the shipped Economics section of `UX-CONTRACT.md` and `DESIGN.md`. The current user instruction supersedes the old entire-assortment/article-only export contract.

## Global constraints

- New branch/PR from current main; no merge or auto-merge.
- API/file ownership and Plan/Flow math remain unchanged; no new data-loading or settings flows.
- SKU identifies each export row; never merge different SKUs sharing an article.
- Dates are inclusive acceptance dates within loaded history; profit follows delivered Economics route quantities/current rates, not payouts.
- Show pre-advertising model profit, known uploaded spend, and their difference once. Missing costs/routes/spend remain visibly incomplete, not fabricated zero.
- Active search/filter covers all matching products, independent of load-more; backend owns selection.
- Copy has an accessible name, no visual hover tooltip, and a small success popup only after clipboard success.
- Cluster exploration keeps the selected article visible, scrolls its cluster region independently and requires collapse to return to other articles. Its own history charts remain available.

## Review focus

- Shared/missing articles and formula-looking identities must export independently and safely by SKU.
- No ad files, valid zero spend, spend with unknown DRR and partial routes must not masquerade as complete zero expense/profit.
- Unreachable price goals and tax breakpoints must not produce a false lower-price recommendation.
- Changing filters/scenarios while requests/downloads are pending must not deliver a stale product selection.
- Clipboard denial, rapid copy clicks, focused-cluster redraws, keyboard exit and narrow view must retain usable controls and the correct SKU.

## Task 1: Backend selection, pricing and period totals

**Files:** `backend/economics/{workspace,export,selection,summary}.py`, `backend/api.py`; `tests/economics/test_workspace.py`, `tests/api/test_economics_selection.py`, `tests/api/test_cost_prices.py`.

**Interfaces:** `select_products(products, *, search='', filter='all') -> list`; `summarize_products(products, *, history_complete=True) -> dict`; workspace products add `profit_before_ads_total`, `price_action`, `price_delta`, `price_delta_rate`. Shared report requests accept `search` and `filter`, return filtered products plus original catalog count and totals. Export adds a SKU column while preserving original column positions.

- [x] Write tests for duplicate/blank article exports, selected-only rows, empty/invalid selection, search/filter counts, lower/minimal target margin and ROI prices, unreachable goals, clipped advertising and incomplete/zero summary inputs.
- [x] Run focused tests and verify expected RED assertions against the existing behavior.
- [x] Implement backend selection, positive price search from one kopek, independent before-ad route profit and filtered totals; preserve numeric XLSX and formula safety.
- [x] Run `python -m pytest tests/economics tests/api/test_cost_prices.py tests/api/test_economics_selection.py -q`; expected PASS.
- [x] Commit the backend task and record its verification.

## Task 2: Workspace selection, downloads and summary UI

**Files:** `frontend/assets/js/economics_workspace.js`, `frontend/assets/css/workspace.css`, `tests/browser/economics_focus_smoke.py`; update existing Economics browser checks.

**Consumes:** Task 1 request filters and returned catalog count, totals and price direction.
**Produces:** Server-owned search/filter results, three-line profit card, lower-price state/filter, independent retryable export error.

- [x] Add a real-loopback browser regression for filtering/export contents and retry, all matching rows beyond load-more, lower-price feedback, period summary and search races.
- [x] Run it; expected RED on the missing filtered export/summary behavior.
- [x] Send filter/search with every scenario/export request, debounce search and discard stale responses; show server totals/directions. Keep export errors separate and allow retry; reject empty export and changed pending selection.
- [x] Run `python -m tests.browser.economics_focus_smoke` and relevant frontend/API tests; expected PASS for selection/download/summary assertions.
- [x] Commit the workspace task and record its verification.

## Task 3: Focused cluster exploration and copy

**Files:** Same workspace JS/CSS and browser regression.

**Consumes:** Selected product data and existing daily history component.
**Produces:** A bounded, keyboard-accessible cluster scroller; selected-only article view until collapse; restoration of table/window position; independent accessible copy control and success/error popup.

- [x] Extend the browser regression with cluster scroll containment, next-article absence, always-visible collapse, restoration, redraw stability, history access, actual clipboard contents, denied permission and absence of visual tooltip.
- [x] Run it; expected RED on current unbounded disclosure and missing copy control.
- [x] Render the active article in the existing table surface, constrain cluster scroll with overscroll containment, preserve scroll across redraws and restore the list on collapse. Copy exact SKU asynchronously and report the actual result without opening/collapsing the article.
- [x] Run the new browser check plus the existing periods/advertising/Plan browser checks; expected PASS, no JavaScript errors or unexpected external calls.
- [x] Commit the focus/copy task and record its verification.

## Task 4: Acceptance, review and publication

**Files:** `DESIGN.md`, `UX-CONTRACT.md`, `.github/workflows/ci.yml`, `docs/acceptance/2026-10-02-economics-export-pricing-focus.md`.

**Consumes:** Tasks 1–3 behavior and tests.

- [x] Update durable Economics selection/export/price/profit/focus contracts; add the browser check and screenshots to CI.
- [x] Run full pytest, eight JS syntax checks, production browser scenarios and diff check; expected PASS. Inspect desktop/narrow screenshots.
- [x] Request one fresh whole-branch review; handle important findings in one test-first correction pass and rerun full verification.
- [ ] Publish exact tested tree as a new PR; wait for Python, browser and Windows portable CI on the published head. Verify open/unmerged and no auto-merge.
