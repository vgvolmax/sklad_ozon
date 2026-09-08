# Article-First Plan & Shipment Workspace — UI Amendment

**Date:** 2026-09-08  
**Status:** approved durable UI correction  
**Applies to:** `План` only  
**Business spec:** `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## 1. Precedence

For the `План` screen this amendment supersedes conflicting layout/workflow statements in the current root `DESIGN.md`, `UX-CONTRACT.md`, and the deferred selected-network PR-E plan.

Specifically superseded for `План`:

- the wide primary `SKU × cluster` decision table as the canonical default workspace;
- repeated long product identity in every cluster row;
- primary-details-via-`Открыть детали` drawer interaction;
- selected supply-network draft/applied UI;
- network-only `/api/replan` dirty-state behavior;
- planned alternate-origin coverage UI.

Everything else in root `DESIGN.md` / `UX-CONTRACT.md` remains authoritative unless this amendment is more specific: visual tokens, four top-level routes, locale, accessibility, semantic controls, search behavior, Flow, Economics, Data, notices, scrollbars and general component states.

The implementation PR that changes runtime `План` MUST update root `DESIGN.md` and `UX-CONTRACT.md` in the same changeset so this temporary precedence bridge can be folded into the canonical root contracts.

## 2. Design intent

The current wide table makes the cluster row the visual object even when the operator's actual question is about one article. Searching an article such as `40750` produces many repeated product-name blocks and forces horizontal comparison across too many unrelated metrics.

The new canonical mental model is:

> **choose one article, then see everything needed to understand and execute its supply plan in one persistent workspace.**

Reuse the interaction grammar already proven by `Потоки спроса → По артикулу`: bounded selector on the left, selected context and related evidence on the right.

Do not copy the Flow visualization itself. Reuse the **master/detail context model**.

## 3. Visual identity retained

No redesign of the product identity occurs.

Keep:

- current light engineering-console palette/tokens;
- `Golos Text` + mono data role defined by project design context;
- semantic Ozon/model/warning/success/danger roles;
- restrained surfaces, borders and spacing;
- no gradients/glass/KPI mosaic;
- existing decision line as the memorable product signature:

```text
Ozon → Наша потребность → Наш план
```

The intentional design change is **structure**, not decoration.

## 4. Plan information architecture

Keep four top-level application sections unchanged:

```text
План
Потоки спроса
Экономика
Данные
```

Inside `План`, add two sibling views:

```text
Товары | Отгрузки
```

- `Товары` is default.
- `Отгрузки` is the cross-SKU operational schedule/export workspace.
- Switching between them must not reset the active AnalysisSnapshot or shipment scenario draft.
- This is an in-section view switch, not a fifth global navigation item.

## 5. `Товары`: desktop composition

Canonical desktop layout:

```text
┌────────────────────────┬──────────────────────────────────────────────┐
│ Поиск                  │ 40750 · Герметик анаэробный ...            │
│ Быстрые фильтры        │ SKU 3118873729                              │
│                        │ Кратность 6 · Остаток · Объём · Зона       │
│ article selector       ├──────────────────────────────────────────────┤
│ one item = one SKU     │ Ozon → Наша потребность → Наш план          │
│                        ├──────────────────────────────────────────────┤
│                        │ Кластеры                                    │
│                        │ focused table for selected article          │
│                        ├──────────────────────────────────────────────┤
│                        │ Отгрузки этого артикула                     │
│                        ├──────────────────────────────────────────────┤
│                        │ Диагностика / доказательства                │
└────────────────────────┴──────────────────────────────────────────────┘
```

The detail side is the primary content. Do not put it into a modal or require a click on `Открыть детали` to see normal product planning evidence.

## 6. Article selector

### 6.1 One item = one SKU/article

Never repeat the same product once per cluster in the selector.

Each item shows, in this hierarchy:

```text
40750 · Герметик анаэробный 250 мл
SKU 3118873729
К поставке 102 шт. · 4 кластера          [status if needed]
```

The long marketplace product name may be truncated to a stable two-line/ellipsis display in the selector, while the full name appears once in the right header.

### 6.2 Search

Search matches:

- article;
- SKU;
- product name.

It is local/immediate for the bounded analysis result, has an explicit accessible clear button when non-empty, and restores focus after clear.

### 6.3 Filters

Existing concepts such as discrepancy, probable deficit, expensive logistics and incomplete data may remain only if they are aggregated to article-level meaning.

A filter must not produce duplicate article rows merely because several clusters match.

### 6.4 Selection state

- first visible article is selected when no valid prior selection exists;
- explicit selected article remains selected through local filtering when still visible;
- when filtering removes it, select the first visible result and announce context change accessibly;
- selection is encoded in URL/session route state when existing route-state conventions allow it;
- use native `<button>` semantics with `aria-pressed` or equivalent established selector pattern.

## 7. Product detail header

Show once:

- article;
- full product name;
- SKU;
- pack multiplicity;
- seller available stock;
- seller stock usable in complete packs;
- canonical volume per unit;
- placement-zone summary;
- concise blocking/incomplete badge only when needed.

Example:

```text
40750 · Герметик анаэробный разборный, 250 мл, синий
SKU 3118873729

