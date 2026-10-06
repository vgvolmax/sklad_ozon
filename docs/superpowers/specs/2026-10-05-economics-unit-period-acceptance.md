# Economics unit/period acceptance

Approved scope: `2026-10-05-economics-unit-period-design.md`. PR #206 remains open.

| Cases | Evidence |
|---|---|
| A01 | `test_period_profit.py`: manual 12000/5900 result; identical store expenses. |
| A02, A26 | `economics_buyouts_smoke`: local mode/progress/cancel, stable card DOM/draft/focus/cluster, errors and retry. |
| A03 | New FILES-only unit upload and API catalog without cluster/orders; explicit routes, current/target price, no history panel; real browser. |
| A04, A07, A27 | `test_pricing.py`: absent current price, tier boundaries, universal route target, exact currency grid, zero cost and ROI. |
| A05, A06 | Own loaded-history fallback has source/dates; missing/ambiguous tariffs stay unknown with route diagnostics. |
| A08–A12 | `test_pricing.py`, `test_workspace.py` and fallback browser: real/individual plan zero, absent versus incomplete report, unchanged before-ad basis. |
| A13–A15 | `test_period_profit.py`/period API: all store advertising including SKU without orders; SKU storage is common, modeled services are excluded. Uploaded ad files are not an expense input to the aggregate. |
| A16–A18 | `test_finance.py` and `test_period_profit.py`: duplicate pages, conflict/cursor rejection, one-unit return, signed negative quantity, unknown return. |
| A19 | Canonical daily net demand includes in-progress without origin and fulfilled units, excludes cancelled units; fulfilled-only facts stay unchanged. |
| A20 | Period API/XLSX and browser filter: store totals/expenses unchanged; selected contribution separate. |
| A21 | Old buyout SKU with complete private inputs enters profit and coverage while public API unit catalog and immutable Plan remain scoped. |
| A22–A24 | Empty quantities with known expenses, missing versus known-zero finance, upload priority, transient explicit cost edits, private snapshot evidence. |
| A25 | Account lock/change, stale analysis, overlapping periods/responses and export invalidation: API and production browsers. |
| A28, A29 | Focus browser exports beyond 12 displayed rows; duplicate articles retain separate SKU rows/DRR/cost inputs. |
| A30 | All five production browser scripts; native keyboard/clipboard actions, contained scrolling, narrow layout and 200% zoom. |

Full-suite and browser command outputs are recorded with the implementation task ledger and PR CI. The static premium audit detects 32 existing `affordance.actionless-button` items (base: 36); the detector does not resolve runtime bindings. Actual actions are checked in production browser scenarios. This is not a clean static-audit claim.

Finance reads use the existing current Seller adapter and synthetic transport tests. A live seller-account run has not been performed; unknown service types remain visible and make the result partial. No assertion of exact Seller settlement reconciliation or future SPP/demand behavior is made.

## Final review and follow-up verification

One fresh-context review found three Important issues. Each was reproduced by a failing regression before its fix:

| Finding | Regression and correction |
|---|---|
| FILES discarded orders without an assigned origin and falsely certified rejected/undated quantities | `test_files_order_quantity_preserves_originless_orders_and_reports_gaps`: net orders retain blank origins; rejected numbers, undated orders and unknown statuses invalidate the private quantity-completeness evidence. Fulfilled route weights are unchanged. |
| Retained totals acquired newly selected dates/mode after a failed refresh | `test_retained_period_report_keeps_its_mode_and_dates_on_failure_loading_and_cancel`, production buyout browser: controls describe the request; retained totals keep their actual dates/mode and an explicit previous-calculation notice. Export remains disabled. The period browser checks that notice removal preserves SKU-edit scroll position. |
| Repeated full tariff scans and unused target searches blocked the API | `test_catalog_pricing_on_9000_tariff_rows_stays_within_interactive_budget`: 100 distinct SKU × 10 routes against 9,000 tariff rows improved from 25.90s to 1.67s locally (5s regression budget). A request-local route/volume index preserves canonical missing/ambiguous/tier handling and source rows; equivalent results are reused. `test_pricing_does_not_block_other_async_requests` proves the heavy calculation no longer blocks the application event loop. |

The initially deferred Minor in origin/destination group target prices was fixed on 2026-10-06. Group prices now use the same universal tariff-grid solver as the visible SKU price; an individually feasible maximum is not treated as sufficient across tariff jumps.

Review boundaries and decisions:

- Live Seller compatibility remains a user-test boundary: synthetic transport and normalized schema fixtures verify the existing adapter. Unexpected live expense schemas can remain unknown and make the total partial.
- Windows portable and exact-published-head CI are publication gates outside the read-only review. Their final evidence belongs to PR #206; passing local tests alone does not complete these gates.

## Follow-up calculation audit fixes (2026-10-06)

| Reproduced defect | Regression and correction |
|---|---|
| Orders for removed SKU disappeared with current-catalog Plan filtering; 35 units became a falsely complete 26 | `test_removed_sku_orders_are_in_store_total_without_reactivating_plan`: private whole-store quantities and fulfilled routes retain nine historical units. Complete uploaded unit inputs yield 23800 before common expenses; missing inputs preserve 9 uncovered units. No finance row is required; Plan/public SKU cards stay current-catalog-only; filtered period XLSX retains the historical SKU. |
| A zero-sale commission correction inherited three original posting units; a delivery-only correction made existing buyouts unknown | `test_zero_sale_adjustments_do_not_create_or_erase_buyouts`: service adjustments contribute zero units, existing three-unit profit remains 450. Explicit compensated free purchases still count; missing sale amount/price and ambiguous free settlements remain unknown rather than inventing original posting units. |
| Broad words in fee names falsely established modeled expense coverage | `test_fee_scope_does_not_hide_unmodeled_expenses`: 18 signed scope cases in both modes. Known inbound delivery expense/credit changes profit 450 to 350/550; unknown subscription refunds and generic commission/delivery/return/placement names stay visible and partial; recognized customer-route services remain excluded once. Classification uses recognized whole names/descriptions rather than generic substrings. |
| A service group target ignored another route's higher tariff after crossing a price tier | `test_group_target_rechecks_all_routes_at_the_proposed_price`: both group roles now return 2418.61 instead of the unsafe 162.80; missing higher-tier coverage gives unknown. The existing 9000-row pricing scale gate protects request responsiveness. |

The fee scope cases are synthetic supported-schema fixtures, not a claim that every live Seller type is mapped. A new unrecognized type remains partial and retains its amount/description for inspection.

One fresh final review independently passed 65 focused tests and found two additional Important edge cases, with no Critical or Minor findings. Both were reproduced before correction:

- `test_missing_sale_amount_and_seller_price_keep_buyouts_unknown`: absent sale amount with absent or explicitly zero seller price stays unknown/partial instead of certifying zero buyouts. Service corrections and compensated-free purchases retain their established behavior.
- `test_historical_quantity_only_sku_remains_filterable_and_exportable`: a removed SKU with nine in-progress orders, or nine finance-only units, remains searchable, selectable by the incomplete filter and exportable without uploaded pricing or fulfilled route evidence. Its known quantity stays uncovered; Plan/public cards and immutable snapshots remain scoped.

Local verification after the final code fixes: 2069 pytest cases passed (one existing Starlette deprecation warning), 165 focused regressions passed, all five production browser scripts passed again, 9 JavaScript syntax checks passed, and the 9000-row scale gate passed. Exact published-head CI including Windows remains the publication gate; the resulting head and job outcomes are recorded in PR #206.
