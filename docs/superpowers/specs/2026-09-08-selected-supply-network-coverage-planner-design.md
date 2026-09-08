# Selected Supply Network & Coverage Planner — Design

**Date:** 2026-09-08  
**Status:** approved design; written spec pending user review  
**Scope:** Product Completion planning layer after real-data PR5  
**Supersedes:** any earlier proposal to use observed/clean historical route shares as allocation weights for future supply placement; the `physical_ceiling` placement semantics in `2026-09-02-ozon-fbo-product-completion-design.md` where destination and placement cluster were assumed to be the same object  
**Does not supersede:** destination-demand semantics, demand estimate, stockout/clean-route analytics, current route-impact analytics, Safe/Calculated plan families, fixed `MAX_MARGIN` scarcity strategy, SCOZ-lite runtime architecture, existing Flow historical evidence semantics

## 1. Product problem

The current plan answers how much each `SKU × destination_cluster` needs, but an operator cannot practically create new FBO supply for every destination cluster where demand exists.

The operator instead chooses a limited **supply network**: the clusters where they are operationally willing to create new supply. The application must then preserve each destination's demand identity while deciding where the stock that serves that demand should physically be placed.

Example:

```text
Destination need:
Москва 500
Казань 100

Selected supply network:
Москва = selected
Казань = not selected

Physical supply plan may become:
Москва 600
  500 for Москва demand
  100 for Казань demand
```

The Kazan 100 never becomes Moscow demand. Moscow is only the planned physical origin that will serve Kazan demand.

This introduces a new explicit layer:

```text
Destination Need
→ Coverage Assignment
→ Coverage Legs
→ Seller Stock Allocation
→ Origin Supply Plan
```

The existing direct model `Destination Need → Supply Plan in the same cluster` is no longer sufficient.

## 2. Non-negotiable semantics

### 2.1 Destination owns demand

All existing real-data invariants remain unchanged:

- `destination_cluster` is where customer demand arose;
- `origin_cluster` is where stock is physically fulfilled/placed;
- physical dispatch from an origin never increases that origin's own demand;
- external fulfillment never erases destination demand;
- changing the selected supply network cannot change `DemandEstimate`, demand history, stockout episodes, route cleaning, or `calculated_need_qty`.

### 2.2 Historical route share is evidence, not a future placement weight

Observed and clean historical route shares are contaminated by historical availability: a route may have low share because the origin rarely had stock, not because Ozon considers that route poor.

Therefore future coverage assignment MUST NOT use formulas such as:

```text
selected_share = historical_share / sum(selected_historical_shares)
```

Historical observed/clean flows remain valuable for:

- historical Flow visualization;
- proving that a route has occurred;
- route/context explanation;
- stockout/substitution analysis;
- comparison of planned routing with historical behavior.

They do not determine future coverage quantities.

### 2.3 Route tariff is the primary route-ranking proxy

When destination demand must be served non-locally from the selected supply network, the primary deterministic ranking is the current imported Ozon logistics tariff for the route.

Interpretation:

> lower route tariff = more economically/logistically natural route among currently feasible selected origins.

This is a planning proxy, not a claim that the application reproduces Ozon's internal real-time routing engine.

Geographic distance is not used while a matching tariff exists.

### 2.4 Restrictions report is the physical source of truth

The Ozon warehouse restrictions report is the canonical source for whether a SKU can be placed into a cluster and for the available placement ceiling exposed by that report.

For every SKU, the effective network is:

```text
user-selected supply clusters
∩ clusters with at least one explicitly ALLOWED warehouse for that SKU
```

The user does not manually resolve warehouse restrictions SKU by SKU.

Unknown, conflicting, or missing restriction evidence is fail-closed for the affected placement and remains diagnosable.

## 3. End-state planning pipeline

