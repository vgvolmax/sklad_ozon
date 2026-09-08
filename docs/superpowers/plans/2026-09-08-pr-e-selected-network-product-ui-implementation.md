# PR-E Selected Supply Network Product UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the product UI to the authoritative PlanningSnapshot model, add the draft/applied supply-network workflow with explicit `Пересчитать план`, expose a physical origin supply roll-up, and add a bounded planned-placement Flow view without changing historical Flow semantics.

**Architecture:** Preserve the current vanilla-JS product shell and established dense logistics-console visual language. Keep `state.snapshot` as the immutable AnalysisSnapshot for upstream evidence during migration, add one independent `planningSnapshot`, and add a dedicated supply-network state object whose checkbox edits are draft-only. The single recalculation button chooses full analysis when upstream inputs are dirty and `/api/replan` when only the network is dirty. Add only backend-owned UI presentation aggregates that are missing from PR-D; frontend may filter/sort those aggregates but must not calculate demand, coverage quantities, economics or roll-up totals.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, existing `SkladOzon` shared owners, FastAPI presentation contracts, pytest frontend/static/browser tests, Node syntax checks; Frontend Design + Frontend Design Premium; no npm/framework/build system.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Before implementation, load and follow both installed `frontend-design` and `frontend-design-premium` skills, then read `DESIGN.md`, `UX-CONTRACT.md`, the 2026-09-08 spec and the current sibling Plan/Flow implementation.
- Run Frontend Design Premium Canonical UI Resolution Gate before creating UI. Reuse `SkladOzon.SearchField`, `FormState`, `Notice`, `ProgressPanel`, `FlowView`, `DetailDrawer` and shared styles; add exactly one shared `SkladOzon.SupplyNetworkSelector` owner.
- Do not introduce a new visual identity or unrelated DESIGN token changes.
- Checkbox edits are draft only and issue no network request.
- The only apply action is the existing `Пересчитать план`; do not add `Применить сеть`.
- Previous successful plan remains visible while full analysis/replan is pending or fails.
- Full analysis is used when any upstream source/scenario input is dirty; `/api/replan` is used only when the active AnalysisSnapshot is current and only network selection is dirty.
- A PlanningSnapshot response is applied only if its `analysis_snapshot_id` still equals the active AnalysisSnapshot ID and the request sequence is current.
- On success, applied network and draft network become the same. On failure, previous applied PlanningSnapshot remains and draft edits stay available for retry.
- Destination table remains `Ozon → Наша потребность → План`; `План` is destination covered quantity, not physical inbound into that destination cluster.
- Calculated Plan is the primary `Наш план`; Safe is a separate conservative comparison.
- Physical roll-up is origin-oriented and backend-owned.
- Historical Flow stays `История → Наблюдаемое | Очищенное`; planned placement is a separate top-level `План размещения` view and never a third evidence source.
- Planned Flow must remain bounded by selected context; no global Sankey/chord or route-count-dependent canvas height.
- Frontend may filter/sort already-calculated backend rows/links for presentation. It must not sum coverage/economics to create business totals.
- Accessibility target WCAG 2.2 AA: native checkboxes/buttons, visible focus, search clear control, keyboard parity, stable busy geometry, narrow-width and 200% zoom operability.
- No `alert()`, `confirm()`, `prompt()`, framework, npm, TypeScript, bundler or new runtime dependency.

---

## File Structure

Backend presentation support, only where required to keep formulas out of JavaScript:
- Modify `backend/decision/contracts.py` — add cluster-level origin roll-up and aggregate planned-flow link contracts to PlanFamilySnapshot.
- Modify `backend/decision/planning.py` — build exact backend-owned cluster totals and origin→destination planned-flow aggregates from final coverage legs.
- Modify `tests/api/test_replan.py` — prove aggregate totals equal final coverage legs and remain bounded by cluster-pair identity.

Frontend:
- Modify `frontend/index.html` — script hook/order only if a new pure planning module is introduced; otherwise preserve shell.
- Modify `frontend/assets/js/core.js` — AnalysisSnapshot/PlanningSnapshot/supply-network state, dirty-state and request-body helpers.
- Modify `frontend/assets/js/components.js` — canonical `SkladOzon.SupplyNetworkSelector`.
- Create `frontend/assets/js/planning.js` — pure presentation selectors for authoritative PlanningSnapshot rows/links; no business arithmetic.
- Modify `frontend/assets/js/app.js` — full-vs-replan orchestration, Plan rendering, physical roll-up, destination explanations.
- Modify `frontend/assets/js/flow.js` — `История | План размещения` state/rendering while preserving historical functions.
- Modify `frontend/assets/css/app.css` — only component/layout states required for selector, roll-up and planned-flow distinction using existing tokens.
- Modify `tests/frontend/test_ui_state.py` — network draft/applied/stale semantics.
- Modify `tests/frontend/test_analysis_submit.py` — request routing/full-vs-replan behavior.
- Modify `tests/frontend/test_plan_view.py` — selector, covered destination values, physical roll-up and uncovered copy.
- Modify `tests/frontend/test_flow_view.py` — history/planning semantic separation.
- Modify `tests/frontend/test_flow_real_scale.py` — bounded planned-flow real-scale acceptance.
- Modify `tests/frontend/test_product_shell.py` only for new script/owner wiring.

