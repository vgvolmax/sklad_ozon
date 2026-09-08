# PR-E Article-First Plan & Shipment UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `frontend-design`, `frontend-design-premium`, and superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Execute task-by-task with TDD and review checkpoints.

**Goal:** Replace the current wide primary Plan table with an article-first master/detail workspace and add the manual shipment-planning/export workflow while preserving the established visual system, analytical sections and historical Flow.

**Architecture:** Keep the four-route vanilla frontend and existing shared primitives. Inside `План`, introduce `Товары | Отгрузки`: `Товары` reuses the context-selection grammar of `Потоки спроса → По артикулу`; `Отгрузки` edits a downstream shipment scenario and calls PR-D's local shipment endpoints. Analysis state and shipment state stay independent so changing dates/methods never falsely marks demand/Flow stale.

**Tech Stack:** existing committed vanilla HTML/CSS/JavaScript, current shared frontend primitives, pytest static/browser-model tests; no framework, bundler, npm or new dependency.

**Specs:**
- `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`
- `docs/superpowers/specs/2026-09-08-article-first-plan-ui-amendment.md`

**Behavior authority:** root `DESIGN.md`, root `UX-CONTRACT.md`, and the UI amendment where it is more specific. PR-E MUST fold the amendment into the two root contracts in the same changeset as runtime UI.

## Global Constraints

- Preserve top-level routes: `План`, `Потоки спроса`, `Экономика`, `Данные`.
- Do not add a fifth top-level `Отгрузки` route; it is a `План` subview.
- Keep the established decision-line signature and visual tokens; no new palette/gradient/KPI-card language.
- One article selector item = one SKU/article, never one row per cluster.
- Normal product-plan detail is persistently visible on the right; no repeated `Открыть детали` primary action.
- Existing Flow remains historical evidence. Do not replace or regress `Потоки спроса → По артикулу`.
- Frontend never calculates multiplicity, quantity allocation, urgency, PVZ volume eligibility, scheduling or XLSX content.
- Frontend may group/sum backend presentation values only for display when the backend contract already declares the values complete; never convert missing to zero.
- Keep separate `analysisDirty` and `shipmentDirty` ownership.
- Shipment input change never calls full analysis automatically.
- No Ozon Seller API call/browser request is introduced.
- Search fields retain explicit clear button, keyboard focus and local immediate filtering.
- Controls use native semantic elements; no clickable `div`/`span` substitutes.
- Busy controls keep stable geometry and prevent duplicate requests.
- Previous successful analysis/shipment result remains visible during recalculation/failure with explicit stale ownership.
- Target WCAG 2.2 AA; verify 200% zoom and sibling sections after layout changes.
- Root `DESIGN.md`/`UX-CONTRACT.md` update is part of PR-E acceptance, not optional documentation cleanup.

---

## File Structure

- Modify `frontend/assets/js/core.js` — Plan subview, article selector state/models, shipment scenario draft/applied state, request builders and presentation helpers.
- Modify `frontend/assets/js/app.js` — article-first Plan rendering, shipment workspace, Data supplier-packaging input, local shipment API/export calls.
- Reuse `frontend/assets/js/flow.js` as behavioral reference; modify only if a shared selector helper is extracted without changing Flow output.
- Modify `frontend/assets/css/app.css` — article master/detail, compact metadata, focused cluster table and shipment-manifest surfaces using existing tokens.
- Modify `frontend/index.html` only where stable section containers/form inputs require it.
- Modify `DESIGN.md` — replace wide-table canonical Plan layout with article-first + shipment manifest design while preserving tokens/identity.
- Modify `UX-CONTRACT.md` — replace selected-network/replan workflow with two-layer analysis/shipment state and new Plan subviews.
- Modify `tests/frontend/test_ui_state.py` — subview/selection/shipment draft state.
- Modify `tests/frontend/test_plan_view.py` — article selector/detail/cluster table and no repeated product table.
- Modify `tests/frontend/test_analysis_submit.py` — optional supplier packaging upload; analysis vs shipment request ownership.
- Create `tests/frontend/test_shipment_view.py` — opportunity editor, schedule results, export and failure recovery.
- Modify `tests/frontend/test_product_shell.py` — Plan subview semantics/top-level routes unchanged.
- Run `tests/frontend/test_flow_view.py` and `test_flow_real_scale.py` unchanged as Flow regressions.

---

### Task 1: Replace Plan row state with article-first context state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`
- Modify: `tests/frontend/test_plan_view.py`

**State contract:**

