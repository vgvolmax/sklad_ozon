# Economics daily panels and explicit zero-DRR assumption

## Verdict

The change is bounded to the Economics workspace. Advertising still joins by
canonical SKU; the matched product list makes the result inspectable. Unknown
real DRR keeps `n/a` while current calculations use an explicit zero assumption.
Commission displays both percent and rubles per unit. Product panels compare
daily SPP and ordered units across the complete loaded order period.

## Change impact

Demand/Need/Flow, route economics, shipment calculations and source-mode ownership
retain their existing math. Economics scenarios/exports consume applied DRR
without changing the immutable snapshot. No database, dependency or chart
framework is added. Project schema v5 and advertising schema 1 stay unchanged;
source-cache schema 2 accepts an optional buyer price and old caches load with
unknown buyer price. Updating order history supplies new evidence.

## Technical design

Adapters join buyer amounts by SKU, not financial row position or seller article;
non-RUB/invalid amounts stay unknown and do not reject demand records. API
customer-price money/scalar fields and legacy financial `client_price` are read.
SPP uses explicit historical `seller_price` when present, otherwise legacy
product `price`, validating base currency as well. This new SPP-only base does
not change existing route/revenue price normalization. Current catalog prices
are not used to reconstruct historical ceiling prices.
File price headers are per unit; a paid amount is the whole row amount.

Server-only immutable daily aggregates use accepted business dates, all lifecycle
states, and all channels. Daily SPP is `(Σ seller×qty − Σ buyer×qty) / Σ seller×qty`.
Any missing/invalid pair leaves SPP unknown for that day, preserving quantities.
Empty days become zero orders only with complete coverage. Values outside the
declared history period are excluded. Original records/prices are not exposed.

The current-snapshot endpoint accepts 1–100 known SKU and rejects stale evidence.
The browser requests only visible panels and caches by snapshot, preserving
expansion across redraws. SVG charts share calendar positions; observed SPP
min/max owns the vertical scale, constant values stay finite and gaps break lines.
Hover/focus/keyboard gives one popup for both charts, inside the table viewport.
Errors retain a local retry; they do not break the financial workspace.

## Implementation order

Meaningful failing tests preceded the backend evidence and chart geometry. Source
normalization/persistence and explicit DRR assumptions were implemented first,
then daily aggregates/API, panel rendering/interaction and export/doc updates.

## Verification

Production Economics browser with the real loopback API exercises DRR-zero,
absolute commission, compact/expanded charts, observed scale, exact hover values,
keyboard traversal/Escape, touch-day selection, delayed error/retry with focus
restoration, matched product identities, batch/retry/correction,
campaign addition/deletion, export and narrow-window popup containment. It reports
zero JavaScript errors and external requests. Full final-tree regression suite:
1846 passed, with one pre-existing Starlette deprecation warning. Existing Plan
browser smoke passes with zero JavaScript errors/external requests. Eight runtime
JavaScript modules pass syntax checks, and `git diff --check` passes. Independent
read-only review has no remaining critical or important findings. Repository CI,
including Windows portable smoke, is checked on the published PR before handoff.

A local bounded-series check with 500 SKU × 364 observed days returns a 100-SKU
batch in 0.51 seconds. Evidence is scanned per requested SKU; grouping once per
batch remains an optional optimization if real-history latency warrants it.

Premium strict audit retains the same 29 existing actionless-button findings as
the merged baseline, with no findings in the new daily-panel module. These are
static template/binding heuristics; this is not a clean-audit claim. New panel
actions are exercised through production browser behavior. Original customer
screenshots/XLSX and generated test artifacts are excluded from git.
