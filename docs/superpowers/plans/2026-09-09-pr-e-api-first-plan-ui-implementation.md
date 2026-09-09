# PR-E API-First Article Plan & Shipment UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `frontend-design`, `frontend-design-premium`, and superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Execute task-by-task with TDD and browser review checkpoints.

**Goal:** Make Ozon API the primary `Данные` workflow, replace the wide Plan table with article-first master/detail, and expose shipment intent/live Ozon validation/manifests without changing the established visual identity or historical Flow.

**Architecture:** Keep the four-route vanilla frontend and existing shared primitives. `Данные` gets one canonical Ozon connection/source panel plus explicit manual fallback. `План` gets `Товары | Отгрузки`; Products consumes backend analysis/ShippablePlan presentation contracts, Shipments edits local intent and calls candidate→validate→plan→export endpoints only on explicit actions. Root `DESIGN.md` and `UX-CONTRACT.md` are migrated in the same changeset so shipped UI and durable contracts finish aligned.

**Tech Stack:** committed vanilla HTML/CSS/JavaScript, existing FastAPI endpoints, pytest frontend/static/browser-model tests; no npm/framework/bundler/new frontend dependency.

**Specs:**
- `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`
- `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md`

## Global Constraints

- Preserve top-level `План | Потоки спроса | Экономика | Данные`.
- Do not change established palette/type/tokens except where root docs/runtime already drift and the same PR reconciles them.
- Frontend never receives stored API key or password.
- API-first and FILES fallback are explicit modes; no silent fallback/mixing.
- One article selector item = one SKU/article, never one per cluster.
- Historical `Потоки спроса` remains unchanged.
- Frontend does not calculate demand, pack allocation, candidate grouping, Ozon acceptance, urgency, ranking or XLSX.
- Shipment field edits are draft-only; no automatic external calls.
- `Найти варианты в Ozon` explains temporary drafts and never claims a real supply is created/booked.
- Previous successful data/analysis/shipment result stays visible through stale/loading/failure states.
- Target WCAG 2.2 AA and 200% zoom.
- PR-E must update root `DESIGN.md` and `UX-CONTRACT.md` to final canonical runtime behavior.

---

### Task 1: Add canonical Ozon connection/vault frontend state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`
- Create: `tests/frontend/test_ozon_connection.py`

**State contract:**

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
  mode: 'api',             // api | files
  snapshotId: null,
  syncedAt: null,
  syncBusy: false,
  syncError: null,
  endpointStates: []
}
```

- [ ] **Step 1: Add initial/reconcile tests for configured/locked/unlocked states; no secret field exists in long-lived app state after setup submit.**
- [ ] **Step 2: Add stale-response/run-sequence state for status/sync operations.**
- [ ] **Step 3: Add explicit source-mode transition helper: switching to files requires deliberate action; API error alone never changes mode.**
- [ ] **Step 4: Run RED, implement state helpers, run GREEN and commit.**

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_ozon_connection.py -q
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py tests/frontend/test_ozon_connection.py
git commit -m "feat: add Ozon connection UI state"
```

---

### Task 2: Render first-setup/unlock/lock Ozon connection UI in `Данные`

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `frontend/index.html` only if stable form containers are needed.
- Modify: `tests/frontend/test_ozon_connection.py`

- [ ] **Step 1: Add semantic form tests for Client-Id, masked API-Key, vault password, confirmation and real labels. Show/hide API key exists only for entering/replacing a new key.**
- [ ] **Step 2: Add validation tests: password mismatch, empty fields, inline error association, no browser validation bubble/alert and stable busy geometry.**
- [ ] **Step 3: Add locked-after-restart view requiring password only; wrong password preserves entry and shows `Не удалось разблокировать хранилище...`.**
- [ ] **Step 4: Add unlocked connection panel with masked Client-Id suffix and `Обновить данные`, `Заблокировать`, `Заменить подключение`. Never render saved API key.**
- [ ] **Step 5: Wire setup/unlock/lock/test localhost endpoints with stale-response protection and persistent failure recovery.**
- [ ] **Step 6: Use existing tokens/components; no crypto jargon or new visual palette.**
- [ ] **Step 7: Run focused tests and commit.**

```bash
python -m pytest tests/frontend/test_ozon_connection.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css frontend/index.html tests/frontend/test_ozon_connection.py
git commit -m "feat: manage Ozon connection in Data view"
```

---

### Task 3: Make API sync primary and manual files an explicit fallback

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_analysis_submit.py`
- Create/Modify: `tests/frontend/test_data_quality.py`

- [ ] **Step 1: Render API-first Data hierarchy: connection status → Ozon domain freshness rows → local Unitka/pack inputs → `Использовать ручной импорт`. Existing upload controls stay hidden until fallback mode is explicitly entered.**
- [ ] **Step 2: Add fallback disclosure copy proving `Данные API и файлов в одном расчёте не смешиваются`; switching mode is user action, not an error fallback.**
- [ ] **Step 3: Add sync progress with stable business stages and preserve previous snapshot on failed refresh; show `sourceSyncedAt`, not analysis/shipment timestamps as one value.**
- [ ] **Step 4: Extend analysis request builder: API mode sends source snapshot ID plus local economics/pack files/settings; FILES mode keeps legacy multipart; never includes both source families.**
- [ ] **Step 5: Add stale ownership tests: source refresh invalidates analysis/shipment; analysis setting change does not auto-sync; shipment intent change does neither.**
- [ ] **Step 6: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_data_quality.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend
git commit -m "feat: make Ozon API the primary data source"
```

