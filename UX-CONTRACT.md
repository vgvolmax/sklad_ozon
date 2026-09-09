# UX Contract

## Status and precedence

This root contract is a **transitional durable UX contract** for the current repository while the API-first roadmap is implemented.

Read active product behavior in this order:

1. `docs/superpowers/specs/2026-09-09-api-first-roadmap-corrections.md`;
2. `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md` for target `План` / `Данные` behavior;
3. `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md` for business/operational ownership;
4. this file for durable cross-screen UX behavior and the currently shipped visual interaction baseline;
5. `DESIGN.md` for visual tokens/identity.

The superseded selected-network / PlanningSnapshot workflow is **not** an active requirement. Do not reconstruct or reintroduce `SupplyNetworkSelector`, network-only replan, selected-network coverage planning or old `План размещения` behavior from Git history/archive.

PR-E must update this file in the same changeset as the final API-first runtime UI so no transitional wording remains.

## Product context

- **Audience:** владелец/менеджер Ozon FBO, принимающий решения по потребности, размещению и операционной поставке.
- **Primary jobs:** сравнить внешний сигнал Ozon с собственной моделью; понять географию спроса/исполнения; получить рассчитанный план; превратить его в физически поставляемые полные упаковки; подобрать реальный способ/точку/окно через Ozon; скачать точный шаблон для ручного выполнения.
- **Target market:** русскоязычная работа с Ozon FBO.
- **Locale:** `ru-RU`.
- **Register:** плотный рабочий интерфейс без маркетинговой лексики; технические codes только в диагностике.
- **Accessibility:** WCAG 2.2 AA; 200% zoom remains operable.

## Business-context sources

| Domain / scope | Authoritative source |
|---|---|
| API-first shipment/data architecture and operational rules | `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md` + correction patch |
| Target Plan/Data frontend behavior | `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md` + correction patch |
| Demand/stockout/Flow semantics | `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md` |
| Product Completion semantics not superseded later | `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md` |
| Runtime/backend/frontend boundary | `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` |

Archived documents have no active UX precedence.

## Visual contract

- `DESIGN.md` defines the approved visual identity and semantic tokens.
- Runtime implementation remains committed vanilla HTML/CSS/JavaScript.
- No gradients, glassmorphism, dark-dashboard language, decorative KPI mosaics or Ozon-brand imitation.
- Use the existing light engineering-console register, compact spacing, data density, semantic color roles and stable layout geometry.
- `Ozon → Наша потребность → План` remains the decision-line signature.
- Color is never the only carrier of status.
- Existing shared primitives are reused rather than duplicated screen-locally.

## Canonical navigation

Top-level routes remain exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Route changes preserve section-local state during the session and remain compatible with browser Back/Forward when routing is hash-based.

Document titles remain route-specific and user-readable.

## Current-runtime versus active target

Before PR-E, some committed Plan/Data screens still represent the previously shipped UI. That runtime is compatibility evidence, not permission to extend superseded selected-network behavior.

For any new API-first work:

```text
09.09 API-first UI spec + correction patch
wins over old Plan/Data runtime patterns
```

Historical `Потоки спроса` and existing visual identity are explicitly preserved unless a later approved design changes them.

## Shared behavior owners

Recurring behavior has one canonical owner. Equivalent screen-local copies are prohibited.

Existing/shared owners include:

```text
SearchField
Notice/status
ProgressPanel
DataTable/table framing
FormState
FlowView / Flow primitives
RankedBars where already used
```

API-first roadmap adds canonical owners in PR-E:

```text
OzonConnectionPanel
CredentialVaultDialog
SourceModePanel
ArticlePlanSelector
PlanProductWorkspace
ShipmentIntentForm
HandoffPointSelector
ShipmentManifest
OzonValidationStatus
```

The old `SupplyNetworkSelector` is not an active future owner.

## Component behavior baseline

All interactive controls must have stable:

```text
default
hover
focus-visible
active/selected
disabled
busy
error
```

Busy state does not change control geometry. Validation errors are persistent and correction-oriented; toasts may acknowledge but never contain the only error detail.

