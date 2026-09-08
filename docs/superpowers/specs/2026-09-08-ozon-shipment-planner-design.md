# Ozon FBO Shipment Planner & Article-First Plan — Design

**Date:** 2026-09-08  
**Status:** approved product/design correction  
**Scope:** Product Completion downstream execution layer after real-data PR5  
**Supersedes for the active roadmap:** `2026-09-08-selected-supply-network-coverage-planner-design.md`, `2026-09-08-route-cost-index-amendment.md`, and the old selected-network PR-A…PR-E implementation sequence wherever they describe alternate-origin coverage, RouteCostIndex-based future placement, network replan, desired coverage legs, or selected-network MAX_MARGIN scarcity.  
**Does not supersede:** destination-demand semantics, DemandEstimate, stockout/clean-route analytics, current FBO/inbound subtraction, historical Flow, existing route-economics analysis, Safe/Calculated analytical plan families, seller-stock evidence, SCOZ-lite runtime architecture, or the four top-level product sections.

## 1. Product outcome

The current milestone is not a generic network optimizer and does not create Ozon supply requests through Seller API.

The operator needs a practical answer:

> **what to ship, to which Ozon clusters, on which selected shipping date, by which selected hand-off method, and which Ozon XLSX templates to upload manually.**

The application must preserve the existing analytical calculation and add a separate operational execution layer:

```text
Observed Destination Demand
→ Demand Estimate
→ Calculated Need
→ current Safe / Calculated analytical plan
→ operational shippable quantities
→ selected shipment clusters
→ user-provided shipment opportunities (date + method + max clusters)
→ shipment batching / schedule recommendation
→ Ozon XLSX files
→ manual upload and slot booking in Ozon
```

The app recommends dates. It does **not** claim a slot is available or booked.

## 2. What remains unchanged

### 2.1 Destination still owns demand

`destination_cluster` remains customer-demand geography. Changing shipment dates, methods, cluster selection or batching never changes historical demand, DemandEstimate, stockout evidence or `calculated_need_qty`.

### 2.2 Current FBO and inbound remain upstream

The existing need formula remains authoritative:

```text
raw_need = raw_demand_forecast
         - current_fbo_stock
         - inbound_qty  # only when include_inbound is enabled

calculated_need_qty = max(0, ceil(raw_need))
```

Unknown FBO/inbound evidence is not coerced to zero.

### 2.3 Seller stock remains a separate physical ceiling

Seller available stock does not reduce demand. It limits what can actually be shipped after demand has been calculated.

### 2.4 Historical Flow and route economics remain analytical evidence

Existing `Потоки спроса` history, route substitutions, current modeled route economics and local counterfactuals remain in the product. They are not removed.

What is removed from the active roadmap is only the proposed **future-placement** use of RouteCostIndex / alternate-origin Coverage Planner.

## 3. Active milestone vs deferred work

### 3.1 Active now

- enrich the already-uploaded Ozon restrictions report with explicit capacity and placement-zone evidence;
- import product pack multiplicity from the supplier price workbook;
- convert the existing analytical plan into physically shippable whole-pack quantities;
- let the operator choose clusters to include in the current shipment run;
- let the operator define shipment opportunities: dates, hand-off methods and maximum clusters per shipment;
- respect volume/method/zone restrictions that are actually proven or configured;
- recommend batching and shipping dates;
- produce exact-format Ozon XLSX templates for manual upload;
- replace the wide `SKU × cluster` primary Plan table with article-first master/detail UX.

### 3.2 Explicitly deferred

- Ozon Seller API integration;
- live timeslot discovery or booking;
- creation of Ozon drafts/supply requests;
- cargo-box/pallet packing and label generation;
- brute-force slot search;
- alternate-origin demand coverage (`Москва` physically holding stock for `Казань` future demand);
- RouteCostIndex as a future-placement decision score;
- selected-network `/api/replan` and PlanningSnapshot layer from the superseded roadmap;
- global LP/min-cost-flow portfolio optimizer.

