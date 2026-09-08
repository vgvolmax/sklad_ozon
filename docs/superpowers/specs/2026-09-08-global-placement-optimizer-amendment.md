# Global Placement Optimizer — Selected Network Amendment

**Date:** 2026-09-08  
**Status:** approved clarification; canonical for implementation  
**Parent designs:**
- `docs/superpowers/specs/2026-09-08-route-cost-index-amendment.md`
- `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`
- `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`

**Scope:** the final planning decision layer that converts Safe/Calculated destination targets into one globally optimized physical supply plan across the user-selected supply network.

**Supersedes:**
- the `LOCAL first` hard-allocation rule;
- the greedy constrained-destination / sequential-fill Coverage Planner as the quantity allocator;
- the split where PR-B fixes desired route quantities before PR-C sees economics;
- seller-stock scarcity optimized independently per SKU as the complete end-state;
- the single non-selectable `MAX_MARGIN` product objective;
- any UI/source text saying the Plan scenario contains only horizon, inbound and recalculation;
- the three-gap model where a global shipment cap does not exist;
- Route Cost Index amendment §4–§5 only where those sections imply that candidate route ranking itself chooses final quantities.

**Does not supersede:** destination-demand semantics, DemandEstimate, stockout/clean-route analytics, historical Flow evidence, Safe/Calculated plan families, current customer-delivery tariff semantics, `DirectRouteQuote`, pair-level `RouteCostIndex`, cluster identity, SCOZ-lite runtime architecture, Project JSON persistence, or the rule that frontend contains no business formulas.

---

## 1. Product goal

The operator chooses:

1. the clusters where new supply is operationally acceptable;
2. the total number of units to place in the new supply (`shipment_total_qty`);
3. the economic objective: `MAX_PROFIT` or `MAX_MARGIN`.

The application must automatically decide:

- which SKUs to include in that limited shipment;
- how many units of each SKU to include;
- in which selected physical origin cluster each unit should be placed;
- which destination demand each placement is intended to cover.

The result must be globally feasible and globally optimal for the selected objective inside the modeled constraints. It must not be a sequence of locally reasonable greedy decisions that can strand demand even when a better feasible assignment exists.

Canonical decision chain:

```text
Observed destination demand
→ Demand Estimate
→ Calculated Need
→ Safe / Calculated destination targets
→ Selected Supply Network
→ Restrictions + capacity
→ Exact route/economics candidates
→ GLOBAL PLACEMENT OPTIMIZER
→ Final SKU × origin × destination legs
→ Destination coverage view + Physical origin supply plan
```

Changing network, shipment quantity or optimization mode is downstream planning only. It never changes demand history, stockout evidence, route cleaning or calculated need.

---

## 2. Existing Ozon restrictions report has two independent jobs

The already-uploaded Ozon report such as `Ограничение складов по товарам_01.09.2026.xlsx` is one source file but must produce two logically separate normalized outputs.

### 2.1 Physical supply capability

The report contains warehouse-level facts including:

```text
Артикул
SKU
Название товара
Кластер
Склад
Возможно ли поставить товар
Зона размещения
Ошибки в карточке товара
Склад оборудован под хранение товара
Статус ликвидности: Без продаж, ограничен
Максимальный размер поставки
```

The authoritative planning fields are:

```text
SKU
cluster
warehouse
allowed
capacity_kind
max_supply_qty
```

`Зона размещения`, `Ошибки в карточке товара`, `Склад оборудован...` and liquidity status are explanation/diagnostic evidence only. They MUST NOT receive numeric weights and MUST NOT independently override the explicit `Возможно ли поставить товар` result.

The importer may preserve these explanatory fields so the UI can explain a block, but the optimizer's physical eligibility is based on explicit restriction state plus usable capacity.

### 2.2 Ozon 56-day recommendation/reference

The same report also contains:

```text
Рекомендуемая поставка на 56 дней
```

and workbook metadata such as:

```text
Дата формирования отчета: 01.09.2026
Выбранные фильтры: ..., рекомендуемая поставка на 56 дней
```

Normalize one recommendation record per `SKU × destination_cluster`:

