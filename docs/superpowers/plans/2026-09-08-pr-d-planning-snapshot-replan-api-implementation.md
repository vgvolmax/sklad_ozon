# PR-D Planning Basis, Planning Snapshot, Persistence & Replan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR-A/B/C into full analysis, produce an immutable compact `PlanningBasis` plus authoritative `PlanningSnapshot`, persist only successfully applied supply networks, and add stateless `/api/replan` that recalculates coverage/allocation without rerunning upstream analysis.

**Architecture:** Keep current `analyze()` as the upstream business-analysis pipeline. It gains only an explicit seller-stock result. `backend/api.py` first assembles the existing `AnalysisSnapshot`, then uses that snapshot ID plus `AnalysisResult` and normalized inputs to build `PlanningBasis`; this avoids creating a snapshot-ID dependency inside `application.py`. `PlanningBasis` contains only compact backend-resolved primitives needed for replan: destination targets, feasibility + local allocation economics, route index, direct route fee + compact allocation economics, seller stock and confidence evidence. The final `PlanningSnapshot` contains rich `PlanningLegView` rows plus backend-generated cluster-level physical roll-up.

**Tech Stack:** Python 3, FastAPI, frozen dataclasses, `Decimal`, Project JSON schema migration, strict JSON wire parsing, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Selected network remains downstream of `Calculated Need` and cannot change demand history, stockout, clean routes, `DemandEstimate` or `NeedComparison`.
- Existing `AnalysisSnapshot` fields stay immutable/backwards-readable; PR-D only appends optional planning fields.
- Current API root shape remains: `/api/analysis` returns `{"snapshot": wire(AnalysisSnapshot), ...}`. Planning fields live inside that nested snapshot.
- Seller stock comes from current `application.py` resolution; Project JSON is not a second stock source.
- Missing/conflicting seller stock remains unknown and is never coerced to zero.
- `RouteCostIndex` is built once per full normalized customer-delivery tariff dataset, not per SKU.
- Direct fee/economics is resolved once per relevant SKU route during full analysis and stored compactly.
- LOCAL allocation economics is stored explicitly in `PlanningSkuOrigin`, so replan does not need original placements.
- `PlanningBasis` contains no raw report bytes and no full `UnitEconomicsResult` objects.
- `/api/replan` must not call ingestion, demand, stockout, clean-route, route-index, direct tariff lookup or economics functions.
- Cross-docking tariffs never enter PlanningBasis.
- Applied network persistence distinguishes `None` (never successfully applied) from `()` (successfully applied empty network).
- First use with `None` defaults to all current candidate clusters; later new candidates never auto-expand persisted network.
- Failed full analysis/replan never persists the draft network.
- No new session/server state; replan is stateless except existing Project persistence.
- Physical origin roll-up is backend aggregated across SKUs; physical capacity remains per `SKU × origin` and is never inferred from roll-up totals.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/project.py` — schema v2 + `applied_supply_network`.
- Modify `backend/application.py` — explicit `ResolvedSellerStock` output using current semantics.
- Modify `backend/decision/contracts.py` — compact PlanningBasis/PlanningSnapshot contracts and optional planning fields on AnalysisSnapshot.
- Create `backend/decision/planning.py` — basis assembly, network reconciliation, Safe/Calculated execution, rich leg views and origin roll-up.
- Create `backend/decision/planning_wire.py` — strict `PlanningBasis` JSON parser for `/api/replan`.
- Modify `backend/decision/__init__.py` — public planning exports.
- Modify `backend/api.py` — full-analysis planning integration + `/api/replan` + persistence.
- Modify `tests/test_project.py` — schema migration/persistence.
- Create `tests/test_application.py` — seller-stock characterization.
- Create `tests/decision/test_planning.py` — basis/reconciliation/planning/roll-up tests.
- Create `tests/decision/test_planning_wire.py` — strict wire roundtrip/rejection tests.
- Modify `tests/api/test_analysis.py` — nested planning response and full-analysis network request.
- Create `tests/api/test_replan.py` — stateless network-only recalculation/persistence.
- Run `tests/api/test_product_completion_acceptance.py` unchanged as compatibility regression.

---

### Task 1: Migrate Project persistence to schema v2

**Files:**
- Modify: `backend/project.py`
- Modify: `tests/test_project.py`

**Contract:**

```python
SCHEMA_VERSION = 2
```

Append to `Project` after `operational_snapshots`:

```python
applied_supply_network: tuple[str, ...] | None = None
```

- [ ] **Step 1: Add schema-v1 migration test**

Use the current valid persisted payload fixture, set:

```python
payload["schema_version"] = 1
payload.pop("applied_supply_network", None)
```

Load it and assert:

```python
assert project.schema_version == 2
assert project.applied_supply_network is None
```

- [ ] **Step 2: Add null/empty/nonempty roundtrip tests**

Write/load three Projects and assert:

```python
assert roundtrip(None).applied_supply_network is None
assert roundtrip(()).applied_supply_network == ()
assert roundtrip(("Питер", "Москва")).applied_supply_network == ("Москва", "Питер")
```

The test helper uses `dataclasses.replace(Project(), applied_supply_network=value)`, `save_project_atomic()`, then `load_project()`.

- [ ] **Step 3: Add invalid-network tests**

Assert `ProjectValidationError` for duplicate, blank and non-string members.

- [ ] **Step 4: Implement version-specific strict top fields**

```python
_TOP_FIELDS_V1 = {
    "schema_version", "tariffs", "tariff_meta", "product_economics",
    "product_economics_meta", "seller_available_stock",
    "manual_cluster_mappings", "economics_settings", "optimizer_thresholds",
    "operational_snapshots",
}
_TOP_FIELDS_V2 = _TOP_FIELDS_V1 | {"applied_supply_network"}
```

`load_project()` accepts exactly v1/v2. V1 injects `raw_network=None`; v2 accepts only `null` or list of unique nonblank strings. Convert a valid list to `tuple(sorted(raw_network))`.

- [ ] **Step 5: Save only schema v2**

`_to_payload()` emits:

```python
"schema_version": 2,
"applied_supply_network": (
    None if project.applied_supply_network is None
    else list(sorted(project.applied_supply_network))
),
```

Update `_validate()` to accept current schema 2 only for in-memory Project.

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

### Task 2: Expose seller stock using the exact current analysis semantics

**Files:**
- Modify: `backend/decision/contracts.py`
- Modify: `backend/application.py`
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

- [ ] **Step 1: Characterize current stock branches through `analyze()`**

Create four minimal test scenarios in `tests/test_application.py`:

```text
one proven FBS value 7 -> quantity 7, complete
conflicting positive FBS values 7 and 9 -> quantity None, CONFLICTING_FBS_AVAILABLE_STOCK
no FBS evidence + product.available_qty 11 + availability_fbs_authoritative False -> quantity 11, complete
availability_fbs_authoritative True + no proven FBS qty -> quantity None, MISSING_SELLER_AVAILABLE_STOCK
```

For each case assert both the new result and existing allocation/diagnostic outcome.

- [ ] **Step 2: Run tests and verify only new contract is RED**

```bash
python -m pytest tests/test_application.py -q
```

- [ ] **Step 3: Extract current inline resolution to one helper**

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

- [ ] **Step 4: Feed the same resolution to the legacy optimizer**

Call legacy optimizer only when `complete` and quantity is not None. Preserve current diagnostics for incomplete evidence.

- [ ] **Step 5: Return one sorted resolution per SKU considered by allocation**

Do not read `Project.seller_available_stock` here.

- [ ] **Step 6: Run regressions**

```bash
python -m pytest tests/test_application.py tests/supply/test_optimizer.py tests/api/test_analysis.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/decision/contracts.py backend/application.py tests/test_application.py
git commit -m "refactor: expose resolved seller stock evidence"
```

---

### Task 3: Define compact planning contracts and rich plan views

**Files:**
- Modify: `backend/decision/contracts.py`
- Create: `tests/decision/test_planning.py`

**Contracts:**

```python
@dataclass(frozen=True, slots=True)
class PlanningSkuOrigin:
    sku: str
    origin_cluster_id: str
    feasibility: SupplyFeasibility
    local_economics: AllocationEconomics


