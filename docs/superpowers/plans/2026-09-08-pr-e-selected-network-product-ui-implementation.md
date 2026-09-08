# PR-E Selected Supply Network Product UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `frontend-design`, `frontend-design-premium`, and superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Execute task-by-task with TDD and review checkpoints.

**Goal:** Make `PlanningSnapshot` the authoritative user-facing plan, add draft/applied supply-network editing with explicit `Пересчитать план`, show the backend physical origin roll-up, and add a separate `План размещения` Flow surface that explains historical Flow, exact SKU tariff, pair-level `RouteCostIndex` and physical capacity without conflating them.

**Architecture:** Preserve the existing four-tab engineering-console shell and current visual language. Add one compact network editor to the Plan scenario area; checkbox changes edit draft state only. The single existing `Пересчитать план` action selects full analysis when upstream inputs are stale and `/api/replan` when only the network changed. The visible destination plan, physical origin roll-up, gap causes and planned route evidence come from backend `PlanningSnapshot`; frontend owns state transitions, joins, filtering and presentation only.

**Tech Stack:** existing dependency-free browser JavaScript, semantic HTML, current `DataTable`/`SearchField`/`DetailDrawer`, `frontend/assets/css/app.css`, pytest static/browser-model tests; no new dependency or frontend framework.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Behavior authority:** `DESIGN.md`, `UX-CONTRACT.md`, Frontend Design Premium canonical UI/interaction rules.

**Approved implementation clarification (2026-09-08):** `RouteCostIndex` is a SKU-independent structural characteristic of a route pair. Exact direct tariff remains the concrete SKU route price. Do not introduce hardcoded visual bands such as `<0.8 good` or `>1.3 bad` in this PR.

## Global Constraints

- Preserve tabs: `План`, `Потоки спроса`, `Экономика`, `Данные`.
- Preserve decision line: `Ozon → Наша потребность → Наш план`.
- `Наш план` becomes authoritative from `PlanningSnapshot`, not legacy `DecisionRow.safe_plan_qty/calculated_plan_qty`.
- Network checkbox changes never call backend.
- Draft network and applied network remain distinct; visible plan always belongs to the applied network until successful recalculation.
- One `Пересчитать план` button is the only plan commit action.
- Network-only dirty state uses `/api/replan`; any upstream stale state uses full analysis with the current network draft.
- A failed request keeps the previous applied plan visible and preserves the current draft for retry.
- During calculation, keep primary-action geometry stable and disable controls that would create competing drafts.
- Frontend does not calculate route ranking, coverage quantities, capacity, RouteCostIndex or unit economics.
- Summing backend `PlanningLegView.expected_profit` only for a destination display/sort value is permitted as presentation aggregation; it must never feed a decision or request.
- Historical Flow, `RouteCostIndex`, direct tariff and Capacity are separate labeled evidence concepts.
- `1,00` may be explained as the median-relative RouteCostIndex reference; no category thresholds are hardcoded.
- Historical Flow remains `История → Наблюдаемое | Очищенное`; planned placement is a sibling surface, not a third evidence source.
- Network editor uses native checkbox/label semantics, clearable search, visible focus, disabled/busy state and no clickable `div`/`span` controls.
- No global Sankey/chord or KPI-card mosaic.
- Reuse existing CSS tokens; this plan introduces no new durable color/shadow/radius token and therefore does not modify `DESIGN.md`.
- `UX-CONTRACT.md` must be updated because state ownership and recalculation behavior are durable.
- Cross-docking terminology/cost never appears in route-plan UI.

---

## File Structure

