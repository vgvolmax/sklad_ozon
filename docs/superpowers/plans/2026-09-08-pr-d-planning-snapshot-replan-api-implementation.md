# PR-D Planning Basis, Planning Snapshot, Persistence & Replan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR-A/B/C into full analysis, produce an immutable compact `PlanningBasis` plus authoritative `PlanningSnapshot`, persist only successfully applied supply networks, and add a stateless `/api/replan` that recalculates only downstream route/coverage/allocation work for the explicitly selected network.

**Architecture:** Keep `backend/application.py::analyze()` as the upstream demand/history pipeline. Full analysis first assembles the existing immutable `AnalysisSnapshot`, then builds a planning basis referenced to that snapshot ID. The basis stores the normalized Ozon customer-delivery tariff matrix once, pair-level `RouteCostIndex` once, product economics inputs once per SKU, physical feasibility/capacity once per `SKU × origin`, sparse route-history evidence, destination targets/signals and resolved seller stock. It deliberately does **not** precompute `SKU × every origin × every destination` economics. `/api/replan` reconstructs exact direct quotes and direct/local economics only for routes needed by the selected network, then runs Coverage Planner and `MAX_MARGIN`; it never reruns ingestion, demand, stockout, route cleaning or RouteCostIndex normalization.

**Tech Stack:** Python 3, FastAPI, frozen dataclasses, `Decimal`, strict JSON wire parsing, Project JSON schema migration, pytest; PR-A/B/C public contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** the normalized Ozon route tariff matrix is SKU-independent source data. `RouteCostIndex` is stored once per route pair. A concrete SKU still supplies price/volume to exact direct tariff lookup and route economics at planning execution time. This avoids a persisted/precomputed SKU route matrix while preserving exact SKU economics.

## Global Constraints

- Selected network remains downstream of `Calculated Need`; it cannot change demand history, `DemandEstimate`, stockout episodes, clean routes or `NeedComparison`.
- Existing `AnalysisSnapshot` root/evidence fields remain immutable and backwards-readable; PR-D only appends planning fields.
- Current API root shape remains `{"snapshot": wire(AnalysisSnapshot), ...}`; planning objects live inside the nested snapshot.
- Seller stock comes from the exact current `application.py` FBS/operational/product-fallback resolution, never from a second Project lookup.
- Missing/conflicting seller stock stays unknown and is never coerced to zero.
- Restrictions remain the only physical feasibility/capacity source for selected-network planning; no availability fallback is introduced for planner origins.
- The normalized customer-delivery tariff matrix is stored once in `PlanningBasis`; cross-docking/supply-delivery tariffs are excluded.
- `RouteCostIndex` is computed once per full normalized tariff matrix and keyed only by `origin × destination`.
- `/api/replan` may perform direct tariff lookup and direct-route economics from the normalized planning basis because these are downstream planning calculations; it must not repeat tariff ingestion or RouteCostIndex derivation.
- Do not precompute/store `SKU × all-origin × all-destination` direct economics in PlanningBasis.
- `PlanningBasis` contains no raw report bytes, no buyer/order history and no full `UnitEconomicsResult` objects.
- Applied network persistence distinguishes `None` (never successfully applied) from `()` (successfully applied empty network).
- First use with `None` defaults to all current candidate supply clusters; later new candidates never silently expand a persisted network.
- Checkbox draft changes are not persisted; only a successfully returned `PlanningSnapshot.applied_supply_network` is persisted.
- Failed full analysis or replan preserves the previous applied network.
- No new session/server state is introduced; `/api/replan` is stateless apart from existing Project JSON persistence.
- Physical origin roll-up is backend-aggregated across SKUs. Capacity remains per `SKU × origin`; roll-up totals are never reused as capacity.
- Use TDD, exact immutable contracts and no new dependencies.

---

## File Structure

