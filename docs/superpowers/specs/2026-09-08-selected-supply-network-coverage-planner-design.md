# Selected Supply Network & Coverage Planner — Design

**Date:** 2026-09-08  
**Status:** approved design; ready for implementation planning  
**Scope:** Product Completion planning layer after real-data PR5  
**Supersedes:** any earlier proposal to use observed/clean historical route shares as allocation weights for future supply placement; the earlier shorthand where destination need and physical placement capacity were treated as one `SKU × cluster` ceiling  
**Does not supersede:** destination-demand semantics, DemandEstimate, stockout/clean-route analytics, historical Flow evidence, route-impact analytics, Safe/Calculated plan families, fixed `MAX_MARGIN` scarcity strategy, SCOZ-lite runtime architecture

## 1. Product problem

The application already estimates demand correctly by `SKU × destination_cluster`, but a seller cannot practically create new FBO supply in every destination cluster where demand exists.

The operator instead chooses a limited **supply network**: the clusters where they are operationally willing to create new supply. The application must then preserve each destination's demand identity while deciding where the stock that serves that demand should physically sit.

Example:

```text
Destination need:
Москва 500
Казань 100

Selected supply network:
Москва = selected
Казань = not selected

Physical supply plan:
Москва 600
  500 for Москва demand
  100 for Казань demand
```

The Kazan 100 never becomes Moscow demand. Moscow is only the planned physical origin serving Kazan demand.

The new explicit layer is:

```text
Destination Need
→ Destination Target
→ Selected Supply Network
→ Coverage Assignment
→ Desired Coverage Legs
→ Seller Stock Allocation
→ Final Coverage Legs
→ Origin Supply Plan
```

## 2. Non-negotiable semantics

### 2.1 Destination owns demand

Existing real-data invariants remain unchanged:

- `destination_cluster` is where customer demand arose;
- `origin_cluster` is where serving stock is physically placed/fulfilled;
- physical dispatch from an origin never increases that origin's own demand;
- external fulfillment never erases destination demand;
- changing the selected supply network cannot change demand history, `DemandEstimate`, stockout episodes, clean routes, or `calculated_need_qty`.

### 2.2 Historical flow is evidence, not a future placement weight

Observed and clean historical route shares are affected by historical stock availability. A route can have low historical share because stock was rarely available there, not because the route is intrinsically poor.

Therefore future coverage assignment MUST NOT use formulas such as:

```text
selected_share = historical_share / sum(selected_historical_shares)
```

Observed/clean flow remains useful for:

- historical Flow visualization;
- proving that a route has occurred;
- stockout/substitution analysis;
- route/context explanation;
- comparing the planned topology with historical behavior.

Historical quantity/share does not determine planned coverage quantity.

### 2.3 Tariff is the primary non-local route-ranking proxy

For non-local coverage inside the selected network, lower current imported Ozon route tariff means a more natural route for planning purposes.

This is an explicit planning proxy. The application does not claim to reproduce Ozon's hidden real-time routing engine.

Geographic distance is not used while complete tariff evidence exists.

### 2.4 Restrictions are the physical source of truth

The Ozon restrictions report is the canonical source for:

- whether a SKU may be supplied to a warehouse/cluster;
- the maximum supply quantity exposed by that report.

For each SKU:

```text
effective origins
=
user-selected supply clusters
∩ physically feasible clusters from restrictions
```

The user selects the global operational network only. Per-SKU feasible origins are chosen/filter\-ed automatically by the backend.

Unknown or conflicting restriction evidence remains fail-closed.

## 3. End-state planning pipeline

```text
Observed Destination Demand
        ↓
Demand Estimate
        ↓
Calculated Need
        ↓
Safe / Calculated Destination Targets
        ↓
Selected Supply Network
        ↓
Restrictions / Physical Feasibility
        +
Volume-class Route Tariffs
        ↓
Coverage Planner
        ↓
Desired Coverage Legs
        ↓
MAX_MARGIN Allocation Eligibility + Scarcity
        ↓
Final Coverage Legs
        ↓
Origin Supply Plan roll-up
```

Everything from the selected network downward is downstream of `Calculated Need`. A network change never feeds back into demand/routing history.

## 4. Destination targets

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

when both inputs are complete.

Physical capacity is intentionally not part of destination target. Capacity belongs to the **origin** that may hold the serving stock.