- Modify `frontend/assets/js/core.js` — network draft/applied state, recalculation-kind selection, request builders, planning joins/presenters and planned-flow state.
- Modify `frontend/assets/js/app.js` — network editor, analysis-vs-replan routing, authoritative Plan rendering, physical origin roll-up and destination drawer.
- Modify `frontend/assets/js/flow.js` — `История | План размещения` surface and planned-route rendering.
- Modify `frontend/assets/css/app.css` — network editor, physical roll-up and planned evidence styling using existing tokens.
- Modify `UX-CONTRACT.md` — applied/draft/recalc/failure semantics and Flow evidence taxonomy.
- Modify `tests/frontend/test_ui_state.py` — network state and planned/history surface state.
- Modify `tests/frontend/test_analysis_submit.py` — request depth, selected network body and no-auto-request behavior.
- Modify `tests/frontend/test_plan_view.py` — authoritative planning joins, gap labels, network editor, roll-up and route evidence.
- Modify `tests/frontend/test_flow_view.py` — history/planning surface semantics and planned link evidence.
- Modify `tests/frontend/test_flow_real_scale.py` — bounded 40+ destination planned-flow behavior.

No backend production file belongs in PR-E.

---

### Task 1: Add explicit applied/draft supply-network state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`

**State addition:**

```javascript
networkView: {
  candidateClusters: [],
  appliedClusters: [],
  draftClusters: [],
  dirty: false,
  editorOpen: false,
  search: ''
}
```

- [ ] **Step 1: Add initial-state test**

Assert `S.createInitialState().networkView` equals the contract exactly.

- [ ] **Step 2: Add snapshot initialization test**

Given:

```javascript
const snapshot = {
  planning_basis: {candidate_supply_clusters:['Казань','Москва','Питер']},
  planning_snapshot: {applied_supply_network:['Москва','Питер']}
};
```

assert candidate/applied/draft are sorted as:

```javascript
['Казань','Москва','Питер']
['Москва','Питер']
['Москва','Питер']
```

and `dirty === false`.

- [ ] **Step 3: Add draft toggle/revert tests**

```javascript
let next = S.toggleNetworkDraft(state, 'Казань', true);
assert.deepEqual(next.networkView.draftClusters, ['Казань','Москва','Питер']);
assert.equal(next.networkView.dirty, true);
assert.deepEqual(next.networkView.appliedClusters, ['Москва','Питер']);
next = S.toggleNetworkDraft(next, 'Казань', false);
assert.equal(next.networkView.dirty, false);
```

- [ ] **Step 4: Implement state helpers**

```javascript
S.initializeNetworkView = function(state, snapshot) {
  const candidates = [...(snapshot?.planning_basis?.candidate_supply_clusters || [])]
    .sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = [...(snapshot?.planning_snapshot?.applied_supply_network || [])]
    .sort((a,b)=>a.localeCompare(b,'ru'));
  return {
    ...state,
    networkView:{
      candidateClusters:candidates,
      appliedClusters:applied,
      draftClusters:[...applied],
      dirty:false,
      editorOpen:false,
      search:''
    }
  };
};

S.toggleNetworkDraft = function(state, cluster, selected) {
  const selectedSet = new Set(state.networkView.draftClusters);
  if (selected) selectedSet.add(cluster); else selectedSet.delete(cluster);
  const draft = [...selectedSet].sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = state.networkView.appliedClusters;
  const dirty = draft.length !== applied.length || draft.some((x,i)=>x !== applied[i]);
  return {...state,networkView:{...state.networkView,draftClusters:draft,dirty}};
};

S.setNetworkEditorOpen = (state, editorOpen) => ({
  ...state, networkView:{...state.networkView,editorOpen:Boolean(editorOpen)}
});

S.setNetworkSearch = (state, search) => ({
  ...state, networkView:{...state.networkView,search:String(search || '')}
});
```

- [ ] **Step 5: Add success/failure state transition tests**

`S.applyPlanningResult(state, planningSnapshot)` sets applied/draft from returned `applied_supply_network` and clears dirty. `S.preserveNetworkDraftAfterFailure(state)` returns a state where applied plan/network and dirty draft remain unchanged.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py
git commit -m "feat: add selected network draft state"
```

---

### Task 2: Route `Пересчитать план` to full analysis or `/api/replan`

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_analysis_submit.py`

- [ ] **Step 1: Add recalculation-kind tests**

Canonical helper:

```javascript
S.resolveRecalculationKind = function(state) {
  if (!state.snapshot || state.staleSnapshot || !state.snapshot.planning_basis) {
    return 'analysis';
  }
  if (state.networkView.dirty) return 'replan';
  return 'analysis';
};
```