These may return only through a later approved design.

## 4. Source-of-truth data model

### 4.1 Existing Product Economics input

Current `ProductEconomicsInput` already owns:

- seller available stock;
- product volume in liters;
- price/cost/commission inputs used by existing economics.

Shipment planning MUST reuse this volume and seller-stock evidence. Do not create a second conflicting volume/stock source merely because the supplier price workbook also contains weight/volume columns.

### 4.2 Ozon restrictions workbook

The already-uploaded Ozon report remains the source for `SKU × warehouse` physical receiving evidence.

Preserve at least:

```text
SKU
article
cluster
warehouse
allowed
capacity_kind = FINITE | UNLIMITED | UNKNOWN
max_supply_qty
placement_zone
card_error
warehouse_equipment
liquidity_status
ozon_recommended_qty_56d
report_date
```

Hard physical rules:

```text
allowed == Да
AND capacity is UNLIMITED or FINITE(>0)
→ usable warehouse evidence
```

`Да + FINITE(0)` is not usable for positive quantity.

Secondary fields (`placement_zone`, card error, equipped, liquidity) never override explicit `allowed`; they explain and classify.

### 4.3 Cluster-level capacity remains conservative

The user plans by cluster, not by individual Ozon warehouse. Multiple warehouse maxima in one cluster are therefore **not summed** in this milestone.

For explicitly allowed warehouse alternatives:

```text
if any usable row is UNLIMITED:
    cluster capacity = UNLIMITED
elif any usable row is FINITE(>0):
    cluster capacity = max(positive FINITE values)
elif allowed rows exist but all are FINITE(0):
    cluster capacity = FINITE(0)
else:
    cluster capacity = UNKNOWN / ineligible
```

This preserves the previous safe non-additive capacity rule without the old Coverage Planner.

### 4.4 Placement-zone evidence

`Зона размещения` is preserved at warehouse level. Typical source values include sortable, non-sortable, KGT and unknown-zone states.

For `SKU × cluster` derive a bounded evidence status:

```text
KNOWN(zone)       # all usable known rows agree
MULTIPLE(zones)   # usable rows disagree
UNKNOWN           # no usable known zone
```

Do not silently choose one zone when warehouse evidence conflicts.

The shipment planner uses the zone for method compatibility and operational warnings. It does not recalculate Ozon's dimensional classifier itself.

### 4.5 Ozon 56-day recommendation

The restriction workbook also carries `Рекомендуемая поставка на 56 дней`.

Keep it as an external Ozon reference for comparison/Safe Plan. Numeric `0` is explicit zero; `-`/blank is missing, not zero. Deduplicate repeated warehouse rows at `SKU × cluster` and surface conflicts.

It never becomes a physical capacity.

## 5. Supplier pack multiplicity

### 5.1 Authoritative source in the supplied RTP workbook

For the current supplier price workbook, use sheet `Прайс списком` and these columns:

```text
B: КОД      → article
E: Упак     → packaging text
```

The minimum shipping multiplicity is the **right-hand integer after `/`** in `Упак`.

Examples verified in the supplied workbook:

```text
40749: 72/6 → pack_multiple = 6
40750: 36/6 → pack_multiple = 6
40751: 54/9 → pack_multiple = 9
51624: 72/6 → pack_multiple = 6
```

Important: the `Оглавление` cell labelled `КРАТНОСТЬ` is a currency-conversion divisor and is unrelated to product pack multiplicity. Never use it for shipment quantities.

The parser should tolerate a non-standard left side such as `100+/1` as long as the right-hand integer after `/` is valid and positive.

Missing, zero, negative, non-integer or conflicting pack multiplicity is incomplete evidence. It is never silently replaced with `1` for exportable shipment quantities.

### 5.2 Quantity invariant

Every operational shipment line must satisfy:

```text
shipment_qty % pack_multiple == 0
```

Pack multiplicity is applied downstream of analytical demand/plan. It must not rewrite historical demand or `calculated_need_qty`.

## 6. Analytical plan vs operational shippable plan

The existing analytical plan remains explainable and may contain quantities that are not pack multiples.

Create a new operational layer:

```text
ShippableLine
  sku
  article
  product_name
  destination_cluster_id
  analytical_plan_qty
  pack_multiple
  shippable_qty
  rounding_delta_qty
  current_fbo_stock
  inbound_qty
  seller_available_stock
  unit_volume_l
  total_volume_l
  capacity_kind
  capacity_qty
  placement_zone_status
  urgency_date
  reason_codes
```

### 6.1 Whole-pack transformation

For one `SKU × cluster`, the desired whole-pack ceiling for Calculated Plan is:

```text
desired_packs = ceil(analytical_plan_qty / pack_multiple)
```

A finite physical cluster capacity gives:

```text
capacity_packs = floor(capacity_qty / pack_multiple)
```

Seller stock gives one shared SKU-level pack pool:

```text
available_packs = floor(seller_available_stock / pack_multiple)
```

Only whole packs are allocated.

### 6.2 Preserve existing scarcity priority

Do not introduce a new portfolio objective in this milestone. When one SKU has fewer whole packs than its cluster demand, reuse the existing deterministic per-SKU allocation priority/eligibility semantics. The new operational layer changes the **unit of allocation from pieces to packs**, not the business objective.

This ensures:

```text
sum(shippable_qty for SKU) <= seller_available_stock
```

and every positive quantity is a pack multiple.

### 6.3 Rounding is explicit

If analytical plan is 17 and multiplicity is 6, the operational line may be 18 when stock/capacity allow. UI shows:

```text
17 → 18 шт. · кратность 6
```

The extra unit is `rounding_delta_qty`, not additional demand.

### 6.4 Safe Plan remains analytical reference

Safe Plan keeps its existing meaning as a conservative comparison. The active manual Ozon export uses the operationalized **Calculated Plan**. Do not silently redefine Safe Plan to exceed its ceiling because of pack rounding.

## 7. Selected shipment clusters

Cluster selection now means:

> include this destination cluster's operational plan in the current shipment-planning run.

It does **not** mean "allow this cluster to serve another destination's demand".

Changing selected shipment clusters:

- does not rerun demand, stockout or Flow;
- does not rewrite quantities for unselected clusters;
- recomputes only the downstream shipment plan/batching;
- may cause seller-stock whole-pack allocation to be recomputed over the selected shipment scope when the operator intentionally plans only a subset now.

The UI must distinguish the full analytical plan from the current shipment run.

## 8. Shipment opportunities

The operator defines one or more concrete opportunities for the current run.

```text
ShipmentOpportunity
  id
  ship_date
  method
  max_clusters
  max_volume_l
  lead_days
  enabled
```

Supported V1 method identities:

```text
PVZ_CROSSDOCK
SC_CROSSDOCK
DIRECT
```

User-facing labels remain Russian (`ПВЗ`, `СЦ`, `Прямая`).

### 8.1 Why opportunities are explicit

Without Ozon Seller API the app cannot know live slot availability. Therefore the operator supplies dates/methods they are willing to use, and the planner recommends how to fill them.

The result is a **recommended shipping schedule**, not a booked schedule.

### 8.2 Lead days

Without live Ozon routing/API evidence, cross-dock travel time must not be invented.

Each opportunity therefore carries operator-configured `lead_days` used only for scheduling urgency:

```text
latest_ship_date = urgency_date - lead_days
```

If the operator does not provide a usable lead time for a method that needs it, date quality is incomplete and the planner may rank urgency but must not label a date `safe`.

## 9. Method/rule registry

Operational rules change. Keep them in one backend-owned/versioned registry or Project settings, not scattered through frontend conditionals.

