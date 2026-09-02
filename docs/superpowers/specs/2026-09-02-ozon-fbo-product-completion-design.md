# Ozon FBO Product Completion — Design

**Date:** 2026-09-02  
**Status:** approved design; implementation pending

## 1. Status and supersession

This document is the canonical Product Completion design for `sklad_ozon`.

It **does not replace** the canonical runtime architecture in `2026-08-20-scoz-lite-portable-architecture-design.md`. The existing local Python + FastAPI + committed vanilla HTML/CSS/JavaScript boundary remains unchanged.

It extends and, where explicitly stated below, supersedes product/business limits from `2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`.

Intentional changes:

1. the application computes its own explainable demand estimate;
2. Ozon recommendation becomes a comparison/control signal, not the only quantity ceiling;
3. the product exposes **Safe Plan** and **Calculated Plan** side by side;
4. route economics is first-class: ₽, `% of realization`, final margin impact in p.p., and profit opportunity;
5. the frontend becomes a decision tool with a dedicated visual `Потоки спроса` mode.

Business invariants not changed here remain in force.

## 2. Product goal

For every relevant `SKU × destination cluster`, the application must answer:

1. where customer demand arose;
2. from which origin clusters that demand was fulfilled;
3. whether fulfillment geography was probably distorted by stockout/substitution;
4. what the recent destination-demand level is and how it is changing;
5. how many units are needed for a user-selected horizon;
6. what Ozon recommends and whether the two quantities are directly comparable;
7. what each origin→destination route costs in ₽ and as `% of realization`;
8. what margin/profit effect a feasible local placement would have;
9. how limited seller stock should be allocated under the chosen objective;
10. why the application reached its recommendation.

Decision sequence:

`Where demand arose → who fulfilled it → what that routing costs → current demand regime → our need → Ozon comparison → allocation plan`.

## 3. Non-negotiable semantics

- `destination_cluster` = customer-demand geography.
- `origin_cluster` = physical fulfillment/dispatch source.
- `Казань → Москва` is Moscow demand fulfilled from Kazan, never Kazan demand.
- economics changes placement priority, not demand quantity.
- current availability corroborates historical stockout inference; it does not prove historical stock state.
- frontend code contains no demand, stockout, route-economics, unit-economics or optimizer formulas.

## 4. Product architecture

Do not rewrite working ingestion/analytics/economics/supply modules without cause. Product Completion adds or repairs five decision-layer responsibilities:

1. **Demand Estimate Engine** — recent destination demand and three-level dynamic.
2. **Ozon Comparison** — Ozon vs our need with horizon/comparability state.
3. **Route Economics** — actual origin→destination model economics and local counterfactual.
4. **Need Engine** — demand forecast minus cluster stock/inbound according to scenario.
5. **Scenario Allocator** — Safe/Calculated allocations under `Макс. прибыль` or `Макс. маржа`.

A successful run returns an immutable aggregated analysis snapshot. Raw orders are not required in the browser.

## 5. Repair historical stockout/route cleaning

### 5.1 Historical route evidence

Existing strong route-shift thresholds remain the starting policy:

- prior local share >= 60%;
- local share drop >= 30 p.p.;
- external replacement rise >= 20 p.p.;
- fulfilled weekly quantity >= 10;
- destination demand retention >= 60% of baseline;
- completed periods only.

When historical route evidence meets the strong criteria, that **route period is cleaning-eligible independently of current availability**.

The stockout output must keep separate concepts equivalent to:

```text
historical_evidence_strength
route_cleaning_eligible
availability_corroboration
confidence
```

Current availability can raise/lower displayed confidence but is not required to clean a historically contaminated route period. A contradictory current snapshot cannot automatically put a strong historical substitution route back into clean route history.

### 5.2 Demand history is not route history

A route-substitution week is **not automatically removed from destination-demand history**.

If Moscow demand was fulfilled from Kazan, the Moscow destination orders remain valid Moscow demand. Route cleaning is therefore separate from demand-week eligibility.

For Product Completion MVP, a week is eligible for the primary demand median when:

- it is a completed week;
- the order lifecycle population is valid;
- destination cluster identity is resolved;
- the source period is not known incomplete/corrupt.

A probable stockout/route shift may lower demand confidence or add evidence, but does not erase destination demand simply because origin changed. Suppressed demand must not be invented from missing orders without period-specific stock evidence.

This separation is intentional: the robust median protects the demand estimate from ordinary spikes/dips; route cleaning protects logistics/economics from donor substitution.

