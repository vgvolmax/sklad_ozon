# Ozon FBO Product Completion — Design

**Date:** 2026-09-02  
**Status:** approved design; implementation pending

## 1. Status and supersession

This document is the canonical Product Completion design for `sklad_ozon`.

It **does not replace** the canonical runtime architecture in `2026-08-20-scoz-lite-portable-architecture-design.md`. The existing local Python + FastAPI + committed vanilla HTML/CSS/JavaScript boundary remains unchanged by this design.

It extends and, where explicitly stated below, supersedes business/product limits from `2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`.

The most important intentional changes are:

1. the product now computes its **own explainable demand estimate** instead of only consuming the Ozon recommendation;
2. the Ozon recommendation becomes a comparison/control signal rather than the only quantity ceiling;
3. the product exposes two plan families: **Safe Plan** and **Calculated Plan**;
4. route economics becomes a first-class analytical layer, including cost as `% of realization`, margin impact in percentage points, and profit opportunity in rubles;
5. the frontend becomes a decision tool with a dedicated visual `Потоки спроса` mode rather than a debug-style table/JSON surface.

Business invariants not changed here remain in force.

## 2. Product goal

The application must answer, for each relevant `SKU × destination cluster`:

1. where customer demand actually arose;
2. from which origin clusters that demand was fulfilled;
3. whether the observed fulfillment geography is likely distorted by stockout/substitution;
4. what the cleaned recent demand level is and how it is changing;
5. how many units are needed for a user-selected horizon;
6. what Ozon recommends for the same SKU/cluster and whether that recommendation is directly comparable;
7. how much the current origin→destination route costs in rubles and as a share of realization;
8. what margin/profit effect an alternative local placement would have;
9. how limited seller stock should be allocated under the chosen objective;
10. why the application reached that recommendation.

The main decision sequence is:

`Where demand arose → who fulfilled it → what that routing cost → cleaned demand → our need → Ozon comparison → allocation plan`.

## 3. Non-negotiable domain semantics

- `destination_cluster` is the geography of customer demand.
- `origin_cluster` is the physical fulfillment/dispatch source.
- `Казань → Москва` means Moscow demand fulfilled from Kazan; it is never Kazan demand.
- economics may change **where stock is placed**, but may not fabricate or increase demand.
- current availability is corroborating evidence for historical stockout inference, never proof of a historical event by itself.
- frontend code must not contain demand, stockout, route-economics, unit-economics or optimizer formulas.

## 4. Product architecture: Decision Layer over the existing core

Do not rewrite the existing ingestion/analytics/economics/supply core without cause. Product Completion adds/repairs five explicit decision-layer responsibilities:

1. **Demand Estimate Engine** — cleaned recent demand and dynamic weekly rate.
2. **Ozon Comparison** — Ozon recommendation vs our need with horizon/comparability status.
3. **Route Economics** — actual origin→destination cost and counterfactual local effect.
4. **Need Engine** — forecast minus stock/inbound according to user scenario.
5. **Scenario Allocator** — Safe vs Calculated ceilings and `Макс. прибыль`/`Макс. маржа` allocation.

The application/API returns an immutable analysis snapshot containing enough aggregated evidence for all UI surfaces. Raw order rows do not need to be sent to the browser.

## 5. Repair stockout cleaning before using it for forecasting

The current implementation ties HIGH confidence too strongly to current availability. Product Completion separates **historical cleaning eligibility** from current corroboration.

### 5.1 Historical route evidence

The existing strong route-shift conditions remain the starting thresholds unless a later approved statistical redesign changes them:

- prior local share >= 60%;
- local share drop >= 30 percentage points;
- external replacement rise >= 20 percentage points;
- fulfilled weekly quantity >= 10;
- destination demand retention >= 60% of baseline;
- comparison only across completed periods.

When historical route evidence meets the strong criteria, the affected historical period is **eligible for cleaning** independently of the current availability snapshot.

### 5.2 Availability corroboration