`DESIGN.md` must not change unless implementation requires a genuinely new durable visual-system rule. `UX-CONTRACT.md` already contains the approved behavior and should change only if implementation discovers an authoritative conflict that must be resolved in the same PR.

---

### Task 1: Add backend-owned cluster roll-up and planned-flow presentation aggregates

**Files:**
- Modify: `backend/decision/contracts.py`
- Modify: `backend/decision/planning.py`
- Modify: `tests/api/test_replan.py`

**Interfaces:**

Add presentation contracts:

```python
@dataclass(frozen=True, slots=True)
class PlannedFlowSkuBreakdown:
    sku: str
    article: str
    product_name: str
    quantity: int


@dataclass(frozen=True, slots=True)
class PlannedFlowLink:
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    coverage_type: CoverageType
    sku_breakdown: tuple[PlannedFlowSkuBreakdown, ...]


@dataclass(frozen=True, slots=True)
class OriginClusterSupplySummary:
    origin_cluster_id: str
    total_qty: int
    own_destination_qty: int
    other_destination_qty: int
    sku_count: int
    destination_count: int
```

Extend `PlanFamilySnapshot` with:

```python
origin_cluster_summaries: tuple[OriginClusterSupplySummary, ...]
planned_flow_links: tuple[PlannedFlowLink, ...]
```

`OriginSupplyRow` from PR-D remains the SKU-level drill-down; the new summaries are cluster-level presentation aggregates.

- [ ] **Step 1: Write failing cluster-rollup tests**

```python
def test_origin_cluster_summary_is_backend_owned_and_exact():
    planning = build_fixture_planning_snapshot(
        legs=(
            final_leg("SKU-1", "Москва", "Москва", 50),
            final_leg("SKU-1", "Москва", "Казань", 20),
            final_leg("SKU-2", "Москва", "Тверь", 30),
        )
    )
    row = planning.calculated.origin_cluster_summaries[0]
    assert row.origin_cluster_id == "Москва"
    assert row.total_qty == 100
    assert row.own_destination_qty == 50
    assert row.other_destination_qty == 50
    assert row.sku_count == 2
```

- [ ] **Step 2: Write failing planned-link aggregation test**

```python
def test_planned_flow_link_aggregates_skus_by_exact_cluster_pair():
    planning = build_fixture_planning_snapshot(...)
    link = find_planned_link(planning.calculated, "Москва", "Казань")
    assert link.quantity == sum(x.quantity for x in link.sku_breakdown)
    assert {(x.sku, x.quantity) for x in link.sku_breakdown} == {
        ("SKU-1", 20),
        ("SKU-2", 10),
    }
```

One aggregate row exists per exact origin→destination cluster pair; `Прочие` is never created in backend business data.

- [ ] **Step 3: Run focused backend tests and verify RED**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: new fields/contracts absent.

- [ ] **Step 4: Build aggregates only from final allocated coverage legs**

In `backend/decision/planning.py`, after final legs are built:

```python
# group by exact cluster pair for planned_flow_links
# group by origin_cluster_id for origin_cluster_summaries
```

Use backend `Decimal`/integer exact values already calculated; do not recalculate route preference or allocation.

For a pair where `origin == destination`, `coverage_type=LOCAL`; otherwise `ROUTE`. A pair cannot mix those by identity.

Stable-sort SKU breakdown by `(article or sku, sku)` and links by `(origin_cluster_id, destination_cluster_id)`.

- [ ] **Step 5: Add aggregate integrity assertions**

```python
assert sum(x.total_qty for x in origin_cluster_summaries) == total_covered_qty
assert sum(x.quantity for x in planned_flow_links) == total_covered_qty
assert all(link.quantity == sum(x.quantity for x in link.sku_breakdown)
           for link in planned_flow_links)
```

- [ ] **Step 6: Run focused tests and verify GREEN**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit backend presentation slice**

