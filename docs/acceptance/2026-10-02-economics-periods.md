# Economics periods, weekly charts and historical customer prices

## Result and scope

Economics uses a selected inclusive interval within loaded order history, including
the loaded part of the current week. The same interval controls route quantities,
advertising DRR, charts and XLSX. Day/week charts use quantity-weighted order means;
partial ISO weeks are clipped to the selection. Article separators are stronger,
and editing a lower article's planned DRR preserves focus and both table/window
scroll positions, including scrolling while a response is pending.

Plan/Flow demand windows and allocations retain their original completed-week
semantics. Economics valuations still use current snapshot prices, rates and
tariffs; they are not an Ozon payout ledger. Unknown price evidence stays unknown.

## Historical customer-price recovery

FBO list data can omit the customer price. Matching posting details supply an
explicit historical customer price through `/v2/posting/fbo/get`; FBS uses
`/v3/posting/fbs/get`. Match the posting and unique financial SKU, validate RUB and
reject malformed or ambiguous evidence. Never substitute current catalogue prices,
seller payouts or another SKU's price. Source contracts reference the official
[Ozon FBO customer-price discussion](https://dev.ozon.ru/community/2006-Pole-customer-price-v-otpravleniiakh-v-fbo/).

Production source sync commits usable orders/stocks before optional detail requests.
A paced background worker supplies separate immutable price evidence, prioritizes
visible SKUs and refreshes pending charts. Finalized numeric prices are reused from
a strict account-scoped hash cache, including after restart. Raw posting identifiers
remain process-local. New source/account generations discard stale results; denied
endpoints and repeated transient failures stop repeated requests within the job.
Only older deferred history requests a resumable historical sweep.

## Regression and browser evidence

The full local Python suite passes: **1914 tests**, with one existing Starlette
deprecation warning. New regressions cover selected route reconciliation, current
week isolation, weighted weekly means, advertising clipping, invalid intervals,
cache migration/restart, duplicate and malformed prices, permission circuits,
stale-source/account discard, background synchronization and persistence failures.

All three production browser checks pass: Economics periods, Economics advertising
and Plan. The new check uses the real loopback API and synthetic order evidence:
selected quantities, daily/week tooltips, XLSX dates/quantity, period reset, lower
article focus, nested scroll, delayed responses, automatic price refresh and a
390px viewport. Existing advertising and Plan interactions pass without JavaScript
errors or external requests. Screenshots were inspected. All eight runtime JS
syntax checks and `git diff --check` pass.

## Review and delivery limits

One independent whole-change review identified synchronous detail-fetch latency,
duplicate-SKU price overwrite and repeated denied requests. All three were fixed
with regressions in one correction pass. The stale completed-week UX description
was updated. The premium static audit reports 30 action-binding heuristics versus
29 on the base; the additional period-reset button is bound and exercised in the
browser. This is not a clean static-audit claim.

No live Ozon account was accessed. API availability and missing external evidence
cannot be proven by synthetic tests; initial historical recovery can take time,
while orders and stocks remain usable. Existing installations need an Ozon refresh
and a new calculation to bind the new source evidence. Published-head Python,
browser and Windows portable CI must pass before handoff; the PR remains unmerged.
