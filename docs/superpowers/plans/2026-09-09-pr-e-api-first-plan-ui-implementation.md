# PR-E API-First Article Plan & Shipment UI Implementation Plan

> **Required skills:** `frontend-design`, `frontend-design-premium`, plus Superpowers execution workflow. Implement task-by-task with tests and browser review checkpoints.

**Goal:** make Ozon API the primary `Данные` workflow, replace the wide Plan table with SKU-backed article-first master/detail, and expose shipment intent/live Ozon validation/manifests without changing the established visual identity or historical Flow.

**Stack:** committed vanilla HTML/CSS/JavaScript + existing FastAPI. No npm/framework/bundler/new frontend dependency.

## Global invariants

- Top-level routes remain `План | Потоки спроса | Экономика | Данные`.
- API and FILES are explicit non-mixing modes.
- FILES is analytical fallback only; live handoff/draft/timeslot validation requires API-backed analysis/current source context.
- Frontend never receives saved API key/password.
- SKU is selector/state identity; article is primary display label.
- Shipment edits are local draft state only; no automatic external calls.
- Cross-dock requires resolved seller warehouse + resolved remote-search handoff point.
- `Найти варианты в Ozon` may create temporary drafts but never real supply requests.
- Frontend never calculates demand, whole-pack allocation, candidate grouping, Ozon acceptance, ranking or XLSX.
- Frontend never calculates shipment urgency/stockout dates.
- Preserve previous successful result during refresh/failure.
- WCAG 2.2 AA; 200% zoom operable.
- Same PR updates runtime + root `DESIGN.md` + root `UX-CONTRACT.md` to final post-migration truth.

---

## Task 1 — canonical API connection/vault state

Modify `frontend/assets/js/core.js`; tests in `tests/frontend/test_ui_state.py` / `test_ozon_connection.py`.

State may include:

```javascript
ozonConnection: {
  configured: false,
  locked: true,
  maskedClientIdSuffix: null,
  lastConnectionCheck: null,
  busy: false,
  error: null
},
source: {
  mode: 'api',
  snapshotId: null,
  sourceAsOf: null,
  syncedAt: null,
  syncBusy: false,
  syncError: null,
  endpointStates: []
}
```

No secret field exists in long-lived app state.

Add stale-response/run-sequence ownership and explicit API→FILES transition helper; API error alone never changes mode.

---

## Task 2 — render Ozon connection in `Данные`

Render semantic setup/unlock/lock forms using existing tokens/primitives.

First setup fields:
- Client-Id;
- masked API-Key with temporary show/hide;
- vault password + confirmation.

After save, never render saved API key. Restart locked view asks only vault password.

Unlocked panel shows masked Client-Id suffix and actions:

```text
Обновить данные
Заблокировать
Заменить подключение
```

No crypto jargon in normal UI. Errors are persistent/correction-oriented, labels are real, no browser validation bubbles/`alert()`.

---

## Task 3 — API-first source hierarchy and explicit FILES fallback

In `Данные`, render business-domain freshness rows:

```text
Заказы / история
FBO остатки
Поставки в пути
Остаток продавца
Кластеры
Склады отправления продавца
Зоны размещения
```

Show source basis (`sourceAsOf`) read-only in API mode. Do not expose everyday control for backend 12-week/backfill history policy.

Keep seller-local Unitka/pack inputs separate.

Manual files are hidden/secondary until user explicitly chooses `Использовать ручной импорт`, with disclosure that API/file data are not mixed.

FILES mode remains analytical fallback only. It may calculate existing Plan/Flow from file evidence, but it must not expose live handoff search, temporary draft validation or timeslot checks. Show a clear action to return to API mode, unlock and sync instead of constructing a hybrid FILES+API workflow.

Failed refresh preserves prior source snapshot and never silently switches mode.

Extend analysis request builder:
- API mode sends source snapshot identity + local seller inputs/settings;
- FILES mode keeps legacy file bundle;
- never both;
- API mode does not send arbitrary historical `as_of`.

