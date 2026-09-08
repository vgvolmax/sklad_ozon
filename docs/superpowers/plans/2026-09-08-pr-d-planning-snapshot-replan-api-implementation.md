# PR-D Planning Basis, Planning Snapshot, Persistence & Replan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR-A/B/C into the application without disturbing upstream demand/history semantics: full analysis produces an immutable `PlanningBasis` and authoritative `PlanningSnapshot`, persists the successfully applied supply network, and a stateless `/api/replan` recalculates only coverage/allocation when the network alone changes.

**Architecture:** `AnalysisSnapshot` remains the immutable upstream evidence product. Add two nested immutable planning objects at its boundary: `PlanningBasis` contains all backend-resolved downstream inputs required for a network-only replan, while `PlanningSnapshot` contains one applied-network result. Full analysis precomputes direct route quotes/economics for the current SKU universe and computes the SKU-independent `RouteCostIndex` once from the raw normalized Ozon tariff matrix. Replan consumes those already-resolved inputs; it does not rerun ingestion, demand, stockout, historical route analysis or tariff normalization.

**Tech Stack:** Python 3, FastAPI, frozen dataclasses, JSON wire serialization, Project JSON schema migration, pytest; PR-A/B/C contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** The raw Ozon customer-delivery tariff matrix remains the source of both direct quotes and `RouteCostIndex`. Cross-docking tariffs are outside this pipeline. `RouteCostIndex` is stored once per route pair in planning evidence, not duplicated as a SKU matrix. Direct SKU economics still uses exact matched route fees.

## Global Constraints

- Network selection remains downstream of `Calculated Need`; it cannot change demand history, stockout episodes, clean routes, `DemandEstimate` or `NeedComparison`.
- Current `AnalysisSnapshot` evidence fields stay immutable and backwards-readable in this PR.
- `PlanningSnapshot` is authoritative for the new physical plan; legacy `DecisionRow.safe_plan_qty/calculated_plan_qty` remain transitional until PR-E switches UI ownership.
- `PlanningBasis` must contain backend-resolved data only; frontend never computes route fees, route indices, capacities, economics, coverage or allocation.
- Seller stock in `PlanningBasis` comes from the exact current `application.py` seller-stock resolution (FBS/operational/product fallback + conflict handling), not from a second Project JSON lookup.
- Missing/conflicting seller stock remains unknown/blocked; it is never coerced to zero.
- Route indices are computed once per full tariff dataset and keyed only by route pair.
- Direct route evidence/economics is precomputed for the current SKU × feasible-origin × destination candidate universe so `/api/replan` does not repeat tariff/economics work.
- Project persistence distinguishes `None = no network has ever been successfully applied` from `() = user successfully applied an empty network`.
- First-use default selects all current candidate clusters with at least one explicitly allowed SKU. Newly appearing clusters after persistence default unselected.
- Draft network is persisted only after successful full analysis/replan.
- Failed calculation preserves the prior applied network.
- Network-only replan must not call ingestion, demand, stockout, clean-route or historical route-analysis functions.
- Existing `/api/analysis` and `/api/analysis/stream` remain usable by current frontend before PR-E.
- No new server/session state is introduced; the replan boundary is stateless apart from the existing Project persistence file.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/project.py` — Project JSON v2 migration + `applied_supply_network` persistence.
- Modify `backend/application.py` — expose resolved seller stock, build planning candidate evidence after upstream analysis, and call planning orchestration.
- Modify `backend/decision/contracts.py` — `PlanningBasis`, `PlanningSnapshot`, route/capacity/target evidence and roll-up contracts; append optional planning fields to `AnalysisSnapshot` for transitional wire compatibility.
- Create `backend/decision/planning.py` — build planning basis, reconcile/default network, execute both plan families, assemble destination/origin views.
- Modify `backend/decision/snapshot.py` — attach nested planning objects without changing legacy decision-row calculations yet.
- Modify `backend/decision/__init__.py` — export planning contracts/functions.
- Modify `backend/api.py` — optional network field on full analysis; JSON `/api/replan`; persist applied network only after success.
- Modify `tests/test_project.py` or the repository’s existing project-persistence test file — v1→v2 migration and empty-vs-null network semantics.
- Modify `tests/application/test_application.py` or existing application tests — resolved seller-stock export and planning-basis construction.
- Create/modify `tests/decision/test_planning.py` — network reconciliation, plan-family targets, route-index reuse, roll-ups, conservation.
- Modify `tests/api/test_analysis.py` — transitional nested planning response and selected-network full-analysis behavior.
- Create `tests/api/test_replan.py` — network-only replan behavior and persistence.
- Run `tests/api/test_product_completion_acceptance.py` unchanged as legacy-wire regression.

---

### Task 1: Migrate Project JSON to explicit applied-network persistence

**Files:**
- Modify: `backend/project.py`
- Test: existing Project persistence tests

**Contract:**

```python
SCHEMA_VERSION = 2