```text
OzonSupplyRecommendation
  sku
  destination_cluster_id
  recommended_qty: int | None
  status: EXPLICIT | MISSING | CONFLICTING
  horizon_days: int | None
  report_generated_at: date | None
  source_rows
```

Semantics are strict:

- numeric `0` means Ozon explicitly recommends zero;
- numeric positive values are explicit recommendations;
- `-` / blank means recommendation missing, not zero;
- conflicting repeated values for the same `SKU × cluster` make that recommendation incomplete and diagnostic;
- repeated identical values across warehouse rows are deduplicated;
- horizon is parsed from the report/header when possible; do not hard-code 56 as a universal future invariant;
- report date is parsed from workbook metadata when present.

This recommendation is an Ozon comparison/control signal and Safe Plan input. It is not a physical capacity and never caps Calculated Plan.

---

## 3. Restriction/capacity semantics

### 3.1 Warehouse-level source is retained

Restriction evidence is normalized at `SKU × warehouse`, then summarized to `SKU × origin_cluster` for cluster planning.

### 3.2 Capacity state is explicit

```text
FINITE(value)
UNLIMITED
UNKNOWN
```

Rules:

- numeric `0` is `FINITE(0)`, not UNKNOWN;
- `ALLOWED + FINITE(0)` is physically compatible but currently unusable for placement;
- `Без ограничений` is `UNLIMITED`;
- unknown is never treated as unlimited;
- malformed nonblank capacity is an ingestion diagnostic/error, not UNKNOWN.

### 3.3 Multiple warehouses in one cluster are not additive in V1

For explicitly allowed warehouse alternatives:

```text
known = allowed rows with FINITE or UNLIMITED capacity

if known is empty:
    cluster capacity = UNKNOWN
elif any known row is UNLIMITED:
    cluster capacity = UNLIMITED
else:
    cluster capacity = max(FINITE values)
```

Do not sum warehouse maxima. A cluster-level plan may use the best independently proven receiving option, but the report does not prove that multiple warehouse limits can be consumed simultaneously.

### 3.4 Effective physical origin

For a concrete SKU, an origin is usable only when all are true:

```text
origin is selected by the user
restriction state proves ALLOWED
capacity is UNLIMITED or FINITE(value > 0)
cluster identity is resolved
```

`FINITE(0)` and `UNKNOWN` are not usable placement capacity.

---

## 4. Scenario controls

Planning scenario state now includes:

```text
horizon_days
include_inbound
selected_supply_network
shipment_total_qty
optimization_mode
```

where:

```text
optimization_mode ∈ {MAX_PROFIT, MAX_MARGIN}
shipment_total_qty = positive integer units
```

`shipment_total_qty` is a count of sellable units across all SKUs, not liters/cubic volume.

The operator never enters quantities per cluster or per SKU. Those are optimizer outputs.

Draft changes to any downstream planning control:

```text
selected_supply_network
shipment_total_qty
optimization_mode
```

must not auto-recalculate. They only mark the visible plan stale. The existing explicit action remains:

```text
Пересчитать план
```

A failed replan preserves the previous applied PlanningSnapshot and the current draft controls.

---

## 5. Safe and Calculated destination targets remain separate

### 5.1 Calculated Plan

```text
calculated_destination_target = calculated_need_qty
```

Ozon recommendation does not cap this target.

### 5.2 Safe Plan

When both values are complete:

```text
safe_destination_target = min(
    calculated_need_qty,
    ozon_recommended_qty,
)
```

If Ozon recommendation is missing/conflicting, Safe target is incomplete for that `SKU × destination`; it is not coerced to zero.

Both plan families are run through the same candidate-generation and global-optimization machinery. Calculated remains the primary `Наш план`; Safe remains the conservative comparison/reference.

---

## 6. PR-B boundary: candidate graph, not quantity allocation

PR-B no longer assigns desired quantities to routes.

Its job is to expose the complete feasible topology for later economic optimization.

Conceptual candidate identity:

```text
SKU × origin_cluster × destination_cluster
```

Candidate facts include at least:

```text
sku
origin_cluster_id
destination_cluster_id
coverage_type: LOCAL | ROUTE
origin_capacity
restriction evidence
DirectRouteQuote / direct tariff completeness
RouteCostIndex (pair-level evidence, optional)
historical Flow/confidence evidence (informational)
```

