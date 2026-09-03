# Real-Data Demand, Stockout Impact & Flow — Design

**Date:** 2026-09-03  
**Status:** approved design; implementation split into five PRs  
**Supersedes:** presentation/real-data limitations of `2026-09-02-ozon-fbo-product-completion-design.md` where this document is more specific  
**Does not supersede:** portable runtime architecture, unit economics contracts, MAX_MARGIN strategy, or existing destination-demand semantics

## 1. Why this design exists

Product Completion works end-to-end on synthetic acceptance fixtures, but real Ozon data exposed three product gaps:

1. the Flow screen renders an unbounded number of entities and links, so a real dataset becomes an unusable vertical wall of cards, SVG lines and route buttons;
2. diagnostics are emitted as raw repeated technical messages instead of grouped actionable data-quality states;
3. the existing stockout model and route economics are mostly period aggregates, while the operator needs to understand how local fulfillment changes over time, when probable stockout/substitution occurs, who covers the displaced demand, and how much money the routing distortion costs.

A fourth requirement is foundational and non-negotiable: planning must use the demand of the customer destination cluster, never the physical dispatch volume of a donor/origin cluster.

This design therefore separates four concepts that must never be conflated:

```text
observed destination demand
physical fulfillment routing
probable stockout/substitution distortion
placement economics / plan
```

## 2. Canonical business invariants

### 2.1 Destination owns demand

`destination_cluster` is the geography where customer demand arose.

For an order fulfilled `Москва → Казань`:

- Kazan demand increases by the order quantity;
- Moscow demand does not increase;
- Moscow is only the fulfillment origin/donor for that order.

Planning for `SKU × cluster` is based exclusively on destination demand.

### 2.2 Origin routing never creates donor demand

Physical dispatch volume from an origin may be much larger than that origin's own customer demand because the origin covers neighboring stockouts.

Example:

```text
Москва → Москва  500
Москва → Казань  300
Москва → Тверь   200
```

Physical dispatch from Moscow = 1000, but Moscow destination demand = 500.

The calculated need for Moscow must be derived from 500, never from 1000.

### 2.3 External fulfillment does not erase destination demand

Example:

```text
Москва → Казань 300
Казань → Казань   0
```

Kazan destination demand remains 300 even though local fulfillment is zero.

### 2.4 Demand and route history are separate evidence streams

A probable stockout/substitution episode may make historical routing unrepresentative of the desired placement profile. It must not automatically delete valid customer destination demand.

Route cleaning protects logistics/economics. It does not rewrite where the customer demand occurred.

### 2.5 No fabricated latent demand

For this roadmap, “true demand” means **routing-independent observed destination demand**: the demand visible in orders, attributed to the destination regardless of which origin fulfilled it.

The application does not fabricate orders that never occurred because the item was unavailable everywhere. If evidence suggests total suppression, confidence may fall and the period may be marked censored/affected, but quantity is not invented without a separate approved model and source.

### 2.6 Economics does not create demand

Route economics changes placement priority and quantifies historical routing loss. It never multiplies destination demand or calculated need.

### 2.7 Backend owns all business calculations

The frontend may sort, filter, select and render already-calculated presentation aggregates. It must not calculate demand, stockout, route cleaning, logistics, margin, profit or planning quantities.

### 2.8 Existing plan semantics remain

- `Calculated Plan` is the primary “Наш план”.
- `Safe Plan` is the conservative reference.
- one optimizer objective only: `MAX_MARGIN`.
- seller stock remains per SKU.
- unknown remains `None`, never coerced to zero.

## 3. End-state causal model

```text
                         DESTINATION DEMAND
                                │
                                ├──► demand estimate ─► need ─► plan
                                │
orders ─► daily facts ──────────┤
                                │
                                ▼
                      ORIGIN → DESTINATION
                                │
                                ▼
                        local-share history
                                │
                                ▼
                    probable stockout episodes
                                │
                                ▼
                         donor substitution
                                │
                                ▼
                         route economics
                                │
                                ▼
                       logistics / margin / ₽ loss
```