Assert:

```text
no snapshot -> analysis
stale upstream + network dirty -> analysis
clean upstream + network dirty -> replan
clean upstream + clean network -> analysis
legacy snapshot without planning_basis -> analysis
```

- [ ] **Step 2: Extend full-analysis request builder**

Change signature to:

```javascript
S.buildAnalysisRequestBody = function(
  form,
  scenario,
  selectedSupplyClusters,
  FormDataCtor=globalThis.FormData
) {
  const body = new FormDataCtor(form);
  body.set('horizon_days', String(scenario.horizonDays));
  body.set('include_inbound', String(scenario.includeInbound));
  body.set('selected_supply_clusters', JSON.stringify(selectedSupplyClusters));
  return body;
};
```

Update every existing caller/test to pass `state.networkView.draftClusters`.

- [ ] **Step 3: Add replan request builder**

```javascript
S.buildReplanRequestBody = function(state) {
  return {
    planning_basis: state.snapshot.planning_basis,
    selected_supply_clusters:[...state.networkView.draftClusters]
  };
};
```

Assert an explicit empty draft serializes as `[]`.

- [ ] **Step 4: Implement `runReplan()` using current run sequencing**

Behavior is exact:

1. allocate a new run sequence ID using the same stale-response mechanism as full analysis;
2. set the shared busy state without clearing `state.snapshot`;
3. POST `JSON.stringify(S.buildReplanRequestBody(state))` to `/api/replan` with `Content-Type: application/json`;
4. ignore result/error when its run ID is no longer active;
5. on success replace only `state.snapshot.planning_snapshot`, preserve `planning_basis` and every upstream AnalysisSnapshot field, then apply returned network to `networkView`;
6. on failure preserve previous `planning_snapshot`, applied network and current draft, and render the inline analysis error owner;
7. clear busy state only for the active run.

- [ ] **Step 5: Route the existing recalculate button**

```javascript
const kind = S.resolveRecalculationKind(state);
if (kind === 'replan') {
  runReplan();
} else {
  runAnalysis();
}
```

Successful full analysis calls `S.initializeNetworkView()` using the newly returned snapshot.

- [ ] **Step 6: Prove checkboxes never submit**

Add a static/behavior test asserting the checkbox `change` handler only calls `S.toggleNetworkDraft()` + render and does not reference `runAnalysis`/`runReplan`. Only the existing recalculate action invokes backend calculation.

- [ ] **Step 7: Run tests and commit**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py
git commit -m "feat: replan network only on explicit action"
```

---

### Task 3: Add compact searchable supply-network editor

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

**V1 UI:**

```text
Сеть поставки
Москва · Санкт-Петербург · +2                         [Изменить]

Куда готовы поставлять
[ Поиск кластера…                                      × ]
☑ Москва
☑ Санкт-Петербург
☐ Казань
☐ Пермь
Выбрано: 4
```

V1 intentionally shows no calculated `SKU доступны` count; the basis supplies candidate cluster identities only.

- [ ] **Step 1: Add semantic markup assertions**

Generated control uses:

```text
button for Изменить
input type=search with aria-label="Поиск кластера"
input type=checkbox associated with a label
button for clear-search action
```

Assert no clickable `div`/`span` is used for these actions.

- [ ] **Step 2: Implement filtered list helper**

```javascript
S.filteredNetworkClusters = function(state) {
  const query = (state.networkView.search || '').trim().toLocaleLowerCase('ru');
  return state.networkView.candidateClusters.filter(cluster =>
    !query || cluster.toLocaleLowerCase('ru').includes(query)
  );
};
```

- [ ] **Step 3: Implement summary helper**

```javascript
S.networkSummary = function(clusters) {
  if (!clusters.length) return 'Кластеры не выбраны';
  if (clusters.length <= 2) return clusters.join(' · ');
  return `${clusters[0]} · ${clusters[1]} · +${clusters.length - 2}`;
};
```

While dirty, summary shows the draft set, because that is what the user is editing.

- [ ] **Step 4: Render exact stale-plan notice**

When `networkView.dirty`:

```text
Сеть поставки изменена. План ниже рассчитан для предыдущей сети.
```

The visible plan itself remains unchanged until success.

- [ ] **Step 5: Implement clear-search behavior**

Clear button exists only for nonempty search, sets search to `''`, re-renders and restores focus to the search input.

- [ ] **Step 6: Implement busy state**

While calculation is active disable `Изменить`, search, clear-search and all network checkboxes. Keep editor/list height and recalculate button width stable; preserve the draft state.

- [ ] **Step 7: Add CSS classes with existing tokens only**

```text
.network-summary
.network-editor
.network-editor-head
.network-search
.network-list
.network-option
.network-dirty
```

Reuse existing panel border/background/radius/spacing/focus tokens. Do not add root colors or shadows.

- [ ] **Step 8: Run tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_ui_state.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: add supply network editor"
```