- Modify `backend/project.py` — Project schema v2 and `applied_supply_network` persistence/migration.
- Modify `backend/application.py` — expose current seller-stock resolution as immutable evidence without changing upstream analysis behavior.
- Modify `backend/decision/contracts.py` — compact planning-basis contracts, rich planning views and optional planning fields on `AnalysisSnapshot`.
- Create `backend/decision/planning.py` — build physical origin universe, planning basis, route evidence, both plan families and backend roll-ups.
- Create `backend/decision/planning_wire.py` — strict JSON parser for the self-contained PlanningBasis sent to `/api/replan`.
- Modify `backend/decision/__init__.py` — export planning contracts/functions.
- Modify `backend/api.py` — parse requested supply network for both full-analysis transports, attach planning objects, add `/api/replan`, persist successful applied network.
- Modify `tests/test_project.py` — schema migration and applied-network persistence.
- Create `tests/test_application.py` — seller-stock characterization.
- Create `tests/decision/test_planning.py` — basis, origin-universe, target, tariff/index, execution, conservation and roll-up tests.
- Create `tests/decision/test_planning_wire.py` — strict wire roundtrip/rejection tests.
- Modify `tests/api/test_analysis.py` — nested planning response and full-analysis selected-network behavior.
- Create `tests/api/test_replan.py` — network-only stateless recalculation/persistence tests.
- Run `tests/api/test_product_completion_acceptance.py` unchanged as compatibility regression.

No frontend file belongs in PR-D.

---

### Task 1: Migrate Project persistence to schema v2

**Files:**
- Modify: `backend/project.py`
- Modify: `tests/test_project.py`

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

- [ ] **Step 1: Add schema-v1 migration test**

In `tests/test_project.py`, take the current valid saved payload fixture, set:

```python
payload["schema_version"] = 1
payload.pop("applied_supply_network", None)
```

Write it to disk, load through `load_project()`, and assert:

```python
assert project.schema_version == 2
assert project.applied_supply_network is None
```

Assert all pre-existing business fields equal the schema-v1 fixture values.

- [ ] **Step 2: Add null/empty/nonempty roundtrip tests**

Use this exact helper:

```python
def _roundtrip_network(tmp_path, value):
    source = replace(Project(), applied_supply_network=value)
    path = tmp_path / "project.json"
    save_project_atomic(path, source)
    return load_project(path)
```

Assert:

```python
assert _roundtrip_network(tmp_path, None).applied_supply_network is None
assert _roundtrip_network(tmp_path, ()).applied_supply_network == ()
assert _roundtrip_network(tmp_path, ("Питер", "Москва")).applied_supply_network == (
    "Москва", "Питер"
)
```

- [ ] **Step 3: Add invalid-network tests**

Assert `ProjectValidationError` for:

```python
("Москва", "Москва")
("Москва", "")
("Москва", 7)
```

- [ ] **Step 4: Implement strict version-specific field sets**

```python
_TOP_FIELDS_V1 = {
    "schema_version", "tariffs", "tariff_meta", "product_economics",
    "product_economics_meta", "seller_available_stock",
    "manual_cluster_mappings", "economics_settings", "optimizer_thresholds",
    "operational_snapshots",
}
_TOP_FIELDS_V2 = _TOP_FIELDS_V1 | {"applied_supply_network"}
```

`load_project()` accepts only version 1 or 2. Version 1 injects `raw_network=None`; version 2 requires `null` or a list of unique nonblank strings and converts a valid list to `tuple(sorted(raw_network))`.

When reconstructing `Project`, switch the loader to keyword arguments so the new final field cannot silently shift a positional constructor.

- [ ] **Step 5: Save only schema v2**

`_to_payload()` emits:

```python
"schema_version": 2,
"applied_supply_network": (
    None
    if project.applied_supply_network is None
    else list(sorted(project.applied_supply_network))
),
```

Update `_validate()` so only in-memory schema 2 is accepted.

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

### Task 2: Expose resolved seller stock using current analysis semantics

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

- [ ] **Step 1: Characterize the four current stock branches through `analyze()`**

Build minimal fixtures that reach the current stock resolution and assert:

```text
one proven positive FBS value 7
→ quantity 7, complete=True

conflicting positive FBS values 7 and 9
→ quantity None, complete=False, CONFLICTING_FBS_AVAILABLE_STOCK

no FBS evidence + product.available_qty 11 + availability_fbs_authoritative=False
→ quantity 11, complete=True

availability_fbs_authoritative=True + no proven FBS value
→ quantity None, complete=False, MISSING_SELLER_AVAILABLE_STOCK
```

For each fixture also assert the pre-existing allocation/diagnostic behavior remains the same.

- [ ] **Step 2: Run the characterization tests before refactor**

```bash
python -m pytest tests/test_application.py -q
```

Expected: tests that inspect the new `resolved_seller_stock` field fail; legacy assertions establish the baseline.

- [ ] **Step 3: Extract exactly the current stock resolution**

Add:

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

- [ ] **Step 4: Feed the same object to the legacy optimizer path**

Call the legacy optimizer only when `complete` is true and `quantity` is not `None`. Preserve the current missing/conflicting diagnostics exactly.