The two branches separate immediately after order normalization. Routing evidence never feeds back into destination demand quantity.

## 4. Five-PR roadmap

The work is intentionally split into five mergeable PRs. Each PR must be independently testable and may not pull later responsibilities forward.

### PR1 — True Demand & Daily Fulfillment Foundation

**Purpose:** create one canonical daily facts layer and prove that planning is invariant to origin routing.

Deliverables:

- backend-only `DailyDemandCell` grouped by `date × SKU × destination`;
- backend-only `DailyFulfillmentCell` grouped by `date × SKU × origin × destination`;
- one linear pass from normalized `OrderRecord` into daily facts;
- existing weekly demand and weekly routes derived from daily facts;
- existing M1/M2/L demand estimate unchanged;
- existing need formula unchanged;
- origin mix may change fulfillment/routes but cannot change demand, demand estimate or need;
- no large daily dataset is added to browser snapshot.

Merge proof includes the donor-inflation trap, mirror external-fulfillment case and origin-permutation invariance.

Detailed PR1 design: `docs/superpowers/specs/2026-09-03-pr1-true-demand-daily-fulfillment-design.md`  
Detailed PR1 implementation plan: `docs/superpowers/plans/2026-09-03-pr1-true-demand-daily-fulfillment-implementation.md`

### PR2 — Daily Stockout Episodes & Precise Route Cleaning

**Purpose:** turn daily fulfillment facts into a time-localized explanation of probable substitution.

Required semantics:

- detection identity is `SKU × destination`, never cluster-only;
- preserve the existing historical concept: high prior local share, material local-share drop, external replacement rise and retained destination demand;
- daily presentation evidence is based on daily facts and a 7-day rolling view to suppress one-day noise;
- current availability / `days_without_stock` is corroboration, not proof of historical stock state;
- output explicit episodes with start/end dates and replacement origins;
- route cleaning becomes episode-aware so contaminated route evidence can be excluded more precisely than a whole synthetic aggregate;
- destination demand history is not removed merely because routing changed;
- weekly stockout compatibility remains available until the new episode detector is proven equivalent or intentionally superseded by a dedicated PR2 spec.

PR2 must produce backend contracts suitable for PR3 but must not redesign the Flow frontend.

### PR3 — Stockout Financial Impact & Presentation Aggregates

**Purpose:** quantify the economic cost of observed substitution and build bounded presentation data for the later UI.

For each relevant route/day/episode, backend applies current modeled economics to historical quantities and exposes separately:

```text
extra_logistics_rub
margin_delta_pp
profit_delta_per_unit
profit_loss_rub
```

Canonical interpretation:

- these values are modeled using current tariffs/settings against historical observed quantities;
- they are not claimed to be historical invoice charges unless a source explicitly provides them;
- observed-period values and any future forecast-horizon values must be separately named and labelled;
- incomplete route economics stays `None` with reasons.

PR3 also creates bounded presentation aggregates such as:

```text
DestinationDailySeries
StockoutEpisodeView
EpisodeDonorBreakdown
EpisodeSkuBreakdown
DestinationImpactSummary
```

Exact names may vary in the dedicated PR3 spec, but the interfaces must keep destination demand, routing and economics separate.

The browser must not receive raw orders or an unbounded daily route matrix.

### PR4 — Data Quality & Real-Data Coverage

**Purpose:** make incomplete real-data calculations actionable and determine whether missing coverage represents source gaps or normalization/import defects.

The following repeated raw diagnostics must be grouped by cause and affected entity:

- `MISSING_TARIFF`;
- `MISSING_SELLER_AVAILABLE_STOCK`;
- `MISSING_PRODUCT_ECONOMICS`;
- `MISSING_ARTICLE_TO_SKU`;
- `WORKSHEET_DIMENSION_REPAIRED`;
- aggregate blockers such as `INCOMPLETE_LOGISTICS_COVERAGE`.