Current availability evidence can be `supports`, `neutral`, or `contradicts` and affects displayed confidence/explanation. It must not be a required condition for excluding a historically contaminated route period.

A contradictory current snapshot may lower confidence but cannot automatically restore a strong historical substitution week to clean history.

The stockout output therefore needs an explicit historical field such as:

```text
historical_evidence_strength
cleaning_eligible
availability_corroboration
confidence
```

The exact names may follow existing Python conventions, but the concepts must remain separate.

### 5.3 Availability importer enrichment

Where the source report provides them, retain and normalize evidence including `daysWithoutStock`, report date, current FBO quantity and other availability fields needed by the approved historical/corroboration rules. Missing source evidence remains `null`/unknown, never zero by assumption.

## 6. Clean route fallback hierarchy

Expected-route analytics and placement economics must implement the full fallback hierarchy:

1. `SKU × origin` clean route profile;
2. `SKU × origin` observed route profile;
3. origin profile across all SKUs;
4. global fulfilled route profile.

Every returned route profile records source level, sample size and confidence. The frontend must be able to expose the fallback source in diagnostics/detail.

Uncovered tariff share is not renormalized away.

## 7. Own demand estimate

### 7.1 Source population

Demand is attributed by destination only.

For weekly demand estimation use full completed weeks from the net-demand population (`fulfilled + in_progress`, excluding cancelled). The current incomplete ISO week is not part of the base or trend calculation.

Weeks identified as historically distorted for the relevant `SKU × destination` by the approved cleaning rules are removed from the cleaned series used for the primary estimate.

### 7.2 Eight-week three-level model

Use the **latest eight cleaned full weeks** in chronological order when available.

Let:

- `M1` = median of cleaned weeks 1–4 (older half);
- `M2` = median of cleaned weeks 5–8 (recent half);
- `L` = quantity in the latest cleaned full week (week 8).

The UI must preserve these three visible levels as a human-readable dynamic:

`M1 → M2 → L`

Example: `19,5 → 24,5 → 29 шт./нед.`.

### 7.3 Regime classification

Relative change between `M1` and `M2`:

- growth when `M2 / M1 - 1 > +10%`;
- stable when change is within `±10%`;
- decline when change `< -10%`.

For `M1 = 0`, do not divide by zero. Treat transition from zero to meaningful positive demand as insufficient/transition evidence and return an explicit reason code; do not fabricate an infinite growth percentage.

### 7.4 Latest-week confirmation

The latest week confirms the current regime using the same 10% tolerance around `M2`:

- growth is confirmed when `L > M2 × 1.10`;
- decline is confirmed when `L < M2 × 0.90`;
- stability is confirmed when `L` remains within `±10%` of `M2`.

The latest week is evidence of continuation, not an independent forecast baseline.

### 7.5 Current weekly rate

Base current rate is `M2`.

For confirmed growth or confirmed decline:

```text
raw_adjustment = 0.5 × (L - M2)
adjustment_cap = ±20% of M2
current_weekly_rate = M2 + clamp(raw_adjustment, -20% × M2, +20% × M2)
```

For stable regime or an unconfirmed growth/decline regime:

```text
current_weekly_rate = M2
```

The product must display `base`, `regime`, `latest-week confirmation`, `adjustment`, and final weekly rate separately. The final number may not be a black box.

### 7.6 Short-history fallback

- **8+ cleaned full weeks:** full three-level model above.
- **4–7 cleaned full weeks:** median of available cleaned full weeks; no trend adjustment; confidence at most medium.
- **1–3 cleaned full weeks:** median of available cleaned full weeks; no trend adjustment; confidence low.
- **0 cleaned full weeks:** fall back to available observed completed-week history if present, explicitly marked `observed_fallback` and low confidence. If no completed demand history exists, own estimate is incomplete rather than zero.

These fallback rules prevent old/contaminated history from being silently treated as high-confidence current demand.

## 8. User-selected horizon and need calculation

### 8.1 No hidden safety buffer

There is no automatic safety stock or hidden buffer.