@dataclass(frozen=True, slots=True)
class PlanningRouteCandidate:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    direct_tariff_complete: bool
    direct_route_fee: Decimal | None
    direct_tariff_reason_code: str | None
    allocation_economics: AllocationEconomics
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None


@dataclass(frozen=True, slots=True)
class PlanningDestinationSignal:
    sku: str
    destination_cluster_id: str
    demand_confidence: SignalConfidence
    distortion_confidence: SignalConfidence | None


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
    destination_signals: tuple[PlanningDestinationSignal, ...]
    optimizer_thresholds: OptimizerThresholds
    tariff_source_name: str
    tariff_report_generated_at: str | None


@dataclass(frozen=True, slots=True)
class PlanningLegView:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    coverage_type: CoverageType
    desired_qty: int
    final_allocated_qty: int
    direct_route_fee: Decimal | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
    route_cost_index_spread: Decimal | None
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None
    expected_profit_per_unit: Decimal | None
    expected_profit: Decimal
    eligible: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DestinationPlanView:
    sku: str
    destination_cluster_id: str
    target_qty: int
    final_allocated_qty: int
    network_uncovered_qty: int
    allocation_blocked_qty: int
    stock_uncovered_qty: int
    legs: tuple[PlanningLegView, ...]


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

Append final default fields to `AnalysisSnapshot`:

```python
planning_basis: PlanningBasis | None = None
planning_snapshot: PlanningSnapshot | None = None
```

- [ ] **Step 1: Add contract identity tests**

Reject duplicate:

```text
PlanningSkuOrigin (sku,origin)
PlanningRouteCandidate (sku,origin,destination)
RouteCostIndex (origin,destination) inside PlanningBasis
PlanningDestinationSignal (sku,destination)
```

Validate local economics identity matches `PlanningSkuOrigin`, route allocation economics identity matches SKU+origin, and route direct-fee completeness consistency matches PR-B primitive rules.

- [ ] **Step 2: Add rich leg and destination conservation validation**

Reject `PlanningLegView.final_allocated_qty > desired_qty` and `DestinationPlanView` where:

```text
final_allocated_qty + network_uncovered_qty + allocation_blocked_qty + stock_uncovered_qty != target_qty
```

Also assert `final_allocated_qty == sum(leg.final_allocated_qty)`.

- [ ] **Step 3: Add cluster-level origin roll-up contract test**

Expected result from:

```text
SKU-A Moscow->Moscow = 10
SKU-B Moscow->Kazan = 20
```

is one `OriginPlanView("Москва")` with total 30, own 10, external 20, Moscow destination `[SKU-A 10]` and Kazan destination `[SKU-B 20]`.

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: new contracts absent.

- [ ] **Step 5: Implement immutable contracts and validations**

`OriginPlanView` intentionally has no SKU identity; it is a physical cluster roll-up. `PlanningSkuOrigin` remains the SKU-specific physical evidence source.

- [ ] **Step 6: Run and verify GREEN**

```bash
python -m pytest tests/decision/test_planning.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/decision/contracts.py tests/decision/test_planning.py
git commit -m "feat: define compact planning snapshot contracts"
```

---

### Task 4: Build PlanningBasis after existing AnalysisSnapshot identity exists

**Files:**
- Create: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Public interface:**

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

Candidate clusters are sorted unique origins where at least one placement feasibility is:

```text
allowed == True
capacity_kind FINITE with max_supply_qty > 0
or capacity_kind UNLIMITED
```

UNKNOWN and finite zero are not selector candidates.

- [ ] **Step 2: Add target-family tests**

For each Need:

```text
Calculated target exists when calculated_need_qty is known and equals it
Safe target exists only when calculated_need_qty and ozon_recommended_qty are both known and equals min(the two)
missing target evidence is absence, never zero
```

Store both families as `DestinationTarget` rows distinguished by `plan_family`.

- [ ] **Step 3: Add local compact economics test**

For each usable `PlacementAssessment`, `PlanningSkuOrigin.local_economics` must equal:

```python
to_allocation_economics(placement.economics)
```