@dataclass(frozen=True, slots=True)
class Project:
    schema_version: int = field(default=SCHEMA_VERSION, init=False)
    tariffs: tuple[TariffRow, ...] = ()
    tariff_meta: ReportMeta | None = None
    product_economics: tuple[ProductEconomicsInput, ...] = ()
    product_economics_meta: ReportMeta | None = None
    seller_available_stock: dict[str, int] = field(default_factory=dict)
    manual_cluster_mappings: dict[str, str] = field(default_factory=dict)
    economics_settings: EconomicsSettings | None = None
    optimizer_thresholds: OptimizerThresholds | None = None
    operational_snapshots: tuple[OperationalSnapshot, ...] = ()
    applied_supply_network: tuple[str, ...] | None = None
```

- [ ] **Step 1: Add v1 migration test**

Load a valid schema-v1 JSON payload without `applied_supply_network` and assert:

```python
project.applied_supply_network is None
project.schema_version == 2
```

The in-memory object upgrades to current schema; existing business fields remain equal.

- [ ] **Step 2: Add null-vs-empty roundtrip test**

```python
assert roundtrip(Project(applied_supply_network=None)).applied_supply_network is None
assert roundtrip(Project(applied_supply_network=())).applied_supply_network == ()
```

- [ ] **Step 3: Add network validation tests**

Reject blank cluster IDs and duplicate IDs. Canonicalize a valid supplied tuple to stable lexical order before persistence or require caller-sorted input and validate exact uniqueness; choose one rule and encode it once. For this plan use canonical sorting in `Project.__post_init__`/validation:

```python
if network is not None:
    if any(not isinstance(x, str) or not x.strip() for x in network):
        raise ProjectValidationError("Supply network cluster IDs must be nonblank strings.")
    if len(network) != len(set(network)):
        raise ProjectValidationError("Supply network cluster IDs must be unique.")
```

Serializer writes `sorted(network)`.

- [ ] **Step 4: Implement versioned loader**

Define `_TOP_FIELDS_V1` as the current schema-1 set and `_TOP_FIELDS_V2 = _TOP_FIELDS_V1 | {"applied_supply_network"}`. `load_project()` accepts only versions 1 or 2:

```python
version = payload.get("schema_version")
if version == 1:
    _strict(payload, _TOP_FIELDS_V1, "project")
    raw_network = None
elif version == 2:
    _strict(payload, _TOP_FIELDS_V2, "project")
    raw_network = payload["applied_supply_network"]
else:
    raise ProjectValidationError("Missing or unsupported schema version.")
```

For v2, `raw_network` must be `null` or a JSON list of unique nonblank strings. Save always emits schema version 2.

- [ ] **Step 5: Run Project tests**

```bash
python -m pytest tests -q -k "project and not product_completion"
```

Expected: Project persistence tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/project.py tests
git commit -m "feat: persist applied supply network"
```

---

### Task 2: Expose resolved seller stock from current analysis semantics

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/decision/contracts.py`
- Test: application tests

**Contract:**

```python
@dataclass(frozen=True, slots=True)
class ResolvedSellerStock:
    sku: str
    quantity: int | None
    complete: bool
    reason_codes: tuple[str, ...]