```bash
git add backend/decision/contracts.py backend/decision/planning.py tests/api/test_replan.py
git commit -m "feat: expose planning presentation aggregates"
```

---

### Task 2: Introduce AnalysisSnapshot + PlanningSnapshot client state without breaking historical views

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `tests/frontend/test_ui_state.py`

**Interfaces:**

Extend initial state while keeping `snapshot` as the active AnalysisSnapshot compatibility name:

```javascript
{
  snapshot: null,
  planningSnapshot: null,
  supplyNetwork: {
    candidateIds: [],
    appliedIds: [],
    draftIds: [],
    dirty: false,
    query: '',
    open: false,
    reconciliationWarnings: []
  },
  ...existing state...
}
```

Add pure helpers:

```javascript
S.installAnalysisAndPlanning(state, analysisSnapshot, planningSnapshot)
S.setSupplyNetworkDraft(state, clusterId, checked)
S.setSupplyNetworkQuery(state, query)
S.toggleSupplyNetworkEditor(state, open)
S.isUpstreamDirty(state)
S.isPlanDirty(state)
S.canNetworkOnlyReplan(state)
S.applyPlanningSnapshot(state, planningSnapshot)
S.buildReplanRequest(state)
```

- [ ] **Step 1: Write failing install-state test**

```python
def test_full_result_installs_applied_and_draft_network(js_runner):
    state = call_js("installAnalysisAndPlanning", initial_state, analysis, planning)
    assert state["snapshot"]["snapshot_id"] == analysis["snapshot_id"]
    assert state["planningSnapshot"]["analysis_snapshot_id"] == analysis["snapshot_id"]
    assert state["supplyNetwork"]["appliedIds"] == ["Москва", "Питер"]
    assert state["supplyNetwork"]["draftIds"] == ["Москва", "Питер"]
    assert state["supplyNetwork"]["dirty"] is False
```

Use the test harness style already present in `test_ui_state.py` rather than inventing a second JS runner.

- [ ] **Step 2: Write failing draft-only checkbox test**

```python
def test_network_toggle_changes_draft_only(js_runner):
    next_state = call_js("setSupplyNetworkDraft", applied_state, "Москва", False)
    assert next_state["supplyNetwork"]["appliedIds"] == ["Москва", "Питер"]
    assert next_state["supplyNetwork"]["draftIds"] == ["Питер"]
    assert next_state["supplyNetwork"]["dirty"] is True
    assert next_state["inputRevision"] == applied_state["inputRevision"]
```

Network edits must not increment upstream `inputRevision`.

- [ ] **Step 3: Write failing replan-eligibility tests**

```javascript
canNetworkOnlyReplan === true
```

only when:
- AnalysisSnapshot exists and is not upstream-stale;
- PlanningSnapshot references it;
- network is dirty.

If horizon/files/mappings are dirty, it must be false so the button chooses full analysis.

- [ ] **Step 4: Run UI-state tests and verify RED**

```bash
python -m pytest tests/frontend/test_ui_state.py -q
```

Expected: helpers/state absent.

- [ ] **Step 5: Implement immutable pure state helpers**

Normalize candidate/applied/draft IDs as stable unique arrays. Applying a PlanningSnapshot must verify:

```javascript
if (planningSnapshot.analysis_snapshot_id !== state.snapshot.snapshot_id) {
  return state; // stale base; caller records/ignores stale completion
}
```

On success:
- replace `planningSnapshot`;
- set applied/draft IDs from response;
- clear network dirty/query error state;
- preserve unrelated table/Flow navigation state.

- [ ] **Step 6: Build exact replan payload helper**

```javascript
S.buildReplanRequest = state => ({
  api_version: 1,
  analysis_snapshot_id: state.snapshot.snapshot_id,
  planning_basis: state.snapshot.planning_basis,
  selected_supply_cluster_ids: [...state.supplyNetwork.draftIds]
});
```

No frontend business calculations.

- [ ] **Step 7: Run UI-state tests and verify GREEN**

```bash
python -m pytest tests/frontend/test_ui_state.py -q
node --check frontend/assets/js/core.js
```

Expected: PASS / exit 0.

- [ ] **Step 8: Commit state slice**

```bash
git add frontend/assets/js/core.js tests/frontend/test_ui_state.py
git commit -m "feat: model applied and draft supply network state"
```

---

### Task 3: Create the canonical SupplyNetworkSelector shared owner

**Files:**
- Modify: `frontend/assets/js/components.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_product_shell.py`
- Modify: `tests/frontend/test_plan_view.py`

**Interfaces:**