```javascript
planView: {
  subview: 'products',          // products | shipments
  articleQuery: '',
  articleFilter: 'all',
  selectedSku: null,
  clusterSort: {key:'cluster', direction:'asc'},
  clusterPage: 1,
  clusterPageSize: 50
},
shipmentView: {
  selectedClusters: [],
  opportunities: [],
  dirty: false,
  busy: false,
  error: null,
  appliedScenario: null,
  plan: null
}
```

Preserve existing unrelated Flow/Economics/Data state.

- [ ] **Step 1: Add initial-state and route-state tests**

Assert default `subview === 'products'`, no selected SKU before snapshot initialization, and existing top-level section route remains `plan` rather than adding a new global route.

- [ ] **Step 2: Add article aggregation helper tests**

Define:

```javascript
S.buildArticlePlanItems = function(snapshot) { ... };
```

One output item per SKU. It joins `snapshot.decision_rows`, `snapshot.shippable_plan.sku_summaries`, and current incomplete/status evidence.

For article `40750` with 24 cluster decision rows, assert exactly one selector item.

Item shape:

```javascript
{
  sku,
  article,
  productName,
  analyticalPlanQty,
  shippableQty,
  positiveClusterCount,
  incomplete,
  statusLabel
}
```

- [ ] **Step 3: Add article selection reconciliation tests**

`S.initializePlanArticleContext(state, snapshot)`:

- keeps previous `selectedSku` if still present;
- otherwise selects first visible article in stable `ru`/article order;
- zero-item snapshot leaves `selectedSku = null`.

- [ ] **Step 4: Add local search/filter tests**

```javascript
S.filteredArticlePlanItems(items, query, filter)
```

matches article, SKU, name; filter results remain one item per SKU. Search/filter reset cluster page but not shipment state.

- [ ] **Step 5: Run RED, implement state/model helpers, run GREEN**

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_plan_view.py -q
```

- [ ] **Step 6: Commit**

```bash
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py tests/frontend/test_plan_view.py
git commit -m "feat: add article-first Plan state"
```

---

### Task 2: Render left article selector and persistent product detail header

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

Canonical layout follows the UI amendment.

- [ ] **Step 1: Add semantic selector markup tests**

Assert:

- search input has label/accessibility name;
- clear control is a `<button>`;
- each article selector item is a button with selected semantics;
- no per-cluster `Открыть детали` action appears in default products view;
- product name appears once in right header, not once per cluster row.

- [ ] **Step 2: Render compact selector items**

Each selected/list item renders:

```text
article · compact product name
SKU secondary
К поставке N шт. · M кластеров
```

Only one concise warning/incomplete badge may appear. Do not build a KPI mosaic.

- [ ] **Step 3: Render persistent product header**

From backend `ShippableSkuSummary` / product data show:

```text
article + full name
SKU
Кратность
Наш склад
Доступно кратно
Объём/шт.
Зона
```

Unknown values display `Не рассчитано`, never `0` by frontend fallback.

- [ ] **Step 4: Add layout CSS with existing tokens**

Create business-named classes such as:

```text
.plan-workspace
.plan-article-selector
.plan-article-list
.plan-product-detail
.plan-product-meta
```

Desktop uses bounded left column + flexible right content. Do not change root page-max/tokens or add screen-local hex values.

- [ ] **Step 5: Add narrow/zoom CSS contract**

At the existing project breakpoint/appropriate container width, stack selector above detail. Keep selector bounded, cluster table local-scroll, and no root `overflow:hidden`.

- [ ] **Step 6: Run focused tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: render article-first Plan workspace"
```

---

### Task 3: Render article decision line and focused cluster table

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add selected-SKU decision-line model tests**

Define backend-safe presentation helper:

```javascript
S.buildArticleDecisionLine(snapshot, sku)
```

It aggregates only complete backend numeric values. If any required Ozon/need component is incomplete, the corresponding aggregate is `null`/`Не рассчитано`, not a partial sum represented as total.

Plan display distinguishes:

```text
analytical Calculated Plan total
operational shippable total
rounding delta
```

Example copy:

```text
Ozon 96 → Наша потребность 101 → К поставке 102 шт.
Аналитический план 101 → 102 · кратность 6
```

- [ ] **Step 2: Add selected-SKU cluster-row helper tests**

```javascript
S.buildSelectedArticleClusterRows(snapshot, sku)
```

joins one `DecisionRow` per destination with its `ShippableLine` if present.

Canonical row fields:

```javascript
cluster
fbo
inbound
ozon
need
analyticalPlan
packMultiple
shippableQty
roundingDelta
volumeL
zone
status
```

