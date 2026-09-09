# Route Cost Index — Selected Network Design Amendment

**Date:** 2026-09-08  
**Status:** approved clarification; canonical for implementation  
**Parent design:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`  
**Scope:** Ozon customer-delivery tariff topology and its use inside selected-network coverage planning  
**Supersedes in parent design:** §3 tariff-input shorthand, §6.1–§6.2 route-topology wording, §8.4 exact-fee tie behavior, §11.2 tariff basis wording, PR-A wording in §14, and acceptance case 3 where those sections imply a volume-band-only topology or presentation-only normalized route score. All other parent-design semantics remain unchanged.

## 1. Raw source of truth

The planning tariff source is the normalized Ozon **customer-delivery** route matrix:

```text
origin_cluster
× destination_cluster
× price interval
× volume interval
→ logistics fee
```

This matrix is distinct from FBO cross-docking / seller supply-delivery tariffs. Cross-docking prices, discounts or temporary free supply programs MUST NOT enter this route topology or customer-delivery economics.

`TariffRow` remains the normalized raw contract. The application stores/carries the normalized matrix once; it MUST NOT expand it into a persisted `SKU × origin × destination` matrix.

## 2. Two different tariff-derived concepts

### 2.1 `RouteCostIndex` — structural pair evidence

`RouteCostIndex` describes one non-local pair:

```text
origin_cluster × destination_cluster
```

It is SKU-independent.

For every exact tariff class:

```text
TariffClass =
(
  min_volume_liters,
  max_volume_liters,
  min_price,
  max_price
)
```

calculate the median fee over **non-local** unambiguous route rows in that same class:

```text
class_median[c]
= median(fee(route,c) for non-local unambiguous routes in c)
```

Then for every unambiguous non-local route/class cell:

```text
normalized_ratio(route,c)
= fee(route,c) / class_median[c]
```

Finally:

```text
RouteCostIndex(route)
= median(normalized_ratio(route,c) across eligible classes observed for route)
```

LOCAL rows (`origin == destination`) are excluded from both the class baseline and RouteCostIndex outputs.

A class whose non-local median fee is zero or cannot be established from unambiguous rows is not eligible for index normalization.

### 2.2 Index quality

Every RouteCostIndex exposes at least:

```text
index_value
coverage_ratio
spread_iqr
observed_class_count
eligible_class_count
```

where:

```text
coverage_ratio = observed_class_count / eligible_class_count
```

and `spread_iqr` is the deterministic IQR of normalized class ratios using the implementation plan's fixed quartile definition.

Coverage/spread are evidence quality, not allocation gates unless a later approved design explicitly introduces thresholds.

No backend or UI hardcodes labels such as:

```text
< 0.8 = good
> 1.3 = bad
```

in this version.

## 3. `DirectRouteQuote` — concrete SKU route price

A concrete planning leg still requires the exact current fee for the SKU's product conditions:

```text
origin
× destination
× product volume
× product price when price is required by source rows
→ DirectRouteQuote
```

The direct quote is the monetary input to route economics. Missing/ambiguous/price-required evidence stays incomplete and is never replaced by RouteCostIndex.

Therefore:

```text
RouteCostIndex != SKU logistics fee
RouteCostIndex != allocation margin
RouteCostIndex != historical Flow share
```

## 4. Coverage Planner ranking

LOCAL remains the first product rule and is not ranked against external routes by RouteCostIndex.

For residual non-local coverage, a candidate origin must already satisfy selected-network, restrictions/capacity and complete DirectRouteQuote requirements.

Candidate ordering is:

```text
1. lower exact DirectRouteQuote fee
2. when exact fees are equal: known lower RouteCostIndex
3. when still tied: higher route-evidence confidence
4. stable origin cluster ID
```

A missing RouteCostIndex sorts after a known index only inside an exact direct-fee tie. A favorable RouteCostIndex never makes an incomplete DirectRouteQuote usable.

Historical Flow quantity/share never changes desired coverage quantity and is not a primary route-ranking input.

## 5. MAX_MARGIN boundary

`RouteCostIndex` stops at topology/coverage evidence.

After Coverage Planner creates desired legs, scarcity allocation uses the exact direct/local route economics of those legs under the existing MAX_MARGIN policy. Numeric RouteCostIndex MUST NOT be an allocation sort key or substitute for margin/profit/ROI.

## 6. PlanningBasis scale boundary

The immutable downstream planning basis carries, once:

- normalized customer-delivery `TariffRow` matrix;
- pair-level `RouteCostIndex` rows;
- compact product price/cost/commission/volume inputs by SKU;
- physical `SKU × origin` feasibility/capacity;
- destination targets and confidence evidence;
- resolved seller stock;
- sparse historical route evidence.

It MUST NOT precompute/persist exact economics for every theoretical `SKU × origin × destination` combination.

A network-only `/api/replan` may perform exact direct tariff lookup and direct/local route economics **only for routes needed by the selected network**. This is downstream planning work and does not rerun demand, stockout, clean-route history, tariff ingestion or RouteCostIndex derivation.

## 7. Historical Flow % semantics

Whenever planned-route evidence displays or stores a historical `Flow %` for a concrete `SKU × origin × destination`, the percentage is destination-oriented:

```text
observed_destination_share
=
observed fulfilled quantity for (SKU, origin, destination)
/
observed fulfilled quantity for (SKU, destination) across all origins
```

This is exactly the semantic represented by `backend.analytics.flows.FulfillmentFlowCell.destination_share`.

Do **not** use `clean_routes.RouteDistributionCell.share` for this UI/planning evidence field: that share is origin-profile-oriented and answers a different question.

Clean history may still contribute route-confidence evidence, but the displayed factual Flow percentage uses the observed destination-oriented share unless a future UI explicitly labels another denominator.

Missing observed route evidence is `not observed` / `None`, not a fabricated zero-percent observation.

## 8. UI evidence taxonomy

For a non-local planned leg, keep four concepts separate:

```text
Historical Flow %   = what fulfillment history showed for this SKU/destination
RouteCostIndex      = structural relative cost of the route pair across tariff classes
Direct SKU tariff   = current exact monetary route fee for this SKU
Capacity            = physical SKU × origin restriction evidence
```

`RouteCostIndex = 1.00` means the route's median normalized class cost equals the median reference. It is not a probability or percentage of demand.

LOCAL presentation omits external RouteCostIndex. Local execution economics may still have an exact local tariff if the source matrix provides one.

## 9. Required acceptance additions

Implementation must additionally prove:

1. **Class normalization:** price/volume effects are removed by normalizing only within identical tariff classes before pair aggregation.
2. **No SKU index matrix:** two SKUs reuse one RouteCostIndex pair collection and one normalized tariff matrix.
3. **Direct-fee primacy:** a route with better RouteCostIndex but higher exact SKU fee loses to the cheaper exact route.
4. **Index tie-break:** equal exact SKU fees are deterministically broken by lower known RouteCostIndex.
5. **No rescue:** missing/ambiguous direct tariff remains unusable even with a favorable RouteCostIndex.
6. **Scarcity isolation:** RouteCostIndex cannot change MAX_MARGIN scarcity order.
7. **Flow denominator:** displayed historical Flow % equals `FulfillmentFlowCell.destination_share`, never the origin-profile share from `RouteDistributionCell.share`.
8. **Cross-docking isolation:** seller supply/cross-docking tariffs do not enter RouteCostIndex or DirectRouteQuote.
9. **Bounded replan basis:** normalized tariff rows exist once; no all-SKU route-economics Cartesian product is persisted.

## 10. Precedence

For the tariff-topology points covered here, precedence is:

```text
2026-09-08 Route Cost Index amendment
→ 2026-09-08 Selected Supply Network & Coverage Planner design
→ earlier Product Completion / real-data specs
→ implementation plans
```

Outside this amendment's explicit scope, the parent selected-network design remains canonical unchanged.