Initial reviewed rule for PVZ cross-dock planning:

- planned total volume must not exceed **1000 liters**;
- actual point capacity may be lower and is confirmed manually in Ozon;
- current Ozon public guidance also describes small box supplies and box/weight limits, but V1 has no cargo-packing model and therefore does not pretend to validate box count or per-box weight.

Source reviewed 2026-09-08: Ozon Marketplace public post `https://t.me/s/ozonmarketplace/2046`.

Initial conservative zone policy:

- `KGT` and `UNKNOWN/MULTIPLE` zone evidence are not auto-assigned to PVZ;
- sortable/non-sortable may be planned to PVZ only when the Ozon restriction itself permits the target cluster and all other known V1 constraints pass;
- SC/direct remain available subject to restriction/capacity and user configuration.

Any later change to these defaults must update the rule registry evidence/date and tests.

## 10. Shipment batching and scheduling

### 10.1 Atomic planning unit

The scheduler consumes whole-pack `ShippableLine` quantities. A line may be split across multiple shipment opportunities only in whole packs.

### 10.2 Constraints per shipment

For every planned shipment:

```text
unique_cluster_count <= opportunity.max_clusters
sum(line_volume_l) <= opportunity.max_volume_l  # when finite
all assigned line quantities are whole-pack multiples
all lines are compatible with the opportunity method/zone policy
```

### 10.3 Urgency

Use the existing demand rate and current FBO/inbound evidence to derive an explainable depletion/urgency date when possible. Unknown demand rate or stock evidence produces unknown urgency, not a fabricated far-future date.

The scheduler prefers the **latest feasible opportunity that is still on/before the line's latest recommended ship date**. This avoids shipping unnecessarily early while protecting urgent lines.

If no opportunity is on time, assign to the earliest feasible later opportunity when possible and mark `LATE_RECOMMENDATION` with days late.

### 10.4 Deterministic bounded heuristic

V1 is not a general optimizer. Use a deterministic bounded assignment:

1. sort shippable lines by known latest ship date ascending; unknown urgency last;
2. within the same urgency, larger total volume first, then stable cluster/article IDs;
3. for each line, consider enabled compatible opportunities sorted by:
   - on-time before late;
   - latest on-time date first;
   - fewer currently used clusters;
   - lower remaining-volume waste;
   - stable opportunity ID;
4. allocate the maximum whole-pack quantity that fits;
5. continue residual packs to the next feasible opportunity;
6. residual quantity with no feasible opportunity becomes `UNSCHEDULED` with exact constraint reasons.

No brute-force subset search.

## 11. Ozon XLSX export

The supplied Ozon template contains exactly:

```text
артикул
имя (необязательно)
количество
```

There is no cluster column. Therefore export ownership is:

```text
one XLSX = one cluster inside one planned shipment
```

For a shipment containing several clusters, return one ZIP:

```text
2026-09-16_PVZ_01.zip
  Москва.xlsx
  Казань.xlsx
  Пермь.xlsx
```

Each workbook preserves the official header names/order and contains only positive assigned quantities for that shipment+cluster.

Rows are keyed by seller article; `имя` uses the current product name when available. Quantity is integer and must satisfy the pack-multiple invariant.

Do not add helper columns to the Ozon workbook. Operational explanations remain in the app UI.

## 12. Internal API boundary

"No Ozon API" does not mean "no local backend endpoint".

Keep calculation in Python. The browser never implements quantity/scheduling formulas.

Recommended local surface:

```text
POST /api/shipment-plan
POST /api/shipment-export
```

`/api/shipment-plan` recalculates only the downstream operational plan from an immutable analysis/basis plus current shipment scenario.

`/api/shipment-export` renders the already-calculated shipment plan into XLSX/ZIP bytes and never recalculates demand.

No request is sent to `api-seller.ozon.ru` in this milestone.