```javascript
S.SupplyNetworkSelector.render(container, {
  candidateIds,
  appliedIds,
  draftIds,
  query,
  open,
  disabled,
  reconciliationWarnings,
  onToggleOpen,
  onQueryChange,
  onQueryClear,
  onClusterChange
});
```

- [ ] **Step 1: Run Canonical UI Resolution Gate before code**

Read completely:
- project `DESIGN.md`;
- project `UX-CONTRACT.md`;
- Frontend Design Premium `references/canonical-ui-resolution.md`;
- current `SkladOzon.SearchField`, shared button/form styles and one sibling disclosure/detail pattern.

Record privately that `SupplyNetworkSelector` is the one canonical owner; do not create equivalent checkbox markup in `app.js`.

- [ ] **Step 2: Write failing static/behavior tests**

Assert the component:
- uses a real button labelled `Изменить` / `Закрыть` according to state;
- uses `S.SearchField` or the same canonical search behavior with explicit clear;
- renders real `<input type="checkbox">` controls with associated labels;
- marks applied vs draft state in accessible text;
- shows reconciliation warnings as text;
- contains an internally bounded scroll region for a long cluster list;
- has no apply button of its own.

- [ ] **Step 3: Run focused frontend tests and verify RED**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py -q
```

Expected: owner absent.

- [ ] **Step 4: Implement shared owner in `components.js`**

Use semantic DOM. Search is local and immediate; filtering cluster labels is presentation only. Checkbox `change` calls `onClusterChange(id, checked)` and does not issue HTTP itself.

The summary format is compact:

```text
Сеть поставки
Москва · Санкт-Петербург · Екатеринбург · +1    [Изменить]
```

When open, render a search field and internally scrollable list. Candidate IDs not in applied but present in draft are visibly draft-selected; do not visually imply applied until recalculation succeeds.

- [ ] **Step 5: Add only existing-token CSS**

Add component classes for:
- compact summary row;
- editor border/surface;
- stable internal max-height/overflow;
- checkbox row hover/focus-within;
- applied/draft explanatory text;
- narrow-width stacking.

Use existing CSS custom properties; do not add a new palette/radius/shadow system.

- [ ] **Step 6: Run component/static tests and syntax check**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py -q
node --check frontend/assets/js/components.js
```

Expected: PASS.

- [ ] **Step 7: Commit selector owner**

```bash
git add frontend/assets/js/components.js frontend/assets/css/app.css tests/frontend/test_product_shell.py tests/frontend/test_plan_view.py
git commit -m "feat: add supply network selector component"
```

---

### Task 4: Route the single recalculation action to full analysis or network-only replan

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_analysis_submit.py`
- Modify: `tests/frontend/test_ui_state.py`

**Interfaces:**
- Existing `runAnalysis()` remains full-analysis path.
- Add `runReplan()` for network-only JSON path.
- One button handler chooses:

```javascript
if (S.canNetworkOnlyReplan(state)) runReplan();
else runAnalysis();
```

- [ ] **Step 1: Write failing “checkbox sends no request” test**

Simulate opening selector and toggling several clusters. Assert mocked `fetch` call count remains zero until `Пересчитать план` activation.

- [ ] **Step 2: Write failing network-only request test**

Given current AnalysisSnapshot and only network dirty:
- click `Пересчитать план`;
- assert one POST to `/api/replan`;
- assert JSON body contains current `analysis_snapshot_id`, exact `planning_basis` and draft IDs;
- assert no multipart `/api/analysis/stream` call.

- [ ] **Step 3: Write failing upstream-dirty request test**

Change horizon or source/mapping revision and network draft, then click:
- assert full analysis path is used;
- assert multipart body includes `selected_supply_cluster_ids` JSON for the same draft network;
- assert `/api/replan` is not called.

- [ ] **Step 4: Run submit/state tests and verify RED**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py -q
```

Expected: replan routing absent.

- [ ] **Step 5: Include draft network in full-analysis body when known**

Extend `S.buildAnalysisRequestBody()`:

```javascript
if (Array.isArray(supplyNetworkDraft)) {
  body.set('selected_supply_cluster_ids', JSON.stringify(supplyNetworkDraft));
}
```

On first analysis before candidate network exists, omit the field so backend first-run resolution applies.

- [ ] **Step 6: Implement `runReplan()` with stable pending state**

Use the existing global run sequence / busy mechanism rather than creating a second competing loader system. Save:

```javascript
const runId = ++runSequence;
const baseAnalysisId = state.snapshot.snapshot_id;
```

POST JSON to `/api/replan`.

On success apply only when:

```javascript
runId === runSequence &&
state.snapshot?.snapshot_id === baseAnalysisId &&
response.analysis_snapshot_id === baseAnalysisId
```

Otherwise discard as stale without overwriting state.

- [ ] **Step 7: Preserve previous plan on failure**

Do not clear `planningSnapshot` when the request starts. On failure:
- keep applied network/planning snapshot;
- keep draft network + dirty state;
- show retryable inline error;
- release busy state.

- [ ] **Step 8: Install both snapshots atomically on full-analysis success**

Parse the additive PR-D full response:
- AnalysisSnapshot remains the top-level existing payload;
- `planning_snapshot` is installed with it in one state update.

Only then sync applied/draft network and clear dirty state.

- [ ] **Step 9: Run submit/state tests and verify GREEN**

```bash
python -m pytest tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/app.js
```

Expected: PASS / exit 0.

- [ ] **Step 10: Commit orchestration slice**

```bash
git add frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_analysis_submit.py tests/frontend/test_ui_state.py
git commit -m "feat: replan only after explicit network apply"
```

---

### Task 5: Switch Plan recommendation and destination rows to PlanningSnapshot

**Files:**
- Create: `frontend/assets/js/planning.js`
- Modify: `frontend/index.html`
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `tests/frontend/test_plan_view.py`
- Modify: `tests/frontend/test_product_shell.py`

**Interfaces:**

Pure presentation helpers in `planning.js`:

```javascript
S.planFamily = (state, family='calculated') => state.planningSnapshot?.[family] || null;
S.destinationPlanKey = row => `${row.sku}\0${row.destination_cluster_id}`;
S.indexDestinationPlanRows = planningFamily => new Map(...);
S.buildOriginClusterRollupRows = planningFamily => planningFamily?.origin_cluster_summaries || [];
S.findOriginSkuRows = (planningFamily, originId) => ...; // filter only, no summing
S.findPlannedFlowLinks = (planningFamily, mode, key) => ...; // filter only
```

- [ ] **Step 1: Write failing decision-line test**

With intentionally different transitional AnalysisSnapshot totals and PlanningSnapshot totals, assert rendered `Наш план`/Safe values come from PlanningSnapshot:

```python
assert "600 шт." in plan_html_from_planning
assert legacy_analysis_plan_total not in canonical_plan_value
```

Ozon and own need remain sourced from AnalysisSnapshot.

- [ ] **Step 2: Write failing destination-row coverage test**

If AnalysisSnapshot need is Kazan=100 and PlanningSnapshot destination row says covered=70 with 30 network uncovered, assert the Plan table shows:
- `Наша потребность 100`;
- `Наш план 70`;
- explicit `Не покрыто выбранной сетью: 30` in status/detail.

Do not read transitional `DecisionRow.calculated_plan_qty` for the migrated Plan value.

- [ ] **Step 3: Run Plan tests and verify RED**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_product_shell.py -q
```

Expected: current UI still uses AnalysisSnapshot plan fields.

- [ ] **Step 4: Add `planning.js` and script order**

Load after `core.js`/`components.js` and before `app.js`; preserve existing Flow module order dependencies. Add Node syntax check to CI-compatible verification commands in this plan, but do not introduce a build step.

- [ ] **Step 5: Update decision line model**

Refactor `S.buildDecisionLineModel` to accept both snapshots:

```javascript
S.buildDecisionLineModel = function(analysis, planning) {
  return {
    steps: [
      {label:'Ozon', value:analysis.summary.total_ozon_recommended_qty},
      {label:'Наша потребность', value:analysis.summary.total_calculated_need_qty},
      {label:'Наш план', value:planning.calculated.total_covered_qty}
    ],
    safe: {label:'Safe Plan', value:planning.safe.total_covered_qty},
    ...
  };
};
```

- [ ] **Step 6: Join destination presentation by identity, not by row order**

`buildPlanRows` keeps AnalysisSnapshot demand/need/evidence and attaches backend PlanningSnapshot destination row by `(sku, destination_cluster_id)`.

Frontend may join identities and select fields; it must not recompute covered/uncovered quantities.

Status vocabulary:
- network > 0 → `Не покрыто выбранной сетью`;
- allocation_blocked > 0 → `Заблокировано правилами расчёта`;
- stock > 0 → `Не хватило доступного товара`.

Multiple causes may appear together with exact quantities.

- [ ] **Step 7: Update drawer `Решение` section**

Add backend-provided origin composition for the destination:

```text
Где лежит запас:
Москва 70
Питер 30
```

Use `DestinationPlanRow.origins`; do not derive by summing final legs in JS.

- [ ] **Step 8: Run Plan tests and syntax checks**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_product_shell.py -q
node --check frontend/assets/js/planning.js
node --check frontend/assets/js/core.js
node --check frontend/assets/js/app.js
```