Кратность 6 шт. · Наш склад 186 шт. · Доступно кратно 186 шт.
Объём 0,25 л/шт. · Сортируемый
```

Do not turn these facts into six decorative KPI cards. Use a compact manifest-like metadata line/grid.

## 8. Article decision line

Aggregate existing destination rows for the selected SKU and show:

```text
Ozon → Наша потребность → Наш план
```

`Наш план` in this article header is the operational Calculated Plan total (`shippable_qty`) when shipment-planning evidence is complete. Preserve analytical Calculated Plan total as an explicit secondary value when pack rounding/capacity changes it.

Example:

```text
Ozon 96 → Наша потребность 101 → К поставке 102 шт.
Аналитический план 101 → 102 · кратность 6
```

Never imply that the +1 rounding unit is extra demand.

If any aggregate component is incomplete, show `Не рассчитано` / partial completeness instead of summing missing values as zero.

Safe Plan remains a clearly labelled conservative analytical reference; do not make it the export quantity.

## 9. Selected article cluster table

The table is nested detail, not the global dataset owner.

Default columns, in order:

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

Rules:

- no product-name/article/SKU columns: identity is already in the header;
- no default route-profit/margin/economics columns: those remain available in `Экономика`, `Потоки спроса` or a secondary disclosure;
- numeric columns align for comparison;
- `17 → 18` may be rendered in `К поставке` or adjacent plan cell when rounding occurred;
- FBO/inbound unknown uses `Не рассчитано`, never `0`;
- `Да + capacity 0`, missing multiplicity, unknown zone and other blockers use concise localized statuses with detail evidence available below;
- table owns its own overflow/scroll; do not make the entire page horizontally scroll because of it.

## 10. Article shipment assignments

Below the cluster table show where the selected SKU is currently assigned in the active shipment plan.

Example:

```text
16 сентября · ПВЗ
Москва + Казань
48 шт. этого артикула · 120 л