PR-B MUST NOT:

- allocate target quantity locally first;
- consume capacity greedily;
- choose constrained destinations sequentially;
- create fixed `desired_qty` legs that PR-C is forbidden to reroute;
- use historical route shares as future quantity weights.

LOCAL is preserved as candidate metadata and a late deterministic preference, not a hard first allocation rule.

A non-local candidate requires a complete current `DirectRouteQuote`. A favorable RouteCostIndex never rescues missing/ambiguous direct tariff evidence.

---

## 7. PR-C boundary: one global optimizer

### 7.1 Decision variable

For each eligible candidate:

```text
x[sku, origin, destination] ∈ nonnegative integers
```

means the number of units of that SKU physically placed in `origin` to cover demand owned by `destination`.

### 7.2 Hard constraints

For each `SKU × destination`:

```text
sum_origin x[sku, origin, destination]
<= destination_target[sku, destination]
```

For each `SKU × origin` with finite capacity:

```text
sum_destination x[sku, origin, destination]
<= capacity[sku, origin]
```

For each SKU with proven seller stock:

```text
sum_origin_destination x[sku, origin, destination]
<= seller_available_stock[sku]
```

Across the entire shipment:

```text
sum_sku_origin_destination x[sku, origin, destination]
<= shipment_total_qty
```

No allocation may use a blocked/incomplete candidate edge.

### 7.3 Economic eligibility

Before final optimization, direct/local unit economics are calculated for candidate edges actually needed by the selected network.

Existing eligibility rules remain hard constraints unless separately superseded:

```text
economics complete
profit_per_unit > 0
min_profit_per_unit
min_margin_rate
min_roi
```

An ineligible edge cannot receive flow.

### 7.4 Lexicographic optimization

The optimizer uses this priority order:

```text
1. maximize feasible allocated quantity, capped by shipment_total_qty;
2. among solutions with that same allocated quantity, optimize the selected economic objective;
3. when the economic objective is exactly tied, prefer lower exact direct logistics fee;
4. then prefer LOCAL;
5. then prefer known lower RouteCostIndex;
6. then higher route/demand confidence;
7. then stable SKU/origin/destination identifiers.
```

This prevents a tiny margin improvement from leaving usable requested shipment quantity unallocated.

### 7.5 Objectives

`MAX_PROFIT`:

```text
maximize Σ x[sku,origin,destination] × profit_per_unit[sku,origin,destination]
```

`MAX_MARGIN` with fixed allocated unit count:

```text
maximize Σ x[sku,origin,destination] × margin_rate[sku,origin,destination]
```

`MAX_VOLUME` does not exist. Quantity is a scenario constraint, not an optimization mode.

Numeric RouteCostIndex is never a primary economic objective and never substitutes for exact route economics.

---

## 8. Algorithmic requirement

The V1 end-state must use a deterministic global flow optimization, not the old greedy Coverage Planner.

The recommended dependency-free formulation is integer **min-cost max-flow**:

```text
SOURCE
→ global shipment cap
→ SKU stock nodes
→ SKU × origin capacity nodes
→ SKU × destination candidate edges
→ destination target nodes
→ SINK
```

Run enough flow to determine the maximum feasible quantity up to `shipment_total_qty`, then solve the selected economic objective for that fixed quantity using deterministic integer/scaled costs.

A pure-Python successive-shortest-augmenting-path implementation is acceptable. Do not add a solver dependency unless a later change demonstrates a concrete need.

The implementation must prove with a regression case that it avoids the former greedy trap, e.g.:

```text
Destinations: Москва 100, Казань 100
Origins: Москва capacity 100, Питер capacity 100
Allowed routes:
  Москва → Москва
  Москва → Казань
  Питер  → Москва
  Питер  → Казань blocked

Global optimum:
  Питер  → Москва 100
  Москва → Казань 100
```

A hard `LOCAL first` policy would cover only 100 and is therefore prohibited.

---

## 9. Causal gap accounting

The new global cap requires four distinct causes. Do not collapse them into one `uncovered` number.

Compute causally in stages:

1. selected network + restrictions/capacity + direct tariff completeness;
2. economics/threshold eligibility;
3. seller stock by SKU;
4. global shipment cap.