## 13. Plan UX: article-first master/detail

### 13.1 Why the current table is replaced

The current primary Plan screen repeats a long product name once per cluster and forces the user to reason across a very wide `SKU × cluster` grid. Searching `40750` still produces many visually duplicated rows and hides the product as the main object of work.

The canonical Plan view becomes **article-first**.

### 13.2 Preserve the top-level information architecture

Keep the existing four sections:

```text
План
Потоки спроса
Экономика
Данные
```

Do not add a fifth global route just for shipments.

Inside `План`, use two sibling surfaces:

```text
Товары | Отгрузки
```

`Товары` is the default article-first workspace. `Отгрузки` is the cross-SKU shipment schedule/export workspace.

### 13.3 Article-first layout

Desktop composition:

```text
┌──────────────────────┬─────────────────────────────────────────────┐
│ Search + filters     │ 40750 · Герметик ...                       │
│                      │ SKU 3118873729                              │
│ article list         │ Кратность 6 · Остаток · Объём · Зона      │
│ one row = one SKU    ├─────────────────────────────────────────────┤
│                      │ Ozon → Наша потребность → Наш план         │
│                      ├─────────────────────────────────────────────┤
│                      │ cluster detail table for selected article   │
│                      ├─────────────────────────────────────────────┤
│                      │ shipment assignments for selected article   │
│                      ├─────────────────────────────────────────────┤
│                      │ diagnostics / evidence                      │
└──────────────────────┴─────────────────────────────────────────────┘
```

This intentionally reuses the interaction grammar of `Потоки спроса → По артикулу`: select one context on the left, keep all related evidence visible on the right.

### 13.4 Left article selector

One selectable row per SKU/article, not per cluster.

Show compactly:

- article / short product name;
- SKU secondary text;
- aggregate operational plan quantity;
- number of clusters with positive plan;
- one concise state badge when needed.

Search matches article, SKU and product name. Filters apply to article-level aggregates.

### 13.5 Right product workspace

Order is fixed:

1. **Product header** — article, name, SKU, pack multiple, seller stock, shippable stock in whole packs, unit volume, placement-zone summary;
2. **Decision line** — `Ozon → Наша потребность → Наш план` aggregated for the selected SKU with explicit incompleteness when any required component is unknown;
3. **Cluster table** — one row per destination cluster, focused columns only;
4. **Shipment assignments** — where this article appears in current planned shipments;
5. **Diagnostics/evidence** — incomplete FBO, pack, capacity, zone or scheduling evidence.

The primary details are not hidden behind repeated `Открыть детали` buttons.

### 13.6 Canonical cluster table columns

Default columns:

```text
Кластер
FBO
В пути
Ozon
Потребность
Аналитический план
Кратность
К поставке
Объём
Зона
Статус
```

Secondary economics/history remain available in `Экономика`, `Потоки спроса`, or a disclosure; do not restore the old 12+ column primary table.

### 13.7 Shipment workspace

`План → Отгрузки` owns:

- selected cluster scope;
- opportunity editor (date, method, lead days, max clusters, volume limit where editable);
- action `Рассчитать отгрузки` / `Пересобрать отгрузки`;
- shipment cards/list grouped by date and method;
- totals: clusters, SKU lines, pieces, liters;
- late/unscheduled warnings;
- `Скачать шаблоны Ozon` per planned shipment.

Changing shipment inputs does not mark DemandEstimate stale. It only marks the shipment plan stale.

### 13.8 Visual system

Reuse the existing engineering-console design system and tokens. No new palette, gradient, dashboard KPI mosaic or decorative cards.

The distinctive system signature remains the decision line. Shipment cards use restrained logistics-manifest structure: date/method as header, cluster list and physical totals as content, status/warnings as evidence.

No full-screen modal for ordinary planning. Native semantic controls, visible focus, stable busy geometry and local clearable search remain mandatory.

