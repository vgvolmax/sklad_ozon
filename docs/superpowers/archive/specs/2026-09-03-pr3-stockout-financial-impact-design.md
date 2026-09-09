# PR3 — Stockout Financial Impact & Presentation Aggregates — Design Brief

**Date:** 2026-09-03  
**Status:** approved scope/design brief; implementation plan follows after PR2 contracts are merged  
**Parent design:** `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`  
**Depends on:** PR1 daily facts + PR2 stockout episodes

## 1. Purpose

Quantify the modeled financial impact of external fulfillment and probable stockout/substitution episodes, then convert backend evidence into bounded presentation aggregates suitable for a real-scale UI.

The operator must be able to answer:

- how many units were fulfilled externally;
- what the current modeled route cost is;
- what a feasible local route would cost;
- how much extra logistics the observed routing implies;
- how much margin and profit are lost/gained versus local placement;
- how much of that effect belongs to a specific stockout episode;
- why a value cannot be calculated when economics is incomplete.

## 2. Canonical economics comparison

For each `SKU × origin × destination`, reuse the existing current-vs-local counterfactual semantics.

Current route:

```text
origin → destination
```

Local counterfactual:

```text
destination → destination
```

Hold non-route product assumptions constant and change only placement/route-dependent economics according to backend tariff and unit-economics contracts.

## 3. Three effects must remain distinct

Never collapse logistics, margin and profit into one ambiguous “loss” number.

Canonical values for a quantity basis `q`:

```text
extra_logistics_rub
  = (current_route_logistics_per_unit - local_logistics_per_unit) × q

margin_delta_pp
  = (local_margin_rate - current_margin_rate) × 100

profit_delta_per_unit
  = local_profit_per_unit - current_profit_per_unit

profit_loss_or_opportunity_rub
  = profit_delta_per_unit × q
```

Sign must be preserved. If local placement is economically worse, the values may be negative and the UI must say so rather than clamp to zero.

## 4. Historical interpretation

These are modeled comparisons using **current imported tariffs/settings** applied to **historical observed quantities**.

Do not describe them as historical invoice charges.

User-facing copy must make the time/economics basis clear, e.g.:

> Оценка по текущим тарифам и настройкам на фактическом объёме периода.

## 5. Quantity bases

Keep these quantity bases separate:

### 5.1 Observed-period route impact

Uses actual observed fulfilled route quantity in the analysis period.

Equivalent existing concept:

```text
observed_profit_opportunity_rub
```

This value remains an immutable audit-style period metric.

### 5.2 Episode impact

Uses only the quantity inside a PR2 stockout/substitution episode.

It answers:

> сколько денег стоило именно это вероятное замещение.

### 5.3 Clean evidence impact

If a presentation compares observed vs clean route evidence, the evidence-specific quantity must be separately labelled and must not overwrite the observed audit metric.

### 5.4 Forecast impact

A future forecast-horizon value is optional and out of PR3 unless the implementation plan introduces a separately named backend field with an explicit forecast quantity/share basis.

Never reuse an observed-period name for a forecast value.

## 6. Episode economics

For every PR2 episode, aggregate only external routes inside the episode.

Required episode-level values where complete:

```text
external_quantity
local_quantity
local_share / external_share
extra_logistics_rub
weighted_current_margin_rate
weighted_local_margin_rate
margin_delta_pp
profit_loss_or_opportunity_rub
```

Also retain donor-origin and SKU breakdowns so the operator can explain the total.

All multi-SKU weighted values must be computed in backend using quantity/value denominators, not averaged naively in frontend.

## 7. Incomplete economics

Fail closed.

If any required tariff/product economics/local feasibility component is missing for a presented aggregate, do not silently treat it as zero.

Return:

```text
complete = false
value = None
reason_codes = (...)
```

The implementation plan must decide whether a multi-route aggregate can expose a partial covered amount alongside coverage ratio. If added, partial and complete totals must be separately named; a partial amount must never masquerade as full impact.

