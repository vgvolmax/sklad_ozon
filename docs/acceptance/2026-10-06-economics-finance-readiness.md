# Economics finance readiness — verification

Base: main `ff76e2d` after merged PR #206. Branch: `codex/economics-finance-readiness`.

## Confirmed defects

- The initial buyout report used all partial rows as “missing unit economics”, although the missing input was finance quantity. Complete unit inputs do not provide accepted buyout quantity.
- After a finance-load failure the retry button ran the period calculation instead of finance sync. Cancellation had the same incorrect retry destination.
- An XLSX of buyouts could be exported before any finance quantity was loaded.
- The coverage warning listed raw SKU IDs without separate reasons or bounded disclosure.

## Result

- Independent unit/quantity coverage is returned for the entire store; filters only limit product contribution rows.
- Before loading, the buyout panel names the required finance data and action, with the actual count of available unit models. Unloaded advertising says “Не загружена”.
- Incomplete unit and unknown quantity lists use articles and names. Duplicate articles retain distinct SKU identities; absent articles fall back to SKU. Lists are bounded and progressively disclosed.
- Retry repeats sync after finance failure/cancellation and calculation after calculation failure. Previous successful figures retain their mode/date and stale-state safeguards.
- UI/API block buyout export before finance loading. Partial loaded finance remains exportable with explicit quantity/unit reasons. XLSX uses the same separate coverage and article labels.
- Financial formulas, signed returns, store-wide advertising and subtraction of known expenses remain unchanged. Unclassified services explicitly qualify completeness, including advertising.

## Validation

- Baseline: 2069 pytest passed.
- New domain/API/executable JavaScript regressions observed RED before implementation: missing independent coverage, wrong retry sync count, initial buyout readiness, API export status 200 instead of 400, and XLSX reason classification.
- Full final suite: **2079 passed**, one existing Starlette/httpx deprecation warning; 41 targeted regressions passed.
- All nine JavaScript syntax checks and `git diff --check` passed.
- Five production browser scripts passed: Plan, advertising, periods, focus and buyouts. They cover explicit loading, errors, correct retry after cancellation/failure, account changes, stale replies, card DOM/input/focus, filtered XLSX contents, narrow layouts and 200% zoom.
- Local browser tests used an existing Chrome headless engine because the default Playwright shell was unavailable. GitHub CI remains the authoritative pinned-browser and portable Windows check for the published head; its result belongs in the PR.
- Premium static audit reported 33 `affordance.actionless-button` detections, compared with 32 on the base. The scanner cannot resolve attached handlers: 31 in untouched modules, an existing conditional mode/cancel template, and the newly conditional retry callback. The changed controls have executable/browser verification. No actionless coverage control was detected. The audit is not claimed as green.

## Independent review and corrections

One fresh reviewer found no mathematical or data-preservation defect. Cross-reason duplicate articles could lose SKU disambiguation; a covered sibling could also make a missing product ambiguous. Whole-store article ambiguity now drives both UI and XLSX. Tests reproduced both cases before the correction.

Export errors could inherit an earlier finance retry operation. This was corrected in the same fix pass: XLSX retry performs export, not another month of Seller finance reads. Both executable JavaScript and production browser regression verify it. The final full suite passed after these fixes; no deferred review finding remains. Actual-account advertising completeness remains outside verified evidence below.

## Live-account boundary

The screenshots show no successfully loaded finance snapshot in the app. They use September in the app and October in Ozon. A screenshot of “Экономика магазина” does not supply its underlying finance records to this app. No downloaded accrual XLSX or normalized live response was supplied; current public documentation redirects were inaccessible.

The code and synthetic integration confirm retrieval/subtraction of recognized advertising for identical dates in both modes. They do **not** certify that every real advertising type in this account is recognized or reconcile its totals against the cabinet. No fee names, quantities or account data were guessed. The next live check needs the accrual report for the same selected period, and any explicit finance-load error.

No merge or auto-merge is performed.