This is the only local economics source required by future replan.

- [ ] **Step 4: Build historical exact-pair evidence from fulfillment flow**

Call `aggregate_observed_flows(observed_routes)` and index by `(sku,origin,destination)`. Use its `quantity` and `destination_share`; do not use origin-distribution `RouteDistributionCell.share`.

Route confidence:

```text
HIGH if exact identity exists in clean_routes.clean_routes
MEDIUM if absent from clean but exists in clean_routes.observed_routes
LOW otherwise
```

- [ ] **Step 5: Build RouteCostIndex once**

```python
route_cost_indices = build_route_cost_indices(tariffs)
```

Store the tuple directly. Two SKUs sharing one pair still produce one pair-level index.

- [ ] **Step 6: Precompute each relevant non-local direct route once**

For every product with known volume, each usable SKU-origin and every destination appearing in either family target for that SKU:

```python
quote = quote_direct_route(
    tariffs,
    origin_cluster_id=origin,
    destination_cluster_id=destination,
    volume_liters=product.volume_liters,
    price=product.price,
)
unit = calculate_direct_route_economics(
    product,
    origin,
    quote,
    economics_settings,
)
compact = to_allocation_economics(unit)
```

Create `PlanningRouteCandidate` with primitive quote fields and `compact`. Store incomplete candidates too.

- [ ] **Step 7: Build destination confidence rows**

For every target identity, demand confidence is the matching `DemandEstimate.confidence` or LOW if absent. Distortion confidence is matching `RecommendationDistortionSignal.confidence` for `(sku,recommended_cluster_id)` or None.

- [ ] **Step 8: Run basis tests**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build backend-owned planning basis"
```

---

### Task 5: Reconcile selected network and execute both plan families

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

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
    reconciliation_warnings: tuple[str, ...] = (),
) -> PlanningSnapshot:
```

- [ ] **Step 1: Add exact network reconciliation cases**

```text
candidates M,P,K; persisted None; requested None -> M,P,K
candidates M,P,K; persisted M,P; requested None -> M,P; K unselected
candidates M,P,K; persisted empty; requested None -> empty
candidates M,P; persisted M,Old; requested None -> M + warning SUPPLY_CLUSTER_NO_LONGER_AVAILABLE:Old
candidates M,P; requested empty -> empty
candidates M,P; requested M,K -> ValueError because K is not candidate
```

- [ ] **Step 2: Implement reconciliation exactly**

Requested network wins when supplied and must be subset of current candidates. Without request: persisted `None` defaults all candidates; otherwise intersect persisted with candidates and warn for disappeared entries. Never silently add new candidates to persisted network.

- [ ] **Step 3: Build PR-B primitive route evidence per SKU/pair**

Index pair-level RouteCostIndex and each SKU route candidate. Produce:

```python
RoutePlanningEvidence(
    origin,
    destination,
    candidate.direct_tariff_complete,
    candidate.direct_route_fee,
    candidate.direct_tariff_reason_code,
    None if index is None else index.index_value,
    None if index is None else index.coverage_ratio,
    None if index is None else index.spread_iqr,
    candidate.route_confidence,
    candidate.observed_flow_qty,
    candidate.observed_flow_share,
)
```

- [ ] **Step 4: Run PR-B Coverage Planner for each SKU/family**

Use matching `PlanningSkuOrigin.feasibility`, family targets and selected network.

- [ ] **Step 5: Create PR-C candidates with compact local/direct economics**

For LOCAL desired leg, use matching `PlanningSkuOrigin.local_economics`. For ROUTE desired leg, use matching `PlanningRouteCandidate.allocation_economics`. Add target quantity and matching `PlanningDestinationSignal` confidence fields.

If `ResolvedSellerStock.complete` is false, do not call `allocate_coverage_legs()` with zero. Produce zero final quantities for desired legs and classify their entire desired quantity as allocation blocked with the seller-stock reason code.

Otherwise call `allocate_coverage_legs()` with the proven quantity.

- [ ] **Step 6: Join desired + final evidence into `PlanningLegView`**