### 5.3 Availability enrichment

Where the source report provides them, retain normalized fields including `daysWithoutStock`, report date, current FBO quantity and other direct availability evidence. Missing source evidence stays unknown/null, never assumed zero.

## 6. Route-profile fallback hierarchy

Expected logistics must implement the full fallback hierarchy:

1. `SKU × origin` clean profile;
2. `SKU × origin` observed profile;
3. origin profile across all SKUs;
4. global fulfilled route profile.

Every profile carries source level, sample size and confidence. Uncovered tariff share is never renormalized away.

## 7. Own demand estimate

### 7.1 Source population

Demand is attributed exclusively by destination.

Use completed weekly net demand (`fulfilled + in_progress`, excluding cancelled). The current incomplete ISO week is excluded from the base/trend calculation.

The phrase **demand-eligible full week** below means a completed, data-quality-valid destination-demand week as defined in §5.2. It does not mean “every probable stockout week removed”.

### 7.2 Eight-week three-level model

Use the latest eight demand-eligible full weeks in chronological order.

- `M1` = median of weeks 1–4;
- `M2` = median of weeks 5–8;
- `L` = latest full week, i.e. week 8.

The UI exposes the three levels directly:

`M1 → M2 → L`

Example: `19,5 → 24,5 → 29 шт./нед.`.

### 7.3 Regime

For `M1 > 0`:

- growth: `M2 / M1 - 1 > +10%`;
- stable: change within `±10%` inclusive;
- decline: change `< -10%`.

For `M1 = 0`, do not divide by zero or report infinite growth. A transition to positive demand is explicitly marked as a transition/insufficient historical baseline.

### 7.4 Latest-week confirmation

Using the same tolerance around `M2`:

- growth confirmed when `L > M2 × 1.10`;
- decline confirmed when `L < M2 × 0.90`;
- stability confirmed when `L` is inside `M2 ±10%`.

The latest week confirms or challenges the regime; it is not the forecast baseline by itself.

### 7.5 Current weekly rate

Base = `M2`.

For confirmed growth/decline:

```text
raw_adjustment = 0.5 × (L - M2)
cap = ±20% of M2
current_weekly_rate = M2 + clamp(raw_adjustment, -0.20 × M2, +0.20 × M2)
```

For stable regime or unconfirmed growth/decline:

```text
current_weekly_rate = M2
```

Expose separately: `M1`, `M2`, `L`, regime, confirmation, adjustment and final weekly rate.

### 7.6 Short-history fallback

- 8+ eligible weeks: full model.
- 4–7: median of all eligible weeks, no trend adjustment, confidence at most medium.
- 1–3: median of available eligible weeks, no trend adjustment, low confidence.
- 0: own estimate incomplete; do not fabricate zero.

Observed-vs-clean route fallbacks remain a separate logistics concept and are not reused as a hidden demand formula.

## 8. Horizon and calculated need

### 8.1 No safety buffer

No automatic safety stock/buffer exists. User-selected days are the entire coverage target.

```text
raw_demand_forecast = current_weekly_rate × horizon_days / 7
```

Keep the raw forecast as a decimal for explanation. Shipment quantities are integers.

### 8.2 Inbound flag

Scenario flag:

`Учитывать поставки в пути` — boolean, default enabled.

Without inbound:

```text
raw_need = raw_demand_forecast - current_fbo_stock
```

With inbound:

```text
raw_need = raw_demand_forecast - current_fbo_stock - inbound_qty
```

Canonical integer need:

```text
calculated_need_qty = max(0, ceil(raw_need))
```

This intentionally rounds upward only after stock/inbound subtraction so the selected horizon is not under-covered because of fractional forecast units.

The UI always shows current FBO stock and inbound separately. Unknown stock/inbound evidence is not coerced to zero unless the importer/source proves zero.

## 9. Ozon comparison

For each `SKU × destination` expose:

- Ozon recommended quantity;
- Ozon recommendation horizon when known;
- our selected horizon;
- raw demand forecast;
- calculated need to supply;
- `Δ units` and `Δ %` where meaningful;
- comparability status;
- confidence and human-readable disagreement reasons.

Never linearly scale Ozon recommendation to our horizon.

If horizons differ, show both originals and `Горизонты различаются`. Difference may be displayed for orientation, but it must not be presented as a clean like-for-like model error.

## 10. Hybrid plan model

Both plan families are computed under the same chosen optimization objective and shown side by side.

### 10.1 Safe Plan