---

### Task 4: Join PlanningSnapshot into authoritative Plan rows

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add planning destination index helpers**

```javascript
S.planningDestinationKey = row => `${row.sku}\0${row.destination_cluster_id}`;

S.destinationPlanMap = function(snapshot, family) {
  const block = snapshot?.planning_snapshot?.[family];
  return new Map((block?.destination_views || []).map(item => [
    S.planningDestinationKey(item), item
  ]));
};
```

- [ ] **Step 2: Replace plan-owned row values in `S.buildPlanRows()`**

For every legacy `DecisionRow`, join calculated/safe destination views. Returned presentation row must set:

```javascript
safe_plan_qty: safe?.final_allocated_qty ?? null,
calculated_plan_qty: calculated?.final_allocated_qty ?? null,
network_uncovered_qty: calculated?.network_uncovered_qty ?? null,
allocation_blocked_qty: calculated?.allocation_blocked_qty ?? null,
stock_uncovered_qty: calculated?.stock_uncovered_qty ?? null,
planning_legs: calculated?.legs || []
```

Add display-only planned profit:

```javascript
planned_expected_profit: calculated
  ? calculated.legs.reduce((total,leg)=>total + Number(leg.expected_profit || 0),0)
  : null
```

This sum is presentation-only and is never sent back to backend.

- [ ] **Step 3: Add conflicting legacy-value regression**

Fixture:

```text
DecisionRow.calculated_plan_qty = 999
PlanningSnapshot.calculated destination final_allocated_qty = 40
```

Assert table/drawer row uses `40`. Do the same for Safe.

- [ ] **Step 4: Make decision-line plan totals authoritative**

`S.buildDecisionLineModel(snapshot)` keeps Ozon/Need from `snapshot.summary`, but uses:

```javascript
snapshot.planning_snapshot.calculated.total_allocated_qty
snapshot.planning_snapshot.safe.total_allocated_qty
```

for Calculated/Safe plan values.

- [ ] **Step 5: Update plan sort/blocked filter ownership**

`profit` sort uses `planned_expected_profit`. `blocked` matches when any of:

```javascript
row.network_uncovered_qty > 0
row.allocation_blocked_qty > 0
row.stock_uncovered_qty > 0
```

or Calculated plan is unavailable. Do not use legacy `PHYSICALLY_INFEASIBLE` as the new selected-network blocked owner.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py
git commit -m "feat: render authoritative selected-network plan"
```

---

### Task 5: Show causal destination gaps and placement in DetailDrawer

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add exact presentation labels**

For the selected destination show:

```text
Цель направления
Покрыто планом
Сеть не покрывает
Заблокировано экономикой/данными
Не хватило товара
Где разместить
```

- [ ] **Step 2: Render gap quantities separately**

Map only backend values:

```text
network_uncovered_qty -> Сеть не покрывает
allocation_blocked_qty -> Заблокировано экономикой/данными
stock_uncovered_qty -> Не хватило товара
```

Never display their sum as generic `Не покрыто`.

- [ ] **Step 3: Render final placement legs**

Under `Где разместить`, list only legs with `final_allocated_qty > 0`:

```text
Москва — 70 шт.
Питер — 30 шт.
```

Sorting by `final_allocated_qty DESC`, then origin label, is presentation only.

- [ ] **Step 4: Preserve upstream evidence sections**

`Динамика спроса`, `Ozon vs наша модель`, historical execution and diagnostics continue to use the base AnalysisSnapshot. Replan must not replace them.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py
git commit -m "feat: explain destination coverage plan"
```