The user selects the horizon in days. If the user wants extra cover, they increase the horizon, e.g. from 60 to 67 days.

```text
demand_forecast_qty = current_weekly_rate × horizon_days / 7
```

Rounding policy must be explicit and consistent in backend contracts. The UI should preserve the unrounded rate for explanation and show integer shipment quantities.

### 8.2 Current stock and inbound flag

Canonical scenario flag:

`Учитывать поставки в пути` — boolean.

Default: enabled.

Without inbound:

```text
calculated_need_qty = max(0, demand_forecast_qty - current_fbo_stock)
```

With inbound:

```text
calculated_need_qty = max(0, demand_forecast_qty - current_fbo_stock - inbound_qty)
```

The UI always shows current FBO stock and inbound quantity separately, regardless of the flag.

Missing stock/inbound evidence is not silently converted to zero if the source contract cannot prove zero.

## 9. Ozon comparison

For every relevant `SKU × destination cluster` expose:

- Ozon recommended quantity;
- Ozon recommendation horizon when source metadata provides it;
- our selected horizon;
- our demand forecast;
- calculated need to supply;
- `Δ units` and `Δ %` where mathematically meaningful;
- comparability status;
- confidence and human-readable reasons for disagreement.

### 9.1 Different horizons

Never linearly rescale the Ozon recommendation to our horizon. The internal Ozon forecast logic is unknown.

If Ozon horizon differs from our selected horizon:

- keep both original quantities;
- show `Горизонты различаются`;
- mark the comparison as partial/non-like-for-like;
- do not present `Δ %` as a clean model-error percentage without that warning.

## 10. Hybrid planning model

Ozon recommendation is no longer the only business ceiling.

For each candidate cluster expose two ceilings/plans.

### 10.1 Safe Plan

Safe Plan never exceeds Ozon's recommendation and never exceeds our own current need or physical feasibility:

```text
safe_ceiling = min(ozon_recommended_qty, calculated_need_qty, physical_ceiling)
```

### 10.2 Calculated Plan

Calculated Plan is independent of Ozon quantity but remains bounded by our need and physical feasibility:

```text
calculated_ceiling = min(calculated_need_qty, physical_ceiling)
```

This allows the product to say, for example:

`Ozon: 72 → Our need: 104`, while still offering a conservative Safe Plan capped at 72.

Recommendation distortion changes trust/explainability; it does not itself create demand.

## 11. Scenario allocator

Seller stock is not fungible across SKUs. Allocation is performed for each SKU using that SKU's available quantity as the stock ceiling.

If available seller quantity exceeds total eligible need, the remainder stays unallocated. Do not ship units merely to consume available stock.

The user chooses one objective:

### 11.1 `Макс. прибыль`

Allocate eligible units toward clusters with the highest expected **absolute net profit per incremental unit**, up to the selected plan ceiling.

### 11.2 `Макс. маржа`

Allocate eligible units toward clusters with the highest **net margin rate after all modeled costs**, up to the selected plan ceiling.

Tie-breaker order should remain deterministic and may use:

1. primary objective;
2. route/demand confidence;
3. lower distortion risk;
4. higher demand ceiling;
5. stable cluster identifier.

Exact existing threshold settings for minimum profit/margin/ROI remain available as eligibility constraints unless later removed by an approved decision.

The UI may show a compact comparison of both scenario outcomes so the user can see the cost of choosing margin over absolute profit, but only one scenario is active for the final plan at a time.

There is no `Макс. объём` scenario because the SKU quantity available for allocation is already fixed.

## 12. Route economics as a first-class layer

For each observed relevant `SKU × origin × destination` route calculate and expose:

- fulfilled quantity;
- share of destination demand;
- route logistics cost in rubles;
- route logistics cost as `% of realization`;
- current net profit/unit and net margin rate;
- local destination→destination counterfactual when feasible and complete;
- local counterfactual route cost `% of realization`;
- counterfactual net margin;
- `margin_delta_pp`;
- `profit_opportunity_rub` for the affected observed/forecast volume;
- completeness/confidence/reason.