- [ ] **Step 3: Render only canonical default cluster columns**

Exactly:

```text
Кластер | FBO | В пути | Ozon | Потребность | Аналитический план |
Кратность | К поставке | Объём | Зона | Статус
```

Do not include product identity, route-profit, margin or expected-profit columns by default.

- [ ] **Step 4: Make rounding visually explicit**

When delta != 0 render e.g.:

```text
17 → 18 шт.
```

with compact secondary `кратность 6`, without warning color unless the rounding itself causes a real constraint issue.

- [ ] **Step 5: Preserve analytical deep links**

Provide secondary actions/links such as `Открыть в потоках` / `Экономика` through existing navigation patterns; do not duplicate full route economics into the Plan table.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py
git commit -m "feat: show focused article cluster plan"
```

---

### Task 4: Add `Товары | Отгрузки` subview navigation without adding a global route

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_product_shell.py`
- Modify: `tests/frontend/test_ui_state.py`

- [ ] **Step 1: Add semantic subview tests**

Use buttons/tab semantics consistent with existing app navigation. Assert top-level nav still has exactly four product sections and document title remains `План — Sklad Ozon` for both subviews.

- [ ] **Step 2: Add state helper**

```javascript
S.setPlanSubview(state, subview)
```

accepts only `products` / `shipments` and preserves selected article + shipment draft.

- [ ] **Step 3: Route/share state**

Extend current hash/route serialization only if existing route contract supports non-sensitive section-specific state. Preserve Back/Forward and avoid putting file names/paths in URL.

- [ ] **Step 4: Render subview switch with stable geometry**

`Товары` and `Отгрузки` are visually subordinate to top-level nav and use existing active/focus semantics.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_product_shell.py tests/frontend/test_ui_state.py
git commit -m "feat: add Plan product and shipment views"
```

---

### Task 5: Add supplier-packaging input to `Данные` / analysis request

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/index.html` if the current data-form structure requires static markup.
- Modify: `tests/frontend/test_analysis_submit.py`
- Modify: `tests/frontend/test_data_quality.py` when status presentation is shared.

- [ ] **Step 1: Add input markup/copy tests**

Label:

```text
Прайс поставщика с кратностью упаковки
```

Help:

```text
Лист «Прайс списком»: КОД + Упак. Например 36/6 → кратность 6.
```

Input is optional for analytics but shipment/export readiness shows incomplete when absent.

- [ ] **Step 2: Extend analysis FormData builder**

When a file is selected, send:

```text
supplier_packaging_file
```

When absent, do not synthesize an empty File/Blob and do not block current analysis submit.

- [ ] **Step 3: Show shipment-specific data-quality state**

Missing/malformed pack source is not a generic `analysis failed` banner. It appears as shipment readiness/incomplete evidence and links user to the Data input.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_data_quality.py -q
git add frontend/assets/js/app.js frontend/index.html tests/frontend/test_analysis_submit.py tests/frontend/test_data_quality.py
git commit -m "feat: upload supplier pack data"
```

---

### Task 6: Add shipment scenario draft/applied state and request builder

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`
- Create: `tests/frontend/test_shipment_view.py`

**State helpers:**

```javascript
S.setShipmentClusters(state, clusterIds)
S.addShipmentOpportunity(state, opportunity)
S.updateShipmentOpportunity(state, id, patch)
S.removeShipmentOpportunity(state, id)
S.buildShipmentPlanRequest(state)
S.applyShipmentPlanResult(state, plan)
S.preserveShipmentDraftAfterFailure(state, message)
```

- [ ] **Step 1: Add dirty ownership tests**

Changing clusters/date/method/lead/max-clusters/volume sets `shipmentView.dirty === true` but leaves `state.staleSnapshot` / analysis dirty state unchanged.

Changing horizon/inbound/source data keeps existing analysis-stale behavior and invalidates old shipment plan ownership.

- [ ] **Step 2: Add draft/applied failure recovery tests**

A failed `/api/shipment-plan` preserves:

- previous successful shipment plan;
- previous applied scenario;
- current edited draft;
- `dirty === true`;
- persistent error message.

- [ ] **Step 3: Add exact request body test**

`S.buildShipmentPlanRequest()` sends current snapshot ID, backend `shippable_plan`, `as_of`, selected clusters and opportunities exactly as PR-D wire expects. Decimal volume values are serialized as strings.

