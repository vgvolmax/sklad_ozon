# UX Contract

## Status and precedence

This root contract is the durable cross-screen behavior contract for the currently shipped application plus the migration boundary for the active API-first roadmap.

Read current/target behavior in this order:

1. `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md` for active business/data/operational ownership;
2. `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md` for target `План` / `Данные` behavior;
3. this file for durable cross-screen behavior and current runtime baseline;
4. `DESIGN.md` for visual identity/tokens.

There is no active correction/amendment overlay.

The superseded selected-network / PlanningSnapshot workflow is not an active future requirement. Do not reconstruct `SupplyNetworkSelector`, network-only replan, selected-network coverage planning or old `План размещения` behavior from Git history/archive.

Before PR-E, committed Plan/Data runtime may still show older presentation. That is compatibility evidence only; new API-first work follows the 09.09 canonical specs. PR-E must update runtime + this file + `DESIGN.md` together so the final root contracts describe shipped behavior without migration notes.

## Product context

- Audience: owner/manager planning Ozon FBO placement and shipments.
- Primary jobs: compare Ozon vs own demand model; inspect demand/fulfillment geography; get Calculated Plan; convert it into whole-pack shipment quantities; choose real seller/handoff points and observed Ozon windows; export exact manual templates.
- Locale: `ru-RU`.
- Register: dense professional operational UI, not marketing.
- Accessibility target: WCAG 2.2 AA; all functions remain reachable at 200% zoom.

## Visual contract

- `DESIGN.md` owns approved visual identity/tokens.
- Runtime remains committed vanilla HTML/CSS/JavaScript.
- Preserve light engineering-console language, compact spacing, stable geometry and semantic color roles.
- `Ozon → Наша потребность → План` remains the signature comparison line.
- No gradients, glassmorphism, dark-dashboard language, decorative KPI mosaics or Ozon-brand imitation.
- Color is never the only carrier of status.

## Canonical navigation

Top-level routes remain exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Inside target `План`:

```text
Товары | Отгрузки
```

Historical `Потоки спроса` remains a first-class analytical route and is not a shipment scheduler.

## Shared behavior ownership

Recurring behavior must have one shared owner. Equivalent screen-local copies are prohibited.

Existing/shared owners include concepts equivalent to:

```text
SearchField
Notice/status
ProgressPanel
DataTable/table framing
FormState
FlowView
RankedBars where already used
```

API-first PR-E adds/standardizes:

```text
OzonConnectionPanel
CredentialVaultDialog
SourceModePanel
ArticlePlanSelector
PlanProductWorkspace
ShipmentIntentForm
SellerWarehouseSelector
HandoffPointSelector
ShipmentManifest
OzonValidationStatus
```

The old `SupplyNetworkSelector` is not an active future owner.

## Component behavior baseline

All enabled interactive controls provide stable:

```text
default
hover
focus-visible
active/selected
disabled
busy
error
```

Busy state must not change control geometry. Errors are persistent and correction-oriented. Toasts may acknowledge, but never hold the only actionable failure detail.

Use semantic native buttons, labels, inputs, checkboxes and tables where appropriate. No browser `alert`, `confirm` or `prompt` for normal product flows.

## Async/stale-response contract

External/source/analysis/shipment actions are explicit user actions.

Required behavior:
- duplicate submit prevention;
- request/run identity so stale responses cannot replace newer state;
- previous successful result stays visible during refresh and recoverable failure;
- edited draft values remain available for correction/retry;
- source refresh, analysis recalculation and shipment validation own separate freshness states;
- Ozon/API failure never silently switches to FILES mode.

## Data-source UX

API is the primary operational source. FILES is an explicit reserve workflow, not an automatic peer toggle.

Target `Данные` hierarchy:

```text
Ozon connection/session
→ source basis/freshness by business domain
→ local Unitka / pack inputs
→ explicit manual FILES fallback
```

API and FILES domains are not mixed inside one analysis run.

Secrets never appear in long-lived frontend state, URL, Project JSON, logs or source snapshots.

Keep distinct:

```text
Данные Ozon обновлены
План рассчитан
Варианты Ozon проверены
```

API `source_as_of` is backend-owned and read-only in UI. API history depth is backend policy, not an everyday UI control.

## Ozon connection/vault UX

First setup collects Client-Id, masked API-Key, vault password and confirmation. Saved API key is never shown again. Restart asks only for vault password.

Unlocked connection view exposes masked Client-Id suffix and actions to refresh, lock and replace connection.

No inactivity auto-lock in active scope.

Wrong password/auth/network failures preserve entered values where safe and provide specific recovery steps.

## Article-first Plan contract

Presentation is article-first; canonical state identity is SKU:

```text
selectedSku = stable item identity
article = primary seller-facing label
```

Never collapse multiple Ozon SKUs sharing one article.

Left selector is bounded and shows one item per SKU-backed product context. Search matches article/SKU/name with explicit clear.