---

### Task 4: Replace Plan global row state with article-first context

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`
- Modify/Create: `tests/frontend/test_plan_view.py`

**State:**

```javascript
planView: {
  subview: 'products',      // products | shipments
  articleQuery: '',
  articleFilter: 'all',
  selectedSku: null,
  clusterSort: {key:'cluster', direction:'asc'},
  clusterPage: 1,
  clusterPageSize: 50
}
```

- [ ] **Step 1: Add `buildArticlePlanItems(snapshot)` tests: 24 cluster decision rows for article 40750 become exactly one selector item.**
- [ ] **Step 2: Add selection reconciliation: keep prior SKU if still present; else first visible stable article; no item→null.**
- [ ] **Step 3: Add local search/filter helper matching article/SKU/name; clear is immediate and restores focus.**
- [ ] **Step 4: Add `products|shipments` subview helper while top-level route remains `plan`.**
- [ ] **Step 5: Run RED, implement model/state helpers, run GREEN and commit.**

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_plan_view.py -q
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py tests/frontend/test_plan_view.py
git commit -m "feat: add article-first Plan state"
```

---

### Task 5: Render article selector, persistent detail and focused cluster table

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Render bounded left selector: `article · short name`, SKU secondary, `К поставке N · M кластеров`, at most one concise warning. Each item is a semantic button with selected state.**
- [ ] **Step 2: Render selected product header once: article/full name/SKU, pack multiple, resolved seller stock, whole-pack available, unit volume, placement-zone quality, source freshness. Unknown=`Не рассчитано`.**
- [ ] **Step 3: Render decision line. If exact Ozon comparison is absent in API mode, show `Ozon: нет сопоставимого API-сигнала` instead of zero/substitute.**
- [ ] **Step 4: Render only canonical selected-SKU cluster columns: `Кластер | FBO | В пути | Ozon | Потребность | Аналитический план | Кратность | К поставке | Объём | Зона | Статус`.**
- [ ] **Step 5: Show rounding explicitly (`17 → 18`, `кратность 6`) without warning tone unless a real constraint exists. Remove repeated product identity and default `Открыть детали` per cluster.**
- [ ] **Step 6: Desktop bounded selector + flexible detail; at 200% zoom/narrow width stack selector above detail; cluster table owns overflow, never root page.**
- [ ] **Step 7: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: render article-first Plan workspace"
```

---

### Task 6: Add shipment intent and hand-off point selector

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Create: `tests/frontend/test_shipment_view.py`

**State:**

```javascript
shipmentView: {
  selectedClusters: [],
  dateFrom: null,
  dateTo: null,
  allowedMethods: [],
  selectedHandoffPointIds: [],
  preferredClusters: 3,
  maxClusters: 5,
  dirty: false,
  candidates: null,
  validation: null,
  plan: null,
  busyStage: null,
  error: null
}
```

- [ ] **Step 1: Add first-use cluster behavior: if no prior explicit selection, select all positive complete ShippablePlan clusters; after explicit selection preserve surviving IDs and leave newly appearing clusters unselected.**
- [ ] **Step 2: Render date range, method checkboxes, preferred/max clusters and searchable hand-off selector backed by API catalog. No free-form Ozon warehouse ID.**
- [ ] **Step 3: Cross-dock requires selected hand-off point; DIRECT does not. Backend still validates.**
- [ ] **Step 4: Changing any shipment field sets shipment dirty only and makes no request.**
- [ ] **Step 5: Validate at least one positive selected cluster/method and valid dates before action; preserve values/errors with accessible descriptions.**
- [ ] **Step 6: Add nearby disclosure: `Для проверки приложение создаст временные черновики в Ozon. Реальные заявки на поставку не создаются.`**
- [ ] **Step 7: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_shipment_view.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_shipment_view.py
git commit -m "feat: add shipment intent workspace"
```

---

### Task 7: Wire explicit candidate → validate → plan async flow

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_shipment_view.py`

- [ ] **Step 1: `Найти варианты в Ozon` is the only action that starts this external workflow. It first calls `/api/shipment/candidates`, then `/api/shipment/validate`, then `/api/shipment/plan` with backend-produced identities.**
- [ ] **Step 2: Add request ownership/run sequence so old responses cannot overwrite a newer scenario.**
- [ ] **Step 3: Busy UI preserves previous successful manifests and stable controls; show business stage (`Собираем варианты`, `Проверяем в Ozon`, `Получаем окна`, `Ранжируем`).**
- [ ] **Step 4: Failure preserves prior successful result + current edited draft and remains `dirty`; never auto-switches source mode.**
- [ ] **Step 5: Add locked-vault handling: explain `Разблокируйте Ozon API`, link/focus Data connection action; no secret prompt embedded ad hoc in Plan.**
- [ ] **Step 6: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_shipment_view.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_shipment_view.py
git commit -m "feat: validate shipment options with Ozon"
```

