# PR-D Planning Basis, Planning Snapshot, Persistence & Replan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR-A/B/C into the application without disturbing upstream demand/history semantics: full analysis produces an immutable `PlanningBasis` and authoritative `PlanningSnapshot`, persists the successfully applied supply network, and a stateless `/api/replan` recalculates only coverage/allocation when the network alone changes.

**Architecture:** `AnalysisSnapshot` remains the immutable upstream evidence product. Add two nested immutable planning objects at its boundary: `PlanningBasis` contains all backend-resolved downstream inputs required for a network-only replan, while `PlanningSnapshot` contains one applied-network result. Full analysis computes the SKU-independent `RouteCostIndex` once from the normalized Ozon customer-delivery tariff matrix, then precomputes exact direct quotes/economics for the current SKU route candidate universe. Replan consumes those already-resolved inputs and never reruns ingestion, demand, stockout, historical route analysis, tariff-index normalization or direct tariff lookup.

**Tech Stack:** Python 3, FastAPI, frozen dataclasses, JSON wire serialization, Project JSON schema migration, pytest; PR-A/B/C contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** The raw Ozon customer-delivery tariff matrix is the source of both direct quotes and `RouteCostIndex`. Cross-docking tariffs are outside this pipeline. `RouteCostIndex` is stored once per route pair in planning evidence, not as a SKU matrix. Direct SKU economics still uses exact matched route fees.

## Global Constraints