18 сентября · СЦ
Пермь
12 шт. этого артикула · 30 л
```

If shipment inputs changed since the last successful shipment plan, keep the old assignments visible but label them explicitly as calculated for the previous shipment scenario.

Do not mark the upstream analytical plan stale when only shipment inputs changed.

## 11. `Отгрузки` workspace

### 11.1 Purpose

This is the operational execution view across all selected products/clusters. It answers:

> what should we prepare for each chosen date/method, and which Ozon templates should we upload?

### 11.2 Scenario editor

Canonical controls:

- selected shipment clusters;
- opportunity date;
- method (`ПВЗ`, `СЦ`, `Прямая`);
- lead days when needed;
- max clusters for that opportunity;
- volume limit when user override is allowed.

Users can add/remove multiple opportunities.

Use semantic form controls. No click-only `div` rows. Date input may remain native if the existing product contract accepts OS-owned date UI.

### 11.3 Recalculation action

Shipment inputs are draft state only until:

```text
Рассчитать отгрузки
```

After a successful shipment plan exists and draft changes again, label the action:

```text
Пересобрать отгрузки
```

There is no selected-network `Пересчитать план` endpoint for these changes.

Upstream scenario still uses the existing `Пересчитать план` action for horizon/inbound/full analysis.

### 11.4 Shipment result presentation

One planned shipment is a restrained logistics-manifest surface, not a KPI card.

Header:

```text
16 сентября · ПВЗ
```

Body:

```text
Москва · Казань · Пермь
1 930 шт. · 824 л · 36 SKU
Рекомендовано вовремя
```

Actions:

```text
Скачать шаблоны Ozon
```

Optional disclosure shows SKU/cluster assignments and manual checks.

For multiple clusters the download is a ZIP of per-cluster Ozon workbooks; copy must make this clear.

### 11.5 Status vocabulary

Use distinct localized states:

- `Рекомендовано вовремя`;
- `Рекомендация по дате неполная`;
- `Позже рекомендуемой даты на N дн.`;
- `Не удалось запланировать`.

Constraint reasons below must remain causal, for example:

- `Лимит объёма ПВЗ`;
- `Лимит кластеров в поставке`;
- `Зона размещения не подходит`;
- `Нет подходящей даты/способа`;
- `Неизвестна кратность`.

Do not imply live Ozon slot confirmation.

## 12. Dirty-state model

Canonical frontend state separates:

```text
analysisDirty
shipmentDirty
```

- horizon/inbound/source import change → `analysisDirty`;
- cluster scope/opportunities/date/method/lead/max-clusters change → `shipmentDirty` only;
- successful full analysis replaces AnalysisSnapshot + ShippablePlan and invalidates old ShipmentPlan;
- successful `/api/shipment-plan` replaces ShipmentPlan and clears `shipmentDirty`;
- failure preserves the last successful result and the user's draft inputs for correction/retry.

No draft shipment input is represented as if it already owns the visible successful shipment result.

## 13. Data screen addition

Add one clearly named optional input:

```text
Прайс поставщика с кратностью упаковки
```

Help text explains the expected current RTP contract:

```text
Лист «Прайс списком»: КОД + Упак (например 36/6 → кратность 6)
```

Do not expose or mention `Оглавление!КРАТНОСТЬ` as product multiplicity.

Missing supplier-packaging file does not block historical analytics; it blocks/marks incomplete operational shipment/export quantities.

## 14. Responsive / zoom behavior

Desktop/laptop remains primary.

At narrow widths / 200% zoom:

- do not preserve a tiny two-column split;
- article selector becomes a bounded top section/collapsible selection surface above product detail;
- selected article context remains visible;
- cluster table keeps local horizontal overflow if required;
- shipment controls wrap vertically without hiding labels/actions;
- no root `overflow:hidden` or fixed full-viewport trick that breaks sibling sections.

Verify all four top-level sections after any shared layout change.

## 15. Accessibility and interaction contract

Target WCAG 2.2 AA.

- selectors/actions use native buttons/inputs/labels;
- visible `focus-visible` state uses existing token;
- selection is not color-only;
- searches have accessible clear controls;
- busy actions retain geometry and prevent duplicate submission;
- status updates use the shared live-region/Notice system;
- old successful content remains stable during downstream recalculation;
- errors are persistent inline text with correction action, not toast-only;
- `Скачать шаблоны Ozon` is disabled only with an explicit reason when the shipment itself is incomplete/unscheduled.

## 16. Migration / removal checklist

When PR-E implements this amendment, remove from the canonical Plan runtime and tests:

- default wide `DataTable` over all `SKU × cluster` rows;
- repeated full product names in cluster rows;
- primary `Открыть детали` per-row action;
- selected-network draft/applied/replan state from the deferred roadmap if it was never implemented;
- planned alternate-origin Flow surface from the deferred roadmap if it was never implemented.

Do **not** remove:

- current analytical decision data;
- route economics;
- Flow `По артикулу` and other historical modes;
- existing detail drawer primitive where still useful for secondary contexts;
- Data/Economics sections;
- shared DataTable/SearchField/Notice primitives used elsewhere.

The goal is targeted migration, not a frontend rewrite.