```

Append to `AnalysisResult`:

```python
resolved_seller_stock: tuple[ResolvedSellerStock, ...] = ()
```

- [ ] **Step 1: Add characterization tests for current stock resolution**

Cover exact current branches:

```text
one positive FBS value -> quantity that value, complete
conflicting positive FBS values -> quantity None, reason CONFLICTING_FBS_AVAILABLE_STOCK
no FBS evidence + product.available_qty known + not FBS-authoritative -> product available qty
FBS-authoritative but no proven FBS qty -> quantity None
```

- [ ] **Step 2: Run baseline tests**

```bash
python -m pytest tests/application -q
```

Use the repository’s actual application-test path if named differently; the test file must directly call `analyze()` and characterize current behavior before refactor.

- [ ] **Step 3: Extract the current inline stock expression into one pure helper**

```python
def _resolve_seller_stock(
    *,
    sku: str,
    product: ProductEconomicsInput | None,
    fbs_values: set[int] | None,
    conflicting_fbs: bool,
    availability_fbs_authoritative: bool,
) -> ResolvedSellerStock:
    if conflicting_fbs:
        return ResolvedSellerStock(
            sku, None, False, ("CONFLICTING_FBS_AVAILABLE_STOCK",)
        )
    if fbs_values is not None:
        positive = {value for value in fbs_values if value > 0}
        if positive:
            return ResolvedSellerStock(sku, next(iter(positive)), True, ())
        return ResolvedSellerStock(sku, 0, True, ())
    if product is not None and not availability_fbs_authoritative:
        if product.available_qty is not None:
            return ResolvedSellerStock(sku, product.available_qty, True, ())
    return ResolvedSellerStock(
        sku, None, False, ("MISSING_SELLER_AVAILABLE_STOCK",)
    )
```

Use this same object to feed the legacy optimizer in the current code path so no stock semantics drift.

- [ ] **Step 4: Return the resolutions in `AnalysisResult`**

Sort by SKU and include every SKU considered by allocation, including incomplete values.

- [ ] **Step 5: Run application + legacy optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py tests -q -k "application or seller_stock"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/application.py backend/decision/contracts.py tests
git commit -m "refactor: expose resolved seller stock evidence"
```

---

### Task 3: Define immutable PlanningBasis and PlanningSnapshot contracts

**Files:**
- Modify: `backend/decision/contracts.py`
- Create: `tests/decision/test_planning.py`

**Core contracts:**

```python
@dataclass(frozen=True, slots=True)
class PlanningRouteCandidate:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    direct_quote: DirectRouteQuote
    direct_economics: UnitEconomicsResult
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None


@dataclass(frozen=True, slots=True)
class PlanningSkuOrigin:
    sku: str
    origin_cluster_id: str
    feasibility: SupplyFeasibility


@dataclass(frozen=True, slots=True)
class PlanningBasis:
    basis_id: str
    analysis_snapshot_id: str
    scenario: ScenarioSettings
    candidate_supply_clusters: tuple[str, ...]
    targets: tuple[DestinationTarget, ...]
    sku_origins: tuple[PlanningSkuOrigin, ...]
    route_cost_indices: tuple[RouteCostIndex, ...]
    route_candidates: tuple[PlanningRouteCandidate, ...]
    seller_stock: tuple[ResolvedSellerStock, ...]
    demand_confidence: tuple[tuple[str, str, SignalConfidence], ...]
    distortion_confidence: tuple[tuple[str, str, SignalConfidence | None], ...]
    optimizer_thresholds: OptimizerThresholds
    tariff_source_name: str
    tariff_report_generated_at: str | None


@dataclass(frozen=True, slots=True)
class DestinationPlanView:
    sku: str
    destination_cluster_id: str
    target_qty: int
    final_allocated_qty: int
    network_uncovered_qty: int
    allocation_blocked_qty: int
    stock_uncovered_qty: int
    legs: tuple[FinalCoverageLeg, ...]


@dataclass(frozen=True, slots=True)
class OriginPlanView:
    sku: str
    origin_cluster_id: str
    total_qty: int
    own_destination_qty: int
    external_destination_qty: int
    legs: tuple[FinalCoverageLeg, ...]


@dataclass(frozen=True, slots=True)
class PlanningFamilySnapshot:
    plan_family: PlanFamily
    destination_views: tuple[DestinationPlanView, ...]
    origin_views: tuple[OriginPlanView, ...]
    total_target_qty: int
    total_allocated_qty: int
    total_network_uncovered_qty: int
    total_allocation_blocked_qty: int
    total_stock_uncovered_qty: int
    expected_profit: Decimal


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    planning_snapshot_id: str
    basis_id: str
    analysis_snapshot_id: str
    created_at: str
    applied_supply_network: tuple[str, ...]
    reconciliation_warnings: tuple[str, ...]
    safe: PlanningFamilySnapshot
    calculated: PlanningFamilySnapshot
```