```text
safe_ceiling = min(ozon_recommended_qty, calculated_need_qty, physical_ceiling)
```

Safe allocation never exceeds Ozon recommendation, our own need or physical feasibility.

### 10.2 Calculated Plan

```text
calculated_ceiling = min(calculated_need_qty, physical_ceiling)
```

Calculated allocation is independent of Ozon quantity.

### 10.3 Primary recommendation

**Calculated Plan is the primary “Наш план” recommendation. Safe Plan is the conservative comparison/reference.**

The application does not automatically submit anything to Ozon, so no extra “commit plan” selector is required in this phase. Both allocations remain visible for comparison.

Recommendation distortion changes trust/explanation; it never creates demand.

## 11. Scenario allocator

Seller stock is not fungible across SKUs. Allocation runs independently per SKU using that SKU's available seller quantity as the total stock ceiling.

If total eligible need is smaller than seller stock, the remainder is left unallocated.

The user chooses one objective:

### 11.1 `Макс. прибыль`

Fill eligible cluster ceilings in descending expected absolute net profit per incremental unit.

### 11.2 `Макс. маржа`

Fill eligible cluster ceilings in descending net margin rate after all modeled costs.

Deterministic tie-breaks:

1. primary objective;
2. higher route/demand confidence;
3. lower distortion risk;
4. larger eligible need;
5. stable cluster ID.

Existing configurable minimum profit/margin/ROI thresholds remain eligibility constraints unless a later approved decision removes them.

The UI may show a compact outcome comparison for both objectives, but only one objective drives `Наш план` at a time.

There is no `Макс. объём` objective because available SKU quantity is already fixed.

## 12. Route economics

For every relevant `SKU × origin × destination` route expose:

- observed fulfilled quantity and route share;
- modeled route logistics cost ₽ under the imported/current tariff/economics inputs;
- route cost as `% of realization`;
- modeled current profit/unit and net margin;
- feasible local `destination → destination` counterfactual;
- local route cost `% of realization`;
- local counterfactual net margin;
- margin delta p.p.;
- profit delta per unit;
- completeness/confidence/reasons.

This is a **modeled current-economics comparison applied to observed route mix**, not a claim about historical invoice charges unless a source explicitly provides those charges.

### 12.1 Counterfactual

For `Казань → Москва`, compare the Kazan-origin economics with a feasible Moscow-local placement for the same SKU and destination context. Hold non-route assumptions constant; change route/placement-dependent costs according to backend tariff/economics contracts.

If local placement is infeasible, tariff coverage missing or unit economics incomplete, counterfactual = `not computable`, never zero benefit.

### 12.2 Two percentages must both be visible

Example:

- logistics: `10,1% → 7,1% of realization`;
- final net margin: `18,4% → 21,4% = +3,0 п.п.`.

### 12.3 Profit opportunity time basis

Do not use one ambiguous `profit_opportunity_rub` without a period label.

Canonical values:

```text
observed_profit_opportunity_rub
  = profit_delta_per_unit × observed_route_qty_in_analysis_period
```

This is the default ₽ value in `Потоки спроса` because it answers “сколько этот фактический поток стоил бы при текущей экономике”.

A projected value may also be computed when the backend has a valid forecast volume and route-share basis:

```text
forecast_profit_opportunity_rub
```

It must be separately labelled with the selected forecast horizon. Never mix observed-period and forecast-horizon ₽ values.

### 12.4 Economics does not create demand

A +3 p.p. local benefit changes cluster placement priority for known demand. It never multiplies need.

## 13. Cluster identity and freshness

All importers must resolve cluster identity through one canonical normalization/alias/manual-mapping layer. Independently normalized free text is not guaranteed identity.

Ambiguous unresolved clusters visibly block affected calculations. Manual mappings persist in Project JSON.

Populate report metadata where available:

- generated date;
- period start/end;
- Ozon recommendation horizon.

Analysis snapshot includes freshness/comparability warnings. Old/restored or materially mismatched reports cannot silently appear current.

## 14. Immutable analysis snapshot

Every successful calculation produces a self-contained immutable snapshot. Changing source files, mappings, horizon, inbound flag or objective marks the current result as requiring recalculation; only a successful new run atomically replaces it.

At minimum:

```text
snapshot_id
created_at
report_meta + freshness
scenario_settings
input_statuses
summary
decision_rows
demand_estimates
observed_routes
clean_routes
stockout_signals
distortion_signals
route_economics
unit_economics
safe_allocations
calculated_allocations
flow_view_aggregates
diagnostics
```

