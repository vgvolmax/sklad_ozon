# PR-E Selected Supply Network Product UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `frontend-design`, `frontend-design-premium`, and superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Execute task-by-task with TDD and review checkpoints.

**Goal:** Make `PlanningSnapshot` the authoritative user-facing plan, add a draft/applied selected-supply-network workflow with explicit `Пересчитать план`, show the physical origin supply roll-up, and extend `Потоки спроса` with a separate planned-placement mode that explains Flow, direct tariff, `RouteCostIndex` and capacity without conflating them.

**Architecture:** Keep the current four-tab engineering-console shell and existing visual language. Add one compact supply-network control to the Plan scenario area; editing happens in an inline expandable panel rather than a new modal system. Checkbox changes modify draft state only. The existing `Пересчитать план` button chooses full analysis when upstream inputs are stale and `/api/replan` when only the network changed. Plan quantities, origin roll-ups and gap causes come only from backend `PlanningSnapshot`; frontend performs joins/filtering/presentation, never planning math.

**Tech Stack:** existing dependency-free browser JS, semantic HTML, current `DataTable`, `SearchField`, `DetailDrawer`, CSS in `frontend/assets/css/app.css`, pytest frontend/static tests; no new frontend framework or dependency.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Behavior authority:** project `DESIGN.md`, project `UX-CONTRACT.md`, Frontend Design Premium canonical UI/interaction rules.

**Approved implementation clarification (2026-09-08):** `RouteCostIndex` is shown as a numeric structural route characteristic independent from SKU. Direct tariff remains the concrete SKU route price. Do not create hardcoded visual bands such as `<0.8 good` / `>1.3 bad` in this PR.

## Global Constraints

- Preserve tabs: `План`, `Потоки спроса`, `Экономика`, `Данные`.
- Preserve the decision line `Ozon → Наша потребность → Наш план`.
- `Наш план` in UI becomes authoritative from `PlanningSnapshot`, not legacy `DecisionRow.calculated_plan_qty`.
- Network checkbox changes never call backend immediately.
- Draft network and applied network are visibly distinct; visible plan remains tied to applied network until successful recalculation.
- Same `Пересчитать план` button chooses request depth:
  - upstream files/scenario/mappings dirty -> full analysis with current network draft;
  - network only dirty -> `/api/replan`;
  - nothing dirty -> current full-analysis refresh behavior may remain.
- On failure, keep last successful plan visible and preserve draft network for retry.
- During calculation, keep button geometry stable and disable controls that would create competing drafts.
- No frontend planning formulas, route ranking, capacity aggregation, route-index calculation or economics calculation.
- `RouteCostIndex`, direct tariff, historical Flow and Capacity must be labeled as different concepts.
- `RouteCostIndex` helper copy uses `1,00` only as the mathematical median-relative reference; do not invent category thresholds.
- Historical Flow remains `История → Наблюдаемое | Очищенное`; planned placement is a sibling mode, not a third evidence source.
- Searchable network editor uses native checkboxes + labels, clearable search, visible keyboard focus, disabled/busy states and no clickable divs.
- Do not add a global Sankey or dense dashboard-card mosaic.
- Reuse current CSS tokens/components; update `DESIGN.md` only if a new durable visual token is genuinely required. This plan expects no new durable token.
- Update `UX-CONTRACT.md` because workflow/state ownership changes are durable.
- No cross-docking terminology or costs appear in route-plan UI.

---

## File Structure