- [ ] **Step 5: Return one sorted resolution for every SKU in the allocation universe**

Do not read `Project.seller_available_stock` inside `analyze()`.

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

### Task 3: Define compact self-contained PlanningBasis contracts

**Files:**
- Modify: `backend/decision/contracts.py`
- Create: `tests/decision/test_planning.py`

**Contracts:**

```python
@dataclass(frozen=True, slots=True)
class PlanningProductInput:
    sku: str
    price: Decimal | None
    cost: Decimal | None
    commission_rate: Decimal | None
    volume_liters: Decimal | None


@dataclass(frozen=True, slots=True)
class PlanningSkuOrigin:
    sku: str
    origin_cluster_id: str
    feasibility: SupplyFeasibility


@dataclass(frozen=True, slots=True)
class PlanningRouteHistory:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
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
    tariff_rows: tuple[TariffRow, ...]
    route_cost_indices: tuple[RouteCostIndex, ...]
    products: tuple[PlanningProductInput, ...]
    economics_settings: EconomicsSettings
    seller_stock: tuple[ResolvedSellerStock, ...]
    route_history: tuple[PlanningRouteHistory, ...]
    destination_signals: tuple[PlanningDestinationSignal, ...]
    optimizer_thresholds: OptimizerThresholds
    tariff_source_name: str
    tariff_report_generated_at: str | None
```

The basis contains normalized tariff rows, not uploaded file bytes. `ProductEconomicsInput.available_qty` is intentionally absent; seller stock has its own resolved contract.

- [ ] **Step 1: Add identity/validation tests**

Reject duplicate keys:

```text
PlanningSkuOrigin: (sku, origin)
PlanningRouteHistory: (sku, origin, destination)
PlanningDestinationSignal: (sku, destination)
RouteCostIndex inside basis: (origin, destination)
PlanningProductInput: sku
```

Validate all quantities/nonnegative Decimal values and ensure every `PlanningSkuOrigin.feasibility` identity equals its own `sku/origin`.

- [ ] **Step 2: Add self-contained tariff/product test**

Construct a basis with one normalized `TariffRow` and one `PlanningProductInput`; serialize with existing `wire()` and assert all values needed to perform an exact direct lookup are present without `UnitEconomicsResult` or raw report bytes.

- [ ] **Step 3: Add no-SKU-route-matrix test**

Two SKUs using the same tariff matrix must still produce:

```python
len(basis.tariff_rows) == len(source_tariffs.records)
```

not one copied tariff row per SKU.

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contracts do not exist.

- [ ] **Step 5: Implement immutable contracts and validation**

Append optional planning fields to the end of `AnalysisSnapshot`:

```python
planning_basis: PlanningBasis | None = None
planning_snapshot: PlanningSnapshot | None = None
```

Use forward annotations where required to keep file-order definitions valid.

- [ ] **Step 6: Run contract tests**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: contract slice passes.

- [ ] **Step 7: Commit**

```bash
git add backend/decision/contracts.py tests/decision/test_planning.py
git commit -m "feat: define compact planning basis"
```

---

### Task 4: Define rich PlanningSnapshot views and cluster-level physical roll-up

**Files:**
- Modify: `backend/decision/contracts.py`
- Modify: `tests/decision/test_planning.py`

**Contracts:**

```python
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
    origin_capacity_kind: RestrictionCapacityKind
    origin_capacity_qty: int | None
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

- [ ] **Step 1: Add destination conservation validation**

Reject a destination view unless:

```text
final_allocated_qty
+ network_uncovered_qty
+ allocation_blocked_qty
+ stock_uncovered_qty
= target_qty
```

Also require `final_allocated_qty == sum(leg.final_allocated_qty)`.

- [ ] **Step 2: Add rich-leg validation**

Reject:

- `final_allocated_qty > desired_qty`;
- finite capacity without `origin_capacity_qty`;
- unlimited/unknown capacity with a numeric capacity;
- LOCAL leg with non-null external route index;
- route index coverage/spread present without route index value.

- [ ] **Step 3: Add cluster-level roll-up contract test**

Given final legs:

```text
SKU-A Москва -> Москва = 10
SKU-B Москва -> Казань = 20
SKU-C Питер  -> Казань = 5
```

assert there are exactly two origin views. Moscow is:

```text
total_qty=30
own_destination_qty=10
external_destination_qty=20
destinations:
  Москва 10 -> SKU-A 10
  Казань 20 -> SKU-B 20