This supersedes the earlier shorthand:

```text
safe_ceiling = min(Ozon, Need, physical_ceiling)
calculated_ceiling = min(Need, physical_ceiling)
```

where one cluster implicitly played both destination and origin roles.

Unknown target inputs remain incomplete; they are never coerced to zero.

## 5. Selected Supply Network

### 5.1 What the user controls

The user selects only the clusters where new supply is operationally acceptable:

```text
☑ Москва
☑ Санкт-Петербург
☐ Казань
☑ Екатеринбург
```

The user never enters supply quantities per cluster. Quantities are calculated by the backend.

Existing FBO stock and inbound remain upstream destination-need inputs regardless of whether that destination is selected for new supply.

### 5.2 Candidate cluster universe

The selector is built from canonical cluster identities present in the current restrictions/mapping layer.

For the current SKU universe, the UI may show how many SKUs have at least one explicitly allowed warehouse in each cluster. This is informational only.

Clusters with unresolved identity are not silently added to the network.

### 5.3 Initial default and persistence

On first use, when Project JSON contains no prior applied supply network, default-select all current candidate clusters that have at least one explicitly allowed SKU. This preserves a broad/backward-compatible starting network and lets the user deliberately narrow it.

After the first successful plan calculation, persist the **applied** supply network in Project JSON.

On later runs:

- previously applied cluster IDs remain selected when still present in the current candidate universe;
- newly appearing clusters default to unselected, so a source-data update never silently expands the operator's network;
- disappeared/unresolved selected clusters are excluded from the effective network and surfaced as a reconciliation warning;
- an empty reconciled network is not silently replaced with “all clusters”.

Draft checkbox changes are not persisted as applied until recalculation succeeds.

### 5.4 Draft vs applied network

Checkbox changes are draft state only. They MUST NOT trigger recalculation.

After the first change, the UI states that the visible plan still belongs to the previous applied network, for example:

`Сеть поставки изменена. План ниже рассчитан для предыдущей сети.`

The existing action remains:

`Пересчитать план`

The draft becomes applied only after a successful calculation. Failure preserves the previous applied network and keeps the draft available for retry.

### 5.5 Recalculation depth

The same user-facing button covers both cases:

- source files, horizon, inbound or other upstream analysis inputs changed → full analysis;
- only selected supply network changed → downstream replan only.

If upstream inputs and the network are both dirty, the full analysis request includes the current draft network and returns a plan for that same network.

The frontend may decide which endpoint to call from dirty-state ownership, but it never calculates planning quantities.

## 6. Route tariff model

### 6.1 Route topology is not persisted per SKU

SKU-specific persisted affinity matrices are prohibited.

For network topology, the reusable route ranking is primarily:

```text
volume_band × origin_cluster × destination_cluster
```

A SKU maps to the appropriate volume band from normalized product economics data.

If the imported tariff source already requires another lookup dimension such as price to resolve one fee unambiguously, the direct quote may use that source dimension. It does **not** turn price into a separate route-topology concept and does not justify a duplicated SKU route matrix.

### 6.2 Direct fee is the decision source

Non-local candidate origins are ranked directly by matched route fee:

```text
logistics_fee ASC
```

A normalized `route_affinity` such as `best_fee / route_fee` may be exposed for explanation, but it is presentation only and must never become a second ranking formula.

### 6.3 Direct route lookup is separate from historical expected logistics

Existing `expected_logistics()` remains for historical/current origin-profile analysis. It uses an observed/clean route distribution and returns a weighted expected fee.

Coverage planning needs a separate pure operation for one candidate `origin → destination`:

```text
DirectRouteQuote
  origin_cluster_id
  destination_cluster_id
  volume_band
  matched_fee
  lookup_status
  source_row
```

The implementation may enrich the quote with route-specific unit economics for allocation, but route lookup and historical expected logistics remain separate concepts.

Missing, ambiguous or otherwise incomplete tariff evidence is never replaced by a fabricated fee.

## 7. Restrictions and capacity

### 7.1 Eligibility

For `SKU × selected origin`, placement is feasible only when at least one warehouse mapped to that cluster is explicitly `ALLOWED` for the SKU.

`PROHIBITED`, `UNKNOWN`, missing restriction rows, conflicting warehouse identity or conflicting restriction states remain fail-closed under existing safeguards.