- Modify `frontend/assets/js/core.js` — network draft/applied state, dirty-state resolution, request builders, authoritative planning joins/presenters.
- Modify `frontend/assets/js/app.js` — Plan network editor, full-vs-replan action routing, PlanningSnapshot rendering, origin roll-up, destination detail.
- Modify `frontend/assets/js/flow.js` — `История | План размещения` mode and planned route visualization/details.
- Modify `frontend/assets/js/components.js` only if a small reusable disclosure/list primitive is needed; do not create an overlay system.
- Modify `frontend/assets/css/app.css` — compact network editor, origin roll-up and planned-route evidence styling using existing tokens.
- Modify `UX-CONTRACT.md` — exact draft/applied/recalculate/failure behavior and Flow mode semantics.
- Modify `tests/frontend/test_ui_state.py` — draft/applied network state and dirty logic.
- Modify `tests/frontend/test_analysis_submit.py` — request-depth selection and selected-network request body.
- Modify `tests/frontend/test_plan_view.py` — PlanningSnapshot ownership, roll-up, gap explanations, route index/direct fee display.
- Modify `tests/frontend/test_flow_view.py` and `tests/frontend/test_flow_real_scale.py` — History vs Planned Placement and real-scale stability.
- Modify `tests/frontend/test_product_shell.py` only if static required selectors/labels need coverage.
- Modify `tests/api/test_product_completion_acceptance.py` only if end-to-end browser-facing acceptance fixture must expose planning wire; backend semantics remain PR-D-owned.

---

### Task 1: Add explicit applied/draft supply-network state

**Files:**
- Modify: `frontend/assets/js/core.js`
- Test: `tests/frontend/test_ui_state.py`

**State contract:**

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

Assert `S.createInitialState().networkView` exactly equals the contract above.

- [ ] **Step 2: Add snapshot initialization test**

Given:

```javascript
snapshot.planning_basis.candidate_supply_clusters = ['Казань','Москва','Питер'];
snapshot.planning_snapshot.applied_supply_network = ['Москва','Питер'];
```

assert:

```javascript
candidateClusters === ['Казань','Москва','Питер']
appliedClusters === ['Москва','Питер']
draftClusters === ['Москва','Питер']
dirty === false
```

- [ ] **Step 3: Add draft toggle tests**

```javascript
let next = S.toggleNetworkDraft(state, 'Казань', true);
assert.deepEqual(next.networkView.draftClusters, ['Казань','Москва','Питер']);
assert.equal(next.networkView.dirty, true);
assert.deepEqual(next.networkView.appliedClusters, ['Москва','Питер']);
```

Toggling back to exactly the applied set clears `dirty`.

- [ ] **Step 4: Add successful apply and failed-request state tests**

`S.applyPlanningResult(state, planningSnapshot)` resets applied/draft to returned applied network and `dirty=false`.

`S.preserveNetworkDraftAfterFailure(state)` keeps both the prior applied set and current dirty draft unchanged.

- [ ] **Step 5: Implement pure state helpers**

Add:

```javascript
S.initializeNetworkView = function(state, snapshot) {
  const candidates = [...(snapshot?.planning_basis?.candidate_supply_clusters || [])].sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = [...(snapshot?.planning_snapshot?.applied_supply_network || [])].sort((a,b)=>a.localeCompare(b,'ru'));
  return {...state, networkView:{candidateClusters:candidates,appliedClusters:applied,draftClusters:[...applied],dirty:false,editorOpen:false,search:''}};
};

S.toggleNetworkDraft = function(state, cluster, selected) {
  const set = new Set(state.networkView.draftClusters);
  selected ? set.add(cluster) : set.delete(cluster);
  const draft = [...set].sort((a,b)=>a.localeCompare(b,'ru'));
  const applied = state.networkView.appliedClusters;
  const dirty = draft.length !== applied.length || draft.some((x,i)=>x!==applied[i]);
  return {...state, networkView:{...state.networkView,draftClusters:draft,dirty}};
};
```

Add pure setters for `editorOpen` and `search`.

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

### Task 2: Route `Пересчитать план` to full analysis or network-only replan

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Test: `tests/frontend/test_analysis_submit.py`

**Pure decision helper:**

```javascript
S.resolveRecalculationKind = function(state) {
  if (state.staleSnapshot || !state.snapshot) return 'analysis';
  if (state.networkView.dirty) return 'replan';
  return 'analysis';
};
```

- [ ] **Step 1: Add request-kind tests**

Assert:

```text
network dirty only -> replan
scenario/input stale + network dirty -> analysis
no snapshot -> analysis
nothing dirty -> analysis
```

- [ ] **Step 2: Add full-analysis request body test**

Extend `S.buildAnalysisRequestBody()` so it always sets current draft network:

```javascript
body.set('selected_supply_clusters', JSON.stringify(state.networkView.draftClusters));
```

The function signature becomes:

```javascript
S.buildAnalysisRequestBody(form, scenario, selectedSupplyClusters, FormDataCtor)
```

Update all call sites/tests.

- [ ] **Step 3: Add replan JSON builder test**

```javascript
S.buildReplanRequestBody = function(state) {
  return {
    planning_basis: state.snapshot.planning_basis,
    selected_supply_clusters: [...state.networkView.draftClusters]
  };
};
```

Assert empty draft serializes as `[]`, not omitted/null.

- [ ] **Step 4: Implement `runReplan()` in `app.js`**

Behavior:

1. increment `runSequence` and capture local run id;
2. set shared calculation busy state without replacing snapshot;
3. POST JSON to `/api/replan`;
4. ignore a response if run id is stale;
5. on success replace only `state.snapshot.planning_snapshot` with returned planning snapshot, preserve immutable upstream snapshot fields and current `planning_basis`, apply returned network, clear error;
6. on failure keep previous planning snapshot and current network draft, set inline error;
7. always clear busy state for current run.

- [ ] **Step 5: Update existing recalculate handler**

```javascript
const kind = S.resolveRecalculationKind(state);
if (kind === 'replan') runReplan();
else runAnalysis();
```

A full analysis sends the current draft network. On successful full analysis call `S.initializeNetworkView()` from the returned snapshot.

- [ ] **Step 6: Add no-auto-request test**

Static/behavior test must prove checkbox `change` handler only updates state and does not call `runAnalysis` or `runReplan`; backend action occurs only from `#recalculate`.

- [ ] **Step 7: Run submit tests**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend
git commit -m "feat: replan network only on explicit action"
```

---

### Task 3: Add compact searchable supply-network editor

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Test: `tests/frontend/test_plan_view.py`

**UI shape:**

```text
Сеть поставки
Москва · Санкт-Петербург · +2                         [Изменить]

when expanded:
┌─────────────────────────────────────────────────────────────┐
│ Куда готовы поставлять                                     │
│ [ Поиск кластера…                                     × ]  │
│ ☑ Москва                 428 SKU доступны                  │
│ ☑ Санкт-Петербург       397 SKU доступны                  │
│ ☐ Казань                286 SKU доступны                  │
│ ...                                                         │
│ Выбрано: 4                                                │
└─────────────────────────────────────────────────────────────┘
```

SKU-available counts come from backend basis only if PR-D exposes them; if basis does not contain counts, omit the count text completely rather than calculating it from raw restrictions in frontend.

- [ ] **Step 1: Add static semantic tests**

Assert generated markup uses:

```text
button for Изменить
input type=search with explicit label/aria-label
input type=checkbox nested/associated with label
no onclick div/span controls
```

- [ ] **Step 2: Add network search model helper**

```javascript
S.filteredNetworkClusters = function(state) {
  const q = (state.networkView.search || '').trim().toLocaleLowerCase('ru');
  return state.networkView.candidateClusters.filter(
    x => !q || x.toLocaleLowerCase('ru').includes(q)
  );
};
```

The clear button appears only when query is nonempty, clears immediately and restores focus to search.

- [ ] **Step 3: Implement summary label**

Pure helper:

```javascript
S.networkSummary = function(clusters) {
  if (!clusters.length) return 'Кластеры не выбраны';
  if (clusters.length <= 2) return clusters.join(' · ');
  return `${clusters[0]} · ${clusters[1]} · +${clusters.length - 2}`;
};
```

Summary shows **draft** selection while dirty; a stale notice underneath makes clear the visible plan still belongs to applied selection.

- [ ] **Step 4: Render dirty notice**

Exact copy:

```text
Сеть поставки изменена. План ниже рассчитан для предыдущей сети.
```

Show only when `networkView.dirty === true`.

- [ ] **Step 5: Implement busy state**

While analysis/replan is active:

- disable checkboxes, search and `Изменить`;
- keep network list geometry stable;
- keep button width stable and use existing `Пересчитываем…` label;
- do not clear the draft.

- [ ] **Step 6: Add CSS using existing tokens only**

Create classes:

```text
.network-summary
.network-editor
.network-editor-head
.network-search
.network-list
.network-option
.network-option-meta
.network-dirty
```

Use current panel border/background/radius/spacing variables from `app.css`; do not introduce new root colors or shadows.

- [ ] **Step 7: Run plan UI tests**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_ui_state.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend
git commit -m "feat: add supply network editor"
```

