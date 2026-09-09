# API-First Plan & Data UI — Canonical Design

**Date:** 2026-09-09  
**Status:** APPROVED / ACTIVE UI SOURCE OF TRUTH  
**Scope:** target `План` / `Данные` UI for the active API-first shipment roadmap.  
**Business owner:** `2026-09-09-ozon-api-first-shipment-planner-design.md`.

This document is self-contained. Prior shipment/UI correction overlays are archived history only.

## 1. Product register

The product remains a dense light engineering/logistics console for a Russian-speaking Ozon FBO operator.

Keep:

- established palette/type/spacing language from `DESIGN.md` and runtime tokens;
- `Ozon → Наша потребность → План` as the signature comparison line;
- compact desktop/laptop density;
- top-level routes exactly `План | Потоки спроса | Экономика | Данные`;
- historical `Потоки спроса` behavior and current economics screens unless a later approved design changes them.

Do not introduce gradients, glassmorphism, marketing hero blocks, dark-dashboard language, decorative KPI mosaics or Ozon-brand imitation.

Target WCAG 2.2 AA and 200% zoom operability.

## 2. Information architecture

Inside `План`:

```text
Товары | Отгрузки
```

### `План → Товары`

Single job:

> inspect one SKU-backed product context, compare Ozon/Need/Plan, and see exact whole-pack quantities by destination cluster.

Desktop composition:

```text
┌ bounded product selector ┐ ┌ selected product workspace ┐
│ article / short name     │ │ identity + decision line   │
│ SKU secondary            │ │ cluster table              │
│ shipment summary         │ │ assignment evidence        │
└──────────────────────────┘ └────────────────────────────┘
```

At narrow width / 200% zoom, selector stacks above workspace. Do not squeeze two unusable columns.

### `План → Отгрузки`

Single job:

> express shipment intent, resolve seller/handoff points, explicitly ask Ozon to validate bounded candidates, and inspect/export validated logistics options.

The user controls intent. The UI never fabricates availability.

### `Данные`

Canonical hierarchy:

```text
Ozon API connection/session
→ source freshness/capability status
→ seller-local Unitka / pack-multiplicity inputs
→ explicit FILES fallback
```

API is primary. FILES is a reserve analytical workflow, not a peer auto-toggle or a hybrid live-validation mode.

## 3. Canonical product identity

Presentation is article-first; state identity is SKU.

```text
selectedSku = canonical selector identity
article = primary seller-facing label
```

Never collapse two Ozon SKUs because they share one article. If that occurs, render separate SKU-backed selector items and show an identity diagnostic.

Search may match article, SKU and name.

## 4. `План → Товары`

### 4.1 Product selector

Each selector item represents exactly one SKU-backed product, not one cluster.

Compact item:

```text
40750 · Кран шаровой ...
SKU 123456789
К поставке 48 · 6 кластеров
```

At most one concise blocking/incomplete status is shown in the selector item. Detailed diagnostics stay in the workspace.

Search is local and immediate with an explicit clear button; clear restores input focus.

Selection reconciliation:

- keep prior SKU if it still exists;
- otherwise choose first visible stable item;
- never use article alone as state key.

### 4.2 Product header

Show identity once:

```text
article
full product name
SKU
pack multiple
resolved seller stock
whole-pack available
unit volume
placement-zone evidence/quality
analysis/source freshness
```

Unknown values render `Не рассчитано`, never zero by frontend fallback.

### 4.3 Decision line

Keep:

```text
Ozon → Наша потребность → План
```

If API mode lacks an exact comparable Ozon recommendation, show e.g.:

```text
Ozon: нет сопоставимого API-сигнала
```

Never substitute another metric.

### 4.4 Selected-SKU cluster table

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

The table belongs only to selected SKU and owns its local overflow/pagination. Product name/article are not repeated in every cluster row.

Pack adjustment is explicit (`17 → 18`, `кратность 6`) and is not styled as an error unless a real constraint exists.

Selected shipment clusters later are filter-only; changing them never changes this analytical/whole-pack table quantity.

## 5. `Данные` API connection and vault

### 5.1 First setup

```text
Подключить Ozon API

Client-Id
[____________]

API-Key
[••••••••••••] [Показать]

Пароль хранилища
[••••••••]

Повторите пароль
[••••••••]

Пароль потребуется после каждого запуска.
Если пароль забыт, подключение нужно настроить заново.

[Сохранить и проверить]
```

API key/password are masked by default. Show/hide applies only while entering/replacing a new key. Saved API key is never rendered back.

