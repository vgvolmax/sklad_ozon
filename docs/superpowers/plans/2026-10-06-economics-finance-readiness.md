# Economics finance readiness implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Distinguish missing buyout quantities from missing unit economics, present articles and recover finance-load failures in a new PR; do not merge.

**Architecture:** Keep Python as the owner of monetary calculations and independent quantity/unit coverage. The existing period panel owns presentation, explicit finance loading and retry. Whole-store coverage remains independent of product filters.

**Tech Stack:** Python, Decimal, FastAPI, vanilla JavaScript, pytest and existing Playwright smoke.

**Spec:** `docs/superpowers/specs/2026-10-05-economics-unit-period-design.md`, sections 9–10, root UX-CONTRACT.md; user report of 06.10.2026.

## Global Constraints

- Work from main after merged PR #206, on `codex/economics-finance-readiness`; do not merge or enable auto-merge.
- One unit basis, signed quantity and common expense ledger remain unchanged.
- No guessed buyout quantity or live finance type mapping; unknowns remain explicit.
- Articles are presentation, SKU remains canonical identity; duplicate articles never collapse.
- Financial loading remains explicit and account/period scoped. No new runtime dependencies.

## Review Focus

- No finance snapshot with complete unit inputs: request loading, never blame all unit economics.
- Unknown return quantity with complete unit inputs: identify quantity separately.
- Filtered-out missing unit input: retain whole-store article warning.
- Shared articles and missing article: preserve distinct SKU identities and safe fallback.
- Finance error/cancel versus calculation error: retry the failed operation, preserving valid prior results.

### Task 1: Correct coverage, presentation, retry and export readiness

**Files:** `backend/economics/period_profit.py`, `period_api.py`, `export.py`; `frontend/assets/js/economics_buyouts.js`; domain/API/frontend tests and `tests/browser/economics_buyouts_smoke.py`; DESIGN.md and UX-CONTRACT.md.

**Interfaces:** `build_period_profit(...)` retains its existing fields and adds per-product `unit_complete` and whole-store `coverage` with `unit_available_count`, `missing_unit_products`, `missing_quantity_products`, `ambiguous_articles`. Reason lists contain SKU/article/name and do not depend on selected products. The panel uses these reasons and bounded native disclosures; `retryOperation` selects sync, refresh or download. Buyout export without a covering finance snapshot is unavailable in UI and returns explicit API error.

- [x] Add domain tests for no-finance complete units and independent missing quantity/unit coverage under filtering and known-zero quantities. Add API export/readiness and XLSX reason tests. Add executable frontend regression for sync retry and initial buyout readiness; extend production browser smoke.
- [x] Run new tests: expected RED for absent coverage, enabled empty buyout export and wrong retry operation.
- [x] Add independent coverage fields without changing formulas; replace misleading warning with article-first bounded details and explicit loading prerequisite. Retry sync after load failure/cancel; preserve refresh retry after calculation failure. Align export reasons, disable initial buyout export and guard API.
- [x] Run domain/API/frontend tests, full pytest, JS syntax and five production browser scripts: expected PASS. Run design static audit, documenting existing out-of-scope false positives separately.
- [ ] Commit, record validation, perform one fresh whole-branch review, fix Important/Critical through RED→GREEN. Publish new PR, check exact-head CI including Windows; no merge.

Local implementation and fresh review complete: 2079 full tests, 41 targeted tests, five browser scripts and nine JS checks passed. Both review findings were reproduced and corrected in one pass. Publication and exact-head CI are recorded in the PR after this local plan revision.

Live account data is not available. Public official docs redirect to an inaccessible destination. This PR cannot certify classification of every actual Ozon advertising service or compare against the user's account totals. Screenshot periods differ (September vs October).