Append defaults to `AnalysisSnapshot`:

```python
planning_basis: PlanningBasis | None = None
planning_snapshot: PlanningSnapshot | None = None
```

- [ ] **Step 1: Add identity/conservation validation tests**

Validate unique route candidate `(sku, origin, destination)`, unique route-index pair, unique SKU-origin feasibility, nonnegative totals, and `PlanningSnapshot.basis_id == PlanningBasis.basis_id` when assembled together.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contracts absent.

- [ ] **Step 3: Implement immutable contracts**

Do not store raw tariff rows in `PlanningSnapshot`. Raw normalized tariffs remain upstream source data; basis contains only route indices and the resolved candidate quotes/economics needed for current SKU planning.

- [ ] **Step 4: Run and verify GREEN**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/decision/contracts.py tests/decision/test_planning.py
git commit -m "feat: define immutable planning snapshots"
```

---

### Task 4: Build candidate network, RouteCostIndex and planning route evidence after upstream analysis

**Files:**
- Create: `backend/decision/planning.py`
- Modify: `backend/application.py`
- Test: `tests/decision/test_planning.py`
- Test: application tests

**Interfaces:**

```python
def build_planning_basis(
    *,
    analysis_snapshot_id: str,
    scenario: ScenarioSettings,
    needs: Iterable[NeedComparison],
    demand_estimates: Iterable[DemandEstimate],
    distortions: Iterable[RecommendationDistortionSignal],
    observed_routes: RouteProfile,
    clean_routes: CleanRouteResult,
    products: Iterable[ProductEconomicsInput],
    tariffs: ImportResult[TariffRow],
    placements: Iterable[PlacementAssessment],
    resolved_seller_stock: Iterable[ResolvedSellerStock],
    optimizer_thresholds: OptimizerThresholds,
    economics_settings: EconomicsSettings,
) -> PlanningBasis:
```

- [ ] **Step 1: Add candidate-cluster test**

Candidate cluster universe equals sorted clusters where at least one `PlacementAssessment.feasibility.allowed` is true and capacity state is not UNKNOWN. A cluster may still have SKU-specific prohibitions; this is only the selector universe.

- [ ] **Step 2: Add RouteCostIndex reuse test**

Build two SKUs sharing the same `Москва → Казань` route. Assert `PlanningBasis.route_cost_indices` contains one pair-level index, while `route_candidates` contains two SKU-specific direct quotes/economics.

- [ ] **Step 3: Add target-family test**

For complete Need:

```text
Calculated target = calculated_need_qty
Safe target = min(calculated_need_qty, ozon_recommended_qty)
```

If either Safe input is missing, do not emit a Safe target for that destination; preserve incompleteness through diagnostics/absence, never coerce to zero.

- [ ] **Step 4: Implement exact-pair historical evidence projection**

For each candidate `(sku, origin, destination)`:

```text
observed_flow_qty = exact observed quantity for that SKU/pair, else 0
observed_flow_share = exact observed destination share if observed, else None
route_confidence:
  HIGH   if exact pair exists in clean route evidence
  MEDIUM if exact pair exists only in observed route evidence
  LOW    otherwise
```

No observed share enters quantities/ranking directly.

- [ ] **Step 5: Build route indices once**

Call:

```python
route_cost_indices = build_route_cost_indices(tariffs)
route_index_by_pair = {
    (x.origin_cluster_id, x.destination_cluster_id): x
    for x in route_cost_indices
}
```

Do not call this once per SKU.

- [ ] **Step 6: Precompute direct quote/economics for relevant routes**

For every product SKU with known volume and every physically feasible candidate origin and every emitted destination target, excluding local pair:

```python
quote = quote_direct_route(
    tariffs,
    origin_cluster_id=origin,
    destination_cluster_id=destination,
    volume_liters=product.volume_liters,
    price=product.price,
)
economics = calculate_direct_route_economics(
    product, origin, quote, economics_settings
)
```

Store the candidate even when quote/economics is incomplete so network gaps/blocked reasons stay explainable. LOCAL economics may reuse the exact local placement economics already produced by current application analysis; do not require a non-local RouteCostIndex.

- [ ] **Step 7: Run planning-basis tests**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/decision/planning.py backend/application.py tests
git commit -m "feat: build backend-owned planning basis"
```