```text
Observed Destination Demand
        ↓
Demand Estimate
        ↓
Calculated Need
        ↓
Destination Target
        ↓
Selected Supply Network
        ↓
Restrictions / Physical Feasibility
        +
Tariff Route Matrix
        ↓
Coverage Planner
        ↓
Desired Coverage Legs
        ↓
MAX_MARGIN Seller Stock Allocation
        ↓
Final Coverage Legs
        ↓
Origin Supply Plan roll-up
```

The planning pipeline is downstream-only from `Calculated Need`. A network change never feeds back into demand/routing history.

## 4. Destination target

### 4.1 Calculated Plan

```text
calculated_destination_target = calculated_need_qty
```

### 4.2 Safe Plan

```text
safe_destination_target = min(
    ozon_recommended_qty,
    calculated_need_qty
)
```

when both values are complete.

Physical feasibility is intentionally removed from the destination-target formula. Physical feasibility belongs to the selected **origin** that will hold stock, not to the destination that owns demand.

This supersedes the earlier Product Completion shorthand:

```text
safe_ceiling = min(ozon_recommended_qty, calculated_need_qty, physical_ceiling)
calculated_ceiling = min(calculated_need_qty, physical_ceiling)
```

where the same cluster was implicitly both destination and placement origin.

Unknown target inputs remain incomplete; they are never coerced to zero.

## 5. Selected Supply Network

### 5.1 User control

The user chooses only the set of clusters where new supply is operationally allowed for the current planning scenario.

Example:

```text
☑ Москва
☑ Санкт-Петербург
☐ Казань
☑ Екатеринбург
```

The user does not enter quantities per selected cluster. Quantities are always calculated by the backend.

Existing FBO stock and inbound at a destination are upstream need inputs and continue to reduce that destination's need even when the destination is not selected for new supply.

### 5.2 Draft vs applied network

Checkbox changes are **draft state** only.

They MUST NOT recalculate on every checkbox toggle.

After the first change, the UI shows that the visible plan still belongs to the previously applied network and enables the canonical action:

`Пересчитать план`

The new network becomes applied only after successful recalculation. On failure, the previous successful plan remains visible and applied.

### 5.3 Recalculation depth

The same user-facing action is used for both cases:

- horizon/inbound/source-data change → full analysis recalculation;
- selected-network-only change → downstream replan only.

The frontend must not duplicate formulas or decide planning quantities. It may only send the changed scenario/network inputs and render the backend result.

## 6. Tariff Route Matrix

### 6.1 Do not persist a route matrix per SKU

Route ranking is not modeled as one persisted `SKU × origin × destination` affinity matrix.

Ozon tariff rows are classified by route plus tariff conditions such as product volume band and, when present in the imported tariff source, price band.

Canonical reusable tariff identity:

```text
TariffClass × origin_cluster × destination_cluster
```

where `TariffClass` contains the imported tariff dimensions required for an unambiguous lookup, primarily product-volume interval and optional price interval when the source actually defines one.

A SKU maps to the matching tariff class using its current normalized product economics inputs. SKUs in the same class reuse the same route ordering.

### 6.2 No synthetic affinity is required for planning

Coverage planning sorts directly by matched route fee:

```text
logistics_fee ASC
```

A normalized `route_affinity`, for example `best_fee / route_fee`, may be exposed as a UI explanation metric, but it is not the decision source and must not introduce a second ranking formula.

### 6.3 Direct route lookup is separate from historical expected logistics

Existing `expected_logistics()` remains authoritative for historical/current origin-profile economics and Flow analysis. It uses an observed/clean route distribution and produces an expected weighted fee.

Coverage Planner needs a different operation: direct lookup for one candidate `origin → destination` under a tariff class.

The implementation must therefore introduce a pure direct-route quote/lookup contract rather than repurposing historical `expected_logistics()`.

A planned route with missing, ambiguous, or price-required tariff evidence is not silently ranked using a fabricated value.

## 7. Restrictions and cluster physical capacity

### 7.1 Eligibility