### 7.2 Preserve capacity evidence explicitly

The restrictions report is the only physical capacity source for this feature. No second capacity file/table is introduced.

For an allowed warehouse row the normalized contract must distinguish:

```text
FINITE(value)   # explicit numeric maximum
UNLIMITED       # source explicitly says "Без ограничений"
UNKNOWN         # capacity not proven by the source
```

The current ambiguous `None` representation must not reach Coverage Planner as both “unlimited” and “unknown”. Import/domain contracts must be extended first.

Malformed numeric values remain diagnostics/errors under existing ingestion policy; they are not silently converted to UNKNOWN.

### 7.3 Multiple warehouses in one cluster

This product plans **clusters**, not individual supply requests to multiple warehouses.

Therefore warehouse maxima are not summed. Summation would assume that all warehouse limits are simultaneously available, which this planning layer does not prove.

For explicitly allowed warehouse alternatives:

```text
known = rows with FINITE or UNLIMITED capacity

if known is empty:
    cluster capacity = UNKNOWN
elif any known row is UNLIMITED:
    cluster capacity = UNLIMITED
else:
    cluster capacity = max(FINITE values)
```

This rule means the cluster plan is supported by at least one independently known receiving option without inventing additive capacity.

An UNKNOWN alternative does not invalidate a separate allowed warehouse with a known usable capacity.

A later warehouse-level planning feature may supersede this rule.

### 7.4 Capacity is per SKU × origin

For every SKU, all desired legs passing through one origin share the same capacity:

```text
sum(desired legs for SKU through origin)
<= finite capacity for SKU × origin
```

The same capacity is not reset separately for every destination.

## 8. Coverage Planner

### 8.1 Coverage leg identity

Coverage is atomic at:

```text
SKU × origin_cluster × destination_cluster
```

Conceptual contract:

```text
CoverageLeg
  sku
  origin_cluster_id
  destination_cluster_id
  desired_qty
  final_allocated_qty
  coverage_type: LOCAL | ROUTE
  direct_route_fee
  volume_band
  route_evidence_summary      # informational
  route_economics
  reason_codes
```

The leg always preserves who owns demand and where serving stock is planned.

### 8.2 LOCAL first

If the destination itself is selected and physically feasible for the SKU, assign its target locally first, up to remaining local capacity.

```text
Казань target = 50
Казань selected + feasible
→ Казань → Казань = 50 LOCAL
```

LOCAL preference is a product rule. A cheaper non-local tariff does not displace feasible local coverage before local capacity is used.

A LOCAL desired leg does not require historical route evidence. If its direct economics is incomplete, the later allocation stage applies the existing fail-closed economics policy and explains the block.

### 8.3 Non-local candidate set

For residual destination target, candidate origins must all be:

- selected by the user;
- physically feasible for this SKU;
- have remaining known usable capacity (or explicit UNLIMITED);
- have a complete direct route tariff lookup to the destination.

Historical route existence is not required.

### 8.4 Non-local ranking

Within one destination, candidates are ordered by:

1. lower direct route fee;
2. better route-evidence confidence only when fees are exactly equal;
3. stable origin cluster ID.

Historical route **share/quantity** never enters this ordering.

### 8.5 Sequential fill, not proportional split

Route score is a ranking, not a percentage allocation.

Example:

```text
Kazan residual = 100
Москва → Казань 47 ₽, remaining capacity 70
Питер  → Казань 52 ₽, remaining capacity 100

Desired:
Москва → Казань 70
Питер  → Казань 30
```

This avoids unnecessary micro-stock fragmentation.

### 8.6 Constrained destinations first

A greedy planner must not consume a scarce origin for a destination with alternatives while stranding a destination that has only that origin.

After LOCAL assignment, process residual destinations by:

1. fewer currently feasible selected origins first;
2. larger residual target first;
3. stable destination cluster ID.

Within each destination, use §8.4 route ranking.

The feasible-origin count is evaluated from the current remaining-capacity state before that destination is assigned. Deterministic tests must cover re-evaluation after prior assignments consume capacity.

This is intentionally a bounded deterministic heuristic, not a general LP/min-cost-flow solver.

### 8.7 Network uncovered

Residual target becomes `network_uncovered_qty` when the selected network cannot produce a desired leg because of:

- no selected physically feasible origin;
- all non-local candidate tariffs missing/ambiguous/incomplete;
- all usable origin capacity exhausted or unknown.

It is never silently assigned to an arbitrary cluster.

## 9. Allocation eligibility and seller-stock scarcity

Coverage Planner answers:

> where should stock ideally sit inside the selected network if supply and allocation eligibility were sufficient?

The existing optimizer policy still decides whether a desired leg is eligible and which eligible legs receive scarce seller stock.

### 9.1 Preserve one MAX_MARGIN policy

Do not create a second ranking implementation. Extract/reuse the existing policy so coverage-leg allocation preserves existing thresholds and deterministic tie-break intent.

Each leg has a hard ceiling of `desired_qty`.

### 9.2 Direct route economics

The allocator must see `origin → destination` identity because legs through the same origin can have different route economics.

Existing minimum profit/margin/ROI and economics-completeness checks remain eligibility constraints unless separately superseded.

### 9.3 Three distinct kinds of uncovered target

Do not collapse all unmet target into one reason.

```text
network_uncovered_qty
```

Selected network/route/capacity could not produce a desired leg.

```text
allocation_blocked_qty
```

A desired leg existed, seller stock was conceptually available, but the leg failed allocation eligibility, e.g. incomplete economics, non-positive profit or configured threshold.

```text
stock_uncovered_qty
```

The leg was allocation-eligible but seller available stock was exhausted before the desired quantity could be filled.

User-facing reasons must preserve this causal distinction.

## 10. Conservation invariants

Before allocation eligibility/scarcity, for every `SKU × destination`:

```text
sum(desired coverage legs to destination)
+ network_uncovered_qty
= destination_target
```

After final allocation:

```text
sum(final allocated coverage legs to destination)
+ network_uncovered_qty
+ allocation_blocked_qty
+ stock_uncovered_qty
= destination_target
```

For every `SKU × origin`:

```text
sum(desired coverage legs through origin)
<= finite origin capacity
```

For every SKU:

```text
sum(final allocated coverage legs)
<= seller available stock
```

Final allocation never exceeds any desired leg ceiling.

Coverage planning never changes demand quantities or destination identity.

## 11. Immutable analysis vs planning state

### 11.1 Separate immutable objects

Network-only replan must not mutate an existing immutable analysis result.

Canonical end-state separates:

```text
AnalysisSnapshot
```

Base analytical facts and upstream calculations:

- report metadata/freshness;
- scenario inputs that affect demand/need;
- demand estimates and need;
- observed/clean routes;
- stockout evidence;
- route-impact analytics;
- unit economics inputs/results;
- bounded `planning_basis`.

and:

```text
PlanningSnapshot
```

A derived immutable plan referencing one base analysis:

- `planning_snapshot_id`;
- `analysis_snapshot_id`;
- applied supply network;
- Safe and Calculated coverage results;
- final coverage legs;
- origin supply roll-ups;
- network/allocation/stock uncovered summaries;
- plan-level explanations/presentation rows.

Plan quantities are authoritative in `PlanningSnapshot`. Any legacy plan fields still carried by `AnalysisSnapshot` during migration are transitional only and must not be read by the migrated UI after a replan.

### 11.2 Planning basis

`AnalysisSnapshot.planning_basis` is a bounded backend-owned input sufficient for downstream replanning without raw imports or upstream recomputation.

It includes only what replan needs, conceptually:

- Safe/Calculated destination targets;
- seller available stock by SKU;
- physical feasibility/capacity evidence;
- volume-band/direct-route quote basis;
- route/demand confidence and distortion evidence required by existing allocation tie-breaks;
- product identities/presentation metadata.

It must not contain raw orders, buyer PII or an unbounded historical route matrix.

### 11.3 Full analysis result

A successful full analysis returns:

```text
AnalysisSnapshot
+
initial PlanningSnapshot
```

The initial PlanningSnapshot is calculated using the selected network supplied with that full request.

### 11.4 Network-only replan

Conceptual endpoint:

```text
POST /api/replan
```

Input:

```text
analysis_snapshot_id
planning_basis
selected_supply_cluster_ids
```

Output:

```text
new immutable PlanningSnapshot
```

The output echoes/references the base `analysis_snapshot_id`. The frontend applies it only if that analysis snapshot is still active; a response for an older base analysis is stale and discarded.

Replan runs only:

```text
network filtering
→ Coverage Planner
→ allocation eligibility + MAX_MARGIN scarcity
→ roll-up/presentation aggregates
```

It does not rerun imports, demand, stockout detection, route cleaning or historical Flow aggregation.

## 12. UI/UX contract

The existing `DESIGN.md` visual language remains authoritative. This feature changes workflow and data semantics, not the visual identity.

### 12.1 Supply-network control

The Plan scenario area gains one compact business control:

```text
Сеть поставки
Москва · Санкт-Петербург · Екатеринбург · +1    [Изменить]
```

`Изменить` opens the canonical searchable non-destructive selection surface with real checkboxes.

The selector shows applied vs draft state clearly. It may show backend-derived eligible-SKU counts per cluster.

### 12.2 Explicit recalculation only

Checkbox changes do not issue requests.

The single primary action is:

`Пересчитать план`

No separate `Применить сеть` button exists.

When busy:

- previous successful analysis/planning result remains visible;
- button geometry stays stable and duplicate submit is blocked;
- success atomically applies the new result;
- failure keeps the previous applied plan and draft network;
- stale responses cannot overwrite a newer active analysis/planning state.

### 12.3 Destination decision view remains demand-oriented

Canonical sequence remains:

```text
Ozon → Наша потребность → План
```

For a destination row, `План` means how much of that destination target is finally covered, not physical inbound to the destination cluster.

Destination detail can explain:

```text
Казань
Наша потребность 100
Покрыто планом 100

Где лежит запас:
Москва 70
Питер  30
```

The explanation distinguishes network, allocation-policy and seller-stock uncovered reasons.

### 12.4 Physical supply roll-up

The Plan workflow exposes an origin-oriented roll-up suitable for creating supplies:

```text
Москва — поставить 600
  свой спрос        500
  другие кластеры   100
    Казань            50
    Тверь             30
    Ярославль         20
```

The default roll-up is **Calculated Plan**, because it is the canonical `Наш план`. Safe Plan remains an explicitly labelled conservative comparison and is never summed with Calculated Plan.

All roll-up values come from backend final coverage legs.

### 12.5 Flow screen separation

Historical Flow remains:

```text
История
  Наблюдаемое | Очищенное
```

Planned placement is not a third historical `evidence_source`.

The Flow section may expose the higher-level switch:

```text
История | План размещения
```

`План размещения` reuses the bounded selected-context visual language and defaults to Calculated Plan. Safe Plan may be available as a clearly labelled comparison.

Historical and planned semantics must remain visibly distinct.

## 13. Explicit non-goals

This feature does not:

- save daily historical inventory snapshots;
- infer future route preference from historical flow share;
- automatically optimize the global set of supply clusters after the user has chosen it;
- use geographic distance while complete tariff evidence exists;
- introduce an LP/min-cost-flow solver;
- introduce a global Sankey/chord;
- change DemandEstimate or stockout formulas;
- move business formulas into frontend JavaScript;
- plan multiple warehouse-level shipments inside one cluster;
- submit supply requests to Ozon.

The system **does** automatically choose/filter per-SKU origins inside the user-selected global network using restrictions, capacity and route tariffs.

## 14. Implementation decomposition

Implementation stays split into small mergeable PRs.

### PR-A — Volume-class route tariffs and direct quotes

- reusable volume-band route matrix/lookup;
- deterministic SKU → volume-band resolution;
- preserve any existing source lookup dimension required to resolve one fee without persisting a SKU matrix;
- direct route quote separate from historical `expected_logistics()`;
- route-specific economics needed by allocation;
- matched/missing/ambiguous/source-dimension tests;
- no UI change.

### PR-B — Restrictions capacity + Coverage Planner

- introduce explicit `FINITE / UNLIMITED / UNKNOWN` capacity states;
- derive `SKU × selected origin` feasibility;
- implement non-additive multi-warehouse cluster ceiling from §7.3;
- LOCAL-first assignment;
- constrained-destination ordering;
- route-fee ranking;
- capacity-aware sequential fill;
- `network_uncovered_qty` and reason codes;
- conservation/capacity tests.

### PR-C — Coverage-aware MAX_MARGIN

- reuse/extract the existing allocation ranking/eligibility policy;
- allocate over `origin → destination` coverage legs;
- preserve existing economics thresholds;
- introduce `allocation_blocked_qty` and `stock_uncovered_qty`;
- prove seller-stock conservation and deterministic ties.