Expected: PASS / exit 0.

- [ ] **Step 9: Commit Plan migration slice**

```bash
git add frontend/index.html frontend/assets/js/planning.js frontend/assets/js/core.js frontend/assets/js/app.js tests/frontend/test_plan_view.py tests/frontend/test_product_shell.py
git commit -m "feat: render authoritative planning snapshot"
```

---

### Task 6: Add physical origin supply roll-up to Plan

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`

**Interfaces:**
- Data source: `planningSnapshot.calculated.origin_cluster_summaries` plus existing backend SKU-level `origin_rows` for drill-down.

- [ ] **Step 1: Write failing roll-up test**

```python
def test_plan_renders_physical_origin_rollup_from_backend_snapshot(...):
    html = render_plan_with(
        origin_summary={
            "origin_cluster_id": "Москва",
            "total_qty": 600,
            "own_destination_qty": 500,
            "other_destination_qty": 100,
        }
    )
    assert "Москва" in html
    assert "600" in html
    assert "свой спрос" in html
    assert "другие кластеры" in html
```

- [ ] **Step 2: Run focused Plan test and verify RED**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

Expected: roll-up absent.

- [ ] **Step 3: Render a bounded origin summary list**

Add a Plan panel after the main recommendation and before/alongside the destination table:

```text
ПЛАН ПОСТАВКИ
Москва — 600 шт.
  свой спрос 500
  другие кластеры 100
```

Use backend totals verbatim. Default sort is descending `total_qty`, stable by cluster ID; sorting presentation rows is allowed.

Do not render every SKU/destination nested by default. On selecting/expanding one origin, show its backend `origin_rows`/destination breakdown in a bounded detail area or existing drawer pattern.

- [ ] **Step 4: Keep Safe separate**

Calculated roll-up is primary. Safe may be exposed as a labelled comparison control/detail, but never added to Calculated totals.

- [ ] **Step 5: Add responsive layout using current tokens**

At narrow width stack origin summary → detail; no fixed viewport height on shared shell. Internal long detail list may own scroll with visible scrollbar.

- [ ] **Step 6: Run Plan tests and syntax check**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
node --check frontend/assets/js/app.js
```

Expected: PASS / exit 0.

- [ ] **Step 7: Commit physical roll-up slice**

```bash
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py
git commit -m "feat: show physical origin supply plan"
```

---

### Task 7: Separate historical Flow from planned placement Flow

**Files:**
- Modify: `frontend/assets/js/core.js`
- Modify: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/planning.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_flow_view.py`
- Modify: `tests/frontend/test_flow_real_scale.py`

**Interfaces:**

Extend Flow state:

```javascript
flowView: {
  view: 'history',       // 'history' | 'planning'
  mode: 'destination',  // destination | origin; historical keeps existing sku mode
  evidence: 'clean',    // history only
  ...existing fields...
}
```

- [ ] **Step 1: Write failing semantic-separation test**

Assert top-level controls are exactly:

```text
История | План размещения
```

and `Наблюдаемое | Очищенное` appears only when `view === 'history'`.

Planned view must not label itself observed/clean evidence.

- [ ] **Step 2: Write failing planned destination-context test**

Given backend planned links:
- Moscow→Kazan 70;
- Peter→Kazan 30;

Select destination Kazan and assert both incoming links are shown with exact quantities and wording that they are planned placement, not historical fulfillment.

- [ ] **Step 3: Write failing planned origin-context test**

Select Moscow and assert destinations it is planned to serve are shown. Route detail uses backend `sku_breakdown`, not historical route opportunity fields.

- [ ] **Step 4: Write real-scale bounded test**

Build a PlanningSnapshot fixture with many cluster-pair links and assert:
- only selected context is rendered;
- major overview is bounded (default Top 8 exact links + presentation-only `Прочие` row if useful);
- canvas/SVG height does not scale as `link_count × constant`;
- exact full selected-context list remains searchable/paged or internally bounded according to existing Flow grammar;
- `Прочие` is never a selectable business route or economics entity.

- [ ] **Step 5: Run Flow tests and verify RED**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
```

Expected: planning view absent.

- [ ] **Step 6: Preserve historical path byte-for-behavior where possible**

Do not rewrite stockout timeline, observed/clean route selection or historical SKU breakdown. Add a higher-level dispatcher:

```javascript
if (state.flowView.view === 'planning') {
  renderPlanningFlow(...);
} else {
  renderHistoricalFlow(...);
}
```