- [ ] **Step 4: Run RED, implement helpers, run GREEN**

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_shipment_view.py -q
```

- [ ] **Step 5: Commit**

```bash
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py tests/frontend/test_shipment_view.py
git commit -m "feat: add shipment planning state"
```

---

### Task 7: Build the shipment opportunity editor

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_shipment_view.py`

Canonical opportunity row fields:

```text
Дата
Способ
Срок в пути, дней
Макс. кластеров
Лимит объёма, л
Удалить
```

Methods:

```text
ПВЗ
СЦ
Прямая
```

- [ ] **Step 1: Add semantic field tests**

Every field has a real label. Delete is a button with accessible name. Method uses the project's accepted native `<select>` behavior. Date uses native date input per current contract unless root UX is intentionally changed in this task.

- [ ] **Step 2: Add selected-cluster editor tests**

Use a searchable checkbox list/compact selector built from clusters present in `shippable_plan.lines`. Checkboxes only edit downstream shipment scope and issue no request by themselves.

- [ ] **Step 3: Add default opportunity behavior**

Adding an opportunity creates a valid local draft with a stable client ID. PVZ displays the default `1000 л` limit/evidence; user can lower the value. Do not display `1000 л` as guaranteed capacity of the actual Ozon point.

- [ ] **Step 4: Add validation**

Before request, validate positive max clusters, nonnegative lead days and positive finite explicit volume. Preserve entered values, show inline error with `aria-invalid`/`aria-describedby`, and focus first invalid field on submit.

- [ ] **Step 5: Add action label state**

No successful plan yet:

```text
Рассчитать отгрузки
```

Successful plan + dirty draft:

```text
Пересобрать отгрузки
```

Clean successful state keeps action available as deliberate recompute but does not misleadingly show analysis `Пересчитать план`.

- [ ] **Step 6: Add CSS using existing tokens only**

Use compact manifest/form surfaces; no decorative KPI cards, new palette or screen-local shadow/radius values.

- [ ] **Step 7: Run tests and commit**

```bash
python -m pytest tests/frontend/test_shipment_view.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_shipment_view.py
git commit -m "feat: add shipment opportunity editor"
```

---

### Task 8: Call `/api/shipment-plan` with stable async/failure behavior

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_shipment_view.py`

- [ ] **Step 1: Add request ownership tests**

Only `Рассчитать/Пересобрать отгрузки` calls `/api/shipment-plan`. Article selection, cluster checkbox, date/method edits never call backend automatically.

- [ ] **Step 2: Add busy-state test**

During request:

- keep previous plan visible;
- disable competing shipment draft actions;
- keep calculate button geometry stable;
- expose perceivable `Рассчитываем отгрузки…` through existing progress/Notice system.

- [ ] **Step 3: Add stale-response protection**

Use the existing run-sequence/request ownership pattern so an older response cannot overwrite a newer shipment calculation.

- [ ] **Step 4: Add success/failure tests**

Success atomically applies returned plan + scenario and clears shipment dirty/error. Failure preserves previous success + current draft as specified in Task 6.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/frontend/test_shipment_view.py -q
git add frontend/assets/js/app.js tests/frontend/test_shipment_view.py
git commit -m "feat: calculate shipment schedule"
```

---

### Task 9: Render shipment manifests and article assignment summaries

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_shipment_view.py`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add shipment manifest tests**

For each `PlannedShipment` render:

```text
16 сентября · ПВЗ
Москва · Казань · Пермь
1 930 шт. · 824 л · N SKU
Рекомендовано вовремя
```

Do not call a recommended date `Окно подтверждено` / `Забронировано`.

- [ ] **Step 2: Add late/incomplete/unscheduled tests**

Exact localized states from UI amendment. Unscheduled lines remain visible with article/cluster/qty/reasons and are not silently omitted from totals.

- [ ] **Step 3: Add article assignment summary**

In `Товары`, selected SKU gets only its assignments grouped by planned shipment date/method, with quantity and volume for that SKU.

- [ ] **Step 4: Add stale shipment notice**

When draft inputs changed, previous result remains visible with clear notice:

```text
Параметры отгрузки изменены. Расписание ниже рассчитано для предыдущих параметров.
```

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/frontend/test_shipment_view.py tests/frontend/test_plan_view.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_shipment_view.py tests/frontend/test_plan_view.py
git commit -m "feat: render shipment manifests"
```

---