Selected-product header shows identity once plus pack multiple, resolved seller stock, whole-pack available, unit volume, zone evidence and freshness.

Unknown = `Не рассчитано`, never frontend zero fallback.

Decision line keeps `Ozon → Наша потребность → План`. If no exact comparable Ozon signal exists, say so explicitly instead of substituting another metric.

Selected-SKU cluster table default fields:

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

Pack rounding is visible but not a warning by itself.

## Shipment intent contract

Target controls:

```text
date range
allowed methods
selected destination clusters
preferred/max clusters per shipment
seller warehouse when cross-dock requires selection
remote handoff point selection
explicit Найти варианты в Ozon action
```

Editing controls marks shipment state dirty only and makes no automatic API call.

Initial cluster scope:
- first complete positive ShippablePlan → all positive complete clusters selected;
- after explicit user change → preserve surviving IDs; newly appearing clusters unselected.

Selected scope is filter-only over existing all-cluster ShippablePlan and never reallocates stock.

## SellerWarehouseSelector contract

Seller warehouses come from current source snapshot.

Cross-dock rules:

```text
0 active → blocking unavailable
1 active → resolved automatically / shown as fixed context
>1 active → user must choose Склад отправления
```

DIRECT does not require the cross-dock seller warehouse field.

Persisted ID is preference only; backend validates current active identity. Do not expose contacts/courier comments.

## HandoffPointSelector contract

Handoff points are remote Ozon search results, not bulk catalog data.

```text
<4 trimmed chars → no request
>=4 → ~300 ms debounced localhost search
```

Required:
- IME-safe input;
- stale-response protection;
- explicit clear;
- previous selected points remain visible during search failure;
- show returned name/address/point type;
- no free-form warehouse-ID input;
- preferred IDs after restart are unresolved preferences until backend search evidence resolves them;
- cross-dock action blocked until required IDs resolve.

## Candidate/validation lifecycle

Keep three concepts distinct:

```text
Кандидат
Проверено Ozon
реальная заявка на поставку
```

Current milestone implements only first two. It may create temporary drafts for checking and does not create a real supply request.

Near `Найти варианты в Ozon` disclose that temporary drafts may be created and real supply requests are not created.

Forbidden success copy before future PR-F:

```text
Поставка создана
Забронировано
Заявка подтверждена
```

Observed timeslot may say `Окно доступно при проверке`.

## Shipment manifest contract

Validated option is a restrained logistics worksheet, not decorative KPI card.

Show when available:

```text
date / method
seller warehouse for cross-dock
concrete handoff point
clusters
accepted qty / estimated item volume / SKU count
Ozon acceptance state
timeslot evidence
optional travel time
checked timestamp
placement-zone composition / manual packing note
```

Rejected/partial items remain visible with article/SKU/cluster/qty and human-readable cause.

Keep causal states distinct:

```text
Ozon отклонил состав
Нет доступных окон
Ozon ограничил частоту проверок
Не удалось связаться с Ozon
Результат создания временного черновика неизвестен
Не подходит по локальному ограничению
Склад отправления недоступен/не выбран
Точка отгрузки устарела/не разрешена
```

Network failure must not render as product rejection.

## PVZ and placement zones

PVZ 1000 L is candidate-total estimated item-volume pre-check.

Before validation use `Предварительно подходит для ПВЗ`.

Passing does not prove packed volume, box count, per-box weight or exact point acceptance.

Placement-zone evidence is backend-owned and survives into candidate/manifest. Multiple zones may produce manual packing guidance; frontend never fabricates boxes/pallets or recomputes compatibility.

## Export UX

Only backend-validated/exportable ranked options expose `Скачать шаблоны Ozon`.

One cluster → XLSX; multiple → ZIP. Browser never generates/repairs quantities.

Backend same-article identity/pack conflicts fail closed; export failure stays local to the manifest and does not erase validated evidence.

## Flow/Economics contracts

Historical Flow remains focused/bounded and preserves destination/origin/SKU semantics. Every visual relationship has exact text equivalent; origin is fulfillment evidence, not future demand ownership.

Economics keeps current mathematical ownership. Shipment ranking is operational/service-level; customer-delivery route costs are not seller→Ozon inbound tariff evidence.

## Responsive/zoom

Desktop/laptop primary. At narrow width/200% zoom:
- article selector stacks above selected-product detail;
- tables own horizontal overflow;
- root page must not use `overflow:hidden` to fake fit;
- shipment controls stack logically;
- manifest actions remain reachable.

## PR-E completion

PR-E finishes migration by making runtime, `DESIGN.md` and this contract agree on:

```text
API-first Data hierarchy
SKU-backed article-first Plan
SellerWarehouseSelector
remote HandoffPointSelector
shipment intent / temporary validation lifecycle
candidate-total PVZ semantics
zone composition/manual packing guidance
backend export
no selected-network future workflow
no real supply creation
```

After PR-E, remove/update migration wording so root contracts describe the shipped UI directly.