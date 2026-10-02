# Economics buyouts implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Calculate realized-product profit with current uploaded costs and known period expenses in a second Economics mode.
**Architecture:** Current Seller finance adapter normalizes immutable account-scoped snapshots. Pure backend aggregation owns money; the financial subview consumes thin NDJSON/report/export endpoints.
**Tech Stack:** Existing Python/FastAPI/openpyxl and committed vanilla JavaScript/CSS; no new runtime dependencies.
**Spec:** `docs/superpowers/specs/2026-10-02-economics-buyouts-design.md`

## Global Constraints

- Do not merge or enable auto-merge.
- Do not consult `docs/superpowers/archive/**`.
- Preserve API/FILES source ownership, planning math, and existing order model.
- No cost-history persistence or extra Data setup. Current uploaded costs win in buyouts.
- Native controls, ru-RU, stable loading geometry and accessible error/status text.

## Review Focus

- Multi-unit and partial returns must not use one unit or the original full return quantity.
- Finance net totals and nested fees must never be summed as independent expenses.
- Existing manual cost overrides must not beat the user's current uploaded costs.
- Filtered SKU profit must not absorb unallocated costs for the whole store.
- Account replacement, failed-day pagination and superseded UI responses preserve safe state.

### Task 1: Finance acquisition and pure profit report

**Files:** Create `backend/economics/buyouts.py`, `backend/ozon/adapters/finance.py`, `backend/ozon/finance_store.py`; modify `backend/ozon/endpoints.py`.
**Interfaces:** `fetch_finance(client, start, end, credential_context_id, progress_callback=None) -> FinanceSnapshot`; `build_buyout_report(snapshot, products, names, search='', filter='all') -> dict`. Snapshot contains normalized signed product proceeds and common adjustments only.

- [x] Write `tests/economics/test_buyouts.py` and `tests/ozon/test_finance.py` for literal hand-calculated examples and pagination/quantity/error boundaries.
- [x] Run those tests; expected failure: missing finance/buyout behavior.
- [x] Implement normalized Decimal values, semantic categories, quantity derivation with posting fallback, atomic fetch and pure aggregation.
- [x] Run the task tests; expected all pass. Commit Task 1.

### Task 2: API, current uploaded costs and export

**Files:** Create `backend/economics/buyout_api.py`; modify `backend/api.py`, `backend/decision/contracts.py`, `backend/economics/export.py`, `backend/main.py` only if router registration needs it.
**Interfaces:** POST `/api/economics/buyouts/sync` NDJSON progress/result; POST `/api/economics/buyouts/workspace` and `/export` take analysis and finance snapshot IDs plus canonical search/filter.

- [x] Add API tests for unloaded/current costs, locked/switched credentials, invalid period/selection, preserved previous loads and XLSX filtered rows/account totals.
- [x] Run new API tests; expected failure: missing endpoints.
- [x] Implement thin guarded endpoints and safe XLSX. Capture current upload cost evidence before directory overrides; keep it backend-only.
- [x] Run scoped API/domain tests; expected all pass. Commit Task 2.

### Task 3: Economics UI and final verification

**Files:** Create `frontend/assets/js/economics_buyouts.js`, `tests/browser/economics_buyouts_smoke.py`; modify workspace JS, index, existing CSS, CI and shipped UI contracts.
**Interfaces:** `S.EconomicsBuyouts.render(root, snapshot, apiFetch, {selector, bindSelector, stale})` owns the financial subview; existing workspace owns the two-mode selector.

- [x] Add browser workflow with real API and controlled Ozon transport; exercise financial mode and reproduce behavior regressions before their fixes.
- [x] Implement mode, independent finance period/load progress, summary, expense disclosure, SKU search/filter/load-more and filtered XLSX.
- [x] Run browser scenario, existing Economics browser scenarios, JS syntax checks and full pytest; expected all pass.
- [x] Update DESIGN/UX contract and acceptance evidence. Commit Task 3.
- [x] Fresh whole-branch review; fix material findings with failing regressions first.
- [ ] Push feature branch, open PR, check exact-head CI and confirm unmerged/auto-merge disabled.