For `SKU × selected cluster`, placement is feasible only if at least one warehouse mapped to that cluster is explicitly `ALLOWED` for the SKU.

`PROHIBITED`, `UNKNOWN`, missing restriction rows, conflicting warehouse/cluster identity, or conflicting restriction states remain fail-closed under existing project safeguards.

### 7.2 Capacity source

The restrictions report is the only physical capacity source for this feature. No new capacity file or manually maintained capacity table is introduced.

The importer must preserve three distinct capacity states for an allowed warehouse row:

```text
FINITE(value)     # explicit numeric maximum
UNLIMITED         # source explicitly says "Без ограничений"
UNKNOWN           # blank/missing/unparseable-as-known capacity evidence
```

`None` must not ambiguously mean both `UNLIMITED` and `UNKNOWN` in the new planning contract. If the existing normalized record cannot distinguish them, the importer/domain contract must be extended before Coverage Planner consumes capacity.

### 7.3 Multiple warehouses inside one cluster

The current implementation uses the minimum explicit warehouse maximum when several warehouses in a cluster are allowed. That rule is no longer canonical for cluster planning.

The planning abstraction is a **cluster supply point**, while warehouse rows describe alternative receiving warehouses inside that cluster. Current Ozon guidance states that when several warehouses can accept products, Ozon may offer one of the available warehouses, and cluster-level recommended quantity can be placed on one warehouse or distributed across several.

This feature intentionally plans clusters, not multiple warehouse-level supply requests. Therefore it must not sum independent warehouse limits that are not guaranteed to be simultaneously usable.

Cluster capacity is derived as follows:

```text
eligible = explicitly ALLOWED warehouse rows for SKU × cluster

if eligible is empty:
    cluster placement is infeasible
elif any eligible capacity is UNKNOWN:
    cluster capacity is UNKNOWN unless another eligible warehouse alone proves a usable finite/unlimited ceiling
elif any eligible capacity is UNLIMITED:
    cluster capacity is UNLIMITED
else:
    cluster capacity = max(FINITE values among eligible warehouses)
```

Operationally, a cluster is usable when at least one allowed warehouse provides a known usable ceiling. Unknown capacity on one alternative warehouse does not invalidate another independently known allowed warehouse.

Rationale: the cluster plan must be achievable through at least one eligible receiving warehouse without assuming additive warehouse ceilings. A later warehouse-level planning feature may intentionally supersede this rule and model distribution across several warehouses.

## 8. Coverage Planner

### 8.1 Coverage leg identity

Coverage is represented atomically as:

```text
SKU × origin_cluster × destination_cluster
```

A leg always preserves both where the demand belongs and where the serving stock is planned to sit.

Canonical conceptual contract:

```text
CoverageLeg
  sku
  origin_cluster_id
  destination_cluster_id
  target_qty
  desired_qty
  final_allocated_qty
  coverage_type: LOCAL | ROUTE
  direct_route_fee
  tariff_class
  route_affinity?             # presentation only
  observed_route_evidence?    # informational only
  clean_route_evidence?       # informational only
  route_economics
  reason_codes
```

Exact field names may follow repository conventions, but the identity and separation are mandatory.

### 8.2 LOCAL first

If a destination is selected as a supply cluster and the SKU is physically feasible there, its own residual destination target is assigned locally first, up to the cluster's available physical capacity.

Example:

```text
Казань target = 50
Казань selected and feasible
→ Казань → Казань = 50 LOCAL
```

Local placement does not compete with a cheaper non-local tariff before local coverage is attempted.

### 8.3 Non-local route ranking

Residual demand is assigned only among selected, physically feasible origins with complete direct tariff evidence.

Within a destination, origins are ranked by:

1. lower direct route logistics fee;
2. better route-evidence confidence when fee is exactly equal;
3. stable origin cluster ID.

Historical share does not appear in this ranking.

### 8.4 Capacity-aware sequential fill

Affinity is a ranking, not a proportional split.

If Kazan residual target is 100 and routes are:

```text
Москва → Казань 47 ₽, capacity remaining 70
Питер  → Казань 52 ₽, capacity remaining 100
```

then desired coverage is:

```text
Москва → Казань 70
Питер  → Казань 30
```

not a normalized percentage split.

This avoids unnecessary micro-stock fragmentation across multiple origins.

### 8.5 Scarce-origin ordering across destinations

A greedy planner must not spend a scarce origin on a destination that has alternatives while stranding another destination that has only that origin.

After LOCAL assignment, residual destinations are therefore processed in this deterministic order:

1. fewer feasible selected origins first;
2. larger residual destination target first;
3. stable destination cluster ID.

Within each destination, candidate origins use the route ranking in §8.3.

This is intentionally a deterministic bounded heuristic, not a general LP/min-cost-flow solver.

### 8.6 Network uncovered quantity

If no feasible selected origin with complete route evidence can cover all residual target, the remainder becomes first-class:

```text
network_uncovered_qty
```

It is not silently assigned to an arbitrary cluster and is not converted to zero demand.

Reason families include at least:

- no selected feasible origin;
- tariff evidence unavailable/ambiguous for all candidate routes;
- origin physical capacity exhausted or unknown.

## 9. Seller Stock Allocation

Coverage Planner answers:

> where should stock ideally sit inside the selected network if enough seller stock exists?

It does **not** assume that enough seller stock exists.

After desired coverage legs are built, seller stock scarcity is handled by the existing fixed policy `MAX_MARGIN`, now at coverage-leg granularity.

The scarcity allocator must see `origin → destination` identity because different legs through the same origin can have different route economics.

Canonical separation:

```text
route tariff / coverage planner = placement preference
MAX_MARGIN allocator           = scarcity policy
```

When seller stock is insufficient, `MAX_MARGIN` may intentionally violate the desired route distribution. Historical route shares never override scarcity policy.

`stock_uncovered_qty` is distinct from `network_uncovered_qty`:

- `network_uncovered_qty`: selected network cannot physically/economically route the target;
- `stock_uncovered_qty`: network could cover it, but seller stock is insufficient.

## 10. Conservation invariants

For every `SKU × destination` before seller-stock scarcity:

```text
sum(desired coverage legs to destination)
+ network_uncovered_qty
= destination_target
```

After seller-stock allocation:

```text
sum(final allocated coverage legs to destination)
+ stock_uncovered_qty
+ network_uncovered_qty
= destination_target
```

For every `SKU × origin`:

```text
sum(desired coverage legs through origin)
<= origin physical capacity, when finite
```

For every SKU:

```text
sum(final allocated coverage legs)
<= seller available stock
```

Globally, coverage planning never changes demand quantities or destination identity.

## 11. Snapshot and replan boundary

### 11.1 Full analysis snapshot remains immutable

A successful full analysis still produces an immutable snapshot containing upstream demand, route history, stockout evidence, economics, feasibility and plan evidence.

### 11.2 Planning basis

The snapshot must expose a bounded backend-owned `planning_basis` sufficient for downstream replanning without re-importing source files or recomputing demand/stockout history.

Conceptually it contains:

- Safe and Calculated destination targets;
- seller available stock by SKU;
- physical feasibility/capacity derived from restrictions;
- tariff-class mapping inputs and direct route quotes/ranking basis;
- route/demand confidence and distortion evidence needed by the scarcity tie-break/explanation;
- product identities required for presentation.

It must not contain raw orders or an unbounded historical route matrix.

### 11.3 Replan endpoint

Add a stateless downstream contract, conceptually:

```text
POST /api/replan
```

Input:

```text
planning_basis
selected_supply_cluster_ids
```

Output:

```text
applied network
coverage results
Safe/Calculated final coverage legs
origin supply roll-up
network/stock uncovered summaries
planning explanations
```

Exact transport shape may follow existing API versioning conventions.

A replan runs only:

```text
network filtering
→ coverage planner
→ MAX_MARGIN scarcity allocation
→ roll-up / presentation aggregates
```

It does not rerun imports, demand, stockout detection, route cleaning or historical Flow aggregation.

## 12. UI/UX contract

The existing `DESIGN.md` visual language remains authoritative. No redesign or new visual identity is introduced.

### 12.1 Plan screen: supply network control

The scenario area gains one compact business control:

```text
Сеть поставки
Москва · Санкт-Петербург · Екатеринбург · +1    [Изменить]
```

`Изменить` opens the canonical non-destructive selection surface using real checkbox controls and search over clusters known from the restrictions/mapping layer.

Useful cluster context may include the count/share of current SKUs that are physically eligible there, but this is informational and backend-derived.

### 12.2 Explicit recalculation

Checkbox changes do not trigger requests.

Dirty-state copy must state that the visible plan belongs to the previous applied network, for example:

`Сеть поставки изменена. План ниже рассчитан для предыдущей сети.`

The existing primary action remains:

`Пересчитать план`

No separate `Применить сеть` action is needed.

### 12.3 Destination decision view remains demand-oriented

The canonical sequence remains:

```text
Ozon → Наша потребность → План
```

For a destination row, `План` means how much of that destination's target is finally covered, not the physical supply quantity into that destination cluster.

Destination detail must be able to explain where covered units are physically planned, for example:

```text
Казань
Наша потребность 100
Покрыто планом 100

Где лежит запас:
Москва 70
Питер  30
```

### 12.4 Physical supply roll-up

The Plan workflow adds a clear origin-oriented roll-up suitable for actually creating supplies:

```text
Москва — поставить 600
  свой спрос        500
  другие кластеры   100
    Казань            50
    Тверь             30
    Ярославль         20
```

The roll-up is derived from final coverage legs only; it never recomputes business formulas in JavaScript.

### 12.5 Flow screen separation

Historical Flow remains historical evidence:

```text
История
  Наблюдаемое | Очищенное
```

Planned placement is not added as a third historical `evidence_source`.

Instead the Flow screen may expose a higher-level view switch:

```text
История | План размещения
```

`План размещения` reuses the bounded selected-context visual language to show planned coverage legs. Historical and planned semantics remain visibly distinct.

### 12.6 Async behavior

When recalculation starts:

- the previous successful plan remains visible;
- the primary action enters a stable busy state;
- duplicate recalculation is blocked;
- success atomically replaces the applied network and plan;
- failure keeps the previous applied plan and preserves the draft network for retry;
- stale responses must not overwrite a newer request.

## 13. What this feature explicitly does not do

This design does not:

- save daily historical inventory snapshots;
- infer future route preference from raw historical flow share;
- automatically optimize which set of supply clusters the user should choose;
- use geographic distance while tariff evidence is available;
- introduce a global Sankey/chord;
- introduce an LP/min-cost-flow solver;
- change DemandEstimate or stockout formulas;
- move business calculations into frontend JavaScript;
- plan warehouse-level shipments inside one Ozon cluster;
- automatically submit a supply request to Ozon.

Automatic **selection of the supply network itself** is intentionally deferred. This feature solves the narrower problem: given a user-selected operational network, use it correctly and automatically per SKU.

## 14. Implementation decomposition

Implementation should remain split into small mergeable PRs after the current real-data PR5 baseline.

### PR-A — Tariff route matrix and direct route quotes

Backend foundation only:

- tariff-class contract;
- deterministic SKU → tariff-class lookup;
- direct route quote/lookup separate from historical `expected_logistics()`;
- direct-route economics needed by coverage/scarcity;
- matched/missing/ambiguous/price-required tests;
- no UI behavior change.

### PR-B — Physical supply network and Coverage Planner