---

### Task 4: Switch Plan quantities to authoritative PlanningSnapshot

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Test: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add pure planning join helpers**

```javascript
S.planningDestinationKey = row => `${row.sku}\0${row.destination_cluster_id}`;

S.calculatedDestinationPlans = function(snapshot) {
  return new Map(
    (snapshot?.planning_snapshot?.calculated?.destination_views || [])
      .map(x => [S.planningDestinationKey(x), x])
  );
};

S.safeDestinationPlans = function(snapshot) {
  return new Map(
    (snapshot?.planning_snapshot?.safe?.destination_views || [])
      .map(x => [S.planningDestinationKey(x), x])
  );
};
```

- [ ] **Step 2: Add ownership test with deliberately conflicting legacy values**

Fixture:

```text
DecisionRow.calculated_plan_qty = 999
PlanningSnapshot calculated destination final_allocated_qty = 40
```

Assert displayed `Наш план` is `40`, not `999`.

Likewise Safe uses `PlanningSnapshot.safe.destination_views`.

- [ ] **Step 3: Update decision-line model**

Use:

```javascript
snapshot.planning_snapshot.calculated.total_allocated_qty
snapshot.planning_snapshot.safe.total_allocated_qty
```

Ozon and model need totals remain upstream AnalysisSnapshot summary values.

- [ ] **Step 4: Add causal uncovered status presentation**

For each destination join expose:

```text
network_uncovered_qty -> Сеть не покрывает
allocation_blocked_qty -> Заблокировано экономикой/данными
stock_uncovered_qty -> Не хватило товара
```

Show quantities separately; never merge all into generic `Не покрыто`.

- [ ] **Step 5: Update drawer “Решение” block**

Add:

```text
Цель направления
Покрыто планом
Сеть не покрывает
Заблокировано
Не хватило товара
Где разместить
```

`Где разместить` lists final legs `origin — qty` from backend. No frontend sum is used for business totals; list rendering only.

- [ ] **Step 6: Run plan tests**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py
git commit -m "feat: render authoritative selected-network plan"
```

---

### Task 5: Add physical Origin Supply Plan roll-up

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Test: `tests/frontend/test_plan_view.py`

**Backend source:** `snapshot.planning_snapshot.calculated.origin_views`.

- [ ] **Step 1: Add render test**

Fixture origin view:

```json
{
  "origin_cluster_id": "Москва",
  "total_qty": 600,
  "own_destination_qty": 500,
  "external_destination_qty": 100,
  "legs": [
    {"destination_cluster_id":"Москва","final_allocated_qty":500},
    {"destination_cluster_id":"Казань","final_allocated_qty":50},
    {"destination_cluster_id":"Тверь","final_allocated_qty":50}
  ]
}
```

Assert rendered content includes:

```text
Москва — 600 шт.
Свой спрос — 500 шт.
Другие кластеры — 100 шт.
Казань — 50 шт.
Тверь — 50 шт.
```

- [ ] **Step 2: Render one compact panel between decision line and destination table**

Heading: `Куда поставить`.

Each selected origin is a disclosure row using native `<details>`/`<summary>`:

```text
Москва                                      600 шт.
  Свой спрос                                500
  Другие кластеры                           100