For each desired leg and matching final leg copy topology fields from desired leg and allocation fields from final leg. This is the authoritative rich plan row used by PR-E; no frontend join to historical sources is required for planned link evidence.

- [ ] **Step 7: Assemble `DestinationPlanView` with hard conservation**

For each target:

```text
sum PlanningLegView.final_allocated_qty
+ network gap
+ allocation blocked
+ stock uncovered
= target qty
```

- [ ] **Step 8: Assemble cluster-level `OriginPlanView`**

Group only final allocated planned legs by origin, then destination, then SKU. Validate:

```text
origin total = own destination + external destinations
origin destination quantity = sum SKU breakdown
sum all origin totals = family total allocated
```

- [ ] **Step 9: Assemble family totals and profit**

Target/gap totals come from destination views. Profit comes from `PlanningLegView.expected_profit`. Do not derive targets from origins because uncovered demand has no origin.

- [ ] **Step 10: Run planning tests**

```bash
python -m pytest tests/decision/test_planning.py tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build selected-network planning snapshot"
```

---

### Task 6: Add strict PlanningBasis wire roundtrip

**Files:**
- Create: `backend/decision/planning_wire.py`
- Create: `tests/decision/test_planning_wire.py`
- Modify: `backend/decision/__init__.py`

**Public interface:**

```python
def planning_basis_from_wire(value: object) -> PlanningBasis:
```

Serialization remains the existing generic API `wire()` function; this task owns strict inverse parsing only.

- [ ] **Step 1: Add roundtrip test**

Build a complete PlanningBasis fixture with:
- one SAFE + one CALCULATED target;
- one finite SKU origin with compact local economics;
- one RouteCostIndex;
- one direct route candidate;
- one seller-stock row;
- one destination signal;
- thresholds and tariff metadata.

Assert:

```python
assert planning_basis_from_wire(wire(basis)) == basis
```

Import `wire` from `backend.api` only in the test; production `planning_wire.py` must not import API.

- [ ] **Step 2: Add strict rejection tests**

For the same wire fixture assert `ValueError` for:

```text
unknown top-level field
missing basis_id
non-finite decimal string
unknown PlanFamily value
unknown RouteConfidence value
route index coverage > 1
finite feasibility without max_supply_qty
route candidate complete=True with direct_route_fee null
```

- [ ] **Step 3: Add strict-object and scalar helpers**

```python
def _object(value, fields, context):
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    unknown = set(value) - set(fields)
    missing = set(fields) - set(value)
    if unknown or missing:
        raise ValueError(f"invalid {context} fields")
    return value


def _decimal(value, context):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{context} must be decimal") from None
    if not result.is_finite():
        raise ValueError(f"{context} must be finite")
    return result


def _decimal_or_none(value, context):
    return None if value is None else _decimal(value, context)
```

Add analogous strict `_string`, `_int`, `_bool`, `_tuple` helpers; bool must not pass `_int`.

- [ ] **Step 4: Implement nested parsers with exact dataclass field sets**

Use each dataclass `__slots__` as the allowed/required field set and explicitly reconstruct:

```text
ScenarioSettings
DestinationTarget
SupplyFeasibility
AllocationEconomics
PlanningSkuOrigin
RouteCostIndex
PlanningRouteCandidate
ResolvedSellerStock
PlanningDestinationSignal
OptimizerThresholds
PlanningBasis
```

Enum reconstruction uses exact constructors such as `PlanFamily(raw)` and `RouteConfidence(raw)`; invalid values become `ValueError`. Decimal fields use helpers above. Tuple/list wire collections must be JSON lists and are converted to tuples.

- [ ] **Step 5: Run wire tests**

```bash
python -m pytest tests/decision/test_planning_wire.py -q
```

Expected: PASS.

- [ ] **Step 6: Export `planning_basis_from_wire`**

Add it to `backend/decision/__init__.py` together with planning build/reconcile exports.

- [ ] **Step 7: Commit**

```bash
git add backend/decision/planning_wire.py backend/decision/__init__.py tests/decision/test_planning_wire.py
git commit -m "feat: parse planning basis wire strictly"
```

---

### Task 7: Attach planning to full `/api/analysis` without breaking current response shape