- preserve explicit `FINITE / UNLIMITED / UNKNOWN` capacity evidence from restrictions;
- derive effective `SKU × selected origin` feasibility from restrictions;
- replace current multi-warehouse `min` rule for this planning path with §7.3 cluster ceiling semantics;
- implement LOCAL-first assignment;
- deterministic constrained-destination ordering;
- route-fee ranking;
- capacity-aware sequential fill;
- `network_uncovered_qty` and reason codes;
- conservation/capacity tests.

### PR-C — Coverage-aware MAX_MARGIN scarcity allocation

- move/reuse the existing ranking policy rather than create a second MAX_MARGIN implementation;
- allocate seller stock over coverage legs while preserving origin+destination identity;
- distinct `stock_uncovered_qty`;
- prove seller-stock conservation and deterministic ties.

### PR-D — Planning basis and downstream replan API

- bounded `planning_basis` in immutable analysis output;
- stateless replan transport;
- full-analysis vs network-only recalculation boundary;
- stale/duplicate request safeguards;
- snapshot/API contract tests.

### PR-E — Product UI and durable UX contract update

- supply-network selector with draft/applied state;
- explicit `Пересчитать план` behavior;
- physical supply roll-up;
- destination coverage explanation;
- uncovered states;
- `История | План размещения` Flow-level separation;
- update `UX-CONTRACT.md` and, only if a durable visual component rule changes, `DESIGN.md` in the same PR;
- keyboard, focus, narrow viewport and real-scale browser acceptance.

## 15. Acceptance cases

At minimum the implementation must prove:

1. **Destination identity:** rerouting Kazan target to Moscow changes physical origin plan but never Moscow/Kazan demand or need.
2. **Historical-share trap:** a historically rare cheap route can rank ahead of a historically frequent expensive route; historical shares are informational only.
3. **Tariff-class reuse:** two SKUs in the same tariff class share route ordering without a duplicated persisted SKU route matrix.
4. **Restriction filter:** a user-selected cluster that is prohibited for one SKU is automatically excluded for that SKU without removing it from the global user selection.
5. **Capacity evidence:** explicit unlimited capacity is distinguishable from unknown/missing capacity; unknown is never treated as unlimited.
6. **Multi-warehouse cluster:** cluster capacity uses one independently proven eligible warehouse ceiling and does not sum alternative warehouse maxima.
7. **Local first:** selected feasible local destination covers itself before non-local candidates.
8. **Capacity spillover:** best route fills to its finite ceiling, then residual target goes to the next route.
9. **Constrained destination:** a destination with one feasible origin is not stranded because another destination with alternatives consumed that origin first.
10. **Network uncovered:** no feasible/tariff-complete selected route yields explicit uncovered quantity, not fabricated placement.
11. **Seller-stock scarcity:** desired coverage can be fully network-feasible while final coverage is reduced by seller stock under MAX_MARGIN.
12. **Draft network:** toggling checkboxes alone does not alter the applied plan.
13. **Explicit recalc:** pressing `Пересчитать план` applies the new network only after successful backend result.
14. **Failure recovery:** failed replan leaves the previous successful plan applied and the changed network available for retry.
15. **No upstream rerun:** network-only replan does not recompute demand/stockout/clean-route history.
16. **Historical Flow unchanged:** observed/clean evidence remains historical and is not overwritten by plan routing.
17. **Real-scale bounded UI:** planned Flow/roll-up does not render an unbounded all-network graph.

## 16. Canonical precedence after approval

Once this specification is approved for implementation, source precedence for the affected planning scope becomes:

```text
2026-09-08 Selected Supply Network & Coverage Planner
→ 2026-09-03 real-data roadmap + matching PR specs
→ 2026-09-02 Product Completion design
→ DESIGN.md / UX-CONTRACT.md
→ SCOZ-lite runtime architecture
→ implementation plans
```

The 2026-09-08 document supersedes earlier sources only where it is more specific about selected supply networks, destination-to-origin coverage assignment, tariff-based route ranking, physical-capacity ownership, replan semantics, and planned-flow UI. All unrelated approved semantics remain in force.