```

- [ ] **Step 4: Run and verify RED/GREEN cycle**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Implement only enough validation/contracts to make these tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/decision/contracts.py tests/decision/test_planning.py
git commit -m "feat: define authoritative planning views"
```

---

### Task 5: Build the full physical origin universe from restrictions

**Files:**
- Create: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Public helper:**

```python
def build_planning_origins(
    restrictions: Iterable[RestrictionRecord],
) -> tuple[PlanningSkuOrigin, ...]:
```

- [ ] **Step 1: Add no-demand-origin regression**

Fixture:

```text
SKU-1 has demand only in Казань
restrictions allow SKU-1 in Москва with FINITE 100
```

Assert `build_planning_origins()` contains `SKU-1 × Москва` even though Moscow has no demand/recommendation row. This proves planner origins are not inherited from legacy destination candidates.

- [ ] **Step 2: Add prohibited/unknown capacity cases**

For every `SKU × cluster` appearing in normalized restriction rows, group its warehouse rows, create `WarehouseCapability` values using the explicit PR-B capacity state, and call `assess_feasibility()`.

Assert prohibited rows remain infeasible and allowed-but-UNKNOWN capacity remains represented as allowed with unknown capacity; Coverage Planner will fail-close it later.

- [ ] **Step 3: Implement grouped origin assessment**

Create warehouse capabilities only from restrictions rows with canonical cluster identity:

```python
WarehouseCapability(
    warehouse=row.warehouse,
    cluster_id=row.cluster,
    max_supply_qty=row.max_supply_qty,
    capacity_kind=row.capacity_kind,
)
```

Group by `(sku, cluster)` and call `assess_feasibility()` with all restriction rows for that SKU plus the grouped capabilities.

- [ ] **Step 4: Define candidate supply clusters**

The selector universe is sorted unique `origin_cluster_id` from `PlanningSkuOrigin` rows where `feasibility.allowed` is true. Capacity UNKNOWN does not make the cluster disappear from the selector; it simply cannot become a usable origin for that SKU until capacity is proven.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/decision/test_planning.py tests/supply/test_placement.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build complete planning origin universe"
```

---

### Task 6: Build PlanningBasis from one completed upstream analysis

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Public interface:**

```python
def build_planning_basis(
    *,
    analysis_snapshot_id: str,
    scenario: ScenarioSettings,
    restrictions: Iterable[RestrictionRecord],
    tariffs: ImportResult[TariffRow],
    products: Iterable[ProductEconomicsInput],
    economics_settings: EconomicsSettings,
    needs: Iterable[NeedComparison],
    demand_estimates: Iterable[DemandEstimate],
    observed_routes: RouteProfile,
    clean_routes: CleanRouteResult,
    distortions: Iterable[RecommendationDistortionSignal],
    resolved_seller_stock: Iterable[ResolvedSellerStock],
    optimizer_thresholds: OptimizerThresholds,
) -> PlanningBasis:
```

- [ ] **Step 1: Add target-family tests**

For a complete need:

```text
Calculated target = calculated_need_qty
Safe target = min(calculated_need_qty, ozon_recommended_qty)
```

If Calculated need is missing, emit no Calculated target for that destination. If either Safe input is missing, emit no Safe target. Never coerce missing target evidence to zero.

- [ ] **Step 2: Add tariff matrix / RouteCostIndex reuse test**

With two SKUs and one shared tariff matrix assert:

```python
basis.tariff_rows == tariffs.records
basis.route_cost_indices == build_route_cost_indices(tariffs)
```

There is no SKU copy of either collection.

- [ ] **Step 3: Add product-input test**

Project every normalized `ProductEconomicsInput` to exactly:

```python
PlanningProductInput(
    sku=item.sku,
    price=item.price,
    cost=item.cost,
    commission_rate=item.commission_rate,
    volume_liters=item.volume_liters,
)
```

Do not copy `available_qty`.

- [ ] **Step 4: Add sparse route-history projection test**

For every exact `SKU × origin × destination` that appears in observed/clean route evidence, create one `PlanningRouteHistory`:

```text
HIGH   when exact clean evidence exists
MEDIUM when exact observed evidence exists but clean does not
LOW    is not persisted as a row; absence means LOW when planning
```

`observed_flow_qty` and `observed_flow_share` are informational. They never determine desired quantities.

- [ ] **Step 5: Add destination signal projection**

For each emitted destination target identity store demand confidence and any distortion confidence. Missing demand estimate uses `SignalConfidence.LOW`; missing distortion signal uses `None`.

- [ ] **Step 6: Implement deterministic basis ID**

Construct the complete immutable basis fields except `basis_id`, serialize them with the existing canonical `wire()` representation plus `analysis_snapshot_id`, hash UTF-8 JSON with sorted keys using SHA-256, and use the hex digest as `basis_id`. Two equal inputs must produce the same basis ID.

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build self-contained planning basis"
```