User-facing diagnostics must answer:

1. what is incomplete;
2. how many routes/SKUs/articles are affected;
3. what calculation is blocked;
4. what the user can inspect or fix.

Example:

```text
34 маршрута без тарифа
Экономика этих маршрутов не рассчитана.
[Посмотреть маршруты]
```

Raw codes remain available only in a technical disclosure.

PR4 may fix real mapping/import defects discovered by the coverage analysis, but must not hide genuinely missing data with fabricated defaults.

If investigation reveals a major independent tariff/source defect rather than a bounded mapping/import correction, create an additional narrowly-scoped PR between PR4 and PR5 instead of inflating PR4.

### PR5 — Real-Scale Flow & Stockout Impact UI

**Purpose:** replace the current unbounded Flow implementation with a decision screen that remains usable on real datasets.

The screen's single job is:

> show where demand arose, who fulfilled it, when local fulfillment broke down, and what the distortion cost.

Required layout behavior:

- search/select destination/origin/SKU instead of rendering every object as a giant card;
- selected-object list uses internal scroll and bounded height;
- visual route area has fixed/bounded height;
- show a bounded number of major links (default Top 8) and aggregate the remainder as `Прочие` for overview presentation;
- selecting an explicit route still exposes its exact backend values;
- no global Sankey/chord and no `links × 90px` canvas growth;
- local and external fulfillment are visually distinguishable;
- SKU breakdown appears only for the selected route/episode context;
- destination/origin/SKU modes remain available;
- observed/clean evidence remains available but is explained as routing evidence, never as demand geography.

The signature visual element is the **locality timeline**:

- daily/rolling local fulfillment share;
- destination demand volume in the same time context;
- highlighted probable stockout/substitution episodes;
- episode-level external units and economic loss;
- drill-down to donor origins and SKUs.

Example information hierarchy:

```text
МОСКВА · собственный спрос 8 420 шт.

Локально 63%   Извне 37%   Потеря прибыли 84 600 ₽

Динамика локальности
local %: 92 91 89 48 22 17 25 78 92 94
                  █ probable stockout █
demand : steady destination demand bars

04–08 августа
155 шт. перекрыто другими кластерами
+12 840 ₽ логистики
−15 460 ₽ прибыли
−4,2 п.п. маржи
[Разобрать эпизод]
```

PR5 real-browser acceptance must use a dataset large enough to reproduce the failure mode seen with the real Ozon report. Tiny synthetic topology alone is insufficient.

## 5. Planning contract in detail

For every `SKU × destination`:

```text
destination orders
    ↓
weekly destination demand
    ↓
M1 → M2 → L
    ↓
current_weekly_rate
    ↓
raw_demand_forecast = current_weekly_rate × horizon_days / 7
    ↓
calculated_need = ceil(forecast − destination FBO − destination inbound)
    ↓
Calculated/Safe allocation
```

Origin routing is absent from this quantity path.

The following must be impossible by contract:

```text
origin shipped 1000
therefore origin demand = 1000
```

## 6. Daily fact populations

A normalized order can contribute to two different analytical populations.

Demand population:

- use existing net-demand lifecycle semantics;
- group by calendar event date, SKU and destination;
- fulfilled and in-progress behavior remains consistent with existing demand contracts;
- cancelled does not become demand.

Fulfillment population:

- use existing fulfilled-route semantics;
- group by calendar event date, SKU, origin and destination;
- in-progress orders may contribute to demand while not yet contributing to physical fulfilled routing.

Therefore the equality `demand == fulfilled routes` is not a valid invariant.

## 7. Stockout interpretation

A probable stockout/substitution episode is evidence that the observed fulfillment geography is distorted, not proof that demand moved to the donor cluster.

The detector must reason at `SKU × destination` level first. Cluster-wide summaries are presentation aggregations of SKU-level evidence.