- Network selection remains downstream of `Calculated Need`; it cannot change demand history, stockout episodes, clean routes, `DemandEstimate` or `NeedComparison`.
- Current `AnalysisSnapshot` evidence fields stay immutable and backwards-readable in this PR.
- `PlanningSnapshot` is authoritative for the new physical plan; legacy `DecisionRow.safe_plan_qty/calculated_plan_qty` remain transitional until PR-E switches UI ownership.
- `PlanningBasis` contains backend-resolved data only; frontend never computes route fees, route indices, capacities, economics, coverage or allocation.
- Seller stock in `PlanningBasis` comes from the exact current `application.py` seller-stock resolution, not from a second Project JSON lookup.
- Missing/conflicting seller stock remains unknown/blocked; it is never coerced to zero.
- Route indices are computed once per full tariff dataset and keyed only by route pair.
- Direct route evidence/economics is precomputed for the current `SKU × feasible origin × destination` candidate universe.
- Project persistence distinguishes `None = no network has ever been successfully applied` from `() = user successfully applied an empty network`.
- First-use default selects all current candidate clusters with at least one explicitly allowed SKU and known usable capacity evidence. Newly appearing clusters after persistence default unselected.
- Draft network is persisted only after successful full analysis/replan.
- Failed calculation preserves the prior applied network.
- Network-only replan must not call ingestion, demand, stockout, clean-route, route-index, tariff-lookup or economics functions.
- Existing `/api/analysis` and `/api/analysis/stream` remain usable by the current frontend before PR-E.
- No new server/session state is introduced; the replan boundary is stateless apart from existing Project persistence.
- Physical cluster roll-up is aggregated across SKUs on backend; per-SKU capacity evidence remains separate at `SKU × origin`.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/project.py` — Project JSON v2 migration + `applied_supply_network` persistence.
- Modify `backend/application.py` — expose resolved seller stock and provide upstream inputs for planning-basis assembly.
- Modify `backend/decision/contracts.py` — `PlanningBasis`, `PlanningSnapshot`, route/capacity/target evidence, destination views and cluster-level origin roll-ups; append optional planning fields to `AnalysisSnapshot`.
- Create `backend/decision/planning.py` — build planning basis, reconcile/default network, execute Safe/Calculated families, assemble destination and cluster-level origin views.
- Modify `backend/decision/snapshot.py` — attach nested planning objects without changing legacy decision-row calculations yet.
- Modify `backend/decision/__init__.py` — export planning contracts/functions.
- Modify `backend/api.py` — optional network field on full analysis; JSON `/api/replan`; persist applied network only after success.
- Modify `tests/test_project.py` — v1→v2 migration and null-vs-empty network semantics.
- Create `tests/test_application.py` — direct `analyze()` characterization of seller-stock resolution and planning inputs.
- Create `tests/decision/test_planning.py` — planning-basis construction, route-index reuse, network reconciliation, roll-ups and conservation.
- Modify `tests/api/test_analysis.py` — transitional nested planning response and full-analysis selected-network behavior.
- Create `tests/api/test_replan.py` — network-only replan behavior, strict wire validation and persistence.
- Run `tests/api/test_product_completion_acceptance.py` unchanged as legacy-wire regression.

---

### Task 1: Migrate Project JSON to explicit applied-network persistence

**Files:**
- Modify: `backend/project.py`
- Test: `tests/test_project.py`

**Contract:** append one field and upgrade schema:

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

- [ ] **Step 1: Add schema-v1 migration test in `tests/test_project.py`**

Start from the same valid payload used by current roundtrip tests, force:

```python
payload["schema_version"] = 1
payload.pop("applied_supply_network", None)
```

Write/load and assert:

```python
assert project.schema_version == 2
assert project.applied_supply_network is None
```

- [ ] **Step 2: Add null-vs-empty roundtrip tests**

Create two Projects using `dataclasses.replace(Project(), applied_supply_network=value)`:

```python
assert roundtrip(None).applied_supply_network is None
assert roundtrip(()).applied_supply_network == ()
assert roundtrip(("Питер", "Москва")).applied_supply_network == ("Москва", "Питер")
```

`roundtrip()` in the test writes with `save_project_atomic()` and reloads with `load_project()`.

- [ ] **Step 3: Add invalid network tests**

Assert `ProjectValidationError` for:

```python
("Москва", "Москва")
("Москва", "")
("Москва", 123)
```

- [ ] **Step 4: Implement versioned top-field validation**

```python
_TOP_FIELDS_V1 = {
    "schema_version", "tariffs", "tariff_meta", "product_economics",
    "product_economics_meta", "seller_available_stock",
    "manual_cluster_mappings", "economics_settings", "optimizer_thresholds",
    "operational_snapshots",
}
_TOP_FIELDS_V2 = _TOP_FIELDS_V1 | {"applied_supply_network"}
```

In `load_project()`:

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

For v2, accept only `None` or list[str]. Reject blanks/duplicates/nonstrings. Convert valid values to `tuple(sorted(raw_network))`. Save always writes schema 2 and `None` or `list(project.applied_supply_network)`.

- [ ] **Step 5: Update `_validate()` for schema 2 and network validation**

Do not change validation of tariffs/economics/snapshots.

- [ ] **Step 6: Run exact tests**

```bash
python -m pytest tests/test_project.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/project.py tests/test_project.py
git commit -m "feat: persist applied supply network"
```

---

### Task 2: Expose seller stock using the exact current resolution semantics

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/decision/contracts.py`
- Create: `tests/test_application.py`

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

- [ ] **Step 1: Create direct characterization tests in `tests/test_application.py`**

Build the smallest existing-domain fixtures that let `analyze()` reach seller-stock resolution. Add four tests:

```text
FBS evidence {7} -> ResolvedSellerStock(quantity=7, complete=True)
FBS evidence {7,9} -> quantity=None, CONFLICTING_FBS_AVAILABLE_STOCK
no FBS field + product.available_qty=11 + availability_fbs_authoritative=False -> quantity=11
availability_fbs_authoritative=True + no proven FBS quantity -> quantity=None, MISSING_SELLER_AVAILABLE_STOCK
```

Each test asserts both the new `resolved_seller_stock` result and the existing optimizer/diagnostic behavior for the same case.

- [ ] **Step 2: Run characterization tests before refactor**

```bash
python -m pytest tests/test_application.py -q
```

Expected: collection/attribute failure only for the new result field; existing behavior assertions establish the baseline.

- [ ] **Step 3: Extract one pure helper from the existing inline stock expression**

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

