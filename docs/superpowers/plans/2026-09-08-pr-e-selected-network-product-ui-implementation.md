# PR-E Selected Supply Network Product UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `frontend-design`, `frontend-design-premium`, and superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Execute task-by-task with TDD and review checkpoints.

**Goal:** Make `PlanningSnapshot` the authoritative user-facing plan, add explicit draft/applied selected-network editing with one `Пересчитать план` action, show cluster-level physical supply roll-up, and add a separate planned-placement Flow surface that explains historical Flow, RouteCostIndex, concrete SKU tariff and capacity as distinct evidence.

**Architecture:** Preserve the current four-tab engineering-console shell and current visual language. Reuse existing `SearchField`, native checkboxes, native `<details>` disclosures and existing busy/status patterns; do not add a new overlay/modal primitive. Checkbox edits change draft state only. `Пересчитать план` calls full analysis when upstream inputs are dirty and `/api/replan` when only network draft differs. Frontend only joins and presents backend PlanningBasis/PlanningSnapshot data; it performs no planning arithmetic.

**Tech Stack:** existing dependency-free browser JS, semantic HTML, existing frontend primitives, `frontend/assets/css/app.css`, pytest frontend/static tests; no new framework or dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Behavior authority:** root `DESIGN.md`, root `UX-CONTRACT.md`, Frontend Design Premium canonical UI/interaction rules.

## Global Constraints

- Preserve tabs exactly: `План`, `Потоки спроса`, `Экономика`, `Данные`.
- Preserve decision line `Ozon → Наша потребность → Наш план`.
- Displayed Safe/Calculated plan quantities come from `PlanningSnapshot`, never legacy `DecisionRow.*_plan_qty` after this PR.
- Checkbox changes never request backend automatically.
- Draft network and applied network are distinct state; visible plan belongs to applied network until success.
- One `Пересчитать план` button chooses request depth:
  - upstream snapshot stale/no snapshot → full analysis with current draft network;
  - only network draft dirty → `/api/replan`;
  - nothing dirty → existing full refresh behavior.
- Failure preserves prior PlanningSnapshot and current draft for retry.
- Controls are disabled during active calculation without geometry shift.
- Frontend never computes route ranking, RouteCostIndex, capacity, economics, destination conservation or physical roll-up totals.
- Historical Flow %, RouteCostIndex, direct SKU tariff and capacity are separately labeled.
- RouteCostIndex uses `1,00` as median-relative explanation only; no hard `0.8/1.3` categories.
- Flow taxonomy is `История | План размещения`; `Наблюдаемое | Очищенное` remains inside History only.
- Network editor uses existing `SearchField`, semantic checkboxes/labels and native buttons.
- Candidate cluster list shows names only in this PR; no frontend-derived SKU availability counts.
- Do not add global Sankey, KPI-card mosaic, modal framework, new dependency or new design token.
- Root `DESIGN.md` is read and must remain unchanged unless implementation demonstrably needs a durable token; this plan expects no DESIGN.md diff.
- `UX-CONTRACT.md` must be updated because workflow/state ownership changes are durable.
- Cross-docking wording/costs never appear in route planning UI.

---

## File Structure

- Modify `frontend/assets/js/core.js` — network state, dirty/request-depth helpers, replan request body, PlanningSnapshot joins/presenters.
- Modify `frontend/assets/js/app.js` — Plan network editor, action routing, authoritative destination plan, cluster physical roll-up and detail drawer.
- Modify `frontend/assets/js/flow.js` — History/Planned surface and planned route evidence rendering.
- Modify `frontend/assets/css/app.css` — network editor, physical roll-up and evidence layout using existing tokens.
- Modify `UX-CONTRACT.md` — applied/draft/recalculate/failure and Flow taxonomy.
- Modify `tests/frontend/test_ui_state.py` — network state transitions.
- Modify `tests/frontend/test_analysis_submit.py` — request depth/bodies/no-auto-request.
- Modify `tests/frontend/test_plan_view.py` — authoritative plan/roll-up/gaps/capacity evidence.
- Modify `tests/frontend/test_flow_view.py` — History/Planned and route evidence.
- Modify `tests/frontend/test_flow_real_scale.py` — bounded planned-flow behavior at real scale.
- Run `tests/frontend/test_product_shell.py` unchanged as shell regression.
- Run `tests/api/test_analysis.py`, `tests/api/test_replan.py`, `tests/api/test_product_completion_acceptance.py` unchanged as backend contract regressions.