### 12.1 Counterfactual principle

For `Казань → Москва`, compare the economics of the actual Kazan-origin fulfillment with the feasible Moscow-local alternative for the same SKU/destination context.

Non-route assumptions remain the same for the comparison; route/placement-dependent costs come from the backend's approved economics/tariff contracts.

If the local placement is physically infeasible, tariff coverage is missing, or unit economics is incomplete, the counterfactual is `not computable`. Missing values are never shown as zero benefit.

### 12.2 Two user-visible economic measures

Both must be shown:

1. **route cost difference as a share of realization** — e.g. `10,1% → 7,1%`;
2. **final net margin effect** — e.g. `18,4% → 21,4% = +3,0 п.п.`.

Also compute absolute profit opportunity in rubles so a small but expensive route can be compared with a large but cheap one.

### 12.3 Economics affects placement, not demand

A +3 p.p. local-placement benefit is a reason to prioritize Moscow for a known quantity of Moscow demand. It must never multiply the Moscow demand quantity.

## 13. Cluster identity and report freshness

### 13.1 Cluster resolution

All report importers must resolve cluster identity through the canonical normalization/alias/manual-mapping layer rather than treating independently normalized free text as guaranteed identity.

Ambiguous unresolved clusters remain visibly unresolved and block affected calculations that require identity equality. Manual mappings persist in Project JSON.

### 13.2 Freshness

Populate report metadata where the source provides it:

- generated date;
- period start/end;
- recommendation horizon.

The analysis snapshot contains a freshness assessment. Materially mismatched report dates are visible to the user and may lower comparison confidence. An old restored report may not silently appear current.

## 14. Immutable analysis snapshot

Each successful calculation produces a self-contained immutable snapshot.

Changing horizon, inbound flag, scenario, mappings or source files does not mutate the displayed prior result. It marks the UI as requiring recalculation. Only a successful new calculation replaces the active snapshot.

At minimum a snapshot contains:

```text
snapshot_id
created_at
report_meta + freshness
scenario_settings
input_statuses
summary
product/cluster decision rows
demand-estimate evidence
observed and cleaned route evidence
stockout/distortion evidence
route economics
unit economics
safe/calculated placement ceilings
scenario allocations
flow-view aggregates
diagnostics
```

Raw order rows and buyer/customer PII are not part of the browser snapshot.

## 15. Product information architecture

Top-level sections:

1. **План** — primary decision table and final allocation.
2. **Потоки спроса** — visual demand/fulfillment analysis.
3. **Экономика** — detailed unit and route economics.
4. **Данные** — source files, freshness, settings, mappings and diagnostics.

The import form must no longer dominate the primary result screen.

## 16. `План` screen

### 16.1 Scenario controls

Compact controls above the result:

- horizon days;
- `Учитывать поставки в пути`;
- objective: `Макс. прибыль` / `Макс. маржа`;
- explicit `Пересчитать план` action.

### 16.2 Decision line

Canonical product signature:

`Ozon → Наша потребность → План`

Global and row-level variants may also show `Δ units`, `Δ %`, route opportunity and expected profit.

### 16.3 Main decision table

Default business columns:

- Article / SKU / product;
- destination cluster;
- demand dynamic `M1 → M2 → L` and regime;
- Ozon recommendation;
- our calculated need;
- delta;
- selected final allocation;
- route overcost / local opportunity;
- net margin;
- expected plan profit;
- confidence/status.

The table must support search, filters, sorting, pagination and column visibility. Do not ship an unbounded table.

Primary fast filters:

- all;
- disagreement;
- probable stockout;
- expensive logistics;
- incomplete economics;
- blocked.

## 17. SKU/cluster detail drawer

A selected decision row opens a wide non-modal right drawer in causal order:

1. Decision.
2. Demand dynamics.
3. How the demand is fulfilled.
4. Ozon vs our model.
5. Economics.
6. Evidence/diagnostics.