---

### Task 6: Add physical `Куда поставить` cluster roll-up

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

**Backend source:** `snapshot.planning_snapshot.calculated.origin_views`.

- [ ] **Step 1: Add exact backend-shape fixture**

```json
{
  "origin_cluster_id": "Москва",
  "total_qty": 600,
  "own_destination_qty": 500,
  "external_destination_qty": 100,
  "destinations": [
    {
      "destination_cluster_id":"Москва",
      "quantity":500,
      "sku_breakdown":[{"sku":"SKU-A","quantity":500}]
    },
    {
      "destination_cluster_id":"Казань",
      "quantity":50,
      "sku_breakdown":[{"sku":"SKU-B","quantity":50}]
    },
    {
      "destination_cluster_id":"Тверь",
      "quantity":50,
      "sku_breakdown":[{"sku":"SKU-C","quantity":50}]
    }
  ]
}
```

Assert rendered values include:

```text
Москва — 600 шт.
Свой спрос — 500 шт.
Другие кластеры — 100 шт.
Казань — 50 шт.
Тверь — 50 шт.
```

- [ ] **Step 2: Render compact panel after decision line and before destination table**

Heading: `Куда поставить`.

Each origin uses native `<details>/<summary>`:

```text
Москва                                      600 шт.
  Свой спрос                                500 шт.
  Другие кластеры                           100 шт.
```

Expanded section iterates backend `destinations`; optional nested SKU breakdown is rendered only from each backend `sku_breakdown` array and is never recomputed from raw restrictions/flows.

- [ ] **Step 3: Empty/gap state**

When no origin has allocated quantity:

```text
Нет рассчитанной поставки для выбранной сети.
```

If Calculated totals contain gaps, show directly below:

```text
Сеть не покрывает: N
Заблокировано: N
Не хватило товара: N
```

from family totals.

- [ ] **Step 4: Add dense CSS using current detail/panel tokens**

No new KPI cards. Keep origin rows scan-friendly at normal and narrow width.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: show physical origin supply plan"
```

---

### Task 7: Split Flow into `История | План размещения`

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `tests/frontend/test_ui_state.py`
- Modify: `tests/frontend/test_flow_view.py`
- Modify: `tests/frontend/test_flow_real_scale.py`

**Exact initial `flowView` after this task:**

```javascript
flowView:{
  surface:'history',
  mode:'destination',
  metric:'units',
  evidence:'clean',
  selectedKey:null,
  selectedRoute:null,
  selectedEpisodeId:null,
  selectorQuery:'',
  selectorPage:1,
  routeQuery:'',
  routePage:1,
  dailyPage:1,
  episodePage:1,
  skuQuery:'',
  skuPage:1,
  showAllRoutes:false
}
```

- [ ] **Step 1: Add state validation helper/tests**

`surface` accepts only `history` or `planning`. Existing `evidence` remains `observed|clean` and affects history only.

- [ ] **Step 2: Render top-level surface controls**

```text
[ История ] [ План размещения ]
```

When `surface==='history'`, preserve existing:

```text
[ Наблюдаемое ] [ Очищенное ]
```

Do not render `План` as a third evidence source.

- [ ] **Step 3: Define one planned-leg source**

```javascript
S.plannedLegs = function(snapshot) {
  const destinations = snapshot?.planning_snapshot?.calculated?.destination_views || [];
  return destinations.flatMap(item => item.legs || [])
    .filter(leg => Number(leg.final_allocated_qty) > 0);
};
```

Destination mode filters these legs by `destination_cluster_id`; origin mode filters by `origin_cluster_id`; SKU mode filters by `sku`. Do not read `origin_views` to reconstruct links because origin roll-up is intentionally aggregated across SKUs.

- [ ] **Step 4: Preserve History behavior unchanged**

Existing Flow selectors, observed/clean evidence, timeline and history link rendering remain the history code path. Add regression assertions that the same history fixture renders the same primary text when `surface='history'`.

- [ ] **Step 5: Add 40-destination real-scale planned fixture**

Use at least 40 final planned destination legs across several origins and multiple SKUs. Assert selector/top-N/pagination remains bounded and no all-network SVG/Sankey/chord is created.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/frontend/test_ui_state.py tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
git add frontend/assets/js/core.js frontend/assets/js/flow.js tests/frontend/test_ui_state.py tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py
git commit -m "feat: add planned placement flow surface"
```