**Files:**
- Modify: `backend/api.py`
- Modify: `backend/decision/snapshot.py`
- Modify: `tests/api/test_analysis.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

- [ ] **Step 1: Add nested response-shape test**

A successful response still has current root shape and planning appears inside `snapshot`:

```python
body = response.json()
assert body["api_version"] == 1
assert body["snapshot"]["snapshot_id"]
assert body["snapshot"]["decision_rows"] is not None
assert body["snapshot"]["planning_basis"]["basis_id"]
assert body["snapshot"]["planning_snapshot"]["applied_supply_network"] is not None
```

- [ ] **Step 2: Parse optional multipart network request**

Add:

```python
def _parse_selected_supply_clusters(raw):
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

`prepare_analysis()` returns this request separately from `ScenarioSettings`; it is not added to `ScenarioSettings`.

- [ ] **Step 3: Keep `assemble_snapshot()` legacy calculation unchanged and append defaults**

The function continues generating `snapshot_id`. After it returns in `run_analysis_pipeline()`:

```python
legacy_snapshot = assemble_snapshot(...current arguments...)
```

Use that exact `legacy_snapshot.snapshot_id` to construct PlanningBasis.

- [ ] **Step 4: Build planning after the legacy snapshot**

```python
basis = build_planning_basis(
    analysis_snapshot_id=legacy_snapshot.snapshot_id,
    scenario=scenario,
    needs=result.needs,
    demand_estimates=result.demand_estimates,
    distortions=result.distortions,
    observed_routes=result.observed_routes,
    clean_routes=result.clean_routes,
    products=products.records,
    tariffs=analysis_tariffs,
    placements=result.placements,
    resolved_seller_stock=result.resolved_seller_stock,
    optimizer_thresholds=thresholds,
    economics_settings=settings,
)
selected, reconciliation_warnings = reconcile_supply_network(
    basis.candidate_supply_clusters,
    project.applied_supply_network,
    selected_network_request,
)
planning_snapshot = build_planning_snapshot(
    basis, selected, reconciliation_warnings
)
snapshot = replace(
    legacy_snapshot,
    planning_basis=basis,
    planning_snapshot=planning_snapshot,
)
```

Use the actual existing assemble call arguments; do not change legacy calculations/rows.

- [ ] **Step 5: Persist only after planning and wire serialization succeed**

First compute:

```python
snapshot_wire = wire(snapshot)
```

Then persist:

```python
save_project_atomic(
    PROJECT_PATH,
    replace(project, applied_supply_network=planning_snapshot.applied_supply_network),
)
```

Return existing API result structure using `"snapshot": snapshot_wire`. If any step before persistence raises, the prior Project remains unchanged.

- [ ] **Step 6: Add full-analysis network tests**

Assert explicit empty network is preserved, explicit subset is returned exactly, and an out-of-candidate cluster yields HTTP 400 `INVALID_SELECTED_SUPPLY_NETWORK` without updating Project.