User-facing text translates technical evidence into business conclusions. Raw status/reason codes are restricted to the diagnostic disclosure.

## 18. Dedicated `Потоки спроса` analytical mode

This is a first-class mode, not a hidden stockout debug screen.

Its purpose is to let a human visually inspect demand→fulfillment relationships and drill from cluster-level imbalance into the SKUs responsible for the flow.

### 18.1 Modes

1. **По кластеру спроса** — choose a destination and see all origins that fulfill it.
2. **По кластеру отгрузки** — choose an origin and see all destinations it serves.
3. **По артикулу** — choose a SKU/article and see its demand and fulfillment geography.

### 18.2 Metric selector

The same view switches among:

- units;
- destination-demand share %;
- margin loss/opportunity in percentage points;
- profit loss/opportunity in rubles.

### 18.3 Cluster overview

Each cluster card shows:

- total destination demand;
- local fulfillment %;
- external fulfillment %;
- donor count;
- economic cost/opportunity of non-local fulfillment where computable.

Cards are ordered/filterable analytical controls, not decorative KPIs.

### 18.4 Focused flow visualization

Use a **cluster-centric hub-and-spoke** view as the primary visualization.

Destination mode example:

```text
        Казань 14%
             \
              \
        [ МОСКВА ] —— Самара 8%
             |
             |
        Москва 78%
```

Connection width encodes the selected metric. The exact value is always present in text and selectable through keyboard/focus interaction.

Do not use a global all-cluster Sankey/chord diagram as the main interface. It becomes unreadable at realistic cluster/SKU counts.

### 18.5 Route drill-down

Selecting `Казань → Москва` shows:

- units;
- share of Moscow destination demand;
- route cost ₽ and `% of realization`;
- current net margin;
- feasible local Moscow→Moscow counterfactual;
- margin delta p.p.;
- profit opportunity ₽;
- stockout/distortion evidence where relevant.

### 18.6 SKU composition inside a route

Below/alongside the selected route, show ranked horizontal bars by SKU/article.

For each SKU:

- units on route;
- share of selected route;
- share of destination demand;
- route cost effect;
- margin/profit opportunity.

This answers the operational question: “14% of Moscow demand comes from Kazan — which articles create those 14%?”

### 18.7 Observed vs cleaned evidence

Where cleaning materially changes the picture, the analytical view can compare `Наблюдаемое` and `Очищенное`. The UI always states which evidence drives the recommendation.

## 19. Economics screen

The Plan screen remains decision-dense and does not expand every unit-economics line item.

The Economics section and detail drawer expose the full backend calculation:

- realization;
- commission;
- acquiring;
- base delivery/FBO costs;
- expected route logistics;
- advertising/services;
- Ozon withholdings/co-invest;
- VAT/tax;
- cost;
- profit/unit;
- margin;
- ROI;
- completeness/blockers/rounding source.

Route comparison provides `Фактическое исполнение` vs `Локальное размещение` without frontend formulas.

## 20. Human-readable evidence

The frontend must not present codes such as `RECOMMENDATION_DISTORTION_SIGNAL` as the primary explanation.

Examples of acceptable product copy:

- `Рекомендация Ozon может быть занижена: часть московского спроса исполнялась из других кластеров во время вероятного дефицита.`
- `20% спроса Москвы сейчас исполняется нелокально.`
- `Локальное покрытие этого объёма потенциально улучшает маржу на 2,6 п.п. и добавляет 18 400 ₽.`
- `Рост спроса подтверждается последней полной неделей.`
- `Горизонты различаются: Ozon 60 дней, наш расчёт 67 дней.`

Technical codes remain available for diagnostics and tests.

## 21. Frontend design and UX contracts

Product Completion UI is governed by:

- `/DESIGN.md` — visual identity, tokens, density and visualization grammar;
- `/UX-CONTRACT.md` — interaction, navigation, table, drawer, async, accessibility and `Потоки спроса` behavior.