- [ ] **Step 7: Implement planned selected-context filtering over backend aggregate links**

Use `planningSnapshot.calculated.planned_flow_links`. Frontend may:
- filter by exact origin/destination;
- sort by backend `quantity`;
- take top 8 for overview;
- group the remainder visually as `Прочие` by summing only for presentation if and only if the existing Flow component already owns presentation-only Top-N grouping. If grouping would require a new business-looking total path, instead show `+ N других связок` without inventing a fake route.

Do not calculate route fees, margins or allocation in JS.

- [ ] **Step 8: Planned route detail uses exact backend breakdown**

For selected planned link show:
- origin → destination;
- planned quantity;
- LOCAL/ROUTE type;
- SKU breakdown from `PlannedFlowSkuBreakdown`.

If direct tariff/economics detail is needed and not yet present in aggregate contract, open/lookup the exact final coverage-leg detail supplied by PlanningSnapshot rather than deriving it from historical Flow.

- [ ] **Step 9: Run Flow tests and syntax checks**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py -q
node --check frontend/assets/js/planning.js
node --check frontend/assets/js/flow.js
```

Expected: PASS / exit 0.

- [ ] **Step 10: Commit planned Flow slice**

```bash
git add frontend/assets/js/core.js frontend/assets/js/flow.js frontend/assets/js/planning.js frontend/assets/css/app.css tests/frontend/test_flow_view.py tests/frontend/test_flow_real_scale.py
git commit -m "feat: add planned placement flow view"
```

---

### Task 8: Integrate network selector into Plan scenario workflow and recovery states

**Files:**
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/frontend/test_plan_view.py`
- Modify: `tests/frontend/test_analysis_submit.py`

**Interfaces:**
- One `SupplyNetworkSelector` instance in the Plan scenario area.
- Dirty copy:

```text
Сеть поставки изменена. План ниже рассчитан для предыдущей сети.
```

- [ ] **Step 1: Write failing dirty-copy/applied-summary test**

After toggling a checkbox:
- summary still identifies previous applied network;
- checkbox list shows draft selection;
- dirty copy is visible;
- `Пересчитать план` stays the only apply action.

- [ ] **Step 2: Write failing failure-recovery test**

Simulate `/api/replan` failure and assert:
- old PlanningSnapshot values remain rendered;
- applied network remains old;
- draft remains changed;
- dirty copy remains;
- retry button is still `Пересчитать план`.

- [ ] **Step 3: Write failing successful-apply test**

On replan success:
- new PlanningSnapshot replaces old;
- applied IDs become response IDs;
- draft syncs to applied;
- dirty copy disappears;
- selector summary updates atomically with plan.

- [ ] **Step 4: Run Plan/submit tests and verify RED**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_analysis_submit.py -q
```

Expected: selector not yet wired into scenario UI.

- [ ] **Step 5: Render selector from canonical component owner**

`app.js` passes callbacks only; it must not hand-build checkbox rows. Network search/toggle updates state locally and rerenders without HTTP.

Disable the recalculation action while a request is active, but keep the selector content/old plan geometry stable. Do not clear old results.

- [ ] **Step 6: Surface reconciliation warnings near network context**

Show backend warnings persistently until the next successful calculation/reconciliation. Do not expose raw technical code as primary copy.

- [ ] **Step 7: Run recovery tests and syntax check**

```bash
python -m pytest tests/frontend/test_plan_view.py tests/frontend/test_analysis_submit.py -q
node --check frontend/assets/js/app.js
```

Expected: PASS / exit 0.

- [ ] **Step 8: Commit workflow integration**

```bash
git add frontend/assets/js/app.js frontend/assets/css/app.css tests/frontend/test_plan_view.py tests/frontend/test_analysis_submit.py
git commit -m "feat: integrate selected supply network workflow"
```

---

### Task 9: Accessibility, narrow viewport and Frontend Design Premium verification

**Files:**
- Modify only files with verified findings from this task.
- Test: frontend tests affected by fixes.

- [ ] **Step 1: Read Premium verification references before declaring done**

Read:
- Frontend Design Premium `references/verification-checklist.md`;
- `references/anti-patterns.md`;
- `references/async-resilience.md`;
- `references/interaction-contract.md`;
- project `DESIGN.md` and `UX-CONTRACT.md` again after implementation.

- [ ] **Step 2: Run full frontend/backend test suite**

```bash
python -m pytest -q
```

Expected: 0 failures.

- [ ] **Step 3: Run JavaScript syntax checks including the new module**

```bash
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/planning.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: all exit 0.