### Task 10: Download exact Ozon templates per planned shipment

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_shipment_view.py`

- [ ] **Step 1: Add export-action visibility tests**

A planned shipment with positive assignments has:

```text
Скачать шаблоны Ozon
```

Unscheduled/incomplete pseudo-shipment has no enabled export action; show reason.

- [ ] **Step 2: Add request test**

Action POSTs the exact `PlannedShipment` object to `/api/shipment-export`, receives blob bytes, derives filename from `Content-Disposition`, and triggers one browser download.

Do not generate XLSX/ZIP client-side.

- [ ] **Step 3: Add busy/error behavior**

Export busy state stays local to the chosen shipment action. Failure keeps schedule visible and displays persistent inline/retry status; no browser `alert()`.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/frontend/test_shipment_view.py -q
git add frontend/assets/js/app.js tests/frontend/test_shipment_view.py
git commit -m "feat: download Ozon shipment templates"
```

---

### Task 11: Fold the approved UI amendment into root design contracts

**Files:**
- Modify: `DESIGN.md`
- Modify: `UX-CONTRACT.md`
- Modify: `tests/frontend/test_product_shell.py`
- Modify: `tests/frontend/test_plan_view.py`

This task is mandatory because runtime behavior now exists; root design context must stop describing the superseded wide-table/replan workflow as canonical.

- [ ] **Step 1: Update `DESIGN.md` durable Plan layout**

Preserve existing tokens, typography, semantic colors, Creative North Star and Flow design. Replace only conflicting Plan statements:

```text
old: context → scenario → decision line → filters → wide table + drawer
new: context/scenario → Plan subviews → article master/detail or shipment manifest workspace
```

Document that the design signature remains the decision line and shipment surfaces use logistics-manifest structure, not dashboard KPI cards.

- [ ] **Step 2: Update `UX-CONTRACT.md` canonical UI map**

Record canonical owners for:

```text
ArticlePlanSelector
PlanProductWorkspace
ShipmentOpportunityEditor
ShipmentManifest
```

They may be shared functions/components within the existing vanilla namespace; do not create equivalent screen-local variants.

- [ ] **Step 3: Replace old main-decision workflow**

Remove selected-network draft/applied `/api/replan` steps from active workflow and document:

```text
analysis dirty -> full Пересчитать план
shipment dirty -> Рассчитать/Пересобрать отгрузки only
```

- [ ] **Step 4: Update Plan dataset navigation contract**

Article selector is bounded/local; selected article cluster table has its own scroll/pagination strategy. Old 50-row global `SKU × cluster` table is no longer the primary Plan owner.

- [ ] **Step 5: Preserve explicit unaffected contracts**

Verify root docs still retain:

- four top-level routes;
- historical Flow modes;
- Economics/Data;
- visual tokens;
- Search/DataTable/Notice/Drawer primitives where still used;
- WCAG/accessibility/scrollbar/layout stability rules.

- [ ] **Step 6: Add static assertions for the new canonical copy and removed old active copy**

Tests should fail if runtime/doc contracts drift back to selected-network `/api/replan` as current Plan workflow.

- [ ] **Step 7: Run tests and commit**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py -q
git add DESIGN.md UX-CONTRACT.md tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py
git commit -m "docs: make article-first Plan canonical"
```

---

### Task 12: Frontend Design Premium acceptance / regression gate

- [ ] **Step 1: Run all frontend tests**

```bash
python -m pytest tests/frontend -q
```

- [ ] **Step 2: Run Flow regressions unchanged**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
```

`Потоки спроса` must retain current bounded real-scale behavior.

- [ ] **Step 3: Run API integration tests**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_shipment_plan.py tests/api/test_shipment_export.py -q
```

- [ ] **Step 4: Run full suite**

```bash
python -m pytest -q
```

- [ ] **Step 5: Manual desktop + 200% zoom acceptance**

Using a realistic snapshot with 100+ SKU and 20+ clusters, verify:

```text
one article appears once in left selector
selected article detail stays readable without horizontal page scroll
cluster table owns local overflow
full product name is not repeated per cluster
search 40750 immediately isolates one product context
keyboard can select article, edit shipment opportunities and download export
focus is visible and not obscured
200% zoom stacks selector above detail rather than squeezing both columns
Plan, Flow, Economics and Data remain reachable/usable after shared CSS changes
busy/error states do not move primary controls
```

- [ ] **Step 6: Manual workflow acceptance**

```text
full analysis -> article plan visible
shipment cluster/date/method edit -> only shipment dirty
calculate shipments -> recommended schedule
select article -> see its assignments
export multi-cluster shipment -> one download ZIP
change opportunity -> previous shipment plan explicitly stale, analysis still current
```

PR-E is complete only after these checks and root design contracts match runtime behavior.