Implementation must not create screen-local equivalents for recurring controls when a canonical owner is defined in `UX-CONTRACT.md`.

## 22. Error handling and incomplete data

Fail closed for ambiguous/missing data that can change a financial or placement decision.

Examples:

- unresolved cluster identity → affected comparison blocked/incomplete;
- missing route tariff → counterfactual not computed;
- incomplete unit economics → placement may be blocked according to thresholds;
- missing historical weeks → explicit fallback/confidence reduction;
- mismatched report horizons/dates → visible warning;
- no clean demand evidence → observed fallback or incomplete, never fabricated zero.

Previous successful results remain available after a failed recalculation, clearly labelled as previous snapshot.

## 23. Testing strategy

Implementation plan must use TDD and add focused tests for at least:

### Demand estimate

- median `M1/M2/L` calculation;
- >10%, ±10%, <-10% regime boundaries;
- latest-week confirmation;
- 50% impulse and ±20% cap;
- stable/unconfirmed no-adjustment behavior;
- short-history fallbacks;
- incomplete current week exclusion;
- cleaning exclusion.

### Stockout/clean routes

- strong historical evidence remains cleaning-eligible with neutral availability;
- contradictory current availability does not automatically restore contaminated weeks;
- full four-level route fallback hierarchy.

### Need/Ozon comparison

- horizon math;
- inbound flag on/off;
- no safety buffer;
- zero floor;
- different-horizon warning without Ozon rescaling;
- missing-stock evidence behavior.

### Plans/allocator

- Safe Plan Ozon ceiling;
- Calculated Plan independence from Ozon;
- physical ceiling;
- max-profit allocation;
- max-margin allocation;
- deterministic tie-breaks;
- unallocated remainder when need < seller stock.

### Route economics

- route cost ₽ and % realization;
- local counterfactual p.p. effect;
- absolute opportunity ₽;
- infeasible/missing-tariff/incomplete-economics behavior.

### UI/data contract

- main decision row contains all required values/reasons;
- flow-view totals reconcile with route aggregates;
- selected route SKU breakdown sums to route quantity;
- observed/cleaned evidence label is preserved;
- raw backend codes are not the only user-facing explanation;
- table/drawer/flow keyboard behavior and accessible text parity.

## 24. Acceptance criteria

Product Completion is not complete until a user can, with real reports:

1. see Ozon quantity and our independently calculated need side by side;
2. see `M1 → M2 → latest week`, regime and confidence behind our estimate;
3. choose any horizon with no hidden safety-stock multiplier;
4. toggle whether inbound supply reduces the need;
5. see Safe Plan and Calculated Plan concepts without conflating them;
6. allocate limited SKU stock under either `Макс. прибыль` or `Макс. маржа`;
7. inspect route cost both as `% of realization` and final margin impact in p.p.;
8. quantify the ruble opportunity of local vs current fulfillment where computable;
9. open `Потоки спроса`, choose a destination cluster and visually see which origin clusters fulfill it;
10. click a route and see which SKUs form that route in units and shares;
11. switch the flow metric among units, share, margin p.p. and profit rubles;
12. inspect the same problem from destination, origin and SKU modes;
13. understand a disagreement without reading raw stockout/distortion codes;
14. see stale/mismatched/incomplete evidence rather than a falsely precise result;
15. reproduce the result from the immutable snapshot settings and report metadata.

## 25. Explicit non-goals for this phase

- Ozon API integration or automatic report download;
- automatic creation of supply orders in Ozon;
- ML/black-box demand forecasting;
- hidden safety-stock optimization;
- global network visualization for all clusters/SKUs as the primary UX;
- cloud/multi-user architecture;
- unrelated runtime/bootstrap redesign;
- rewriting working backend modules solely for stylistic consistency.

## 26. Implementation boundary

The next step after this design is approved is a Superpowers implementation plan. The plan must sequence model corrections before UI surfaces that depend on them, preserve existing working ingestion/economics behavior where possible, and include verification against real/sanitized Ozon fixtures.