---

### Task 7: Reconcile the global selected network deterministically

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Interface:**

```python
def reconcile_supply_network(
    candidate_clusters: Iterable[str],
    persisted_network: tuple[str, ...] | None,
    requested_network: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
```

- [ ] **Step 1: Add exact first-use tests**

```text
persisted=None, requested=None, candidates=(Kazan,Moscow,Peter)
→ applied=(Kazan,Moscow,Peter)

persisted=(), requested=None
→ applied=()
```

- [ ] **Step 2: Add no-silent-expansion tests**

```text
persisted=(Moscow,Peter), candidates=(Kazan,Moscow,Peter), requested=None
→ applied=(Moscow,Peter)
```

Kazan stays unselected.

- [ ] **Step 3: Add disappeared-cluster reconciliation**

```text
persisted=(Moscow,Old), candidates=(Moscow,Peter)
→ applied=(Moscow)
→ warning SUPPLY_NETWORK_CLUSTER_REMOVED:Old
```

- [ ] **Step 4: Add explicit-request validation**

Requested empty tuple is valid. Requested duplicates, blank IDs or a cluster outside current candidates raise `ValueError("INVALID_SELECTED_SUPPLY_NETWORK")`; do not silently drop an invalid requested item.

- [ ] **Step 5: Implement and run tests**

```bash
python -m pytest tests/decision/test_planning.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: reconcile selected supply network"
```

---

### Task 8: Execute one plan family from PlanningBasis

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Private helper:**

```python
def _build_family_snapshot(
    basis: PlanningBasis,
    selected_supply_network: tuple[str, ...],
    plan_family: PlanFamily,
) -> PlanningFamilySnapshot:
```

- [ ] **Step 1: Add exact direct-fee route test**

Create a basis where Kazan target is 100, selected network is Moscow+Peter, capacities are 70/100, and normalized tariff rows make:

```text
Moscow -> Kazan = 47
Peter  -> Kazan = 52
```

Assert desired/final placement fills Moscow 70 then Peter 30 when stock and economics are sufficient.

- [ ] **Step 2: Add RouteCostIndex exact-fee tie test**

Make both direct fees 50 but pair indices Moscow 0.95 and Peter 0.72. Assert Peter is preferred, proving PR-B receives the pair-level index as secondary topology evidence.

- [ ] **Step 3: Build route evidence only for selected usable origins**

For each SKU/family destination target and each selected `PlanningSkuOrigin` for that SKU:

1. skip origin when feasibility is not allowed, capacity is UNKNOWN or finite zero;
2. for `origin == destination`, Coverage Planner handles LOCAL without external route evidence;
3. for non-local pair, reconstruct an `ImportResult` from `basis.tariff_rows` and stored tariff metadata, then call `quote_direct_route()` with the current `PlanningProductInput.volume_liters/price`;
4. look up pair-level `RouteCostIndex` by `(origin,destination)`;
5. look up sparse `PlanningRouteHistory`; absence means `RouteConfidence.LOW`, observed qty 0/share None;
6. create PR-B `RoutePlanningEvidence` primitive with direct fee/index/confidence/history.

Build the tariff `ImportResult` once per family execution, not once per candidate route.

- [ ] **Step 4: Call Coverage Planner per SKU**

Group targets by SKU and call `plan_coverage()` with the global selected network, SKU-origin feasibility and route evidence. Preserve PR-B network gaps unchanged.

- [ ] **Step 5: Resolve direct/local allocation economics only for desired legs**

For every desired leg:

```python
quote = quote_direct_route(
    tariff_result,
    origin_cluster_id=leg.origin_cluster_id,
    destination_cluster_id=leg.destination_cluster_id,
    volume_liters=product.volume_liters,
    price=product.price,
)
unit = calculate_direct_route_economics(
    ProductEconomicsInput(
        product.sku,
        "",
        product.cost,
        None,
        product.price,
        product.commission_rate,
        product.volume_liters,
    ),
    leg.origin_cluster_id,
    quote,
    basis.economics_settings,
)
allocation_economics = project_allocation_economics(unit)
```