---

### Task 5: Reconcile applied network and execute both planning families

**Files:**
- Modify: `backend/decision/planning.py`
- Test: `tests/decision/test_planning.py`

**Interfaces:**

```python
def reconcile_supply_network(
    candidate_clusters: Iterable[str],
    persisted_network: tuple[str, ...] | None,
    requested_network: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
```

```python
def build_planning_snapshot(
    basis: PlanningBasis,
    selected_supply_network: tuple[str, ...],
) -> PlanningSnapshot:
```

- [ ] **Step 1: Add first-use default test**

`persisted_network is None` and `requested_network is None` -> select all current candidate clusters.

- [ ] **Step 2: Add persistence reconciliation tests**

```text
persisted (Moscow, Peter), candidates (Moscow, Peter, Kazan) -> Moscow, Peter; Kazan stays unselected
persisted (Moscow, Old), candidates (Moscow, Peter) -> Moscow + warning for Old
persisted () -> effective (), never default all
explicit requested () -> effective (), valid
requested contains noncandidate cluster -> reject request with validation error; do not silently add
```

- [ ] **Step 3: Implement one-family planning helper**

For each SKU and family:

1. select that family’s targets;
2. map SKU-origin feasibility;
3. build `RoutePlanningEvidence` from precomputed quote/index/history evidence;
4. call `plan_coverage()`;
5. build `CoverageAllocationCandidate` for each desired leg using the precomputed direct/local economics and confidence inputs;
6. if seller stock is incomplete, emit allocation-blocked quantities with `MISSING_SELLER_AVAILABLE_STOCK` rather than calling allocator with zero;
7. otherwise call `allocate_coverage_legs()`;
8. assemble `DestinationPlanView` and `OriginPlanView` on backend.

- [ ] **Step 4: Add conservation tests for both families**

For each destination:

```text
allocated + network_uncovered + allocation_blocked + stock_uncovered = target
```

For each origin view:

```text
total_qty = own_destination_qty + external_destination_qty
```

Global expected profit equals sum of final-leg expected profit.

- [ ] **Step 5: Run planning tests**

```bash
python -m pytest tests/decision/test_planning.py tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build selected-network planning snapshot"
```

---

### Task 6: Attach planning objects to full analysis without breaking current UI wire

**Files:**
- Modify: `backend/decision/snapshot.py`
- Modify: `backend/decision/__init__.py`
- Modify: `backend/api.py`
- Test: `tests/api/test_analysis.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

- [ ] **Step 1: Add response-shape test**

A successful `/api/analysis` response still has current root fields (`snapshot_id`, `scenario`, `decision_rows`, `flow_view_aggregates`, etc.) and additionally:

```python
assert response["planning_basis"]["basis_id"]
assert response["planning_snapshot"]["applied_supply_network"] is not None
```

Current frontend can ignore the extra fields.

- [ ] **Step 2: Add optional full-analysis network request parsing**

Accept multipart field `selected_supply_clusters` only when present. Its value is a JSON array of unique strings:

```python
raw = form.get("selected_supply_clusters")
requested_network = None if raw is None else tuple(json.loads(str(raw)))
```

Validate JSON is a list, every item is a nonblank string, and no duplicates exist. Empty list is valid.

- [ ] **Step 3: Build planning objects after upstream `analyze()` and analysis snapshot ID creation**

Do not modify legacy `DecisionRow` assembly yet. Attach `planning_basis` and `planning_snapshot` as additional immutable fields.

- [ ] **Step 4: Persist applied network only after complete successful response assembly**

After `PlanningSnapshot` exists, update Project with:

```python
replace(project, applied_supply_network=planning_snapshot.applied_supply_network)
```

and `save_project_atomic()`. If planning throws or response returns an error, do not persist.

- [ ] **Step 5: Run API + product acceptance tests**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/snapshot.py backend/decision/__init__.py backend/api.py tests/api
git commit -m "feat: attach planning result to full analysis"
```

---

### Task 7: Add stateless `/api/replan`