Use native semantic buttons, labels, inputs, checkboxes and tables where appropriate. No browser `alert`, `confirm` or `prompt` for normal product flows.

## Async ownership and stale-response safety

External/source/analysis/shipment actions remain explicit user actions.

Required behavior:

- duplicate submit prevention;
- request/run identity so stale responses cannot replace newer state;
- previous successful result remains visible during refresh and on recoverable failure;
- edited draft inputs remain available for correction/retry;
- source refresh, analysis recalculation and shipment validation have separate freshness ownership;
- an Ozon/API failure never silently switches to FILES mode.

## Data-source UX

API is the primary operational source. FILES is an explicit reserve workflow, not an automatic or casual peer toggle.

Canonical hierarchy in target `Данные`:

```text
Ozon connection/session state
→ source freshness by business domain
→ seller-local Unitka / multiplicity inputs
→ explicit manual-import fallback
```

The UI must say that API and file source domains are not mixed inside one analysis run.

Secrets never appear in long-lived frontend state, URL, Project JSON, logs or source snapshots.

Three freshness concepts remain separate when relevant:

```text
Данные Ozon обновлены
План рассчитан
Варианты Ozon проверены
```

## HandoffPointSelector contract

Hand-off points are **remote Ozon search results**, not a bulk preloaded source catalog.

Target interaction:

```text
user types query
<4 trimmed chars → no request
>=4 chars → ~300 ms debounced localhost search
→ Ozon-backed results
→ select concrete warehouse_id
```

Rules:

- IME/composition-safe input;
- stale-response/run-sequence protection;
- previous selected points remain visible during search failure;
- show returned point name, address and point type;
- no free-form warehouse-ID field;
- persisted preferred IDs are only preferences until resolved again after restart;
- cross-dock action remains blocked until required selected IDs are resolved by backend evidence.

## `План → Товары` target contract

The target primary Plan view is article-first master/detail, not a giant global `SKU × cluster` table.

Canonical identity rule:

```text
SKU = stable selector/state identity
article = primary seller-facing display/business label
```

If one article maps to multiple Ozon SKUs, do not collapse them silently. Render separate SKU-backed items and expose identity diagnostics.

### Left selector

Each item is one SKU-backed product context and shows compact business-identifying information such as:

```text
article · short name
SKU secondary
К поставке N · M кластеров
```

Search is local/immediate across article/SKU/name and has an explicit clear action.

### Selected product header

Show product identity once:

```text
article / full name / SKU
pack multiple
resolved seller stock
whole-pack available
unit volume
placement-zone evidence/quality
source freshness
```

Unknown values display `Не рассчитано`, never frontend zero fallback.

### Decision line

Keep:

```text
Ozon → Наша потребность → План
```

When no exact comparable Ozon API recommendation exists, say so explicitly. Never substitute another metric to fill the first value.

### Selected-SKU cluster table

Default target columns:

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

The table belongs only to the selected SKU and owns its local overflow/pagination.

Pack rounding is explicit (`17 → 18`, `кратность 6`) and is not a warning unless a real constraint exists.

## `План → Отгрузки` target contract

Shipment configuration is user intent, not fake availability.

Target controls:

```text
date range
allowed methods
remote hand-off point selection
selected destination clusters
preferred clusters/shipment
max clusters/shipment
explicit action: Найти варианты в Ozon
```

Changing a field marks shipment results dirty/stale only. It makes no Ozon call automatically.

Initial cluster behavior:

- first successful complete ShippablePlan: select all positive complete destination clusters;
- after explicit user selection: preserve surviving selected IDs on later analysis; newly appearing clusters default unselected.

Selected cluster scope is filter-only over the existing all-cluster ShippablePlan. It never reallocates seller stock.

## Shipment candidate/validation lifecycle

Keep three concepts distinct:

```text
Кандидат
Проверено Ozon
реальная заявка на поставку
```

The active milestone implements only the first two. It may create temporary drafts for checking; it does not create the real supply request.

Near `Найти варианты в Ozon`, state that temporary drafts may be created and real supply requests are not created.

Forbidden success copy before future PR-F:

```text
Поставка создана
Забронировано
Заявка подтверждена
```

Observed temporary-draft timeslot wording may say `Окно доступно при проверке`, not booked/confirmed.

## Shipment manifests

A validated option is rendered as a restrained logistics worksheet, not a decorative KPI card.

Show when available:

```text
date / method / concrete hand-off point
clusters
accepted quantity / estimated item volume / SKU count
Ozon acceptance state
timeslot evidence
optional travel-time evidence
checked timestamp
zone composition / packing note when relevant
```

Rejected/partial items stay in context with affected article/SKU/cluster/qty and human-readable Ozon cause.

Stable causal states remain distinct:

```text
Ozon отклонил состав
Нет доступных окон в выбранный период
Ozon временно ограничил частоту проверок
Не удалось связаться с Ozon
Результат создания временного черновика неизвестен
Не подходит по локальному ограничению
```

Network/service failure must not be rendered as product rejection.

## PVZ wording and local pre-check

PVZ 1000 L is a **candidate-total estimated item-volume** pre-check.

Before live validation:

```text
Предварительно подходит для ПВЗ
```

Passing the local estimate does not prove actual packed cargo volume, box count, per-box weight or exact selected-point acceptance.

After successful temporary-draft/timeslot validation, wording may say:

```text
Состав принят Ozon · окно найдено
```

Keep manual note where relevant:

```text
Перед фактической отгрузкой проверьте упаковку, число/вес коробов
и требования выбранной точки в Ozon.
```

## Placement-zone presentation

Normalized zone evidence survives from backend operational lines into candidate/validated manifest presentation.

If one option contains multiple zones:

- show zone composition;
- keep the option together if the selected Ozon method permits it;
- show manual packing guidance (`При упаковке разделите грузоместа по зонам размещения`);
- do not fabricate cargo boxes/pallets or claim packing validation.

Frontend does not recompute placement-zone business logic.

## Manual export UX

Only backend-validated exportable options expose:

```text
Скачать шаблоны Ozon
```

One cluster → XLSX. Multiple clusters → ZIP with per-cluster XLSX.

Browser never generates or repairs export quantities.

Backend aggregation is fail-closed: same `article + cluster` rows with conflicting SKU or pack multiple cannot be silently merged/exported.

Export failure stays local to the chosen manifest; the validated option remains visible.

## `Потоки спроса` contract

Historical Flow remains a first-class analytical mode and is not a shipment scheduler.

Core modes remain bounded/focused:

```text
по кластеру спроса
по кластеру отгрузки
по артикулу/SKU
```

The primary visualization remains selected-context hub-and-spoke / bounded flow, not a global all-cluster Sankey/chord canvas.

Every visual relationship has a text equivalent with exact values. Thickness/color cannot be the only information carrier.

Historical origin is fulfillment evidence, not future demand ownership or automatic shipment weight.

Do not reintroduce the superseded selected-network planned-coverage view as an active target unless a later approved design explicitly does so.

## Economics contract

`Экономика` continues to expose existing unit/route economics and diagnostics without changing mathematical ownership.

Shipment ranking in the active roadmap is operational/service-level. Customer-delivery `RouteCostIndex` / `DirectRouteQuote` is not seller→Ozon inbound cost evidence and must not be surfaced as if it selected the cheapest supply method.

## Responsive / zoom behavior

Desktop/laptop remains the primary work scene, but narrow windows and 200% zoom must keep all functionality reachable.

Target Plan at narrow width stacks:

```text
article selector
↓
selected article detail
```

rather than squeezing two unusable columns.

Tables own their horizontal overflow; root page must not use `overflow:hidden` to fake fit.

Shipment controls stack logically and manifest actions remain reachable.

## PR-E migration acceptance

PR-E finishes this transition by ensuring runtime, `DESIGN.md` and this contract agree on:

```text
API-first Data hierarchy
article-first SKU-backed Plan
remote HandoffPointSelector
shipment intent / candidate / Ozon-validation lifecycle
zone composition
manual export
no selected-network future workflow
```

After PR-E, root contracts become the durable post-migration source and transitional wording must be removed or updated accordingly.