---

### Task 8: Present Flow, RouteCostIndex, direct tariff and Capacity separately

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_flow_view.py`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add RouteCostIndex presenter for `PlanningLegView` fields**

```javascript
S.presentRouteCostIndex = function(leg) {
  if (!leg || leg.route_cost_index === null || leg.route_cost_index === undefined) {
    return {value:'Не рассчитано',coverage:'Не рассчитано',spread:'Не рассчитано'};
  }
  return {
    value:S.presentNumber(leg.route_cost_index,{minimumFractionDigits:2,maximumFractionDigits:2}),
    coverage:S.presentPercentFraction(leg.route_cost_index_coverage),
    spread:S.presentNumber(leg.route_cost_index_spread,{maximumFractionDigits:2})
  };
};
```

- [ ] **Step 2: Add exact explanatory copy test**

```text
1,00 — медианная стоимость маршрута среди сопоставимых тарифных классов. Ниже 1,00 — маршрут обычно дешевле медианы; выше 1,00 — дороже.
```

Assert no `0,8`, `1,3`, `сильная связка` or `слабая связка` category label appears.

- [ ] **Step 3: Render non-local planned-route evidence rows**

Use the backend leg directly:

```text
Исторический поток       63%
Индекс маршрута          0,72
Тариф этого SKU          51 ₽
Capacity origin          240 шт.
```

`Исторический поток` uses `observed_flow_share`; missing history shows `Не наблюдался`, not `0%`.

Capacity presentation is exact:

```text
FINITE    -> N шт.
UNLIMITED -> Без ограничений
UNKNOWN   -> Не подтверждён
```

from `origin_capacity_kind/origin_capacity_qty`.

- [ ] **Step 4: Show RouteCostIndex quality as secondary evidence**

```text
Покрытие тарифных классов: 97%
Разброс IQR: 0,08
```

Quality values never recolor/block the route by hard threshold.

- [ ] **Step 5: LOCAL presentation**

For `coverage_type==='local'` show `Локальное размещение`. Omit external RouteCostIndex and external-route labels; direct local tariff may be displayed as `Тариф локального исполнения` only when backend `direct_route_fee` is present, otherwise `Не рассчитано`.

- [ ] **Step 6: Keep history and planning semantics separate**

History route detail may show pair-level current RouteCostIndex by joining `snapshot.planning_basis.route_cost_indices` on origin+destination. It remains labeled `Структура текущей тарифной матрицы`; historical observed/clean share is not converted into plan quantity.

- [ ] **Step 7: Run evidence tests and commit**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_plan_view.py -q
git add frontend/assets/js/core.js frontend/assets/js/flow.js frontend/assets/js/app.js tests/frontend/test_flow_view.py tests/frontend/test_plan_view.py
git commit -m "feat: explain planned route evidence"
```

---

### Task 9: Update durable UX contract

**Files:**
- Modify: `UX-CONTRACT.md`

- [ ] **Step 1: Document applied/draft network ownership**

Add exactly:

```text
applied network = network represented by the visible successful PlanningSnapshot
draft network = current checkbox edits
checkbox edit = no request
network dirty = stale-plan notice
Пересчитать план = only action that can apply draft
successful calculation = returned network becomes applied
a failed calculation = previous applied plan stays visible and draft is preserved
```

- [ ] **Step 2: Document request-depth ownership**

```text
network-only dirty -> /api/replan
upstream dirty -> full analysis carrying current network draft
```

- [ ] **Step 3: Document Flow taxonomy**

