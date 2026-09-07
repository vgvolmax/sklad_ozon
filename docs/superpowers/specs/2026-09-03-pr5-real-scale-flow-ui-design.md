# PR5 — Real-Scale Flow & Stockout Impact UI — Design Brief

**Date:** 2026-09-03  
**Status:** approved scope/design brief; implementation plan follows after PR3/PR4 presentation contracts are stable  
**Parent design:** `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`  
**Depends on:** PR1 daily facts, PR2 episodes, PR3 impact aggregates, PR4 grouped data-quality state

## 1. Purpose

Replace the current unbounded Flow presentation with a real-scale operator screen that answers one causal question:

> where demand arose, who fulfilled it, when local fulfillment broke down, and what that distortion cost.

The current implementation fails on real datasets because it renders every comparison object as a large card, grows the SVG height with `links × 90px`, and repeats each route below the visualization. PR5 must remove that failure mode rather than cosmetically restyle it.

## 2. Subject and audience

**Subject:** Ozon FBO demand geography and fulfillment substitution.  
**Audience:** marketplace operator/planner who must decide where to place stock and where external fulfillment is destroying margin.  
**Single job:** make routing distortion and its business impact visible without requiring the operator to understand the stockout model internals.

## 3. Visual signature

The signature element is the **locality timeline**.

It combines:

- destination demand volume over time;
- local fulfillment share over time;
- probable stockout/substitution episode bands;
- external donor takeover;
- episode-level economic impact.

The screen should be remembered for showing “locality collapsed while demand stayed present”, not for decorative Sankey lines.

## 4. Information architecture

Keep the existing top-level product section name:

```text
Потоки спроса
```

Inside the section preserve three perspectives:

```text
По кластеру спроса
По кластеру отгрузки
По артикулу
```

Default evidence remains clean where appropriate for representative routing, with observed evidence available as audit/history context.

Evidence switching changes fulfillment/routing evidence. It never changes destination demand geography.

## 5. Selected-context layout

Desktop structure should be bounded and selected-context-first:

```text
┌──────────────────────────────────────────────────────────────────┐
│ controls: mode · metric/evidence as applicable · search          │
├───────────────┬──────────────────────────┬────────────────────────┤
│ compact list  │ selected flow overview   │ selected context       │
│ internal      │ bounded route visual     │ business/economic      │
│ scroll        │ Top links + Прочие       │ details                │
├───────────────┴──────────────────────────┴────────────────────────┤
│ locality timeline / stockout episodes                            │
├──────────────────────────────────────────────────────────────────┤
│ selected episode or route SKU breakdown                          │
└──────────────────────────────────────────────────────────────────┘
```

At narrower widths, columns stack, but each large dataset region keeps its own bounded scroll/expansion behavior.

## 6. Left selector

Never render every destination/origin/SKU as a large multi-metric card.

Required behavior:

- search field;
- compact selectable rows;
- internal vertical scroll;
- bounded height relative to viewport;
- row shows only identity + one or two primary summary values;
- detailed economics move to selected context.

Destination example:

```text
Москва            8 420 шт.
Санкт-Петербург   6 840 шт.
Казань            4 210 шт.
```

SKU row shows product/article/SKU identity without repeating every route metric.

## 7. Bounded route overview

For selected destination/origin/SKU:

- show at most Top 8 explicit links in overview by the active backend ranking/quantity basis;
- aggregate the remaining overview mass as `Прочие`;
- `Прочие` is a presentation group, not a fake route and must not enter economics formulas;
- user can expand/search the complete exact route list in a separate bounded control if needed;
- route selection always resolves to a real backend route identity.

No global Sankey/chord.

No SVG/canvas height proportional to total link count.

## 8. Local vs external visual language

Local fulfillment (`destination → destination`) must be visually distinguishable from external fulfillment.

Use semantic treatment, not rainbow categorization:

- local = neutral/positive engineering signal;
- external = warning/attention signal;
- selected route = strong focus state;
- incomplete economics = clearly incomplete, not fake zero.

Forced-colors mode must remain understandable without relying on hue alone.

## 9. Destination mode

Selected destination is the center of the decision.

Show:

```text
Собственный спрос
Локально исполнено
Из других кластеров
Локальная доля
Внешняя доля
Основные доноры
Экономический эффект внешнего исполнения
```

Critical wording:

```text
Собственный спрос
```

must refer to destination demand, not origin dispatch volume.

If Moscow physically dispatches 1000 but owns 500 destination demand, destination-mode Moscow demand shows 500, never 1000.

## 10. Origin mode

Selected origin answers:

> какой собственный спрос закрывает этот склад/кластер и сколько чужого спроса он сейчас перекрывает.

Show distinct values:

```text
Собственный спрос origin-кластера
Фактически исполнено из origin
Из них свой destination demand
Из них спрос других кластеров
Количество destination-кластеров, которым origin является донором
```

Do not label physical dispatch as “спрос origin”.

This mode is the primary protection against the operator seeing a donor cluster as “high-demand” simply because it covers neighboring stockouts.

## 11. SKU mode

Selected SKU is product identity, not an enormous route spider.

Show:

```text
product name
article
SKU
own destination demand distribution
local/external fulfillment summary
Top origin→destination flows
stockout episodes by destination
```

A popular SKU with dozens of routes must remain bounded.

## 12. Locality timeline