### 5.2 Locked restart

```text
Ozon API
○ Хранилище заблокировано

Пароль
[••••••••]

[Разблокировать]
```

Wrong password preserves typed value and shows a persistent correction-oriented error.

### 5.3 Unlocked state

```text
Ozon API
● Подключено
Client-Id ···4821
Разблокировано для этой сессии

[Обновить данные]
[Заблокировать]
[Заменить подключение]
```

No inactivity auto-lock.

## 6. API source UX

After unlock, show business-domain freshness separately:

```text
Заказы / история
FBO остатки
Поставки в пути
Остаток продавца
Кластеры
Склады отправления продавца
Зоны размещения
```

Do not render one generic green `sync ok` if a capability is incomplete.

Three timestamps remain distinct:

```text
Данные Ozon обновлены
План рассчитан
Варианты Ozon проверены
```

`source_as_of` is backend-owned and shown as the data basis, not editable in API mode.

API history range is backend-owned. Do not add an everyday control for the 12-week/backfill policy.

Failed refresh keeps previous successful snapshot visible and marks new refresh failure without silently entering FILES mode.

## 7. FILES fallback

Primary surface uses an action such as:

```text
[Использовать ручной импорт]
```

On entry, disclose:

```text
Ручной импорт — резервный режим.
Данные API и файлов в одном расчёте не смешиваются.
```

FILES remains an analytical fallback: Plan/Flow may be calculated from manual files where evidence is complete, but live handoff search, temporary Ozon drafts and timeslot validation are unavailable in this mode. Do not silently supplement FILES analysis with current API operational data.

When the user opens `Отгрузки` from FILES-backed analysis, keep local analytical/whole-pack evidence inspectable where available but disable `Найти варианты в Ozon` with a correction-oriented action to return to `Данные`, switch to API mode, unlock and sync.

The mode change is explicit user action. API errors never toggle it automatically.

## 8. Shipment intent

Target controls:

```text
Период поставки
[date from] — [date to]

Способы
☑ ПВЗ
☑ СЦ
☑ Прямая

Кластеры
[scope selector]

Кластеров в поставке
желательно [3]
максимум   [5]

Склад отправления
[resolved seller warehouse / selector when required]

Точка отгрузки
[remote Ozon search]

[Найти варианты в Ozon]
```

Control ownership is intentionally minimal:

- shipment `date_from` / `date_to` use native `input[type="date"]` while platform-owned calendar behavior is acceptable for this desktop tool;
- when multiple active seller warehouses require a choice, use native `<select>`; one active warehouse is fixed resolved context, not a selector;
- `HandoffPointSelector` is the one authored async selection control: accessible remote combobox/listbox with owned search/results behavior.

Do not introduce a custom date picker or custom generic Select solely for visual styling. A later approved UX requirement may change ownership if native behavior becomes insufficient.

Editing any field changes shipment draft state only. It does not recalculate analysis, refetch source data or call Ozon.

### 8.1 Cluster initialization

- first complete positive ShippablePlan: select all positive complete clusters;
- after user explicitly changes selection: preserve surviving selected IDs on later analysis;
- newly appearing clusters default unselected;
- selection is filter-only and never reallocates seller stock.

### 8.2 Seller warehouse selector

Seller warehouses come from the current API source snapshot.

Rules:

- if exactly one active seller warehouse exists, show it as fixed resolved context and backend may auto-use it for cross-dock;
- if multiple active seller warehouses exist and cross-dock is selected, require explicit `Склад отправления` selection using native `<select>`;
- DIRECT does not require this cross-dock field;
- stale/inactive IDs surface a blocking correction message;
- do not expose seller-warehouse contacts/courier comments.

Persisted preferred seller warehouse ID is non-secret preference only; backend still validates it against current snapshot.

## 9. HandoffPointSelector

Hand-off points are remote Ozon search results, not preloaded catalog data.

Interaction:

```text
<4 trimmed characters → no request
>=4 → ~300 ms debounced localhost search
```

Required authored-combobox behavior:

- semantic input + listbox/options with keyboard operation and accessible name/state;
- IME/composition-safe input;
- stale-response/run-sequence protection;
- clear button cancels/invalidates pending work and restores focus;
- previous selected points remain visible while new search is busy/fails;
- show Ozon-returned name, address and point type;
- no free-form warehouse ID entry;
- unknown/stale preferred IDs must be resolved again after restart;
- cross-dock action remains blocked until selected point IDs resolve in backend `HandoffPointStore`.

Do not claim address search beyond what Ozon actually documents for its search string.