```

Expanded detail lists destination legs in descending backend-provided/final quantity order only for presentation. The backend `total_qty`, `own_destination_qty`, `external_destination_qty` stay authoritative.

- [ ] **Step 3: Empty network/result state**

If no origin has allocated units, show:

```text
Нет рассчитанной поставки для выбранной сети.
```

If target remains but gaps exist, show the causal gap summary from planning family totals directly below.

- [ ] **Step 4: Add CSS using current panel/detail styles**

No new KPI cards. Keep origin rows dense and scan-friendly.

- [ ] **Step 5: Run tests**

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

### Task 6: Split Flow screen into `История | План размещения`

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Test: `tests/frontend/test_flow_view.py`
- Test: `tests/frontend/test_flow_real_scale.py`

**State extension:**

```javascript
flowView: {
  surface: 'history',
  evidence: 'clean',
  ...existing fields
}
```

- [ ] **Step 1: Add state/navigation tests**

`surface` accepts only `history` or `planning`. Existing `evidence` remains `observed|clean` and is relevant only when surface is history.

- [ ] **Step 2: Render top-level segmented actions**

```text
[ История ] [ План размещения ]
```

Inside history preserve current:

```text
[ Наблюдаемое ] [ Очищенное ]
```

Do not render `План` as a third evidence-source button.

- [ ] **Step 3: Build planned-flow models only from PlanningSnapshot**

For destination mode, use `calculated.destination_views[].legs`.

For origin mode, use `calculated.origin_views[].legs`.

For SKU mode, filter final legs by SKU.

No planned link quantity is reconstructed from historical Flow.

- [ ] **Step 4: Preserve existing history tests unchanged**

The current History screen should render identically when `surface='history'`.

- [ ] **Step 5: Add real-scale planning test**

Use at least 40 destination legs and several origins. Assert the existing top-N/selector/pagination strategy remains bounded and no unbounded global diagram is rendered.

- [ ] **Step 6: Run Flow tests**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/flow.js tests/frontend
git commit -m "feat: add planned placement flow surface"
```

---

### Task 7: Present Flow %, RouteCostIndex, direct tariff and Capacity as separate evidence

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/app.js`
- Test: `tests/frontend/test_flow_view.py`
- Test: `tests/frontend/test_plan_view.py`

- [ ] **Step 1: Add pure RouteCostIndex presenter**

```javascript
S.presentRouteCostIndex = function(item) {
  if (!item || item.index_value === null || item.index_value === undefined) {
    return {value:'Не рассчитано', coverage:'Не рассчитано', spread:'Не рассчитано'};
  }
  return {
    value:S.presentNumber(item.index_value,{minimumFractionDigits:2,maximumFractionDigits:2}),
    coverage:S.presentPercentFraction(item.coverage_ratio),
    spread:S.presentNumber(item.spread_iqr,{maximumFractionDigits:2})
  };
};
```

- [ ] **Step 2: Add exact explanatory copy test**

Route index help text:

```text
1,00 — медианная стоимость маршрута среди сопоставимых тарифных классов. Ниже 1,00 — маршрут обычно дешевле медианы; выше 1,00 — дороже.
```

Do not include `0,8`, `1,3`, `сильная связка`, `слабая связка` as hard labels in this PR.

- [ ] **Step 3: Planned-route detail renders four distinct rows**

For a non-local leg show:

```text
Фактический поток      63%        # informational historical evidence if present
Индекс маршрута        0,72       # pair topology
Тариф этого SKU        51 ₽       # concrete direct route price
Capacity origin        240 шт.     # physical restriction evidence
```

Capacity value must come from backend planning evidence/snapshot. If PR-D exposes capacity only in basis SKU-origin rows, join it by SKU+origin; do not derive it in frontend.

- [ ] **Step 4: Show index quality without crowding primary row**

Under `Индекс маршрута` or in a native `<details>` evidence block:

```text
Покрытие классов: 97%
Разброс IQR: 0,08
```

These values explain reliability; they do not block UI display when low.

- [ ] **Step 5: History route detail may also show the pair-level RouteCostIndex**

When viewing historical `Екатеринбург → Пермь`, join pair index from `planning_basis.route_cost_indices` and render it next to observed/clean share, explicitly labeled `Структура текущей тарифной матрицы`. Do not reinterpret historical share as planned quantity.

- [ ] **Step 6: LOCAL route presentation**

For local legs show `Локальное размещение`; omit external RouteCostIndex and non-local direct tariff rows rather than showing fake zeros.

- [ ] **Step 7: Run route-evidence tests**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_plan_view.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/assets/js/core.js frontend/assets/js/flow.js frontend/assets/js/app.js tests/frontend
git commit -m "feat: explain planned route evidence"
```

---

### Task 8: Update UX contract for durable behavior

**Files:**
- Modify: `UX-CONTRACT.md`

- [ ] **Step 1: Add selected-network state contract**