This applies to both ROUTE and LOCAL desired legs. LOCAL is excluded only from `RouteCostIndex`; it is not exempt from exact tariff/economics completeness.

- [ ] **Step 6: Apply seller-stock and missing-stock causality**

When `ResolvedSellerStock.complete` is true, call `allocate_coverage_legs()` with the resolved quantity.

When seller stock is incomplete, do not call the allocator with zero. Emit zero final allocations for every desired leg and classify all desired quantity as `allocation_blocked_qty` with the stock reason code (`MISSING_SELLER_AVAILABLE_STOCK` or `CONFLICTING_FBS_AVAILABLE_STOCK`). `stock_uncovered_qty` remains zero because a shortage was not proven.

- [ ] **Step 7: Assemble rich `PlanningLegView`**

For each desired/final leg join:

- direct route fee from its exact quote;
- pair-level RouteCostIndex value/coverage/IQR for non-local routes, otherwise null;
- `PlanningSkuOrigin.feasibility.capacity_kind/max_supply_qty`;
- route confidence/history evidence;
- final eligibility/profit/reason codes.

No frontend join is required for these fields.

- [ ] **Step 8: Assemble destination and cluster-level origin views**

Destination conservation must be:

```text
final allocated
+ network uncovered
+ allocation blocked
+ stock uncovered
= target
```

Build origin roll-up from **final allocated legs only**, grouped first by origin cluster across all SKUs, then destination, then SKU. For every origin:

```text
total_qty = own_destination_qty + external_destination_qty
```

- [ ] **Step 9: Add both-family/global conservation tests**

Run the same invariants for Safe and Calculated families. Expected profit equals the sum of final-leg expected profit.

- [ ] **Step 10: Run focused suites**

```bash
python -m pytest tests/decision/test_planning.py tests/supply/test_coverage.py tests/supply/test_optimizer.py tests/economics/test_tariffs.py tests/economics/test_unit.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: execute selected-network planning"
```

---

### Task 9: Build immutable PlanningSnapshot

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/decision/test_planning.py`

**Public interface:**

```python
def build_planning_snapshot(
    basis: PlanningBasis,
    selected_supply_network: tuple[str, ...],
    reconciliation_warnings: tuple[str, ...] = (),
) -> PlanningSnapshot:
```

- [ ] **Step 1: Add ID/immutability test**

Equal basis + selected network must produce equal deterministic family contents but a new `planning_snapshot_id`/`created_at` each successful call. `basis_id` and `analysis_snapshot_id` are copied exactly.

- [ ] **Step 2: Build both families**

Call `_build_family_snapshot()` once for `PlanFamily.SAFE` and once for `PlanFamily.CALCULATED`; never sum families together.

- [ ] **Step 3: Canonicalize applied network**

Store `tuple(sorted(selected_supply_network))` and the reconciliation warnings exactly as returned by `reconcile_supply_network()`.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest tests/decision/test_planning.py -q
git add backend/decision/planning.py tests/decision/test_planning.py
git commit -m "feat: build immutable planning snapshot"
```

---

### Task 10: Add strict PlanningBasis wire roundtrip

**Files:**
- Create: `backend/decision/planning_wire.py`
- Create: `tests/decision/test_planning_wire.py`

**Public interface:**

```python
def planning_basis_from_wire(value: object) -> PlanningBasis:
```

- [ ] **Step 1: Add exact roundtrip test**

Build a real `PlanningBasis`, serialize with existing `wire()`, parse it, and assert equality.

- [ ] **Step 2: Add strict rejection tests**

Reject:

- unknown top-level field;
- missing required field;
- malformed Decimal string;
- unknown enum value;
- duplicate tariff/index/origin/signal identities;
- non-list collection field;
- `analysis_snapshot_id` or `basis_id` blank.

- [ ] **Step 3: Implement explicit field-by-field parser**

Do not use `PlanningBasis(**payload)` on arbitrary JSON. Parse every nested dataclass, enum, Decimal and tuple explicitly. Reuse `ProjectValidationError`-style strict helpers locally but return `ValueError("INVALID_PLANNING_BASIS")` for public parse failure.

- [ ] **Step 4: Recompute and verify basis ID**

