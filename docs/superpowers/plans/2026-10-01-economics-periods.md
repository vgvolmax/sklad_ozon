# Economics: selected period, weekly history and stable edits

## Verdict and impact

READY with a bounded Economics-only evidence addition. Use the loaded order
calendar, including its current partial week, without changing Plan/Flow demand
windows or allocations. Preserve immutable snapshots and current-rate financial
modeling. Missing historical customer prices must be recovered from verified
Ozon endpoints, never inferred from catalog prices or payouts.

## Technical design

- Bind dated fulfilled route quantities and immutable route valuations to the
  analysis. Validate inclusive calculation dates against observation coverage.
- Use one selected interval for workspace, advertising DRR, charts and XLSX.
  Default to all loaded observations. Advertising uses only uploaded days in
  the interval and the same all-order revenue days.
- Aggregate charts on the server by day or ISO week (Monday–Sunday). Clip edge
  weeks to the selected interval; weight averages by priced units. Keep missing
  values and price coverage visible.
- Restore the currently focused Economics editor and its viewport position
  across each redraw. Preserve expanded articles and charts. Add distinct
  full-width article separators.

## Implementation order

1. Add failing regression tests for date selection, route reconciliation,
   weighted weeks, advertising clipping and API validation.
2. Add server-only period evidence, calculation selection and export metadata.
3. Add period controls, daily/weekly chart requests and stable editor redraws.
4. Investigate API customer-price omissions; add verified recovery and cache
   migration with adapter/runtime regressions if the endpoint is confirmed.
5. Verify production browser behavior, full suite, independent review and CI;
   publish a new PR without merging.

## Review correction

Optional per-posting prices must not block source synchronization at the shared
transport's 1.1-second pacing. Production sync collects process-local price requests
and commits usable demand/stock first. A background worker publishes separate,
immutable price evidence linked to that source; charts refresh pending visible
SKUs without changing the analysis or operational plans. Valid finalized prices
are reused through a strict account-scoped hash cache. Deferred prices older than
the normal overlap keep the endpoint price version behind the current version,
so a later smart refresh can resume historical recovery without repeating known
price requests. Recent pending prices remain in the normal overlap. Permission/method
failures open a per-endpoint circuit; three consecutive transient failures stop
that endpoint for the job. Duplicate product SKUs cannot overwrite invalid prices.

## Verification

Selected-route quantities must reconcile in both cluster cuts. Current-week
Economics routes must remain absent from the original completed-week Plan/Flow
snapshot. Weekly means must equal direct unit-weighted order means. Reject
malformed, reversed and out-of-history intervals. Export must report the same
interval/quantity/DRR as the screen. Browser checks cover a lower article's DRR
edit, asynchronous responses, period reset, weekly popup, narrow viewport and
unchanged immutable analysis. Run the full Python suite, production Economics
and Plan browser checks, JS syntax checks and Windows CI.