Document exactly:

```text
applied network = network of visible successful PlanningSnapshot
draft network = current checkbox edit
checkbox change = no request
dirty draft = visible stale-plan notice
Пересчитать план = only commit action
successful request = draft becomes applied
failed request = applied plan stays visible, draft preserved
```

- [ ] **Step 2: Add request-depth contract**

```text
network-only dirty -> /api/replan
upstream dirty -> full /api/analysis including current network draft
```

- [ ] **Step 3: Add Flow evidence taxonomy**

```text
History: Observed / Clean
Planned Placement: final planned coverage legs
RouteCostIndex: tariff-topology evidence
Direct tariff: concrete SKU route cost
Capacity: physical placement evidence
```

Explicitly state these must not be collapsed into one “route score”.

- [ ] **Step 4: Confirm DESIGN.md needs no change**

Do not edit `DESIGN.md` unless implementation introduced a new durable visual token. Expected outcome for this plan: no DESIGN.md diff.

- [ ] **Step 5: Commit**

```bash
git add UX-CONTRACT.md
git commit -m "docs: define selected network UI workflow"
```

---

### Task 9: Frontend production verification

**Files:** no new production files

- [ ] **Step 1: Run frontend tests**

```bash
python -m pytest tests/frontend -q
```

Expected: PASS.

- [ ] **Step 2: Run API acceptance with planning wire**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_replan.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Static anti-pattern scan**

Run:

```bash
python - <<'PY'
from pathlib import Path
paths = [Path('frontend/assets/js/app.js'), Path('frontend/assets/js/core.js'), Path('frontend/assets/js/flow.js')]
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

Use the repository’s normal local launch and verify all states in one real browser session:

1. initial Plan with persisted/default applied network;
2. open network editor by keyboard;
3. search and clear search;
4. toggle several clusters — no request occurs and stale-plan notice appears;
5. press `Пересчитать план` — network-only request updates plan once;
6. change horizon plus network — one full analysis applies both;
7. force/observe failed replan — old plan remains and draft is preserved;
8. inspect physical `Куда поставить` roll-up;
9. inspect destination drawer with three gap causes;
10. switch `Потоки спроса → История` and verify existing behavior;
11. switch `План размещения` and inspect a non-local route with Flow %, RouteCostIndex, direct tariff and capacity;
12. inspect LOCAL route and verify no fake external index/tariff;
13. repeat at a narrow viewport and 200% browser zoom; no primary action becomes inaccessible;
14. keyboard Tab/Shift+Tab reaches all network controls with visible focus.

- [ ] **Step 6: Commit any verification-driven corrections**

```bash
git add frontend UX-CONTRACT.md tests
if ! git diff --cached --quiet; then git commit -m "fix: harden selected network product workflow"; fi
```

---

## PR-E Acceptance Gate

PR-E is complete only when all are true:

1. Network checkboxes are draft-only and never auto-request.
2. One explicit `Пересчитать план` applies the network.
3. Network-only changes use `/api/replan`; upstream changes use full analysis.
4. Failed recalculation leaves prior applied plan visible and draft intact.
5. PlanningSnapshot, not legacy plan fields, owns displayed Safe/Calculated plan quantities.
6. Destination demand identity remains visible and separate from physical origin roll-up.
7. `Куда поставить` is backend roll-up data, not a frontend aggregation formula.
8. `network_uncovered`, `allocation_blocked`, `stock_uncovered` are visibly distinct.
9. Flow screen has `История | План размещения`; planned mode is not an evidence-source toggle.
10. Historical Flow %, RouteCostIndex, direct SKU tariff and capacity are separately labeled.
11. RouteCostIndex is numeric with coverage/IQR context and no invented 0.8/1.3 hard bands.
12. LOCAL routes do not show fake external index/tariff values.
13. Current History/Flow behavior is regression-green.
14. Search/checkbox/actions are semantic, keyboard accessible and visibly focused.
15. No new dependency, modal system, global Sankey or KPI-card mosaic is introduced.
16. `UX-CONTRACT.md` matches runtime behavior.
17. Frontend, API and full test suites are green; manual browser workflow passes success/failure/loading/narrow/keyboard states.