The existing `conflicting_fbs` set remains authoritative for detecting multiple positive values before helper invocation.

- [ ] **Step 4: Feed the same resolution to the existing legacy optimizer**

Replace the current inline `stock = (...)` expression with the helper result. Only call legacy `optimize_allocations()` when `resolution.complete` and `resolution.quantity is not None`. Preserve existing diagnostics for incomplete resolution.

- [ ] **Step 5: Return all SKU resolutions from `AnalysisResult`**

Store one resolution per SKU considered by the allocation loop, sorted by SKU.

- [ ] **Step 6: Run exact regression set**

```bash
python -m pytest tests/test_application.py tests/supply/test_optimizer.py tests/api/test_analysis.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/application.py backend/decision/contracts.py tests/test_application.py
git commit -m "refactor: expose resolved seller stock evidence"
```

---

### Task 3: Define immutable planning contracts including cluster-level physical roll-up

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
class OriginSkuBreakdown:
    sku: str
    quantity: int


@dataclass(frozen=True, slots=True)
class OriginDestinationBreakdown:
    destination_cluster_id: str
    quantity: int
    sku_breakdown: tuple[OriginSkuBreakdown, ...]


@dataclass(frozen=True, slots=True)
class OriginPlanView:
    origin_cluster_id: str
    total_qty: int
    own_destination_qty: int
    external_destination_qty: int
    destinations: tuple[OriginDestinationBreakdown, ...]


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

- [ ] **Step 1: Add contract validation tests**

In `tests/decision/test_planning.py` assert rejection of:

```text
duplicate PlanningRouteCandidate (sku,origin,destination)
duplicate RouteCostIndex (origin,destination)
duplicate PlanningSkuOrigin (sku,origin)
negative destination/origin totals
OriginPlanView total_qty != own_destination_qty + external_destination_qty
OriginDestinationBreakdown quantity != sum(sku_breakdown.quantity)
```

- [ ] **Step 2: Add cluster-level origin aggregation expectation**

Create two final legs for different SKUs through Moscow:

```text
SKU-A Moscow->Moscow 10
SKU-B Moscow->Kazan 20
```

Expected cluster roll-up:

```text
Moscow total=30
own=10
external=20
Moscow destination breakdown=10 [SKU-A 10]
Kazan destination breakdown=20 [SKU-B 20]
```

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contracts absent.

- [ ] **Step 4: Implement contracts and validation**