`frontend/assets/js/components.js` is intentionally unchanged: existing `SearchField`, `DataTable` and `DetailDrawer` plus native disclosure/checkbox controls are sufficient.

---

### Task 1: Add explicit applied/draft network state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`

**New state:**

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

Keep the full existing `flowView` unchanged in this task.

- [ ] **Step 1: Add exact initial-state assertion**

Assert the new `networkView` object equals the contract above immediately after `S.createInitialState()`.

- [ ] **Step 2: Add snapshot initialization test**

Fixture:

```javascript
const snapshot = {
  planning_basis: {candidate_supply_clusters:['Казань','Москва','Питер']},
  planning_snapshot: {applied_supply_network:['Москва','Питер']}
};
```

Assert initialization produces sorted candidate/applied/draft arrays and `dirty:false`.

- [ ] **Step 3: Add exact pure helpers**

```javascript
S.initializeNetworkView = function(state, snapshot) {
  const candidates = Array.from(
    snapshot?.planning_basis?.candidate_supply_clusters || []
  ).sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = Array.from(
    snapshot?.planning_snapshot?.applied_supply_network || []
  ).sort((a,b)=>a.localeCompare(b,'ru'));
  return {
    ...state,
    networkView:{
      candidateClusters:candidates,
      appliedClusters:applied,
      draftClusters:Array.from(applied),
      dirty:false,
      editorOpen:false,
      search:''
    }
  };
};

S.toggleNetworkDraft = function(state, cluster, selected) {
  const values = new Set(state.networkView.draftClusters);
  if (selected) values.add(cluster); else values.delete(cluster);
  const draft = Array.from(values).sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = state.networkView.appliedClusters;
  const dirty = draft.length !== applied.length || draft.some((x,i)=>x !== applied[i]);
  return {...state,networkView:{...state.networkView,draftClusters:draft,dirty}};
};

S.setNetworkEditorOpen = (state,editorOpen)=>({
  ...state,networkView:{...state.networkView,editorOpen:Boolean(editorOpen)}
});

S.setNetworkSearch = (state,search)=>({
  ...state,networkView:{...state.networkView,search:String(search)}
});
```

- [ ] **Step 4: Add toggle/revert tests**

Select Kazan from applied Moscow/Peter; assert dirty true and applied unchanged. Unselect Kazan again; assert draft equals applied and dirty false.

- [ ] **Step 5: Add successful planning-result helper**

```javascript
S.applyPlanningResult = function(state, planningSnapshot) {
  const applied = Array.from(
    planningSnapshot?.applied_supply_network || []
  ).sort((a,b)=>a.localeCompare(b,'ru'));
  return {
    ...state,
    networkView:{
      ...state.networkView,
      appliedClusters:applied,
      draftClusters:Array.from(applied),
      dirty:false
    }
  };
};
```

Failure has no state helper that resets network; failure handler simply leaves `networkView` unchanged.

- [ ] **Step 6: Run state tests**

```bash
python -m pytest tests/frontend/test_ui_state.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py
git commit -m "feat: add selected network draft state"
```

---