---

## Task 4 — article-first Plan state

Canonical state:

```javascript
planView: {
  subview: 'products',
  articleQuery: '',
  selectedSku: null,
  clusterSort: {key:'cluster', direction:'asc'},
  clusterPage: 1,
  clusterPageSize: 50
}
```

`buildArticlePlanItems` groups cluster rows under SKU identity, not article alone.

If one article maps to multiple SKUs, render separate selector items and identity diagnostic.

Selection reconciliation keeps prior SKU if still available; otherwise first visible stable SKU.

Local search matches article/SKU/name; explicit clear restores focus.

---

## Task 5 — render product selector/workspace

Left bounded selector item:

```text
article · short name
SKU secondary
К поставке N · M кластеров
```

Selected header shows identity once: article/name/SKU, pack multiple, resolved seller stock, whole-pack available, unit volume, placement-zone quality, source freshness.

Unknown = `Не рассчитано`.

Decision line stays `Ozon → Наша потребность → План`; absent exact Ozon signal is explicit, never zero/substitute.

Selected-SKU table columns:

```text
Кластер | FBO | В пути | Ozon | Потребность | Аналитический план |
Кратность | К поставке | Объём | Зона | Статус
```

At 200% zoom/narrow width, selector stacks above detail; table owns horizontal overflow.

---

## Task 6 — shipment intent state and cluster initialization

State:

```javascript
shipmentView: {
  selectedClusters: [],
  dateFrom: null,
  dateTo: null,
  allowedMethods: [],
  sellerWarehouseId: null,
  selectedHandoffPointIds: [],
  preferredClusters: 3,
  maxClusters: 5,
  dirty: false,
  candidates: null,
  plan: null,
  busyStage: null,
  error: null
}
```

First complete ShippablePlan selects all positive complete clusters. After user explicitly edits scope, preserve surviving IDs and leave newly appearing clusters unselected.

Shipment dates use native `input[type="date"]`; do not add a custom calendar in this PR.

Field edits mark shipment dirty only and make no request.

---

## Task 7 — SellerWarehouseSelector

Seller warehouses come from current API source snapshot.

Behavior:

```text
0 active + crossdock selected → blocking unavailable state
1 active → show fixed resolved warehouse; no unnecessary chooser
>1 active + crossdock selected → require explicit Склад отправления via native <select>
DIRECT-only → seller warehouse crossdock field not required
```

Do not build a custom generic Select solely for styling. `SellerWarehouseSelector` is the business owner/wrapper; when a choice is needed its control is native `<select>`.

Persisted ID is only preference; backend validates current active identity.

Show safe non-secret label/address evidence only. Do not surface contact/courier-comment fields.

Changing seller warehouse marks shipment dirty only.

---

## Task 8 — remote HandoffPointSelector

Do not use a preloaded API catalog.

This is the authored selection control because it owns asynchronous search/results behavior. Implement as an accessible input + listbox/options combobox pattern rather than a native `<select>`.

Interaction:

```text
<4 trimmed chars → no request
>=4 → ~300 ms debounced POST /api/ozon/handoff/search
```

Required:
- keyboard-operable input/listbox/options with accessible names/states;
- IME-safe input;
- stale-response protection/cancel semantics;
- explicit clear;
- selected points persist visually during search busy/failure;
- show returned name/address/point type;
- no free-form warehouse ID;
- stale preferred ID after restart must be searched/resolved again.

Cross-dock action requires resolved selected point; backend remains final validator.

---

## Task 9 — explicit candidate→plan workflow

Only `Найти варианты в Ozon` starts external flow:

```text
/api/shipment/candidates
→ /api/shipment/plan
```

`/api/shipment/plan` reconstructs the backend candidates, validates them through
`DraftValidationService`, obtains current Ozon evidence/timeslots, ranks the
validated options, and stores the immutable `ShipmentPlan`. The primary PR-E UI
must not call `/api/shipment/validate`, because doing so would repeat live
validation and could create unnecessary temporary drafts. The endpoint remains
an independently supported backend capability.