At implementation time, update root `DESIGN.md` and `UX-CONTRACT.md` in the same PR as the runtime UI so the article-first owner, Plan subviews, shipment-opportunity behavior and stale-state ownership are mirrored by the canonical project contracts.

## 14. State ownership and recalculation

There are now two independent dirty layers:

```text
analysis_dirty
shipment_plan_dirty
```

Examples:

- horizon / inbound / source file changed → `analysis_dirty = true`;
- selected shipment clusters / dates / methods / max clusters / lead days changed → `shipment_plan_dirty = true` only;
- successful full analysis invalidates any old shipment plan and returns new operational basis;
- successful shipment-plan calculation clears only `shipment_plan_dirty`.

The UI never presents a shipment plan calculated from different analytical inputs as current.

## 15. Active PR-A…PR-E roadmap

The old selected-network implementation plans remain historical evidence and MUST NOT be executed for the active milestone.

New active sequence:

### PR-A — Supply Facts & Pack Multiplicity

- restriction capacity kind + placement zone + Ozon 56-day reference;
- supplier `Упак` multiplicity importer;
- normalized cluster physical facts;
- no shipment quantities yet.

### PR-B — Multiplicity-Aware Shippable Plan

- operationalize current Calculated Plan into whole-pack `ShippableLine`s;
- respect seller stock and finite cluster capacity;
- preserve current per-SKU scarcity priority;
- expose rounding deltas and volume totals.

### PR-C — Shipment Batching & Schedule

- selected shipment cluster scope;
- shipment opportunities;
- PVZ 1000 L rule + configurable method registry;
- deterministic urgency/date assignment;
- late/unscheduled causal reasons.

### PR-D — Local Shipment API & Ozon Export

- `/api/shipment-plan`;
- exact Ozon XLSX renderer;
- ZIP per multi-cluster shipment;
- no Ozon Seller API.

### PR-E — Article-First Plan & Shipment UI

- `План → Товары | Отгрузки`;
- left article selector + right detail workspace;
- focused cluster table;
- shipment opportunity editor/schedule/export;
- durable `DESIGN.md` + `UX-CONTRACT.md` updates and browser/zoom/accessibility acceptance.

## 16. Acceptance examples

### 16.1 Multiplicity

Given:

```text
article = 40750
analytical plan Moscow = 17
pack_multiple = 6
seller stock sufficient
cluster capacity sufficient
```

Then:

```text
shippable Moscow = 18
rounding_delta = +1
```

### 16.2 Seller stock

Given multiplicity 6 and seller stock 20, no combination of planned lines may consume more than 18 pieces because only three complete packs exist.

### 16.3 PVZ volume

A PVZ shipment opportunity with default 1000 L may never receive planned lines whose assigned total volume exceeds 1000 L. Residual whole packs move to another compatible opportunity or become unscheduled.

### 16.4 Max clusters

A shipment with `max_clusters = 3` never contains four unique destination clusters even when volume remains.

### 16.5 Export

For one planned shipment containing Moscow, Perm and Kazan, export returns a ZIP with exactly three Ozon-format XLSX files and no cluster helper column inside them.

### 16.6 UI

Searching article `40750` selects one article item. The right workspace shows all its cluster rows without repeating the full product name in every row. Primary details are visible without an `Открыть детали` action.

## 17. Final architectural boundary

The active product is:

```text
ANALYTICS
Demand / stockout / Flow / economics
        ↓
ANALYTICAL PLAN
Ozon vs our need vs Calculated Plan
        ↓
OPERATIONALIZATION
restrictions + seller stock + pack multiplicity
        ↓
SHIPMENT PLANNER
selected clusters + dates + methods + max clusters + volume rules
        ↓
MANUAL EXECUTION
Ozon XLSX download → operator uploads/books slot in Ozon
```

This is the complete current milestone. Anything that books a live slot or creates a supply request belongs to a future Ozon API milestone.