## 10. External validation disclosure

Near `Найти варианты в Ozon` show persistent explanatory copy:

```text
Для проверки приложение создаст временные черновики в Ozon.
Реальные заявки на поставку не создаются.
```

The button is the only user action that starts candidate → temporary draft → timeslot validation, and it is available only for API-backed analysis with an unlocked current Ozon source context.

If vault is locked, direct the user to `Данные` to unlock. If the current analysis is FILES-backed, direct the user to API mode and sync. Do not embed an ad-hoc secret/password prompt in Plan.

## 11. Candidate and validation states

Keep concepts distinct:

```text
Кандидат
Проверено Ozon
реальная заявка на поставку  # future, absent now
```

Forbidden success copy in current milestone:

```text
Поставка создана
Забронировано
Заявка подтверждена
```

Observed timeslot copy may say:

```text
Окно доступно при проверке
```

not `забронировано`.

## 12. Shipment manifests

Validated options are rendered as restrained logistics worksheets, not decorative KPI cards.

Show when available:

```text
date / method
seller warehouse (for cross-dock)
concrete hand-off point
clusters
accepted qty / estimated item volume / SKU count
Ozon acceptance state
timeslot evidence
optional travel time
checked timestamp
placement-zone composition
manual packing note when relevant
```

Rejected/partial lines stay visible with affected article/SKU/cluster/qty and human-readable Ozon reason.

Causal states stay distinct:

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

Network failure must never render as product rejection.

## 13. PVZ and placement-zone wording

PVZ 1000 L is a **candidate-total estimated item-volume** pre-check.

Before live validation:

```text
Предварительно подходит для ПВЗ
```

Passing does not prove actual packed volume, box count, per-box weight or exact point acceptance.

After successful temporary draft/timeslot validation:

```text
Состав принят Ozon · окно найдено
```

Still show manual reminder where relevant:

```text
Перед фактической отгрузкой проверьте упаковку, число/вес коробов
и требования выбранной точки в Ozon.
```

Placement zones are backend-owned evidence. If an option contains multiple zones, show zone composition and manual guidance such as:

```text
При упаковке разделите грузоместа по зонам размещения
```

Frontend never recomputes zone compatibility or invents boxes/pallets.

## 14. Export UX

Only backend-produced exportable accepted/ranked options expose:

```text
[Скачать шаблоны Ozon]
```

One cluster → XLSX. Multiple → ZIP. Browser never generates or repairs quantities.

Backend identity conflicts disable export and show the blocking reason while keeping the validated option visible.

## 15. Async/freshness ownership

Separate state ownership:

```text
sourceDirty / source freshness
analysisDirty / analysis freshness
shipmentDirty / validation freshness
```

Rules:

- source refresh invalidates downstream analysis/shipment;
- horizon/inbound changes invalidate analysis/shipment but do not auto-sync;
- shipment scope/date/method/seller warehouse/handoff changes invalidate shipment only;
- no checkbox/date edit triggers network automatically;
- duplicate submits are prevented;
- stale responses cannot replace newer state;
- previous successful result remains visible during refresh and recoverable failure.

## 16. Shared behavior owners

Reuse/extend shared project owners rather than screen-local copies. Target recurring owners include:

```text
SearchField
Notice/status
ProgressPanel
DataTable/table framing
FormState
FlowView
OzonConnectionPanel
CredentialVaultDialog
SourceModePanel
ArticlePlanSelector
PlanProductWorkspace
ShipmentIntentForm
SellerWarehouseSelector      # business wrapper may render native <select>
HandoffPointSelector         # authored async combobox/listbox
ShipmentManifest
OzonValidationStatus
```

Native semantic buttons/labels/checkboxes/tables/date inputs/selects are preferred when sufficient. No browser `alert`, `confirm` or `prompt` for product flows.

All enabled interactive controls need default/hover/focus-visible/active/disabled/busy/error behavior. Busy state keeps stable geometry.

## 17. PR-E completion gate

PR-E must make runtime, `DESIGN.md` and `UX-CONTRACT.md` agree on:

```text
API-first Data hierarchy
article-first SKU-backed Plan
seller warehouse resolution
native shipment dates / native seller-warehouse select
remote authored HandoffPointSelector
FILES analytical fallback without hybrid live validation
shipment intent / candidate / validation lifecycle
candidate-total PVZ wording
zone composition/manual packing note
manual backend XLSX/ZIP export
no selected-network future workflow
no real supply creation
```

After PR-E, root docs are the durable shipped contract and must contain no transitional/superseded target semantics.