## 8. Presentation aggregate goal

PR3 prepares bounded backend contracts for PR5 so frontend does not receive or aggregate raw route matrices.

The presentation layer should be able to render a selected destination/SKU without scanning all orders.

Expected concepts:

```text
DestinationImpactSummary
DestinationDailySeries
StockoutEpisodeView
EpisodeDonorBreakdown
EpisodeSkuBreakdown
RouteImpactView
```

Exact dataclass names are fixed in the PR3 implementation plan after PR2 merges.

## 9. Destination daily series

A destination time series must carry only bounded presentation fields needed for the locality timeline, equivalent to:

```text
day
destination_demand_qty
local_fulfilled_qty
external_fulfilled_qty
local_share
external_share
probable_stockout_episode_id / flags
```

Do not ship per-order details or buyer/shipment identifiers.

If economics by day is exposed, use backend-calculated fields and ensure incomplete values remain null/reasoned.

## 10. Episode view

Each episode presentation record should expose equivalent information:

```text
episode_id
sku or aggregate destination context
start_date
end_date
confidence
external_quantity
local_share_before
local_share_during
replacement_origin_count
extra_logistics_rub
margin_delta_pp
profit_loss_or_opportunity_rub
complete
reason_codes
```

A destination-level episode summary may combine multiple SKU-level episodes only through explicit backend aggregation.

## 11. Donor breakdown

For a selected episode/destination, expose donor origins ranked by external quantity or selected backend metric.

Each donor record must preserve:

```text
origin_cluster_id
destination_cluster_id
quantity
share_of_episode_external_qty
extra_logistics_rub or None
margin_delta_pp or None
profit impact or None
complete/reasons
```

## 12. SKU breakdown

For a selected donor route or episode, expose:

```text
sku
article
product_name
quantity
share
extra logistics
margin delta
profit impact
complete/reasons
```

Product identity comes from canonical snapshot identity mapping, not frontend guessing.

## 13. Observed vs clean semantics

Observed and clean are routing-evidence modes.

Switching between them must never change destination demand geography or destination demand quantity.

Where the clean route profile excludes substitution periods:

- observed route quantities remain the historical audit;
- clean routing shows the representative route mix after cleaning;
- episode impact remains tied to observed episode quantities;
- UI labels must not imply clean demand.

## 14. Required proofs

PR3 tests must prove at least:

1. a route with known current/local economics computes exact extra logistics, margin and profit effect;
2. episode quantity uses only dates inside the episode;
3. two donors aggregate to the exact episode total;
4. two SKUs aggregate using correct quantity/value weighting;
5. negative local benefit preserves sign;
6. missing tariff produces `None`/incomplete, not zero;
7. missing product economics produces incomplete state;
8. infeasible local placement produces incomplete counterfactual;
9. observed audit value remains observed even when clean evidence quantity differs;
10. presentation aggregates reconcile to their route/SKU components;
11. no raw buyer/order PII appears in the presentation contracts.

## 15. Performance/boundedness

PR3 aggregation should prepare only the data necessary for selected-context UI.

Avoid snapshot growth proportional to every possible cross-product of:

```text
all SKU × all origins × all destinations × all dates
```

Aggregate from actual observed identities and keep deterministic ordering.

## 16. Out of scope

PR3 does not:

- redesign diagnostics;
- fix unrelated tariff-source defects;
- redesign Flow frontend;
- create latent demand;
- change M1/M2/L or need;
- change optimizer behavior.

## 17. Merge gate

PR3 is mergeable only when:

- financial effects are backend-only;
- logistics/margin/profit remain distinct;
- observed and episode quantity bases are explicit;
- incomplete economics fails closed;
- negative effects preserve sign;
- episode/donor/SKU aggregates reconcile exactly;
- presentation contracts are bounded and PII-free;
- destination demand is never modified by economics;
- full pytest and Windows portable smoke are green.