A typical episode has:

- historically/local baseline with high local share;
- material local-share deterioration;
- one or more external origins increasing their share;
- destination demand broadly retained rather than disappearing in the same proportion;
- optional current availability corroboration.

The application must describe such episodes as probable/likely substitution unless historical inventory evidence proves a stronger statement.

## 8. Economic interpretation

For an external route `origin → destination`, compare current modeled economics with feasible local `destination → destination` placement for the same SKU.

Expose three distinct business effects:

```text
extra logistics = (current route logistics − local logistics) × evidence qty
margin effect   = local net margin − current net margin, p.p.
profit effect   = (local profit/unit − current profit/unit) × evidence qty
```

Do not collapse these into one ambiguous metric.

Negative values remain negative and mean local placement would be worse.

## 9. Diagnostics presentation contract

Diagnostics must have a two-layer presentation.

### User layer

Grouped by actionable cause and severity, with counts and affected entities.

Examples:

```text
КРИТИЧНО
34 маршрута без тарифа
7 SKU без доступного остатка продавца
9 SKU отсутствуют в Юнитке

ПРЕДУПРЕЖДЕНИЯ
18 статей Юнитки вне текущего SKU universe
25 диапазонов Excel автоматически восстановлены
```

### Technical layer

Expandable raw diagnostic details containing codes and entity identities for debugging.

Repeated identical raw messages must never be the primary user interface.

## 10. Frontend design direction

The UI is an operational engineering console, not a decorative dashboard.

Design priorities:

1. bounded information density;
2. one selected context at a time;
3. structural visual hierarchy derived from the causal model;
4. plain Russian copy using business concepts rather than backend terms;
5. keyboard-visible focus, 200% zoom, narrow desktop, reduced motion and forced-colors support;
6. no unbounded lists/canvases;
7. no duplicate presentation of the same route in multiple giant controls.

The memorable element is the locality timeline because it directly expresses the business problem: local fulfillment collapses while destination demand persists and external donors rise.

## 11. Real-data acceptance principles

Every PR after PR1 must be tested not only with a small deterministic fixture but also with a real-scale or generated stress fixture representative of tens of thousands of order rows and many route links.

Acceptance questions include:

- can the operator identify the destination's own demand without confusing donor dispatch volume;
- can the operator see whether a cluster is a donor for neighboring demand;
- can the operator identify probable substitution episodes by date;
- can the operator see which origins covered the episode;
- can the operator quantify extra logistics, margin and profit effect where economics is complete;
- can the operator understand why an impact is not calculated when data is incomplete;
- does the UI remain bounded when an SKU or destination has dozens of routes;
- does no frontend formula re-create backend business logic.

## 12. Dependency graph

```text
PR1 Daily facts / true destination demand
  │
  ▼
PR2 Daily stockout episodes / precise cleaning
  │
  ▼
PR3 Economic impact / bounded presentation aggregates
  │
  ├──────────────► PR4 Data quality / coverage
  │                    │
  └────────────────────┘
           │
           ▼
PR5 Real-scale Flow & stockout UI
```

PR5 must not start from a guessed frontend model before PR3 and PR4 contracts are stable.

## 13. Scope that remains explicitly out

This roadmap does not introduce:

- portfolio/global cross-SKU optimization;
- MAX_PROFIT or MAX_VOLUME selectors;
- automatic order submission to Ozon;
- invented historical inventory levels;
- fabricated lost orders/latent demand;
- React, npm or a new frontend framework;
- a server architecture rewrite;
- global Sankey/chord visualization;
- raw buyer/order PII in snapshot or browser state.

## 14. Documentation rule for future Codex tasks

Every implementation task for this roadmap must cite this design document and the dedicated PR-specific spec/plan.

Do not reconstruct requirements from chat history.

If a later discussion intentionally changes a business invariant, update this document (or add a dated superseding design document) before issuing Codex implementation instructions.