### Task 2: Route one recalculation button to full analysis or replan

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_analysis_submit.py`

- [ ] **Step 1: Add request-depth helper tests**

Required results:

```text
no snapshot -> analysis
staleSnapshot true + network dirty -> analysis
staleSnapshot false + network dirty -> replan
staleSnapshot false + network clean -> analysis
```

- [ ] **Step 2: Implement request-depth helper**

```javascript
S.resolveRecalculationKind = function(state) {
  if (!state.snapshot || state.staleSnapshot) return 'analysis';
  if (state.networkView.dirty) return 'replan';
  return 'analysis';
};
```

- [ ] **Step 3: Extend full-analysis body with the current network draft**

Change signature:

```javascript
S.buildAnalysisRequestBody = function(
  form,
  scenario,
  selectedSupplyClusters,
  FormDataCtor=globalThis.FormData
) {
  const body = new FormDataCtor(form);
  body.set('horizon_days',String(scenario.horizonDays));
  body.set('include_inbound',String(scenario.includeInbound));
  body.set('selected_supply_clusters',JSON.stringify(selectedSupplyClusters));
  return body;
};
```

Update all callers/tests to pass `state.networkView.draftClusters`.

- [ ] **Step 4: Add/implement exact replan JSON builder**

```javascript
S.buildReplanRequestBody = function(state) {
  return {
    planning_basis:state.snapshot.planning_basis,
    selected_supply_clusters:Array.from(state.networkView.draftClusters)
  };
};
```

Test that empty draft serializes as `[]`.

- [ ] **Step 5: Implement `runReplan()` using existing run-sequence stale-response protection**

The function:

```text
increments runSequence and captures run id
sets analysisActive=true without clearing state.snapshot
POSTs JSON to /api/replan
ignores result when run id is no longer current
on success replaces only state.snapshot.planning_snapshot
calls S.applyPlanningResult with returned planning snapshot
clears analysisError
on HTTP/network failure preserves old planning snapshot and network draft, sets inline analysisError
finally clears analysisActive only for current run
```

Use `fetch('/api/replan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(S.buildReplanRequestBody(state))})`.

- [ ] **Step 6: Update `#recalculate` handler**

After existing horizon validation:

```javascript
const kind = S.resolveRecalculationKind(state);
if (kind === 'replan') runReplan(); else runAnalysis();
```

Successful full analysis initializes network state from returned nested PlanningBasis/PlanningSnapshot.

- [ ] **Step 7: Add no-auto-request regression**

The checkbox change binding must call only `S.toggleNetworkDraft`/state render. Test source/behavior to prove neither `runAnalysis()` nor `runReplan()` is invoked from network checkbox `change`.

- [ ] **Step 8: Run submit/state tests**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py
git commit -m "feat: apply network only on explicit recalculation"
```

---

### Task 3: Add compact searchable network editor to Plan scenario area

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

**UI contract:**

Collapsed:

```text
Сеть поставки
Москва · Санкт-Петербург · +2                         [Изменить]
```

Expanded:

```text
Куда готовы поставлять
[ Поиск кластера ]
☑ Москва
☑ Санкт-Петербург
☐ Казань
☐ Пермь
Выбрано: 2
```

No SKU count is shown in this PR.

- [ ] **Step 1: Add pure list/summary helpers**

```javascript
S.filteredNetworkClusters = function(state) {
  const q = (state.networkView.search || '').trim().toLocaleLowerCase('ru');
  return state.networkView.candidateClusters.filter(
    x => !q || x.toLocaleLowerCase('ru').includes(q)
  );
};

S.networkSummary = function(clusters) {
  if (!clusters.length) return 'Кластеры не выбраны';
  if (clusters.length <= 2) return clusters.join(' · ');
  return `${clusters[0]} · ${clusters[1]} · +${clusters.length - 2}`;
};
```

- [ ] **Step 2: Add semantic markup tests**

Rendered editor must contain:

```text
button#network-edit
existing SearchField output with accessible search input and clear action
input[type=checkbox][data-network-cluster] associated with label
```

No `div`/`span` receives click handlers.

- [ ] **Step 3: Render summary from draft selection**

While dirty, summary reflects draft but add exact warning:

```text
Сеть поставки изменена. План ниже рассчитан для предыдущей сети.
```

This warning is absent when clean.

- [ ] **Step 4: Render editor with existing `SearchField`**

Use `S.SearchField.render()` for search/clear. Candidate list comes only from `S.filteredNetworkClusters(state)`. Each checkbox checked state uses `draftClusters.includes(cluster)`.

- [ ] **Step 5: Busy-state behavior**

When `analysisActive`, disable Edit button, search/clear and checkboxes. Keep editor and primary button geometry stable; do not clear draft.

- [ ] **Step 6: Add CSS classes using existing tokens**

```text
.network-summary
.network-editor
.network-list
.network-option
.network-dirty
```

Reuse current panel/background/border/radius/spacing values from `app.css`. Add no root token.

- [ ] **Step 7: Run Plan tests**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_ui_state.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: add supply network editor"
```

---

### Task 4: Switch Plan to authoritative `PlanningSnapshot`

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add destination-plan maps**

```javascript
S.planningDestinationKey = row => `${row.sku}\0${row.destination_cluster_id}`;

S.destinationPlanMap = function(snapshot, family) {
  const rows = snapshot?.planning_snapshot?.[family]?.destination_views || [];
  return new Map(rows.map(x=>[S.planningDestinationKey(x),x]));
};
```

- [ ] **Step 2: Add legacy-conflict ownership test**

Fixture has:

```text
DecisionRow.calculated_plan_qty = 999
PlanningSnapshot calculated destination final_allocated_qty = 40
DecisionRow.safe_plan_qty = 888
PlanningSnapshot safe destination final_allocated_qty = 30
```

Assert displayed calculated is 40 and Safe is 30.

- [ ] **Step 3: Update decision-line model**

Ozon/Need totals remain existing upstream summary values. Plan totals use:

```javascript
snapshot.planning_snapshot.calculated.total_allocated_qty
snapshot.planning_snapshot.safe.total_allocated_qty
```

- [ ] **Step 4: Join destination rows for table rendering**

`S.buildPlanRows(snapshot)` attaches:

```javascript
planningCalculated:calculatedMap.get(key) || null
planningSafe:safeMap.get(key) || null
```

Plan columns render planning final quantities; missing planning view displays `Не рассчитано`, never legacy quantity fallback.

- [ ] **Step 5: Show three causal gap values separately**

Use backend fields with labels:

```text
network_uncovered_qty -> Сеть не покрывает
allocation_blocked_qty -> Заблокировано
stock_uncovered_qty -> Не хватило товара
```

- [ ] **Step 6: Update drawer Решение section**

For calculated destination view show:

```text
Цель направления
Покрыто планом
Сеть не покрывает
Заблокировано
Не хватило товара
Где разместить
```

`Где разместить` lists only `PlanningLegView` rows with positive `final_allocated_qty`, as `origin — qty`. No frontend totals are recomputed.

- [ ] **Step 7: Run Plan tests**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py
git commit -m "feat: render authoritative planning snapshot"
```

---

### Task 5: Render cluster-level physical supply roll-up

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

**Backend source:** `snapshot.planning_snapshot.calculated.origin_views`.

- [ ] **Step 1: Add exact fixture/render expectation**

Fixture:

```javascript
const origin = {
  origin_cluster_id:'Москва',
  total_qty:600,
  own_destination_qty:500,
  external_destination_qty:100,
  destinations:[
    {destination_cluster_id:'Москва',quantity:500,sku_breakdown:[{sku:'A',quantity:500}]},
    {destination_cluster_id:'Казань',quantity:50,sku_breakdown:[{sku:'B',quantity:50}]},
    {destination_cluster_id:'Тверь',quantity:50,sku_breakdown:[{sku:'C',quantity:50}]}
  ]
};
```

Assert UI contains:

```text
Москва — 600 шт.
Свой спрос — 500 шт.
Другие кластеры — 100 шт.
Казань — 50 шт.
Тверь — 50 шт.
```

- [ ] **Step 2: Render `Куда поставить` panel**

Place after decision line and before destination table. Each origin uses native `<details>`/`<summary>`; summary shows origin and backend `total_qty`. Expanded body shows backend own/external totals then destination breakdowns. LOCAL destination may appear but should not be duplicated under external subsection.

- [ ] **Step 3: Empty state**

When `origin_views` is empty show:

```text
Нет рассчитанной поставки для выбранной сети.
```

If family gap totals are nonzero, render the three backend family gap totals immediately below.

- [ ] **Step 4: Add dense CSS using existing tokens**

No new KPI cards. Keep row hierarchy and numeric alignment consistent with current Plan table/panels.

- [ ] **Step 5: Run Plan tests**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: show physical origin supply plan"
```

---

### Task 6: Add `История | План размещения` Flow surface state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `tests/frontend/test_flow_view.py`
- Modify: `tests/frontend/test_flow_real_scale.py`

**Full `flowView` after change:**

```javascript
flowView: {
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

- [ ] **Step 1: Add state validation helper**

```javascript
S.setFlowSurface = function(state, surface) {
  if (!['history','planning'].includes(surface)) throw new Error('invalid flow surface');
  return {...state,flowView:{...state.flowView,surface,selectedRoute:null,routePage:1}};
};
```

Test both valid values and invalid rejection.

- [ ] **Step 2: Render top-level controls**

```text
[ История ] [ План размещения ]
```

History retains current `Наблюдаемое | Очищенное`. Hide those evidence buttons in Planning surface; do not create a third evidence source.

- [ ] **Step 3: Build planned route rows only from `PlanningLegView`**

Calculated plan is the visual planning source:

```javascript
S.plannedLegs = snapshot => (
  snapshot?.planning_snapshot?.calculated?.destination_views || []
).flatMap(x=>x.legs || []).filter(x=>Number(x.final_allocated_qty)>0);
```

Destination mode filters by destination, origin mode by origin, SKU mode by SKU. Route quantity is `final_allocated_qty` from the leg.

- [ ] **Step 4: Keep current History path untouched**

When `surface==='history'`, existing Flow selectors/evidence/daily/episodes use current code/data unchanged.

- [ ] **Step 5: Add real-scale planned-flow test**

Fixture at least 40 destination legs across several origins. Assert existing selector pagination/top-N route presentation remains bounded and no all-network global diagram is created.

- [ ] **Step 6: Run Flow regressions**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/flow.js tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py
git commit -m "feat: add planned placement flow surface"
```

---

### Task 7: Present route evidence as four separate concepts

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_flow_view.py`
- Modify: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add RouteCostIndex presenter**

```javascript
S.presentRouteCostIndex = function(leg) {
  if (leg?.route_cost_index === null || leg?.route_cost_index === undefined) {
    return {value:'Не рассчитано',coverage:'Не рассчитано',spread:'Не рассчитано'};
  }
  return {
    value:S.presentNumber(leg.route_cost_index,{minimumFractionDigits:2,maximumFractionDigits:2}),
    coverage:S.presentPercentFraction(leg.route_cost_index_coverage),
    spread:S.presentNumber(leg.route_cost_index_spread,{maximumFractionDigits:2})
  };
};
```

- [ ] **Step 2: Add exact helper copy test**

Render exactly:

```text
1,00 — медианная стоимость маршрута среди сопоставимых тарифных классов. Ниже 1,00 — маршрут обычно дешевле медианы; выше 1,00 — дороже.
```

Assert no copy introduces `0,8`, `1,3`, `сильная связка` or `слабая связка` as fixed categories.

- [ ] **Step 3: Add SKU-origin capacity lookup from PlanningBasis**

```javascript
S.capacityForLeg = function(snapshot, leg) {
  return (snapshot?.planning_basis?.sku_origins || []).find(
    x => x.sku === leg.sku && x.origin_cluster_id === leg.origin_cluster_id
  )?.feasibility || null;
};
```

Presenter rules:

```text
FINITE -> max_supply_qty + " шт."
UNLIMITED -> "Без ограничений"
UNKNOWN/missing -> "Не подтверждено"
```

Use serialized enum field `capacity_kind`.

- [ ] **Step 4: Planned non-local route detail shows four distinct rows**

From `PlanningLegView` + capacity lookup:

```text
Фактический поток
Индекс маршрута
Тариф этого SKU
Capacity origin
```

Historical Flow uses `observed_flow_share`; if absent show `Не наблюдался`, not 0%. Direct tariff is `direct_route_fee` in ₽. Route index quality appears beneath the index as `Покрытие классов` and `Разброс IQR`.

- [ ] **Step 5: Add historical-route index join**

For History surface, index by pair from `snapshot.planning_basis.route_cost_indices`. Show it in route detail under label:

```text
Структура текущей тарифной матрицы
```

History Flow quantities/shares stay from historical Flow data and are never replaced by planning legs.

- [ ] **Step 6: LOCAL presentation**

For `coverage_type==='local'` show `Локальное размещение`. Omit non-local RouteCostIndex and direct route tariff rows instead of displaying zero. Capacity may still be shown from SKU-origin feasibility.

- [ ] **Step 7: Run evidence tests**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_plan_view.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/flow.js frontend/assets/js/app.js tests/frontend/test_flow_view.py tests/frontend/test_plan_view.py
git commit -m "feat: explain planned route evidence"
```

---

### Task 8: Update durable UX contract

**Files:**
- Modify: `UX-CONTRACT.md`

- [ ] **Step 1: Document applied/draft state**

Add normative rules:

```text
applied network = network of visible successful PlanningSnapshot
draft network = current checkbox state
checkbox edit = no request
dirty draft = visible prior-plan notice
Пересчитать план = only apply action
success = returned network becomes applied and draft resets to it
failure = prior PlanningSnapshot remains visible and draft is preserved
```

- [ ] **Step 2: Document request depth**

```text
network-only dirty -> /api/replan
upstream stale/no snapshot -> full /api/analysis with current draft network
```

- [ ] **Step 3: Document plan ownership**

`PlanningSnapshot` owns displayed Safe/Calculated destination allocations, gaps, planned legs and physical origin roll-up. Legacy plan fields in `DecisionRow` are not display-authoritative after PR-E.

- [ ] **Step 4: Document Flow taxonomy/evidence**

```text
История -> Наблюдаемое | Очищенное
План размещения -> PlanningLegView final allocations
Flow % -> historical observation
RouteCostIndex -> current tariff-topology evidence
Direct tariff -> concrete SKU route cost
Capacity -> physical SKU-origin restriction evidence
```

State explicitly that these are not collapsed into one score.

- [ ] **Step 5: Confirm root DESIGN.md has no diff**

This implementation adds no durable visual token/component family; visual changes use existing tokens and primitives.

- [ ] **Step 6: Commit**

```bash
git add UX-CONTRACT.md
git commit -m "docs: define selected network UI workflow"
```

---

### Task 9: Production verification

**Files:** no new production files

- [ ] **Step 1: Run frontend tests**

```bash
python -m pytest tests/frontend -q
```

Expected: PASS.

- [ ] **Step 2: Run relevant API acceptance**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_replan.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run static anti-pattern scan**

```bash
python - <<'PY'
from pathlib import Path
paths = [
    Path('frontend/assets/js/app.js'),
    Path('frontend/assets/js/core.js'),
    Path('frontend/assets/js/flow.js'),
]
text = '\n'.join(path.read_text('utf-8') for path in paths)
for forbidden in ('alert(', 'confirm(', 'prompt(', 'onclick='):
    assert forbidden not in text, forbidden
for forbidden_copy in ('< 0,8', '> 1,3', '<0,8', '>1,3'):
    assert forbidden_copy not in text, forbidden_copy
print('frontend anti-pattern scan: ok')
PY
```

Expected: `frontend anti-pattern scan: ok`.

- [ ] **Step 5: Verify real browser workflow**

Using normal repository local launch, verify:

1. initial Plan reflects persisted/default applied network;
2. Edit/search/clear/toggle network works by keyboard with visible focus;
3. toggling clusters performs no request and shows stale-plan warning;
4. `Пересчитать план` with network-only dirty performs one replan and applies returned network;
5. changing horizon plus network performs one full analysis with that draft network;
6. failed replan keeps previous plan visible and preserves draft;
7. `Куда поставить` shows cluster totals and nested destination/SKU breakdown correctly;
8. destination drawer shows three causal gap types separately;
9. History Flow remains unchanged in observed/clean modes;
10. Planned Placement shows final planned links only;
11. non-local planned link separately shows Flow %, RouteCostIndex, exact SKU tariff and capacity;
12. LOCAL link does not show fake external index/tariff;
13. narrow viewport and 200% zoom keep primary action/network controls accessible;
14. Tab/Shift+Tab reaches every enabled network control.

- [ ] **Step 6: Run Frontend Design Premium project audit when skill runtime is available**

Use the installed Premium skill `audit_project.py` in strict mode against repository root, then run any project commands configured by `premium-ui.json`. Treat blocking findings as failures and fix before completion.

- [ ] **Step 7: Commit verification-driven corrections only if required**

```bash
git add frontend UX-CONTRACT.md tests
if ! git diff --cached --quiet; then git commit -m "fix: harden selected network workflow"; fi
```

---

## PR-E Acceptance Gate

PR-E is complete only when all are true:

1. Network checkboxes are draft-only and never auto-request.
2. One explicit `Пересчитать план` applies draft network.
3. Network-only dirty uses `/api/replan`; upstream stale uses full analysis.
4. Failure leaves prior plan visible and draft intact.
5. PlanningSnapshot owns displayed Safe/Calculated quantities.
6. Demand destination remains distinct from physical origin placement.
7. `Куда поставить` uses backend cluster-level roll-up and nested breakdowns.
8. Three causal gap types are visibly distinct.
9. Flow surface is `История | План размещения`; planned mode is not a third history evidence source.
10. Historical Flow %, RouteCostIndex, direct SKU tariff and capacity are separate concepts in UI.
11. RouteCostIndex shows numeric value + coverage/IQR without fixed 0.8/1.3 bands.
12. LOCAL does not show fake external index/tariff.
13. Current History Flow behavior remains regression-green.
14. Search, checkboxes and actions are semantic, keyboard-accessible and visibly focused.
15. No new dependency, modal system, global Sankey, KPI-card mosaic or design token is added.
16. UX-CONTRACT matches runtime behavior and DESIGN.md remains unchanged.
17. Frontend/API/full tests and manual browser verification pass.