```text
История -> Наблюдаемое / Очищенное
План размещения -> final Calculated PlanningLegView links
RouteCostIndex -> pair-level tariff-topology evidence
Direct tariff -> concrete SKU execution route price
Capacity -> physical SKU × origin restriction evidence
```

Explicitly prohibit collapsing these into one opaque route score.

- [ ] **Step 4: Commit**

```bash
git add UX-CONTRACT.md
git commit -m "docs: define selected network UI workflow"
```

---

### Task 10: Frontend production verification

**Files:** no new production files

- [ ] **Step 1: Run frontend tests**

```bash
python -m pytest tests/frontend -q
```

Expected: PASS.

- [ ] **Step 2: Run planning API acceptance**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_replan.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Static anti-pattern scan**

```bash
python - <<'PY'
from pathlib import Path
paths = (
    Path('frontend/assets/js/app.js'),
    Path('frontend/assets/js/core.js'),
    Path('frontend/assets/js/flow.js'),
)
text = '\n'.join(path.read_text('utf-8') for path in paths)
for forbidden in ('alert(', 'confirm(', 'prompt(', 'onclick='):
    assert forbidden not in text, forbidden
for forbidden_copy in ('< 0,8', '> 1,3', '<0,8', '>1,3'):
    assert forbidden_copy not in text, forbidden_copy
print('frontend anti-pattern scan: ok')
PY
```

Expected: `frontend anti-pattern scan: ok`.

- [ ] **Step 5: Manual browser workflow verification**

Verify in one real session:

1. initial Plan loads persisted/default applied network;
2. keyboard opens network editor;
3. search and clear-search work;
4. toggle several clusters: no request occurs and stale-plan notice appears;
5. press `Пересчитать план`: exactly one network-only replan updates plan;
6. change horizon plus network: one full analysis applies both;
7. exercise failed replan: old plan remains and draft is preserved;
8. inspect `Куда поставить` cluster roll-up and nested destination/SKU breakdown;
9. inspect destination drawer with all three gap causes;
10. switch `Потоки спроса → История` and verify current observed/clean behavior;
11. switch `План размещения` and inspect non-local route Flow/RouteIndex/tariff/capacity evidence;
12. inspect LOCAL route and verify no fake external RouteIndex;
13. at narrow viewport and 200% browser zoom, primary actions remain accessible;
14. Tab/Shift+Tab reaches search, clear, checkboxes, editor action, recalculate and flow surface controls with visible focus.

- [ ] **Step 6: Commit verification-driven corrections when present**

```bash
git add frontend UX-CONTRACT.md tests
if ! git diff --cached --quiet; then
  git commit -m "fix: harden selected network product workflow"
fi
```

---

## PR-E Acceptance Gate

PR-E is complete only when all are true:

1. Network checkboxes are draft-only and never auto-request.
2. One explicit `Пересчитать план` applies the network.
3. Network-only changes use `/api/replan`; upstream changes use full analysis carrying the same draft.
4. Failed recalculation leaves prior applied plan visible and draft intact.
5. `PlanningSnapshot`, not legacy plan quantities, owns displayed Safe/Calculated plan.
6. Destination demand identity remains separate from physical origin placement.
7. `Куда поставить` consumes backend cluster roll-up and does not reconstruct physical totals from raw data.
8. `network_uncovered`, `allocation_blocked`, `stock_uncovered` remain visibly distinct.
9. Flow has `История | План размещения`; planned mode is not an evidence-source toggle.
10. Planned Flow links come from final `PlanningLegView` rows; historical links remain unchanged.
11. Historical Flow, RouteCostIndex, direct SKU tariff and capacity are separately labeled.
12. RouteCostIndex is numeric with coverage/IQR context and no invented 0.8/1.3 hard bands.
13. LOCAL routes do not show fake external RouteCostIndex values.
14. Search/checkbox/actions are semantic, keyboard accessible and visibly focused.
15. No new dependency, modal system, global Sankey or KPI mosaic is introduced.
16. `UX-CONTRACT.md` matches runtime behavior.
17. Frontend, API and full suites are green and manual success/failure/loading/narrow/keyboard workflow passes.