`OriginPlanView` intentionally has no SKU field. SKU-specific physical capacity stays in `PlanningBasis.sku_origins`; cluster totals are presentation-ready output, not a capacity source.

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/contracts.py tests/decision/test_planning.py
git commit -m "feat: define immutable planning snapshots"
```

---

### Task 4: Build candidate network and planning evidence after upstream analysis

**Files:**
- Create: `backend/decision/planning.py`
- Modify: `backend/application.py`
- Test: `tests/decision/test_planning.py`
- Test: `tests/test_application.py`

**Interface:**

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

Candidate cluster universe equals sorted clusters where at least one `PlacementAssessment.feasibility` is:

```text
allowed == True
capacity_kind in {FINITE, UNLIMITED}
finite max_supply_qty > 0 when FINITE
```

UNKNOWN-only clusters are not selector candidates.

- [ ] **Step 2: Add RouteCostIndex reuse test**

Two SKUs sharing `Москва → Казань` must produce:

```text
1 pair-level RouteCostIndex in planning_basis.route_cost_indices
2 SKU-specific PlanningRouteCandidate rows
```

- [ ] **Step 3: Add exact target-family tests**

For complete Need:

```text
Calculated target = calculated_need_qty
Safe target = min(calculated_need_qty, ozon_recommended_qty)
```

If `calculated_need_qty` is missing, emit neither family target for that identity. If Ozon recommendation alone is missing, Calculated target may exist but Safe target does not. Never coerce missing target evidence to zero.

- [ ] **Step 4: Build observed pair evidence from fulfillment flows, not origin-route share**

Call existing:

```python
observed_flows = aggregate_observed_flows(observed_routes)
```

Index by `(sku, origin_cluster_id, destination_cluster_id)`. For `PlanningRouteCandidate`:

```text
observed_flow_qty = FulfillmentFlowCell.quantity, else 0
observed_flow_share = FulfillmentFlowCell.destination_share, else None
```

Do not use `RouteDistributionCell.share` here because that is an origin distribution share, not destination share.

- [ ] **Step 5: Derive route confidence without numeric thresholds**

Build exact identity sets from:

```python
clean_exact = {
    (x.sku, x.origin_cluster_id, x.destination_cluster_id)
    for x in clean_routes.clean_routes
}
observed_exact = {
    (x.sku, x.origin_cluster_id, x.destination_cluster_id)
    for x in clean_routes.observed_routes
}
```

Then:

```text
HIGH   if identity in clean_exact
MEDIUM if identity in observed_exact only
LOW    otherwise
```

- [ ] **Step 6: Build RouteCostIndex once per tariff dataset**

```python
route_cost_indices = build_route_cost_indices(tariffs)
```

Store the returned tuple directly in `PlanningBasis`. Do not call the function in a SKU loop.

- [ ] **Step 7: Precompute direct quote/economics for all relevant non-local candidate routes**

For each product with known volume, each physically usable SKU-origin, and each destination with at least one emitted target:

```python
quote = quote_direct_route(
    tariffs,
    origin_cluster_id=origin,
    destination_cluster_id=destination,
    volume_liters=product.volume_liters,
    price=product.price,
)
economics = calculate_direct_route_economics(
    product,
    origin,
    quote,
    economics_settings,
)
```

Store incomplete quote/economics candidates too; downstream planner/allocator needs causal failure evidence.

For LOCAL, planning uses the already-computed local `PlacementAssessment.economics` for the same `SKU × destination/origin`; LOCAL does not need a non-local RouteCostIndex.

- [ ] **Step 8: Run exact tests**

```bash
python -m pytest tests/decision/test_planning.py tests/test_application.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/decision/planning.py backend/application.py tests/decision/test_planning.py tests/test_application.py
git commit -m "feat: build backend-owned planning basis"
```

---

### Task 5: Reconcile applied network and execute Safe/Calculated planning

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

- [ ] **Step 1: Add network reconciliation tests**

Assert exactly:

```text
candidates M,P,K; persisted None; requested None -> M,P,K
candidates M,P,K; persisted M,P; requested None -> M,P
candidates M,P,K; persisted empty; requested None -> empty
candidates M,P; persisted M,Old; requested None -> M + warning SUPPLY_CLUSTER_NO_LONGER_AVAILABLE:Old
candidates M,P; requested empty -> empty
candidates M,P; requested M,K -> ValueError for K not candidate
```

Use real cluster strings in tests; sort expected tuples lexically.

- [ ] **Step 2: Implement network reconciliation**

Requested network, when provided, wins over persisted state and must be a subset of candidates. When requested is absent and persisted is `None`, default all candidates. When persisted exists, intersect with candidates and emit one stable warning per disappeared cluster. Never silently add new candidates to persisted state.

- [ ] **Step 3: Implement one-family planner helper**

For each SKU:

1. select that family’s `DestinationTarget`s;
2. map `PlanningSkuOrigin` by origin;
3. create `RoutePlanningEvidence` from precomputed direct candidate + pair-level RouteCostIndex;
4. call `plan_coverage()`;
5. for each desired leg choose economics: LOCAL from local placement evidence, ROUTE from `PlanningRouteCandidate.direct_economics`;
6. create `CoverageAllocationCandidate` with target quantity, demand confidence and destination distortion confidence;
7. if seller stock is incomplete, create zero final legs and `allocation_blocked_qty` using `MISSING_SELLER_AVAILABLE_STOCK`; do not call allocator with zero;
8. otherwise call `allocate_coverage_legs()`.

- [ ] **Step 4: Assemble destination views**

For every emitted target create one `DestinationPlanView`. Its conservation must be:

```text
final_allocated_qty
+ network_uncovered_qty
+ allocation_blocked_qty
+ stock_uncovered_qty
= target_qty
```

- [ ] **Step 5: Assemble cluster-level origin roll-up**

From final allocated legs only, group by `origin_cluster_id`, then by destination and SKU.

For each origin:

```text
total_qty = sum all final legs through origin
own_destination_qty = sum legs where destination == origin
external_destination_qty = sum legs where destination != origin
```

Build `OriginDestinationBreakdown.quantity` from its SKU rows and validate all sums.

- [ ] **Step 6: Assemble family totals**

Totals are sums of backend destination views and final-leg profits. Do not derive total target from origin views because uncovered target has no origin.

- [ ] **Step 7: Run planning tests**

```bash
python -m pytest tests/decision/test_planning.py tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build selected-network planning snapshot"
```

---

### Task 6: Attach planning objects to full analysis without breaking current frontend

**Files:**
- Modify: `backend/decision/snapshot.py`
- Modify: `backend/decision/__init__.py`
- Modify: `backend/api.py`
- Modify: `tests/api/test_analysis.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

