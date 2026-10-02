# Economics buyouts and known period expenses

Approved scope: a new PR from main `b71b3a8`, unmerged and without auto-merge.

## Delivered behavior

- Explicit `По заказам / По выкупам` selector preserves the existing order model.
- Current Seller `/v1/finance/accrual/types` and `/v1/finance/accrual/by-day`
  load every selected inclusive day and cursor page. Both modern `accrual_id` and
  previous top-level identifier are accepted. Deprecated transactions API is unused.
- Financial sale/return quantities use exact unit-price evidence or positive-sale
  posting details; unknown partial returns remain unknown. Free buyer-price sales
  compensated by Ozon still consume stock/cost. Seller price revenue is distinct
  from buyer revenue. Signed `total_amount` is authoritative; nested commission,
  bonus, delivery, advertising, new/unknown fees never cause double subtraction.
- Gross product profit uses current uploaded SKU cost before saved article overrides.
  No cost history/schema or raw financial report storage. The normalized in-memory
  source is account-scoped, bounded, and committed only after a complete valid load.
- Whole-store product profit, common expenses and known-period profit are separate.
  Advertising is displayed as an already-included expense. Uploaded order-model
  advertising is not added again. Unknown/new accruals remain visible adjustments.
- Filters affect only product subtotal and first Excel sheet; whole-store summary
  and expense sheets explain their scope. Empty selections, fee-only months,
  unknown costs, credits and late/failed refreshes have explicit behavior.
- A reused native date range, segmented selector, clipboard feedback, money format,
  load-more table, and natural-height panels preserve existing interaction owners.
  No runtime dependencies, remote side effects, or shipment/forecast changes.

## Verification

- `PYTHONPATH=/tmp/econ-audit-deps python -m pytest -q`: 1962 passed,
  one existing Starlette test-client deprecation warning.
- New domain/adapter/API regressions cover multiunits, partial returns, fully
  discounted sales, item/common advertising, credits, missing cost/quantity,
  dates, pagination, duplicate/conflicting accruals, malformed currency/sums,
  current-upload priority, private evidence, account/session changes, and XLSX
  filtering/literal strings/fee-only periods.
- The new browser test uses the production app, real ASGI/loopback API, real paced
  Seller client with synthetic transport, real current-cost upload and actual XLSX
  download. It covers totals, return reversal, search, whole-store scope, clipboard,
  error/retry, mode-switch races, native validation/focus, narrow and 200% layout.
  CI retains its desktop/narrow/zoom screenshots. No external browser requests.
- Existing Economics advertising, periods and focused-article browser scenarios
  pass. Plan browser smoke passes. All committed JS files pass Node syntax checks.
- Premium strict static audit ran: 35 literal-button findings (31 baseline plus
  calculation selector/new view). Its parser recognizes inline handlers only,
  while this application binds programmatic handlers. Added controls are exercised
  in the production browser; no claim that this static audit is clean.
- Shared visual tokens unchanged. The financial table's dedicated grid/overflow
  contract prevents its width from constraining sibling order-model forms.

Live Ozon financial responses were not available in this session. Wire-shape
fixtures follow the current published Seller API schema; no exact accounting
reconciliation is promised. Taxes and expenses outside Ozon are not included.
Final whole-branch review and exact-head CI results are recorded in the PR.

## Independent review corrections

The fresh whole-branch reviewer found two Important asynchronous-state defects.
Both were reproduced in the production browser before their corrections:

1. A same-FILES-analysis navigation render during export could retain another
   cabinet's cached total; export 409/423 also left that total visible. Outer
   renders now supersede pending generations and hide cached finance before
   revalidation, and credential errors in export clear the cached identity.
2. A successful accrual load followed by failed aggregation discarded the prior
   valid period. New finance identity is now staged and committed with its report.
   Ordinary failures preserve the previous report/export pair and offer aggregation
   retry without another Seller fetch, including when there was no prior report.

The reviewer found no Critical issues and confirmed accounting, cost priority,
quantity handling and scope separation. Live Seller response compatibility was
set aside because no live account response was available; the implementation is
verified against the published wire shape and synthetic transport, with the first
live account load remaining the production compatibility check.