- [ ] **Step 4: Run Frontend Design Premium strict static audit**

Resolve the installed Frontend Design Premium skill directory with the environment's native Skill mechanism, then execute its bundled command:

```bash
python scripts/audit_project.py <repository-root> --mode strict
```

from that resolved skill directory, passing this repository root as the positional project argument. Keep the JSON output as verification evidence and fix every blocking finding. If the skill runtime cannot expose the bundled script path, record that exact tooling limitation and still complete all project-owned checks; do not claim the Premium static audit ran.

- [ ] **Step 5: Search changed frontend code for prohibited patterns**

At repository root run:

```bash
python - <<'PY'
from pathlib import Path
files = [
    Path('frontend/assets/js/core.js'),
    Path('frontend/assets/js/components.js'),
    Path('frontend/assets/js/planning.js'),
    Path('frontend/assets/js/flow.js'),
    Path('frontend/assets/js/app.js'),
]
patterns = ['alert(', 'confirm(', 'prompt(', 'onclick="', 'javascript:']
for path in files:
    text = path.read_text(encoding='utf-8')
    for pattern in patterns:
        if pattern in text:
            print(f'{path}: found prohibited/suspicious {pattern!r}')
PY
```

Expected: no output. Then run the broader grep/checks required by Premium `anti-patterns.md`; fix every true violation.

- [ ] **Step 6: Real-browser interaction acceptance**

Using the repository's available browser acceptance mechanism, exercise at least:
- first full analysis with default network;
- open selector, search, clear search, keyboard through checkboxes;
- toggle multiple clusters and verify no request before button;
- successful network-only replan;
- failed replan with old plan + draft preserved;
- horizon + network dirty causing full analysis;
- destination row showing origin composition;
- physical origin roll-up drill-down;
- `История` historical Flow unchanged;
- `План размещения` destination/origin context;
- one empty-network plan showing network-uncovered rather than auto-selecting all;
- one normal desktop width;
- one narrow viewport;
- 200% zoom;
- reduced-motion mode;
- visible keyboard focus throughout.

- [ ] **Step 7: Verify layout stability**

During pending/error/success transitions:
- primary button dimensions remain stable;
- previous plan does not disappear;
- scrollbar presence does not cause horizontal jump;
- selector internal scroll does not lock page scroll;
- no shared page/root `100vh`/`overflow:hidden` workaround is introduced.

- [ ] **Step 8: Reconcile DESIGN/UX docs only if implementation changed durable rules**

If implementation followed the already-approved contracts exactly, do not edit `DESIGN.md`/`UX-CONTRACT.md` merely to create churn. If a genuine new shared visual/behavioral decision was required, update the owning document and runtime component in the same commit, then rerun Premium audit/tests.

- [ ] **Step 9: Commit verification fixes only after fresh green evidence**

```bash
git add frontend backend tests DESIGN.md UX-CONTRACT.md
git commit -m "test: verify selected network product workflow"
```

Only stage files actually changed; do not create empty doc edits.

---

## PR-E Acceptance Gate

Before opening PR-E, verify from fresh output:

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/planning.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

And complete the Frontend Design Premium strict audit + browser matrix above when the skill/browser runtime is available.

Required product proofs:

- Plan uses AnalysisSnapshot for upstream demand/evidence and authoritative PlanningSnapshot for plan quantities.
- SupplyNetworkSelector has one canonical shared owner and real accessible checkboxes/search.
- Checkbox edits issue zero network requests and alter draft only.
- `Пересчитать план` calls `/api/replan` only for network-only dirty state; upstream dirty state performs full analysis with the same draft network.
- Failed replan leaves previous PlanningSnapshot/applied network visible and preserves draft for retry.
- Stale PlanningSnapshot response cannot attach to a newer active AnalysisSnapshot.
- Successful replan atomically updates plan + applied network.
- Decision line remains `Ozon → Наша потребность → План` with Calculated as primary and Safe separate.
- Destination row plan quantity is final covered destination target, not physical inbound into that destination.
- Three unmet causes have distinct user-facing wording and quantities.
- Physical origin roll-up comes from backend cluster summaries, not JS summation.
- Historical Flow remains historical and observed/clean semantics are unchanged.
- Planned placement is a separate Flow view and remains selected-context/bounded at realistic cardinality.
- No global Sankey/chord, no unbounded route-height growth, no fake `Прочие` business route.
- Keyboard, focus, narrow viewport, 200% zoom, reduced motion and stable loading/error geometry pass.
- No business formulas, route affinity, coverage allocation or unit economics are calculated in frontend JavaScript.