This action is enabled only for API-backed analysis with current source provenance and an unlocked vault. FILES-backed analysis shows a correction-oriented action to return to `Данные` and use API mode; it must not silently sync/live-validate behind the user's back.

Near action, persistent disclosure:

```text
Для проверки приложение создаст временные черновики в Ozon.
Реальные заявки на поставку не создаются.
```

Busy stages reflect only the two observable requests:

```text
Собираем варианты…
Проверяем варианты в Ozon…
```

During the second stage a calm explanation may say that composition, available
windows, and ranking are being checked; the UI must not simulate intermediate
progress with timers.

Run identity prevents stale responses overwriting newer scenario. Previous successful manifests remain visible during refresh/failure. Locked vault directs user to `Данные`, not an ad-hoc password prompt.

---

## Task 10 — manifests and causal failures

Render lifecycle labels:

```text
Кандидат
Проверено Ozon
```

Never render `Поставка создана`, `Забронировано`, `Заявка подтверждена`.

Validated manifest includes when available:
- date/method;
- seller warehouse for cross-dock;
- concrete handoff point;
- clusters;
- accepted qty / estimated item volume / SKU count;
- acceptance/timeslot/travel evidence;
- checked timestamp;
- placement-zone composition and manual packing note.

Keep rejected/partial rows in context with article/SKU/cluster/qty/Ozon reason.

Distinct persistent failures:

```text
Ozon отклонил состав
Нет доступных окон
Ozon ограничил частоту проверок
Не удалось связаться с Ozon
Результат создания временного черновика неизвестен
Не подходит по локальному ограничению
Склад отправления недоступен/не выбран
Точка отгрузки устарела/не разрешена
Для проверки в Ozon переключитесь на API-режим и обновите данные
```

PVZ before live validation uses `Предварительно подходит`; candidate-total ≤1000 L never becomes a packed-cargo guarantee.

For multiple placement zones show backend-provided composition and manual guidance; frontend does not recompute zone rules.

---

## Task 11 — backend export download

Accepted/exportable ranked option shows `Скачать шаблоны Ozon`.

POST backend option identity to `/api/shipment/export`; use returned blob + Content-Disposition filename. Browser never builds/repairs workbook data.

Identity conflict disables export with persistent reason while manifest remains visible.

---

## Task 12 — final durable design/UX contract migration

In the same PR, update root `DESIGN.md` and `UX-CONTRACT.md` to match shipped runtime.

Required final durable ownership includes:

```text
API-first Data hierarchy
SKU-backed article-first Plan
OzonConnectionPanel/CredentialVaultDialog
SellerWarehouseSelector backed by native <select> when a choice is required
native shipment date inputs
remote authored HandoffPointSelector
FILES analytical fallback without hybrid live validation
ShipmentIntentForm
candidate/validation lifecycle
ShipmentManifest/OzonValidationStatus
candidate-total PVZ semantics
zone composition/manual packing guidance
backend XLSX/ZIP export
no selected-network future workflow
no real supply creation
```

Remove transitional language and empty component-map placeholders by either defining real shipped component ownership or explicitly omitting unsupported groups per DESIGN.md contract.

Do not change visual identity merely to fill documentation.

---

## Task 13 — verification gate

Focused suites:

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_ozon_connection.py tests/frontend/test_data_quality.py -q
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_shipment_view.py -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Run project Premium/static design audit if configured, plus real browser review at normal desktop and 200% zoom/narrow width. Preserve existing real-scale Flow acceptance because shared shell/layout changes may affect it.

Acceptance: API is primary Data workflow, Plan is SKU-backed article-first, FILES remains analytical fallback without hybrid live validation, shipment intent uses minimal native date/seller controls plus one authored remote handoff combobox, live validation is explicit/honest, manifests/export remain backend-owned, and runtime + root durable contracts finish aligned.
