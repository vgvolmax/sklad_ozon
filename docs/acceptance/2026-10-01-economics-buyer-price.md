# Economics daily buyer prices and actual/plan bands

## Verdict

The new PR repairs bounded historical-price gaps and adds daily average buyer
prices alongside SPP and ordered units. Actual numbers appear above plan/targets
in teal/purple, with explicit labels. This change does not claim that an external
API always returns a complete historical price pair: unknowns retain evidence
coverage, and an incomplete order no longer hides an entire day's known means.

## Change impact

Demand/Need/Flow, route economics, advertising revenue denominator, shipments and
source-mode ownership retain their existing math. Only Economics daily SPP changes
from ratio of monetary totals to quantity-weighted mean of order percentages,
as requested. The immutable analysis still owns history; updated source evidence
requires a new analysis. No dependency, database, endpoint or schema increment.
Source-cache schema 2 accepts an optional per-channel price-normalization version.

## Technical design

Blank/null canonical buyer fields no longer mask matching financial prices.
Explicit seller bases can also be read from financial products matched by SKU;
malformed/non-RUB money stays unknown and demand rows remain intact. Duplicate
financial identities never produce a positional join. Existing route/revenue price
normalization is unchanged. No current catalogue price reconstructs past orders.

An old channel version requests the existing history_from..as_of once, then
successful normalization stamps version 1. The next refresh resumes the standard
28-day overlap. Missing prices alone do not force repeated full fetches. Failed
or incomplete channel handling and the existing bounded history backfill remain.

Daily means separately track valid SPP-pair units and valid buyer-price units.
The server exposes only aggregate means/counts and observed bounds. A partial day
retains known means and explains coverage; no-order/unknown-price gaps remain gaps.
Three SVG plots share dates but have independent SPP and RUB line scales. Hover,
touch, arrows/Home/End/Escape show daily means and coverage in a bounded popup.
Actual/plan cells are labeled and stacked; necessary price is directly under
seller price. Below-target status remains explicit text instead of a third metric
color. Actual financial results remain the pre-existing model, not Ozon payouts.

## Implementation order

Calculation/adapter and cache-migration regression tests failed first, then passed.
Geometry tests and production-browser actual/plan assertions failed before UI
implementation. Backend means/cache changes shipped in an independent commit,
followed by presentation, synchronized hover and contract/documentation updates.

## Verification

Full local suite: 1864 passed, with the existing Starlette deprecation warning.
Both production browser checks pass with zero JavaScript errors and external
requests. Economics uses a real loopback API and synthetic orders with varying
same-day prices and one missing buyer price: day mean SPP 60%, buyer price 200 RUB,
coverage 2/3 units; next day SPP 50%, buyer price 1450 RUB. It checks actual-above-plan
labels/colors, all three plots, error/retry/focus, keyboard/touch, advertising
batches/replacements/deletion, cost edits, exports and narrow-window popup bounds.
Screenshots were inspected. Runtime JavaScript syntax and git diff --check pass.
Independent review found no critical defects. Its partial-coverage accessibility
finding was fixed with a failing-then-passing production-browser assertion: keyboard
live announcements now include the same covered-unit counts as the visual popup.
Published-head CI, including Windows portable, is checked before handoff; the PR
is not merged by the agent.

Premium strict audit retains the baseline 29 template action-binding heuristic
findings, with none in the daily module; this is not a clean-audit claim. Customer
images and generated test artifacts are excluded from git.
