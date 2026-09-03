# PR2 — Daily Stockout Episodes & Precise Route Cleaning — Design Brief

**Date:** 2026-09-03  
**Status:** approved scope/design brief; implementation plan follows after PR1 contracts are merged  
**Parent design:** `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`  
**Depends on:** PR1 `DailyOrderFacts`

## 1. Purpose

Turn daily fulfillment facts into time-localized evidence of probable stockout/substitution while preserving routing-independent destination demand.

The operator must be able to answer:

- when local fulfillment for a specific `SKU × destination` deteriorated;
- whether destination demand broadly remained present;
- which external origins replaced local fulfillment;
- what date interval is plausibly contaminated routing evidence;
- which route evidence should be excluded from the clean routing profile.

PR2 does not calculate ₽ loss and does not redesign the frontend.

## 2. Detection identity

All primary detection occurs at:

```text
SKU × destination_cluster
```

Never detect stockout only from cluster-wide mix. Cluster-wide signals are presentation aggregations of SKU-level evidence because product-mix changes can otherwise create false locality shifts.

## 3. Evidence series

From PR1 daily fulfillment/demand build backend series per `SKU × destination × day`:

```text
destination demand qty
local fulfilled qty
external fulfilled qty
local share
external share
external origin shares
```

Use a 7-day rolling view for stockout/substitution evidence so one-day route noise does not create an episode by itself.

Daily raw values remain available to backend reasoning; UI presentation contracts are deferred to PR3.

## 4. Historical evidence semantics

Preserve the intent of the existing strong stockout thresholds:

- prior local share is high;
- local share drops materially;
- one or more external origins materially increase replacement share;
- fulfilled/destination volume is large enough to be meaningful;
- destination demand is retained enough that the shift looks like fulfillment substitution rather than disappearance of demand.

The existing weekly policy is the compatibility baseline:

```text
prior local share >= 60%
local share drop >= 30 p.p.
external replacement rise >= 20 p.p.
fulfilled weekly quantity >= 10
demand retention >= 60%
```

PR2 may adapt how these thresholds are evaluated over rolling daily windows, but must not silently weaken the business meaning. Any changed threshold/window formula must be explicit in the PR2 implementation plan and tests.

## 5. Availability corroboration

Current availability and `days_without_stock` may strengthen or weaken displayed confidence.

They are not historical inventory truth.

A strong historical route-shift episode can remain cleaning-eligible without a matching current `days_without_stock` value. A contradictory current snapshot does not automatically restore historically contaminated routing.

## 6. Episode contract

PR2 must produce an immutable backend episode entity equivalent to:

```text
sku
destination_cluster_id
start_date
end_date
baseline_local_share
observed_local_share_min / representative_local_share
destination_demand_retention
replacement_origins[]
historical_evidence_strength
availability_corroboration
confidence
route_cleaning_eligible
reason_codes
```

Each replacement origin must carry enough evidence to explain share before/after or equivalent rolling-window change.

Exact dataclass names belong to the implementation plan after PR1 is merged.

## 7. Episode boundaries

Episodes must be date ranges, not isolated technical flags.

Adjacent qualifying days/windows for the same `SKU × destination` should be merged into one coherent episode unless a return to normal local fulfillment clearly separates them.

The implementation plan must use deterministic merging rules and deterministic ordering.

## 8. Route cleaning

PR2 makes route cleaning more precise than whole-period interpretation.

For a cleaning-eligible episode:

- fulfillment routing evidence inside the contaminated episode may be excluded from clean routing;
- destination demand in those dates remains destination demand;
- clean routing can fall back to observed routing when exclusion leaves insufficient clean evidence, preserving existing fail-safe behavior;
- excluded evidence remains auditable with SKU, date/period, origin, destination, quantity and stockout confidence.

Do not remove destination demand solely because an episode exists.

## 9. Current-week handling

PR1 intentionally retains current-week daily facts while existing weekly analytics exclude the incomplete week.

PR2 may use current-week daily facts for recent operational evidence only if the implementation plan explicitly distinguishes partial-window confidence from completed historical evidence. A partial current week must not be treated as a completed weekly baseline.

## 10. Compatibility with existing weekly signals

During PR2:

- existing `StockoutSignal` behavior remains covered by regression tests;
- new daily episodes are additive until tests demonstrate a deliberate migration path;
- do not delete the weekly detector simply to avoid reconciliation work;
- recommendation distortion logic must not silently change because daily episodes were introduced.

## 11. Required proofs

At minimum the PR2 implementation plan must include deterministic scenarios for:

1. stable high local share → no episode;
2. one-day external spike → no episode after rolling smoothing;
3. sustained local collapse + donor rise + retained destination demand → episode;
4. local collapse + demand collapse → no strong substitution episode or materially reduced confidence;
5. replacement shifts from one donor to another inside the same destination episode;
6. same aggregate cluster pattern caused only by SKU mix → no false SKU-level episode;
7. availability corroborates episode → confidence can increase;
8. current availability contradicts historical episode → historical cleaning eligibility is not automatically erased;
9. route cleaning removes contaminated fulfillment evidence but leaves demand unchanged;
10. deterministic episode start/end and merge behavior.

## 12. Snapshot boundary

PR2 may add compact stockout episode entities to the internal analysis result for PR3.

Do not send an unbounded per-order dataset to the browser.

PR3 is responsible for final UI-ready time-series/episode presentation aggregates.

## 13. Out of scope

PR2 does not implement:

- extra logistics ₽ by episode;
- profit loss ₽ by episode;
- margin loss presentation;
- diagnostics aggregation;
- new Flow UI;
- latent lost-demand reconstruction;
- optimizer changes.

## 14. Merge gate

PR2 is mergeable only when:

- episodes are detected at `SKU × destination`;
- rolling daily evidence suppresses isolated one-day noise;
- replacement origins are explicit;
- destination demand is preserved;
- availability remains corroboration;
- episode route cleaning is auditable;
- existing weekly semantics remain regression-covered;
- no frontend business formula is added;
- full pytest and Windows portable smoke are green.