Canonical quantities:

```text
network_uncovered_qty
allocation_blocked_qty
seller_stock_uncovered_qty
shipment_cap_uncovered_qty
```

Definitions:

- `network_uncovered_qty`: selected network / restriction capacity / route evidence cannot physically produce coverage;
- `allocation_blocked_qty`: physical candidate exists but economics/data eligibility blocks it;
- `seller_stock_uncovered_qty`: eligible coverage exists but seller stock for that SKU is insufficient;
- `shipment_cap_uncovered_qty`: eligible stock-supported coverage exists but the user intentionally requested a smaller total shipment.

Additionally expose:

```text
requested_shipment_qty
allocated_shipment_qty
unallocated_shipment_qty = max(0, requested_shipment_qty - allocated_shipment_qty)
```

`unallocated_shipment_qty > 0` means the application could not use all requested shipment units because confirmed demand/physical/economic/seller-stock constraints were exhausted. It must have human-readable reasons.

---

## 10. Conservation invariants

For every `SKU × destination` after final planning:

```text
final_covered_qty
+ network_uncovered_qty
+ allocation_blocked_qty
+ seller_stock_uncovered_qty
+ shipment_cap_uncovered_qty
= destination_target
```

For every finite `SKU × origin`:

```text
sum_destination final_allocated_qty
<= origin_capacity
```

For every SKU:

```text
sum_origin_destination final_allocated_qty
<= seller_available_stock
```

For the plan family:

```text
sum_all final_allocated_qty
<= shipment_total_qty
```

and when enough feasible eligible stock-supported target exists:

```text
sum_all final_allocated_qty
= shipment_total_qty
```

Destination identity is never rewritten by physical placement.

---

## 11. PlanningBasis and replan boundary

The immutable `PlanningBasis` remains compact and SKU-route-Cartesian-product-free.

It carries once:

- Safe/Calculated destination targets;
- Ozon recommendation/reference with horizon/date/status;
- normalized customer-delivery tariff matrix;
- pair-level RouteCostIndex rows;
- compact product price/cost/commission/volume inputs per SKU;
- physical `SKU × origin` feasibility/capacity summaries;
- seller stock per SKU;
- sparse historical route/confidence evidence;
- optimizer thresholds.

It MUST NOT persist exact economics for every theoretical `SKU × origin × destination` combination.

`PlanningSnapshot` additionally records the applied downstream scenario:

```text
applied_supply_network
shipment_total_qty
optimization_mode
```

A network-only/downstream `/api/replan` recalculates candidate direct quotes/economics and global optimization from PlanningBasis when any of these change:

```text
selected_supply_network
shipment_total_qty
optimization_mode
```

It does not rerun ingestion, DemandEstimate, stockout, clean routes or RouteCostIndex normalization.

---

## 12. UI contract changes

The Plan scenario area now contains:

```text
Горизонт
Учитывать поставки в пути
Количество в поставку, шт.
Оптимизация: Максимум прибыли | Максимум маржи
Сеть поставки
Пересчитать план
```

Do not label `shipment_total_qty` simply as `Объём`, because product volume in liters is a separate tariff dimension.

Draft/applied semantics apply equally to network, shipment quantity and optimization mode.

The final result has two complementary views of one optimizer result.

### 12.1 Destination coverage

Example:

```text
SKU 34886 · Казань
Потребность      100
Наш план          96
из Казани         46
из Москвы         50
не покрыто         4
```

### 12.2 Physical origin supply plan

Example:

```text
Москва                     3 840 шт.
  SKU 34886                   150
  SKU 40749                   230

Пермь                      2 100 шт.
Казань                     1 520 шт.

Всего                      7 460 / 8 000
Не удалось разместить        540
```

The UI must expose why quantity is missing using the causal gap taxonomy.

Historical Flow, RouteCostIndex, direct SKU tariff, capacity and optimizer objective remain separately labeled evidence concepts.

---

## 13. Required acceptance cases

Implementation must prove at minimum:

1. **Greedy-trap avoidance:** global optimizer finds full 200-unit coverage in the §8 counterexample where LOCAL-first greedy covers only 100.
2. **Global SKU competition:** two or more SKUs compete for one `shipment_total_qty`; the optimizer chooses units globally rather than independently exhausting every SKU stock allowance.
3. **MAX_PROFIT difference:** with fixed quantity, higher total profit solution wins even when another SKU/route has higher margin rate.
4. **MAX_MARGIN difference:** with fixed quantity, higher aggregate unit-weighted margin-rate solution wins even when another solution has higher ruble profit.
5. **Quantity priority:** the optimizer never sacrifices feasible requested quantity for a small economic-score improvement.
6. **Restriction zero:** `ALLOWED + FINITE(0)` cannot receive allocation.
7. **Unlimited distinction:** `Без ограничений` remains UNLIMITED and is not confused with missing capacity.
8. **No warehouse summation:** cluster capacity uses max independently known finite alternative, not sum.
9. **Recommendation zero vs missing:** Ozon `0` yields explicit Safe target zero; `-` yields incomplete recommendation, never zero.
10. **Recommendation dedupe/conflict:** identical warehouse repetitions dedupe; conflicting `SKU × cluster` recommendation values block Safe comparison.
11. **Freshness:** report date and recommendation horizon are preserved when available.
12. **Secondary fields are explanatory:** zone/equipment/card-error/liquidity never become optimizer weights or independently override explicit allow/deny.
13. **Direct tariff primacy:** missing/ambiguous direct quote makes a non-local candidate unusable regardless of RouteCostIndex.
14. **RouteCostIndex isolation:** changing only RouteCostIndex cannot change a solution when exact economics/objective are not tied.
15. **Shipment cap accounting:** planned total never exceeds `shipment_total_qty`, and cap-driven unmet target is labeled separately.
16. **Unusable requested quantity:** when requested shipment exceeds all feasible eligible stock-supported demand, `unallocated_shipment_qty` is positive with explicit reasons.
17. **Destination identity:** rerouting demand through another origin never changes destination demand/need.
18. **Replan depth:** network/quantity/mode changes create a new PlanningSnapshot without recomputing upstream analysis.
19. **No SKU route matrix:** PlanningBasis carries tariff/index source once and computes concrete edge economics only for selected-network candidates.
20. **Cross-docking isolation:** seller supply/cross-docking tariffs remain outside DirectRouteQuote, RouteCostIndex and optimizer route economics.

---

## 14. Canonical implementation sequence

PR-A remains the current tariff foundation plan:

```text
docs/superpowers/plans/2026-09-08-pr-a-volume-band-direct-route-quotes-implementation.md
```

The following corrected plans supersede the older PR-B…PR-E plans:

```text
PR-B → docs/superpowers/plans/2026-09-08-pr-b-restrictions-candidate-graph-implementation.md
PR-C → docs/superpowers/plans/2026-09-08-pr-c-global-placement-optimizer-implementation.md
PR-D → docs/superpowers/plans/2026-09-08-pr-d-global-planning-snapshot-replan-implementation.md
PR-E → docs/superpowers/plans/2026-09-08-pr-e-global-placement-product-ui-implementation.md
```

Do not execute these superseded plans for new work:

```text
2026-09-08-pr-b-restrictions-capacity-coverage-planner-implementation.md
2026-09-08-pr-c-coverage-aware-max-margin-implementation.md
2026-09-08-pr-d-planning-snapshot-replan-api-implementation.md
2026-09-08-pr-e-selected-network-product-ui-implementation.md
```

They remain historical records only.

---

## 15. Precedence

For selected-network planning, precedence is now:

```text
2026-09-08 Global Placement Optimizer amendment
→ 2026-09-08 Route Cost Index amendment (remaining tariff-topology scope)
→ 2026-09-08 Selected Supply Network & Coverage Planner design (remaining scope)
→ 2026-09-03 real-data roadmap + matching PR specs
→ 2026-09-02 Product Completion design
→ UX-CONTRACT.md / DESIGN.md except where this amendment explicitly supersedes scenario/objective behavior
→ canonical SCOZ-lite runtime architecture
→ corrected PR-A…PR-E implementation plan
→ superseded/older implementation plans
```

Where older docs say `LOCAL first`, fixed greedy desired legs, per-SKU-only scarcity, or non-selectable `MAX_MARGIN`, this amendment wins.