After parsing all business fields, recompute the canonical SHA-256 basis hash using the same helper as `build_planning_basis()`. Reject the request when the recomputed hash differs from transmitted `basis_id`.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/decision/test_planning_wire.py -q
git add backend/decision/planning_wire.py tests/decision/test_planning_wire.py
git commit -m "feat: validate planning basis wire"
```

---

### Task 11: Attach planning to both full-analysis transports

**Files:**
- Modify: `backend/decision/__init__.py`
- Modify: `backend/api.py`
- Modify: `tests/api/test_analysis.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

- [ ] **Step 1: Add selected-network request parsing tests**

Both `/api/analysis` and `/api/analysis/stream` must accept multipart field:

```text
selected_supply_clusters = JSON array of unique nonblank strings
```

Missing field means `requested_network=None`; `[]` is an explicit empty network. Invalid JSON, non-list value, duplicate/blank/non-string member returns the existing structured HTTP 400 form with code `INVALID_SELECTED_SUPPLY_NETWORK`.

Put parsing in the shared request-preparation path used by both transports so semantics cannot drift.

- [ ] **Step 2: Add response-shape test**

A successful full analysis still returns all current root fields. Inside `response["snapshot"]` additionally assert:

```python
response["snapshot"]["planning_basis"]["basis_id"]
response["snapshot"]["planning_snapshot"]["analysis_snapshot_id"] == response["snapshot"]["snapshot_id"]
```

- [ ] **Step 3: Integrate after the existing AnalysisSnapshot is assembled**

Do not introduce snapshot IDs into `analyze()`. The order is:

```text
result = analyze(...)
base_snapshot = assemble_snapshot(...)
basis = build_planning_basis(analysis_snapshot_id=base_snapshot.snapshot_id, ...)
selected, warnings = reconcile_supply_network(
    basis.candidate_supply_clusters,
    project.applied_supply_network,
    requested_network,
)
planning = build_planning_snapshot(basis, selected, warnings)
snapshot = replace(base_snapshot, planning_basis=basis, planning_snapshot=planning)
```

Use resolved normalized restrictions/tariffs/products already produced by the current full-analysis request.

- [ ] **Step 4: Persist applied network only after successful planning assembly**

After `snapshot` is complete, persist:

```python
save_project_atomic(
    PROJECT_PATH,
    replace(project, applied_supply_network=planning.applied_supply_network),
)
```

Do not persist the request draft before planning succeeds. Preserve all other Project fields.

- [ ] **Step 5: Run full-analysis regressions**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS. Legacy root/wire fields remain readable before PR-E switches UI ownership.

- [ ] **Step 6: Commit**

```bash
git add backend/decision/__init__.py backend/api.py tests/api/test_analysis.py
git commit -m "feat: attach selected-network planning to analysis"
```

---

### Task 12: Add stateless `/api/replan`

**Files:**
- Modify: `backend/api.py`
- Create: `tests/api/test_replan.py`

**Request JSON:**

```json
{
  "planning_basis": {
    "basis_id": "0123456789abcdef",
    "analysis_snapshot_id": "analysis-1",
    "scenario": {
      "horizon_days": 56,
      "include_inbound": true,
      "objective": "max_margin"
    },
    "candidate_supply_clusters": ["Москва", "Питер"],
    "targets": [],
    "sku_origins": [],
    "tariff_rows": [],
    "route_cost_indices": [],
    "products": [],
    "economics_settings": {
      "acquiring_rate": "0",
      "advertising_rate": "0",
      "buyout_rate": "1",
      "fixed_fbo_fee": "0",
      "tax_system": "usn_income",
      "income_tax_rate": "0",
      "vat_rate": "0",
      "co_invest_rate": "0"
    },
    "seller_stock": [],
    "route_history": [],
    "destination_signals": [],
    "optimizer_thresholds": {
      "min_profit_per_unit": "0",
      "min_margin_rate": "0",
      "min_roi": "0"
    },
    "tariff_source_name": "tariffs.xlsx",
    "tariff_report_generated_at": null
  },
  "selected_supply_clusters": ["Москва"]
}
```

The fixture basis ID in the real test must be the canonical hash for the shown payload, generated by the test helper; do not hardcode the illustrative string.

**Response:**

```json
{
  "api_version": 1,
  "kind": "planning",
  "planning_snapshot": {
    "analysis_snapshot_id": "analysis-1",
    "applied_supply_network": ["Москва"]
  }
}
```

The real response contains the complete `PlanningSnapshot` wire.

- [ ] **Step 1: Add successful network-only test**

Start from a real basis returned by full analysis, change selected network, post to `/api/replan`, and assert:

