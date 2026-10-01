# Economics advertising acceptance

Follow-up rule: [daily-panel acceptance](2026-10-01-economics-daily-panels.md)
supersedes the initial `n/a` calculation behavior described below: real DRR
keeps its unknown source label while the Economics model explicitly applies 0%.

## User behavior

Economics accepts optional batches of daily Ozon product-promotion XLSX reports.
SKU is the join key; articles remain labels. `Реальный` is read-only and is either
uploaded daily expense / all-order seller revenue over exactly those expense
dates, or `n/a` with a reason. Planned DRR independently drives target pricing.

Current profit, margin, ROI and shortfall never fall back to an old manual DRR
or zero. No report means unknown expense. Explicit zero expense with positive
ordered revenue means 0%; rates above 100% are valid. All order lifecycle states,
including cancelled orders, and FBO/FBS contribute to the denominator.

## Boundaries and persistence

The feature is supplemental Economics evidence. Demand, Need, Plan, Flow,
source-mode selection and Data uploads keep their existing contracts. Uploading
ads neither recalculates nor invalidates Plan. All-order aggregates are appended
to the server-owned AnalysisSnapshot and excluded from its public wire payload.

`data/advertising.json` schema 1 stores only normalized campaign/SKU/day expense
and file labels. Project stays schema v5; original XLSX files are not retained.
Campaign-period reimports replace the overlapping dates; identical costs are
idempotent. Different campaigns add expense; revenue dates are counted once.
The store uses the existing project persistence lock and atomic fsync/replace.

## Evidence quality and input limits

Only complete daily product reports with an expense total are accepted. Totals
outside the maximum cent-rounding drift reject the file. Small vendor rounding
differences produce an explicit message and retain per-day expense values.
Malformed dimensions are recovered; worksheet cells are bounded while reading.
SKU/day duplicates, negative/missing expense and out-of-period dates reject the
file. Unknown catalog SKU are listed and not stored. Raw percentage columns and
attributed sales are never calculation inputs.

The batch limit is 20 files / 16 MiB per file / 64 MiB per request. Valid files
in a mixed batch can succeed while invalid files retain per-file retry feedback.

## Failure ownership and recovery

Snapshot and cost/advertising fingerprints guard upload and export races. Failed
writes preserve the previous directory and show a retryable error. The queue
survives redraws/navigation; completed files can be cleared without removing
saved campaigns. Import/delete serialize with scenario changes, costs and export.
Deletion uses shared AppDialog confirmation and recalculates Economics.

Missing/rejected history, missing prices, dates outside order coverage or a zero
revenue denominator yield `n/a`. API history retains its completed-week window:
a report extending beyond that window stays unknown until order coverage is
updated to include the report dates. Only uploaded campaigns contribute expense;
the application cannot infer omitted campaigns.

## Validation

- Full Python suite: 1805 passed (one pre-existing Starlette deprecation warning).
- Independent read-only review: no remaining blocking findings; 68 targeted tests.
- Production Economics UI + real loopback API: batch/partial error, save-error
  retry, navigation, duplicate, correction, multiple campaigns, Excel export
  independent of filters, confirmation cancellation/deletion and narrow layout.
- Existing Plan browser smoke passes. Both browser runs have zero JS errors and
  zero external requests. Screenshots are generated as CI artifacts.
- JavaScript syntax and `git diff --check` pass.
- Premium static audit reports 29 actionless-button findings versus 27 on the
  baseline. The two added findings are template/delegated-binding false positives
  in advertising markup: file removal and campaign deletion are bound in
  `bindAdvertising` and exercised by the browser run. Existing baseline findings
  are unchanged; no claim of a clean static-audit exit is made.
- CI now runs the real Economics browser acceptance alongside Plan and the
  existing Windows portable smoke. Original customer uploads are excluded.