For selected destination context, render a time series from PR3 presentation aggregates.

Required channels:

- destination demand quantity as restrained bars/area;
- local fulfillment share as the dominant line;
- probable stockout/substitution intervals as background bands or timeline segments;
- optional external share as secondary encoding if it improves interpretation without clutter;
- episode labels/tooltips use backend-calculated values.

The chart's purpose is to make this visual inference immediate:

```text
locality drops sharply
while destination demand remains broadly present
and external donors rise
```

No frontend stockout inference.

## 13. Episode cards/rows

Under the timeline show a bounded ranked list of probable episodes.

Example:

```text
04–08 августа
Локальность 91% → 24%
155 шт. перекрыто извне
+12 840 ₽ логистики
−15 460 ₽ прибыли
−4,2 п.п. маржи
[Разобрать эпизод]
```

If economics is incomplete, replace affected values with `Не рассчитано` and a concise reason/action state from backend diagnostics.

## 14. Episode drill-down

Selecting an episode reveals:

```text
replacement origins
origin share / qty
affected SKUs
route economics
extra logistics
margin delta
profit effect
confidence / evidence explanation
```

The operator should be able to answer “кто перекрыл этот спрос?” without scanning the global dataset.

## 15. Route drill-down

For an exact route show current vs local counterfactual:

```text
Текущий маршрут: Казань → Москва
Логистика ₽/шт.
Логистика % реализации
Текущая маржа

Локальное размещение: Москва → Москва
Логистика ₽/шт.
Логистика % реализации
Маржа

Δ маржи
Δ прибыли/шт.
Эффект на выбранном объёме
```

Use backend text/values. `None` = `Не рассчитано`.

Negative local benefit must display as local placement worse.

## 16. Metrics and controls

Preserve useful existing metrics where they remain meaningful:

```text
Штуки
Доля спроса, %
Потери маржи, п.п.
Потери прибыли, ₽
```

However, metric switching must not resize the entire page or render all links.

Selection context and evidence should be preserved when possible.

## 17. Diagnostics integration

PR4 grouped data-quality state appears contextually:

- selected route missing tariff → concise inline blocker with link/action to Data quality details;
- selected SKU missing product economics → concise inline state;
- global repeated diagnostics must not flood the Flow screen.

Technical raw codes remain behind disclosure.

## 18. Responsive/accessibility contract

Required real browser checks:

- normal desktop;
- narrow desktop;
- 200% zoom;
- keyboard-only traversal;
- visible focus;
- route/episode selection via native controls;
- drawer/panel focus return where used;
- reduced-motion;
- forced-colors/high contrast;
- no inaccessible off-screen content caused by fixed SVG dimensions.

Tables/lists with many rows own their scroll region.

## 19. Performance/boundedness acceptance

PR5 must be tested with a representative stress dataset, not only the small Product Completion fixture.

The acceptance dataset must contain enough destinations/SKUs/routes to reproduce the previous unbounded failure mode.

Pass criteria:

- page height does not scale linearly with total global route count;
- selected overview renders bounded Top links;
- selector uses internal scroll;
- timeline renders bounded selected-context series;
- switching mode/evidence/metric remains responsive;
- no raw-order rendering loop exists in frontend.

## 20. Frontend responsibility

Frontend may:

- choose selected context;
- search/filter/sort already-calculated presentation rows;
- group `Top N + Прочие` only if backend provides an explicitly safe presentation grouping contract; preferred design is backend-prepared overview groups;
- render charts and tables.

Frontend may not calculate:

- demand;
- local-share business aggregates from raw orders;
- stockout episodes;
- economics;
- weighted margins;
- profit loss;
- need/plan.

## 21. Visual restraint

Do not add decorative KPI-card grids merely because there is space.

The locality timeline is the one strong visual signature. Keep surrounding controls, lists and route details quiet, compact and technical.

Copy is plain Russian and names what the operator recognizes:

```text
Собственный спрос
Локально
Перекрыто другими кластерами
Вероятный период замещения
Потеря прибыли
```

Avoid backend vocabulary in primary UI such as `route_cleaning_eligible` or raw reason codes.

## 22. Required proofs

PR5 acceptance must demonstrate:

1. destination mode never confuses donor dispatch with destination demand;
2. origin mode explicitly separates own demand from foreign demand covered;
3. SKU mode stays bounded with dozens of routes;
4. Top 8 + `Прочие` overview reconciles to total presentation quantity;
5. exact route remains selectable from complete route list;
6. timeline shows demand and local share without frontend stockout math;
7. episode drill-down reconciles to backend episode aggregates;
8. incomplete economics displays `Не рассчитано`;
9. negative economics preserves sign and wording;
10. observed/clean switching never changes demand geography;
11. 200% zoom usable;
12. narrow desktop usable;
13. keyboard focus visible;
14. reduced motion respected;
15. forced colors understandable;
16. real-scale dataset does not recreate the vertical wall of cards/lines.

## 23. Out of scope

PR5 does not:

- change daily/demand/stockout/economics formulas;
- repair source data by itself;
- add a global optimizer;
- introduce a frontend framework;
- add global Sankey/chord;
- serialize buyer/order PII.

## 24. Merge gate

PR5 is mergeable only after PR1–PR4 contracts are stable and real-browser acceptance proves the screen is bounded, understandable and actionable on real-scale data.