No raw order rows or buyer/customer PII are sent as presentation state.

## 15. Information architecture

Top-level sections:

1. **План** — primary decision and allocation.
2. **Потоки спроса** — visual demand/fulfillment analysis.
3. **Экономика** — detailed unit and route economics.
4. **Данные** — files, freshness, settings, mappings, diagnostics.

The import form moves out of the primary decision screen.

## 16. `План`

Scenario controls:

- horizon days;
- inbound flag;
- objective `Макс. прибыль` / `Макс. маржа`;
- `Пересчитать план`.

Canonical visual sequence:

`Ozon → Наша потребность → Наш план`

Safe Plan is shown alongside as the conservative reference.

Main table default business fields:

- article / SKU / product;
- destination cluster;
- dynamic `M1 → M2 → L` and regime;
- Ozon recommendation;
- our need;
- delta;
- Safe Plan;
- Our/Calculated Plan;
- route overcost/local opportunity;
- net margin;
- expected plan profit;
- confidence/status.

Fast filters:

- `Все`;
- `Есть расхождение`;
- `Вероятный дефицит`;
- `Дорогая логистика`;
- `Неполная экономика`;
- `Заблокировано`.

Search, sorting, pagination and column visibility are required. No unbounded result table.

## 17. SKU/cluster detail drawer

Wide non-modal right drawer in fixed causal order:

1. Decision.
2. Demand dynamics.
3. How demand is fulfilled.
4. Ozon vs our model.
5. Economics.
6. Evidence/diagnostics.

Raw codes appear only in diagnostic disclosure. Main path uses human-readable Russian explanations.

## 18. `Потоки спроса`

This is a first-class analytical mode, not a stockout debug screen.

### 18.1 Modes

- **По кластеру спроса** — choose destination; see all origins fulfilling it.
- **По кластеру отгрузки** — choose origin; see destinations it serves.
- **По артикулу** — choose SKU/article; see its demand/fulfillment geography.

### 18.2 Metric selector

- `Штуки`;
- `Доля спроса, %`;
- `Потери маржи, п.п.`;
- `Потери прибыли, ₽`.

For ₽ mode, the default flow screen uses `observed_profit_opportunity_rub`; projected opportunity, if shown, is explicitly labelled with its horizon.

### 18.3 Cluster overview

Each comparison card shows:

- total destination demand;
- local fulfillment %;
- external fulfillment %;
- donor count;
- current modeled non-local route cost effect;
- observed local-placement opportunity ₽ where computable.

### 18.4 Focused flow visualization

Primary visualization = **cluster-centric hub-and-spoke**, not a global Sankey/chord.

Destination mode centers the selected destination and shows origin connections. Origin mode reverses the viewpoint. SKU mode focuses on one SKU and its relevant clusters without showing the global all-SKU network.

Connection width encodes the selected metric, but every link has exact text values and keyboard selection. Color/width are never the sole source of meaning.

### 18.5 Route drill-down

Selecting `Казань → Москва` shows:

- units;
- share of Moscow destination demand;
- route cost ₽ and `% of realization`;
- current net margin;
- feasible local Moscow→Moscow counterfactual;
- margin delta p.p.;
- observed profit opportunity ₽;
- stockout/distortion evidence and completeness.

### 18.6 SKU composition inside route

Ranked horizontal bars by SKU/article show:

- units on route;
- share of route;
- share of destination demand;
- route-cost effect;
- margin/profit opportunity.

This directly answers: “14% of Moscow demand comes from Kazan — which articles create those 14%?”

### 18.7 Observed vs cleaned route evidence

When route cleaning materially changes interpretation, the user can compare `Наблюдаемое` and `Очищенное`. The UI states which route evidence source drives the recommendation.

This observed/clean switch applies to fulfillment/route evidence. It does not retroactively reassign destination demand.

## 19. `Экономика`

Plan view shows only decision-level economics. Detail/Economics surfaces expose full line items already supported by backend economics:

- realization;
- commission;
- acquiring;
- FBO/delivery;
- expected logistics;
- advertising/services;
- withholdings/co-invest;
- VAT/tax;
- cost;
- profit/unit;
- margin;
- ROI;
- completeness/blockers/rounding.

Route detail compares `Фактическое исполнение` vs `Локальное размещение`; frontend never recalculates the unit economics.

## 20. Human-readable evidence

Do not show `RECOMMENDATION_DISTORTION_SIGNAL` as the primary explanation.