- [ ] **Step 1: Add response-shape test**

For a successful `/api/analysis`, assert existing root fields remain present and:

```python
body = response.json()
assert body["snapshot_id"]
assert body["decision_rows"] is not None
assert body["planning_basis"]["basis_id"]
assert body["planning_snapshot"]["applied_supply_network"] is not None
```

- [ ] **Step 2: Parse optional selected-network multipart field strictly**

```python
def _parse_selected_supply_clusters(raw: object) -> tuple[str, ...] | None:
    if raw is None:
        return None
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise ValueError("selected_supply_clusters must be JSON") from exc
    if not isinstance(value, list):
        raise ValueError("selected_supply_clusters must be a JSON array")
    if any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError("selected_supply_clusters must contain nonblank strings")
    if len(value) != len(set(value)):
        raise ValueError("selected_supply_clusters must be unique")
    return tuple(sorted(value))
```

Map parsing failure to HTTP 400 code `INVALID_SELECTED_SUPPLY_NETWORK`.

- [ ] **Step 3: Build planning after upstream analysis and snapshot identity exist**

Keep current legacy `DecisionRow` assembly untouched. Attach `planning_basis` and `planning_snapshot` as additional fields only.

- [ ] **Step 4: Persist applied network only after successful planning assembly**

```python
updated_project = replace(
    project,
    applied_supply_network=planning_snapshot.applied_supply_network,
)
save_project_atomic(PROJECT_PATH, updated_project)
```

If any planning exception is returned as an API error, do not call `save_project_atomic()`.