```text
basis_id unchanged
analysis_snapshot_id unchanged
planning_snapshot_id changed
applied network equals request
destination targets unchanged
physical origin roll-up changes when network changes
```

- [ ] **Step 2: Prove no upstream recomputation**

Monkeypatch these functions to raise during `/api/replan`:

```text
import_availability
import_restrictions
import_orders
estimate_destination_demand
detect_stockouts
build_episode_clean_route_profile
build_route_cost_indices
```

The request must still succeed.

Do **not** monkeypatch `quote_direct_route` or `calculate_direct_route_economics`: downstream replan is intentionally allowed to call them for the selected network.

- [ ] **Step 3: Add invalid-request tests**

Reject with HTTP 400:

```text
malformed planning basis -> INVALID_PLANNING_BASIS
duplicate/blank/non-string selected cluster -> INVALID_SELECTED_SUPPLY_NETWORK
selected cluster outside basis.candidate_supply_clusters -> INVALID_SELECTED_SUPPLY_NETWORK
```

- [ ] **Step 4: Implement endpoint**

Parse basis through `planning_basis_from_wire()`, validate selected network, then call:

```python
planning_snapshot = build_planning_snapshot(
    basis,
    tuple(sorted(selected_supply_clusters)),
)
```

No call to `analyze()` exists in this endpoint.

- [ ] **Step 5: Persist only after successful plan build**

Load current Project, replace only `applied_supply_network`, save atomically, then return response. Any parsing/planning failure leaves Project unchanged.

- [ ] **Step 6: Run replan tests**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/api.py tests/api/test_replan.py
git commit -m "feat: replan selected supply network without reanalysis"
```

---

### Task 13: Final backend verification

**Files:** no new production files

- [ ] **Step 1: Run planning-focused suites**

```bash
python -m pytest \
  tests/economics/test_tariffs.py \
  tests/economics/test_unit.py \
  tests/ingestion/test_restrictions.py \
  tests/supply/test_placement.py \
  tests/supply/test_coverage.py \
  tests/supply/test_optimizer.py \
  tests/decision/test_planning.py \
  tests/decision/test_planning_wire.py \
  tests/api/test_analysis.py \
  tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run legacy Product Completion acceptance**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Static boundary scan**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path('backend/api.py').read_text('utf-8')
start = text.index('@router.post("/api/replan")')
section = text[start:]
for forbidden in (
    'analyze(',
    'estimate_destination_demand(',
    'detect_stockouts(',
    'build_episode_clean_route_profile(',
    'build_route_cost_indices(',
):
    assert forbidden not in section, forbidden
print('replan boundary scan: ok')
PY
```

Expected: `replan boundary scan: ok`.

- [ ] **Step 5: Commit verification-only corrections when present**

```bash
git add backend tests
if ! git diff --cached --quiet; then
  git commit -m "test: harden selected-network planning boundary"
fi
```

---

## PR-D Acceptance Gate

PR-D is complete only when all are true:

1. Project schema v1 loads safely and saves as v2.
2. `None` and empty applied network remain semantically distinct.
3. First-use default, no-silent-expansion and disappeared-cluster reconciliation follow the approved rules.
4. Seller stock comes from current analysis resolution; unknown/conflicting stock never becomes zero.
5. Planning origins include restriction-allowed supply clusters even when those clusters have no destination demand.
6. Restrictions are the only physical feasibility/capacity source for selected-network planning.
7. The normalized customer-delivery tariff matrix exists once in PlanningBasis, not once per SKU.
8. `RouteCostIndex` is computed once per full matrix and stored once per route pair.
9. Exact direct tariff/economics is recalculated downstream only for routes needed by the selected network; there is no persisted all-SKU route-economics matrix.
10. Cross-docking tariffs never enter PlanningBasis or planning execution.
11. LOCAL remains LOCAL-first but still receives exact direct/local economics before allocation eligibility.
12. PlanningSnapshot owns rich final legs, three causal gap types and backend cluster-level origin roll-up.
13. Full analysis may accept a selected network without changing upstream demand/history identities.
14. `/api/replan` does not rerun ingestion, demand, stockout, clean routes or RouteCostIndex derivation.
15. `/api/replan` is allowed to perform direct tariff lookup/economics from the immutable normalized basis.
16. Failed full analysis/replan never persists the draft network.
17. Empty selected network is valid and remains empty.
18. Current AnalysisSnapshot root/wire remains compatible until PR-E migrates UI ownership.
19. Focused, Product Completion and full backend suites are green.