Acceptable examples:

- `Рекомендация Ozon может быть занижена: часть московского спроса исполнялась из других кластеров во время вероятного дефицита.`
- `20% спроса Москвы сейчас исполняется нелокально.`
- `На наблюдаемом объёме локальное покрытие улучшило бы маржу на 2,6 п.п. и дало бы +18 400 ₽ при текущей модели затрат.`
- `Рост спроса подтверждается последней полной неделей.`
- `Горизонты различаются: Ozon 60 дней, наш расчёт 67 дней.`

Technical codes remain available in diagnostics/tests.

## 21. Frontend contracts

UI is governed by:

- `/DESIGN.md` — visual identity and visualization grammar;
- `/UX-CONTRACT.md` — behavior, navigation, tables, drawer, async, accessibility and Flow-mode contract.

Implementation must reuse canonical UI owners instead of screen-local equivalents.

## 22. Error/incomplete behavior

Fail closed when missing/ambiguous data can change a financial or placement decision.

- unresolved cluster → affected calculations incomplete;
- missing route tariff → counterfactual not computed;
- incomplete unit economics → placement blocked according to eligibility rules;
- insufficient weeks → lower confidence/incomplete estimate per §7.6;
- different report dates/horizons → visible warning;
- unknown stock/inbound → no fabricated zero.

After failed recalculation, previous successful snapshot stays visible and is clearly labelled as previous.

## 23. Testing strategy

Implementation plan must use TDD.

### Demand

- M1/M2/L medians;
- ±10% regime boundaries;
- latest-week confirmation;
- 50% impulse and ±20% cap;
- stable/unconfirmed no-adjustment;
- 4–7 / 1–3 / 0-week behavior;
- current incomplete week exclusion;
- route substitution does **not** automatically remove destination demand.

### Stockout/routes

- strong historical evidence remains route-cleaning-eligible with neutral availability;
- contradictory current availability does not automatically restore contaminated route history;
- full four-level route fallback.

### Need/Ozon

- horizon math;
- ceil-after-subtraction rounding;
- inbound on/off;
- no buffer;
- zero floor;
- different-horizon warning without Ozon rescaling;
- unknown stock evidence.

### Plans

- Safe ceiling;
- Calculated independence from Ozon;
- physical ceiling;
- max-profit allocation;
- max-margin allocation;
- deterministic tie-breaks;
- unallocated remainder;
- both Safe/Calculated allocations produced under same objective.

### Route economics

- cost ₽ and `% realization`;
- local counterfactual margin delta p.p.;
- observed-period profit opportunity;
- projected opportunity kept separate when present;
- infeasible/missing-tariff/incomplete behavior.

### UI/data contract

- decision row contains required values/reasons;
- flow totals reconcile to route aggregates;
- route SKU breakdown sums to route quantity;
- observed/clean route source label preserved;
- flow ₽ value period basis is explicit;
- raw codes are not the only user-facing explanation;
- keyboard/accessibility parity for table, drawer, nodes, links and bars.

## 24. Acceptance criteria

With real reports the user can:

1. compare Ozon and independently calculated need;
2. see `M1 → M2 → L`, regime and confidence;
3. choose any horizon without hidden buffer;
4. toggle inbound supply;
5. see Safe Plan and Our/Calculated Plan side by side;
6. allocate limited SKU stock under max-profit or max-margin;
7. see route cost as `% realization` and final margin impact in p.p.;
8. see observed-period ruble opportunity of local vs current fulfillment;
9. open `Потоки спроса`, choose destination and visually see origin composition;
10. click a route and see SKU composition in units/shares;
11. switch flow metric among units, share, margin p.p. and profit ₽;
12. inspect destination, origin and SKU viewpoints;
13. understand disagreement without raw stockout/distortion codes;
14. see stale/mismatched/incomplete evidence instead of false precision;
15. reproduce a result from snapshot settings/report metadata.

## 25. Non-goals

- Ozon API/automatic report download;
- automatic supply-order creation;
- ML/black-box forecasting;
- inferred lost demand from stockout without direct evidence;
- hidden safety-stock optimization;
- global all-cluster network as primary UX;
- cloud/multi-user architecture;
- unrelated runtime/bootstrap redesign;
- rewriting working backend solely for style.

## 26. Implementation boundary

After user review/approval of this written spec, the next Superpowers step is a detailed implementation plan. It must sequence model corrections before UI surfaces that depend on them and preserve working ingestion/economics behavior where possible.
