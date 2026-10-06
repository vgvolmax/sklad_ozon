# Economics calculation fixes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reported calculation defects in PR #206 without merging it.

**Architecture:** Keep whole-store order evidence privately alongside current-catalog Plan inputs. Separate realization quantities from posting service adjustments. Only exclude a finance fee from common expenses when its service scope is established as part of the unit model.

**Tech Stack:** Python, FastAPI, Decimal, pytest; existing portable Windows runtime.

**Spec:** `docs/superpowers/specs/2026-10-05-economics-unit-period-design.md`, sections 5, 9 and 10; user-approved audit fixes.

## Global Constraints

- Continue in `codex/economics-buyouts-expenses`, PR #206; do not merge or enable auto-merge.
- Keep Plan/Flow current-catalog scoping unchanged; private economics evidence is process-memory-only.
- Retain one before-ad unit basis and identical common expenses for orders and buyouts.
- Unknown quantities/services remain partial; known zero stays zero; refunds retain their signs.
- No additional runtime dependencies, persistence of raw finance data, or invented live Seller schema claims.

## Review Focus

- Removed SKU with no cost upload must still contribute known quantity and make profit partial (Task 1).
- Removed SKU without a finance snapshot must remain in whole-store orders (Task 1).
- Service adjustments and fully discounted purchases must remain distinguishable; ambiguous settlement evidence cannot invent units (Task 2).
- Unknown fee names containing commission/delivery/refund must not certify model coverage (Task 3).
- Known customer-route service refunds must remain excluded while known inbound costs and credits are deducted once (Task 3).

### Task 1: Preserve whole-store historical order evidence

**Files:** `backend/api.py`, `tests/api/test_economics_period_profit.py`.

**Interfaces:** Consumes retained `OzonSourceSnapshot.orders`; produces private order quantities and fulfilled-route economics for the period report, preserving public current-catalog SKU cards.

- [x] Add `test_removed_sku_orders_are_in_store_total_without_reactivating_plan` with 26 current + 9 removed units, unit profit 680, total 35 / 23800; parametrize missing removed cost to require partial 26 covered + 9 uncovered. No finance row is needed to discover the removed SKU.
- [x] Run the new test. Expected: FAIL, removed quantity is missing or zero.
- [x] Add optional private whole-store orders to `PreparedAnalysisInputs`; scope dates and completeness using that evidence; build private period route evidence with current uploaded pricing inputs. Include historical identities only in the period report.
- [x] Run period API and current-catalog Plan regressions. Expected: PASS; no removed SKU enters Plan/public Economics, export retains filtered historical quantities.
- [x] Commit and record passing tests.

### Task 2: Distinguish posting adjustments from purchases

**Files:** `backend/ozon/adapters/finance.py`, `tests/ozon/test_finance.py`.

**Interfaces:** Consumes monetary posting evidence; produces signed realized quantity or unknown, never original posting quantity for an adjustment.

- [x] Add `test_zero_sale_adjustments_do_not_create_or_erase_buyouts`: sale_amount=0, positive sale_price, retained seller_price, commission credit or delivery charge; quantity=0, existing purchase quantity remains 3 and contribution 450. Add ambiguity cases for absent sale_price and zero-price settlements without positive compensation.
- [x] Run new tests. Expected: FAIL, adjustment creates 3 units or unknown quantity.
- [x] Gate original-posting fallback on positive sale or explicit zero sale_price plus positive compensated settlement. Positive sale_price with zero sale is a service-only quantity 0; absent evidence remains unknown.
- [x] Run all finance adapter tests, including fully discounted sale and partial return. Expected: PASS.
- [x] Commit and record passing tests.

### Task 3: Classify modeled fees by service scope

**Files:** `backend/ozon/adapters/finance.py`, optional focused classification module, `tests/ozon/test_finance.py`, acceptance documentation.

**Interfaces:** Consumes finance type name and description; produces expense category used by `expense_role` and the unchanged signed common-expense ledger.

- [x] Add `test_fee_scope_does_not_hide_unmodeled_expenses`: unknown subscription refund stays unclassified/partial; known inbound delivery costs 100 against profit 450 yields 350; its credit yields 550. Unknown generic commission/delivery/return stay partial; recognized customer-route logistics/returns remain excluded.
- [x] Run new tests. Expected: FAIL, expense is marked modeled and total full.
- [x] Replace broad modeled-category substring matches with explicit service identification; recognize known additional inbound/service scopes and preserve conservative unknown handling. Retain known advertising/storage/crossdock/acceptance/penalty classifications and signs.
- [x] Run finance/period tests, full `python -m pytest -q`, and five production browser scripts. Expected: PASS.
- [x] Update acceptance evidence and commit.

### Task 4: Correct the previously reported group target price

**Files:** `backend/economics/workspace_pricing.py`, `tests/economics/test_workspace_pricing.py`, acceptance documentation.

**Interfaces:** Consumes the existing request-local `PricingCalculator`; produces the minimum feasible price for all routes in an origin/destination group, matching the visible SKU solver's tariff-grid semantics.

- [x] Add `test_group_target_rechecks_all_routes_at_the_proposed_price`, both group roles: fee 10 below 150 / 1000 above 150 plus another route fee 30; group target must be 2418.61 rather than 162.80. Missing expensive-tier coverage must give unknown rather than the individually feasible maximum.
- [x] Run the new tests. Expected: FAIL, group target equals 162.80.
- [x] Override each group's aggregate target using its own complete route set and planned DRR with the canonical cached solver. Preserve current profit weights and route-level targets.
- [x] Run pricing scale and full pytest. Expected: PASS, 9000-row regression remains within its 5-second budget.
- [x] Update acceptance evidence and commit.

## Final branch verification

- [x] Perform one fresh whole-branch review, including the fixes above. Address Important findings through RED→GREEN and green suite. Two Important edge cases were reproduced and fixed; final suite: 2069 passed; no Critical or Minor findings.
- [ ] Publish to the existing PR with a head lease and wait for exact-head CI including Windows. Expected: open PR, CI success, no merge.

Publication status and exact published-head CI outcomes are recorded in PR #206 after the branch update; they cannot be certified by a pre-publication local plan revision.