**Files:**
- Modify: `backend/api.py`
- Create: `tests/api/test_replan.py`

**Request JSON:**

```json
{
  "planning_basis": {"basis_id": "...", "analysis_snapshot_id": "..."},
  "selected_supply_clusters": ["Москва", "Санкт-Петербург"]
}
```

The actual `planning_basis` object contains the complete wire representation of the contract from Task 3, not only the two identity fields shown above.

**Response:**

```json
{
  "api_version": 1,
  "kind": "planning",
  "planning_snapshot": {}
}
```

- [ ] **Step 1: Add valid network-only replan test**

Start from a real full-analysis `planning_basis`, change selected network, post to `/api/replan`, assert:

```text
basis_id unchanged
analysis_snapshot_id unchanged
planning_snapshot_id changed
applied network equals request
calculated destination targets unchanged
physical origin roll-up changed where routes require it
```

- [ ] **Step 2: Add no-upstream-recompute test**

Monkeypatch these functions to raise if called during `/api/replan`:

```text
import_availability
import_restrictions
import_orders
estimate_destination_demand
detect_stockouts
build_episode_clean_route_profile
build_route_cost_indices
quote_direct_route
```

Request must still succeed. This proves replan uses already-resolved basis data.

- [ ] **Step 3: Add invalid basis/network tests**

Reject malformed PlanningBasis wire, duplicate selected clusters and clusters outside `candidate_supply_clusters` with HTTP 400 and stable error codes:

```text
INVALID_PLANNING_BASIS
INVALID_SELECTED_SUPPLY_NETWORK
```

- [ ] **Step 4: Implement strict wire parser**

Do not pass arbitrary dictionaries into business functions. Add explicit `_planning_basis_from_wire()` validation mirroring `wire()` field names and enum/Decimal parsing. Unknown fields are rejected.

- [ ] **Step 5: Execute planning only**

```python
planning_snapshot = build_planning_snapshot(basis, selected_network)
```

No upstream analysis call exists in this endpoint.

- [ ] **Step 6: Persist only after success**

Load current Project, replace only `applied_supply_network`, save atomically, then return response. If build fails, Project remains unchanged.

- [ ] **Step 7: Run replan tests**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/api.py tests/api/test_replan.py
git commit -m "feat: replan selected supply network without reanalysis"
```

---

### Task 8: Final backend verification

**Files:** no new production files

- [ ] **Step 1: Run planning/backend focused suites**

```bash
python -m pytest tests/economics/test_tariffs.py tests/economics/test_unit.py tests/supply/test_placement.py tests/supply/test_coverage.py tests/supply/test_optimizer.py tests/decision/test_planning.py tests/api/test_analysis.py tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run legacy product acceptance**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; old UI contract still functions before PR-E.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Confirm no replan call path imports/recomputes upstream pipeline**

Search `backend/api.py` `/api/replan` path and `backend/decision/planning.py`; there must be no calls to demand/stockout/clean-route builders or tariff-index builders inside replan execution.

- [ ] **Step 5: Commit any test-only cleanup if required by the completed assertions**

```bash
git add tests
if ! git diff --cached --quiet; then git commit -m "test: verify selected-network planning boundary"; fi
```

---

## PR-D Acceptance Gate

PR-D is complete only when all are true:

1. Project v1 loads safely and saves as v2.
2. `None` and empty applied network remain semantically distinct.
3. First-use default and later reconciliation exactly follow approved rules.
4. Seller stock comes from current analysis resolution; unknown stock never becomes zero.
5. `RouteCostIndex` is built once from the full normalized customer-delivery tariff matrix, not per SKU.
6. Direct quotes/economics remain SKU-specific and exact.
7. Cross-docking tariffs never enter planning basis.
8. `PlanningBasis` contains every backend-resolved downstream input required by replan.
9. `PlanningSnapshot` owns destination coverage, origin physical roll-up and three causal gap types.
10. Full analysis can accept a selected network but still preserves all upstream analysis identities.
11. `/api/replan` does not rerun ingestion, demand, stockout, clean routes, index derivation, tariff lookup or economics.
12. Failed full analysis/replan never persists the draft network.
13. Empty selected network is valid and remains empty.
14. Current root AnalysisSnapshot wire remains compatible until PR-E.
15. Full backend suite and existing Product Completion acceptance are green.