- [ ] **Step 5: Run API regressions**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/snapshot.py backend/decision/__init__.py backend/api.py tests/api/test_analysis.py
git commit -m "feat: attach planning result to full analysis"
```

---

### Task 7: Add stateless `/api/replan`

**Files:**
- Modify: `backend/api.py`
- Create: `tests/api/test_replan.py`

**Request contract:** JSON object with exactly two top-level fields:

```text
planning_basis
selected_supply_clusters
```

`planning_basis` is the exact object previously returned at `/api/analysis` field `planning_basis`. `selected_supply_clusters` is a JSON array of unique nonblank candidate cluster strings; empty array is valid.

**Response contract:**

```text
api_version = 1
kind = planning
planning_snapshot = wire(PlanningSnapshot)
```

- [ ] **Step 1: Add successful replan test using real analysis basis**

In `tests/api/test_replan.py` first obtain `analysis_body` from the existing API fixture/helper used in `tests/api/test_analysis.py`, then:

```python
payload = {
    "planning_basis": analysis_body["planning_basis"],
    "selected_supply_clusters": ["Москва"],
}
response = client.post("/api/replan", json=payload)
assert response.status_code == 200
body = response.json()
assert body["api_version"] == 1
assert body["kind"] == "planning"
assert body["planning_snapshot"]["basis_id"] == analysis_body["planning_basis"]["basis_id"]
assert body["planning_snapshot"]["analysis_snapshot_id"] == analysis_body["snapshot_id"]
assert body["planning_snapshot"]["applied_supply_network"] == ["Москва"]
```

Also compare destination target quantities before/after and assert they are identical while at least one origin roll-up changes in a fixture with alternate routes.

- [ ] **Step 2: Add no-upstream-recompute test**

Monkeypatch these imported functions to raise `AssertionError("unexpected upstream recompute")` during `/api/replan`:

```text
import_availability
import_restrictions
import_orders
estimate_destination_demand
detect_stockouts
build_episode_clean_route_profile
build_route_cost_indices
quote_direct_route
calculate_direct_route_economics
```

The replan request from Step 1 must still return 200.

- [ ] **Step 3: Add invalid request tests**

Assert HTTP 400 with stable codes:

```text
planning_basis missing -> INVALID_PLANNING_BASIS
planning_basis unknown field -> INVALID_PLANNING_BASIS
duplicate selected cluster -> INVALID_SELECTED_SUPPLY_NETWORK
selected cluster not in basis candidate_supply_clusters -> INVALID_SELECTED_SUPPLY_NETWORK
```

- [ ] **Step 4: Implement strict PlanningBasis wire parser**

Create private constructors in `backend/api.py` for every nested PlanningBasis contract. Reuse existing `_decimal_string` inverse semantics: parse decimal wire values using `Decimal(str(value))`, reject non-finite values, reconstruct enums from their exact `.value`, reject unknown/missing fields. Do not pass unvalidated dictionaries to business functions.

- [ ] **Step 5: Execute planning only**

```python
planning_snapshot = build_planning_snapshot(
    basis,
    selected_supply_network,
)
```

No upstream analysis call belongs in `/api/replan`.

- [ ] **Step 6: Persist only after successful build**

Load current Project, replace only `applied_supply_network`, save atomically, then return `{"api_version": 1, "kind": "planning", "planning_snapshot": wire(planning_snapshot)}`.

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

- [ ] **Step 1: Run focused planning/backend suites**

```bash
python -m pytest tests/economics/test_tariffs.py tests/economics/test_unit.py tests/supply/test_placement.py tests/supply/test_coverage.py tests/supply/test_optimizer.py tests/test_application.py tests/decision/test_planning.py tests/api/test_analysis.py tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run legacy Product Completion acceptance**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; old frontend contract remains usable before PR-E.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Static boundary scan**

```bash
python - <<'PY'
from pathlib import Path
api = Path('backend/api.py').read_text('utf-8')
start = api.index("@router.post('/api/replan')")
replan = api[start:]
for forbidden in (
    'estimate_destination_demand(',
    'detect_stockouts(',
    'build_episode_clean_route_profile(',
    'build_route_cost_indices(',
    'quote_direct_route(',
    'calculate_direct_route_economics(',
):
    assert forbidden not in replan, forbidden
print('replan boundary scan: ok')
PY
```

Expected: `replan boundary scan: ok`.

- [ ] **Step 5: Commit verification-only corrections if the completed tests required them**

```bash
git add backend tests
if ! git diff --cached --quiet; then git commit -m "fix: harden planning boundary"; fi
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
7. Observed flow share stored for route evidence is destination share from aggregated fulfillment flow, not origin distribution share.
8. Cross-docking tariffs never enter planning basis.
9. `PlanningBasis` contains every backend-resolved downstream input required by replan.
10. `PlanningSnapshot` owns destination coverage, cluster-level physical origin roll-up and three causal gap types.
11. SKU-specific capacity remains separate from cluster-level roll-up totals.
12. Full analysis can accept a selected network but preserves all upstream analysis identities.
13. `/api/replan` does not rerun ingestion, demand, stockout, clean routes, index derivation, tariff lookup or economics.
14. Failed full analysis/replan never persists the draft network.
15. Empty selected network is valid and remains empty.
16. Current root AnalysisSnapshot wire remains compatible until PR-E.
17. Full backend suite and existing Product Completion acceptance are green.