- [ ] **Step 7: Run API regressions**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/api.py backend/decision/snapshot.py tests/api/test_analysis.py
git commit -m "feat: attach planning result to full analysis"
```

---

### Task 8: Add stateless `/api/replan`

**Files:**
- Modify: `backend/api.py`
- Create: `tests/api/test_replan.py`

**Request JSON:** exactly:

```json
{
  "planning_basis": {},
  "selected_supply_clusters": ["Москва"]
}
```

`planning_basis` is the exact object returned by the preceding full analysis. Empty selected array is valid.

**Response JSON:**

```json
{
  "api_version": 1,
  "kind": "planning",
  "planning_snapshot": {}
}
```

- [ ] **Step 1: Add successful replan test using a real full-analysis basis**

Obtain `analysis_body = client.post("/api/analysis", files=..., data=...).json()`, then:

```python
basis = analysis_body["snapshot"]["planning_basis"]
payload = {
    "planning_basis": basis,
    "selected_supply_clusters": ["Москва"],
}
response = client.post("/api/replan", json=payload)
assert response.status_code == 200
body = response.json()
assert body["api_version"] == 1
assert body["kind"] == "planning"
assert body["planning_snapshot"]["basis_id"] == basis["basis_id"]
assert body["planning_snapshot"]["analysis_snapshot_id"] == basis["analysis_snapshot_id"]
assert body["planning_snapshot"]["applied_supply_network"] == ["Москва"]
```

Fixture must have at least two candidate origins so origin roll-up changes while destination target quantities remain identical.

- [ ] **Step 2: Add strict malformed request tests**

Assert HTTP 400 codes:

```text
missing/invalid planning_basis -> INVALID_PLANNING_BASIS
duplicate selected cluster -> INVALID_SELECTED_SUPPLY_NETWORK
selected cluster outside basis.candidate_supply_clusters -> INVALID_SELECTED_SUPPLY_NETWORK
```

- [ ] **Step 3: Add no-upstream-recompute test**

Monkeypatch the API/planning module references to these functions to raise `AssertionError("unexpected upstream recompute")` during replan:

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

A valid replan must still return 200.

- [ ] **Step 4: Implement endpoint input validation**

Read JSON object, require exactly `planning_basis` and `selected_supply_clusters`. Parse basis with `planning_basis_from_wire()`. Validate selected list with the same nonblank/unique rules and ensure set is subset of `basis.candidate_supply_clusters`.

- [ ] **Step 5: Execute downstream planning only**

```python
planning_snapshot = build_planning_snapshot(
    basis,
    tuple(sorted(selected_supply_clusters)),
)
response_payload = {
    "api_version": 1,
    "kind": "planning",
    "planning_snapshot": wire(planning_snapshot),
}
```

No full-analysis function is called.

- [ ] **Step 6: Persist applied network after successful wire serialization**

Load current Project, replace only `applied_supply_network`, save atomically, return response. Planning failure leaves Project unchanged.

- [ ] **Step 7: Run exact replan tests**

```bash
python -m pytest tests/api/test_replan.py tests/decision/test_planning_wire.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/api.py tests/api/test_replan.py
git commit -m "feat: replan selected network without reanalysis"
```

---

### Task 9: Final backend verification

**Files:** no new production files

- [ ] **Step 1: Run focused suite**

```bash
python -m pytest tests/economics/test_tariffs.py tests/economics/test_unit.py tests/supply/test_placement.py tests/supply/test_coverage.py tests/supply/test_optimizer.py tests/test_application.py tests/decision/test_planning.py tests/decision/test_planning_wire.py tests/api/test_analysis.py tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Product Completion compatibility**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Static replan boundary scan**

```bash
python - <<'PY'
from pathlib import Path
text = Path('backend/api.py').read_text('utf-8')
start = text.index("@router.post('/api/replan')")
replan = text[start:]
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

- [ ] **Step 5: Commit verification-driven corrections only if tests required code changes**

```bash
git add backend tests
if ! git diff --cached --quiet; then git commit -m "fix: harden planning boundary"; fi
```

---

## PR-D Acceptance Gate

PR-D is complete only when all are true:

1. Project v1 loads and saves safely as v2.
2. `None` and empty applied network remain distinct.
3. First-use default and later reconciliation follow approved behavior exactly.
4. Seller stock is exported from current analysis semantics; unknown never becomes zero.
5. RouteCostIndex is built once per full customer-delivery tariff matrix, not per SKU.
6. Direct fees/economics are exact per concrete SKU route and projected once to compact allocation economics.
7. PlanningBasis contains explicit local allocation economics and needs no original placement/economics object during replan.
8. Observed route share in planning evidence is destination share from aggregated fulfillment Flow.
9. Cross-docking tariffs never enter planning data.
10. PlanningSnapshot rich legs preserve Flow/index/direct-fee evidence separately.
11. Origin physical roll-up is cluster-level across SKUs, while capacity stays SKU-specific.
12. Full analysis builds planning only after the existing AnalysisSnapshot ID exists.
13. Current `/api/analysis` root response shape remains compatible.
14. `/api/replan` reconstructs PlanningBasis strictly and performs downstream planning only.
15. Failed full analysis/replan never persists draft network.
16. Empty selected network is valid.
17. Focused, compatibility and full backend suites are green.