---

### Task 8: Render candidate/validated manifests and causal failures

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_shipment_view.py`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Render lifecycle labels `Кандидат` and `Проверено Ozon`; prohibit real-supply completion copy (`Поставка создана`, `Забронировано`, `Заявка подтверждена`).**
- [ ] **Step 2: Render validated manifest with date/method/clusters, qty/liters/SKU count, accepted status, actual observed timeslot, optional travel time and `Проверено <time>`.**
- [ ] **Step 3: Render partial rejection with affected article/cluster/qty/human-readable Ozon reason; rejected lines remain visible.**
- [ ] **Step 4: Distinguish no-slot, rate-limit, Ozon unavailable, draft outcome unknown and local block using persistent copy from canonical vocabulary.**
- [ ] **Step 5: Render PVZ wording `Предварительно подходит` before validation; after validation `Состав принят Ozon · окно найдено`, plus manual packaging/point note when relevant.**
- [ ] **Step 6: In Products view, selected SKU shows only its backend assignments grouped by validated option without duplicating global shipment UI.**
- [ ] **Step 7: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_shipment_view.py tests/frontend/test_plan_view.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_shipment_view.py tests/frontend/test_plan_view.py
git commit -m "feat: render validated shipment manifests"
```

---

### Task 9: Add manual Ozon template download

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_shipment_view.py`

- [ ] **Step 1: Accepted/exportable ranked option shows `Скачать шаблоны Ozon`; rejected/unknown options do not expose enabled export.**
- [ ] **Step 2: POST exact backend-ranked option identity to `/api/shipment/export`, receive blob and filename from Content-Disposition; never generate XLSX/ZIP in browser.**
- [ ] **Step 3: Busy/error stays local to selected manifest and schedule remains visible. No `alert()`.**
- [ ] **Step 4: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_shipment_view.py -q
git add frontend/assets/js/app.js tests/frontend/test_shipment_view.py
git commit -m "feat: download Ozon shipment templates"
```

---

### Task 10: Migrate root DESIGN.md and UX-CONTRACT.md to shipped API-first UI

**Files:**
- Modify: `DESIGN.md`
- Modify: `UX-CONTRACT.md`
- Modify: `tests/frontend/test_product_shell.py`
- Modify: `tests/frontend/test_plan_view.py`
- Modify: `tests/frontend/test_ozon_connection.py`

- [ ] **Step 1: Preserve current tokens, Creative North Star, decision line and Flow visual contract. Replace only superseded wide-Plan/file-primary/selected-network workflow language with the now-shipped API-first article/shipment design.**
- [ ] **Step 2: Canonical UI Map owns `OzonConnectionPanel`, `CredentialVaultDialog`, `SourceModePanel`, `ArticlePlanSelector`, `PlanProductWorkspace`, `ShipmentIntentForm`, `HandoffPointSelector`, `ShipmentManifest`, `OzonValidationStatus`. Remove active `SupplyNetworkSelector`/selected-network replan ownership.**
- [ ] **Step 3: Document three freshness clocks and independent source/analysis/shipment dirty ownership.**
- [ ] **Step 4: Document secret-field behavior, manual fallback, temporary draft disclosure and the absence of final real supply creation.**
- [ ] **Step 5: Add static tests preventing drift back to `/api/replan`, global Plan wide table or file-primary Data workflow as canonical.**
- [ ] **Step 6: Run tests and commit.**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py tests/frontend/test_ozon_connection.py -q
git add DESIGN.md UX-CONTRACT.md tests/frontend
git commit -m "docs: make API-first Plan UI canonical"
```

---

### Task 11: Frontend Design Premium verification gate

- [ ] **Step 1: Run all frontend tests and unchanged Flow regressions.**

```bash
python -m pytest tests/frontend -q
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
```

- [ ] **Step 2: Run API integration suites.**

```bash
python -m pytest tests/api/test_ozon_credentials.py tests/api/test_ozon_sync.py tests/api/test_analysis.py tests/api/test_shipment_candidates.py tests/api/test_shipment_validate.py tests/api/test_shipment_plan.py tests/api/test_shipment_export.py -q
```

- [ ] **Step 3: Run full suite.**

```bash
python -m pytest -q
```

- [ ] **Step 4: Run Frontend Design Premium project audit/verification checklist in strict mode and fix all blocking findings.**

- [ ] **Step 5: Real browser acceptance with 100+ articles/20+ clusters: first vault setup, restart/locked state, API sync success/failure/stale, manual fallback, article search `40750`, shipment intent, temporary draft disclosure, accepted/partial/no-slot/rate-limit/network states, export, keyboard and 200% zoom.**

- [ ] **Step 6: Verify all four top-level routes remain reachable and shared CSS changes do not regress Flow/Economics/Data.**

PR-E is complete only when runtime UI and root durable contracts agree and no screen suggests that the app created/booked a real Ozon supply.
