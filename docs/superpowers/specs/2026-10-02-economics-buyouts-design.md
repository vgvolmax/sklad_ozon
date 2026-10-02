# Экономика по выкупам и известным расходам

## Product contract

Approved in conversation on 2026-10-02: add a second Economics mode in a new PR;
do not merge. This is a management calculation, not an accounting reconciliation.
Use the cost from the user's current uploaded unit economics, without a monthly
cost history or a new cost-persistence workflow. Current model remains available.

- Select an inclusive arbitrary period (up to 366 days per load) in Moscow time.
- Finance accrual dates own realized sales and returns. Do not substitute order
  acceptance dates or predicted buyout rates for actual realization.
- Read current Seller API `/v1/finance/accrual/types` and
  `/v1/finance/accrual/by-day`, with every page for every requested day.
- A sale can contain multiple units and multiple SKUs. Quantity is the absolute
  ratio of realized amount to buyer unit price when the ratio is a whole number.
  When absent/ambiguous, read the matching posting detail; a partial return must
  never silently inherit the original posting's full quantity.
- The authoritative signed `total_amount` is counted once. Nested commission,
  delivery, item and common fees provide the breakdown, not a second deduction.
  Unexplained signed differences remain visible as other accruals.
- Product profit uses known financial net proceeds minus uploaded cost times
  signed realized quantity. Unknown quantity/cost makes that product partial.
- General expenses have a store-wide scope. SKU search/filters alter the selected
  product subtotal only, never assign the whole store's expenses to that subset.
- Advertising inside finance is counted once. Existing advertising uploads stay
  available to the order model; they are not added a second time to financial
  accruals. Show finance advertising explicitly in the expense breakdown.
- Show gross seller-price revenue, purchased/returned units, COGS, product profit,
  common expenses/adjustments and profit after known expenses. Taxes outside Ozon
  are not called actual taxes or silently estimated in this mode.
- Include finance-only/old SKUs; missing current uploaded costs remain explicit.
- Export the filtered product rows and separate store-wide period summary and
  expenses sheets. Spreadsheet-looking names/identifiers remain literal text.
- No cent-perfect reconciliation is a prerequisite for viewing/exporting results.

## Architecture and security

Keep a bounded, normalized, immutable finance snapshot in backend memory, scoped
to credential context. Discard raw posting IDs after normalization (store digests
only); discard customer PII. Do not save raw finance, credentials, or cost history.
The currently uploaded product-cost input is backend-only analysis evidence,
captured before the existing manual cost-directory override, not a new persisted
field in Project JSON. Existing source ownership and planning math stay intact.

Finance adapters use the existing paced fixed-host client, safe read retry policy
and bounded pagination. A malformed page, cursor loop, failed day or account
change rejects the new load, preserving prior valid snapshots. Progress is NDJSON
using the application's existing parser. Report/export checks the current account
and latest analysis cost-input identity. Locked/replaced credentials cannot expose
the prior account's financial results.

## UI ownership

Use the existing Economics segmented buttons to select «По заказам» / «По выкупам».
The finance subview owns its date draft, load progress, search, filter, load-more,
error and download state; native dates and select are approved platform controls.
Reuse app panel/button/table/notice tokens and ru-RU formatters. Keep all controls
reachable at narrow widths and 200% zoom. A failed refresh preserves prior content
with its original period and persistent error. Superseded requests cannot replace
a newer view. No new navigation section or Data settings/import wizard.

## Verification

Test whole-unit/partial-return quantities, multiple SKUs, missing prices/costs,
credits, unknown fees, nested-versus-total amounts, inclusive periods, all pages,
failed-day atomicity, credential changes, changed uploaded costs, stale browser
responses, filtered exports, spreadsheet injection, and current-model regression.
Exercise the production browser UI with a synthetic Ozon transport and real
loopback FastAPI; live seller-account access is not available in this workspace.