### PR-D — Planning snapshots, persistence and replan API

- bounded `planning_basis`;
- immutable `PlanningSnapshot` referencing `AnalysisSnapshot`;
- full-analysis result returns base analysis + initial planning snapshot;
- stateless network-only replan endpoint;
- selected-network initial default, Project JSON persistence and reconciliation;
- full-analysis vs network-only dirty boundary;
- stale/duplicate response safeguards;
- snapshot/API tests.

### PR-E — Product UI + durable UX contract implementation

- supply-network selector with draft/applied state;
- explicit `Пересчитать план` behavior;
- Calculated physical supply roll-up + Safe comparison;
- destination coverage explanations and three uncovered causes;
- `История | План размещения` separation;
- implement/update shared UX owners rather than screen-local controls;
- keyboard/focus/narrow viewport/real-scale browser acceptance.

## 15. Acceptance cases

At minimum implementation must prove:

1. **Destination identity:** rerouting Kazan target to Moscow changes physical origin plan but never Moscow/Kazan demand or need.
2. **Historical-share trap:** a historically rare cheap route may rank ahead of a historically frequent expensive route; history remains informational.
3. **Volume-band reuse:** SKUs in the same tariff volume band reuse route ordering without a persisted SKU route matrix.
4. **Restriction filter:** a globally selected cluster prohibited for one SKU is automatically excluded only for that SKU.
5. **Capacity states:** explicit unlimited is distinguishable from unknown; unknown is never interpreted as unlimited.
6. **Multi-warehouse cluster:** cluster capacity uses the best independently proven single-warehouse ceiling and never sums alternative limits.
7. **Shared origin capacity:** one SKU's origin ceiling is consumed across all destinations served by that origin.
8. **Local first:** selected feasible local destination is assigned locally before non-local routes.
9. **Capacity spillover:** cheapest route fills to its finite ceiling, then residual goes to the next route.
10. **Constrained destination:** a one-origin destination is not stranded because an earlier flexible destination consumed that origin.
11. **Network uncovered:** no feasible/tariff-complete selected route produces explicit network-uncovered quantity.
12. **Allocation blocked:** sufficient seller stock plus incomplete/threshold-failing economics is not mislabeled as seller-stock shortage.
13. **Seller-stock scarcity:** eligible desired coverage may remain unmet specifically because seller stock is exhausted.
14. **Conservation:** final + network-uncovered + allocation-blocked + stock-uncovered equals destination target.
15. **First-run network:** absent persisted selection defaults to all current candidate clusters.
16. **No silent expansion:** newly appearing clusters after a later restrictions import default unselected.
17. **Draft network:** checkbox toggles alone do not alter applied plan or persisted applied network.
18. **Explicit recalc:** the draft network becomes applied only after successful calculation.
19. **Simultaneous dirty inputs:** upstream + network changes produce a full analysis and initial plan for the same draft network.
20. **Failure recovery:** failed replan keeps previous planning snapshot applied and draft available for retry.
21. **Immutable base:** network-only replan produces a new PlanningSnapshot and never mutates/relabels the base AnalysisSnapshot.
22. **Stale base:** planning response for an inactive `analysis_snapshot_id` is discarded.
23. **No upstream rerun:** network-only replan does not recompute demand/stockout/clean-route history.
24. **Historical Flow unchanged:** observed/clean history is not overwritten by plan routing.
25. **Calculated primary:** physical roll-up/plan Flow default to Calculated Plan; Safe remains separate comparison.
26. **Real-scale bounded UI:** plan Flow/roll-up never becomes an unbounded all-network graph.

## 16. Canonical precedence

For selected-network/coverage-planning scope, source precedence is:

```text
2026-09-08 Selected Supply Network & Coverage Planner
→ 2026-09-03 real-data roadmap + matching PR specs
→ 2026-09-02 Product Completion design
→ UX-CONTRACT.md / DESIGN.md for frontend behavior and visual system
→ SCOZ-lite runtime architecture
→ matching implementation plans
```

This document supersedes earlier sources only where it is more specific about selected supply networks, destination-to-origin coverage assignment, tariff-based route ranking, physical-capacity ownership, planning snapshot/replan semantics and planned-flow UI. All unrelated approved semantics remain in force.
