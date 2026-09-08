# PR-D Planning Snapshot, Persistence & Replan API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate PR-A–C into the backend planning pipeline, introduce an immutable `PlanningSnapshot` derived from an immutable `AnalysisSnapshot`, persist the successfully applied supply network, and expose a stateless network-only `/api/replan` path that never reruns imports/demand/stockout/history.

**Architecture:** Keep `AnalysisSnapshot` as the immutable upstream analytical base and add a bounded `PlanningBasis` sufficient for deterministic downstream replanning. Full analysis returns the existing compatible analysis payload plus an initial authoritative PlanningSnapshot; network-only replan accepts the base analysis identity + PlanningBasis + selected cluster IDs and returns a new PlanningSnapshot only. Project JSON moves to schema v2 with nullable applied-network persistence so `null` (“never applied”) differs from `[]` (“explicitly applied empty network”). Legacy plan fields inside AnalysisSnapshot remain transitional compatibility fields until PR-E switches the UI; a replan never mutates them.

**Tech Stack:** Python 3, FastAPI, frozen dataclasses, `Decimal`, Project JSON atomic persistence, pytest; PR-A direct quotes, PR-B Coverage Planner, PR-C coverage allocator; no new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Network-only replan must never mutate or relabel an existing AnalysisSnapshot.
- Replan must not rerun file imports, daily demand, DemandEstimate, stockout detection, route cleaning or historical Flow aggregation.
- `PlanningSnapshot.analysis_snapshot_id` must match its immutable base.
- Planning quantities are authoritative in PlanningSnapshot; legacy AnalysisSnapshot plan fields are transitional only and are not updated by `/api/replan`.
- PlanningBasis must be bounded and contain no raw orders, buyer PII or unbounded historical daily/route data.
- Do not persist a SKU-specific route-affinity matrix. Reusable tariff evidence remains volume/source-band route data plus SKU volume/price lookup inputs.
- First-run network default occurs only when persisted applied network is `None`; an explicitly persisted empty tuple stays empty.
- Newly appearing candidate clusters after a persisted selection default unselected.
- Disappeared/unresolved previously selected clusters are removed from the effective network and surfaced as reconciliation warnings.
- Draft network is persisted only after the corresponding full analysis/replan succeeds.
- Full analysis with upstream + network changes must calculate the initial PlanningSnapshot for the same requested draft network.
- `MAX_MARGIN` remains fixed; Safe and Calculated are separate plan families and are never summed together.
- Maintain API v1 compatibility for existing full-analysis consumers until PR-E migrates the frontend.
- Use TDD; no frontend rendering/state changes in PR-D.

---

## File Structure

- Modify `backend/project.py` — Project schema v2, nullable applied supply network, v1→v2 load compatibility.
- Modify `tests/test_project.py` — migration, null/empty distinction, atomic round-trip.
- Modify `backend/decision/contracts.py` — PlanningBasis/PlanningSnapshot presentation contracts and AnalysisSnapshot planning-basis field.
- Create `backend/decision/planning.py` — candidate-universe reconciliation, bounded basis assembly, plan-family orchestration, PlanningSnapshot assembly and origin rollups.
- Modify `backend/decision/__init__.py` — export planning contracts/functions.
- Modify `backend/application.py` — expose the normalized upstream pieces needed to build PlanningBasis without changing demand/stockout semantics.
- Modify `backend/decision/snapshot.py` — attach PlanningBasis to AnalysisSnapshot while retaining transitional legacy fields.
- Modify `backend/api.py` — selected-network parsing, full-analysis initial PlanningSnapshot, stateless `POST /api/replan`, successful persistence only.
- Modify `tests/api/test_analysis.py` — full-result compatibility + initial PlanningSnapshot.
- Create `tests/api/test_replan.py` — network-only contract, stale identity, no-upstream-recompute and failure persistence.
- Modify `tests/api/test_product_completion_acceptance.py` — destination identity and full-pipeline conservation acceptance.
- Modify `tests/api/test_project_mappings.py` only if Project schema fixture construction requires the new optional field.

No frontend JS/CSS/HTML or DESIGN/UX contract edits belong in PR-D.

---

### Task 1: Add nullable applied network to Project schema v2

**Files:**
- Modify: `backend/project.py`
- Modify: `tests/test_project.py`

**Interfaces:**
- New schema:

```python
SCHEMA_VERSION = 2

@dataclass(frozen=True, slots=True)
class Project:
    ...existing fields...
    applied_supply_cluster_ids: tuple[str, ...] | None = None
```

Semantics:
- `None` = no successful network has ever been applied; first-run default is still allowed.
- `()` = user successfully applied an empty network; do not replace with defaults.
- non-empty tuple = last successfully applied global network.

- [ ] **Step 1: Write failing null-vs-empty round-trip tests**

```python
def test_project_v2_round_trip_preserves_never_applied_network(tmp_path):
    path = tmp_path / "project.json"
    save_project_atomic(path, Project(applied_supply_cluster_ids=None))
    loaded = load_project(path)
    assert loaded.applied_supply_cluster_ids is None


def test_project_v2_round_trip_preserves_explicit_empty_network(tmp_path):
    path = tmp_path / "project.json"
    save_project_atomic(path, Project(applied_supply_cluster_ids=()))
    loaded = load_project(path)
    assert loaded.applied_supply_cluster_ids == ()
```

- [ ] **Step 2: Write failing v1 migration test**

Use a real minimal schema-v1 payload with no network field:

```python
def test_load_schema_v1_migrates_network_to_never_applied(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps(valid_v1_payload()), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.schema_version == 2
    assert loaded.applied_supply_cluster_ids is None
```

The loaded in-memory Project uses current schema v2 even though the source file was v1.

- [ ] **Step 3: Run project tests and verify RED**

```bash
python -m pytest tests/test_project.py -q
```

Expected: new field/schema migration tests fail.

- [ ] **Step 4: Implement explicit schema-version dispatch**

Do not loosen `_strict()` globally. Instead:

```python
SCHEMA_VERSION = 2
_V1_TOP_FIELDS = {...existing v1 fields...}
_V2_TOP_FIELDS = _V1_TOP_FIELDS | {"applied_supply_cluster_ids"}
```

In `load_project()`:

```python
schema_version = payload.get("schema_version")
if schema_version == 1:
    _strict(payload, _V1_TOP_FIELDS, "project")
    applied_supply_cluster_ids = None
elif schema_version == 2:
    _strict(payload, _V2_TOP_FIELDS, "project")
    applied_supply_cluster_ids = _load_cluster_ids(
        payload["applied_supply_cluster_ids"]
    )
else:
    raise ProjectValidationError("Missing or unsupported schema version.")
```

Return an in-memory v2 `Project` in both paths.

- [ ] **Step 5: Validate and serialize the new field canonically**

```python
def _validate_applied_network(value):
    if value is None:
        return
    if not isinstance(value, tuple):
        raise ProjectValidationError("Applied supply network must be a tuple or None.")
    if any(not isinstance(x, str) or not x.strip() for x in value):
        raise ProjectValidationError("Applied supply cluster IDs must be nonblank strings.")
    if len(value) != len(set(value)):
        raise ProjectValidationError("Applied supply cluster IDs must be unique.")
```

Serialize non-None tuples as a stable sorted JSON list; serialize never-applied as JSON `null`.

- [ ] **Step 6: Run project tests and verify GREEN**

```bash
python -m pytest tests/test_project.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit persistence migration**

```bash
git add backend/project.py tests/test_project.py
git commit -m "feat: persist applied supply network"
```

---

### Task 2: Define bounded PlanningBasis and immutable PlanningSnapshot contracts

**Files:**
- Modify: `backend/decision/contracts.py`
- Test: `tests/api/test_analysis.py`

**Interfaces:**

Define bounded reusable planning data without raw order/history matrices:

```python
@dataclass(frozen=True, slots=True)
class PlanningTarget:
    sku: str
    destination_cluster_id: str
    safe_target_qty: int | None
    calculated_target_qty: int | None
    demand_confidence: SignalConfidence
    distortion_confidence: SignalConfidence | None


@dataclass(frozen=True, slots=True)
class PlanningProduct:
    sku: str
    article: str
    product_name: str
    product: ProductEconomicsInput
    seller_available_stock: int | None


@dataclass(frozen=True, slots=True)
class PlanningOriginFeasibility:
    sku: str
    origin_cluster_id: str
    feasibility: SupplyFeasibility
    route_confidence: RouteConfidence


@dataclass(frozen=True, slots=True)
class PlanningBasis:
    targets: tuple[PlanningTarget, ...]
    products: tuple[PlanningProduct, ...]
    origins: tuple[PlanningOriginFeasibility, ...]
    tariff_rows: tuple[TariffRow, ...]
    economics_settings: EconomicsSettings
    optimizer_thresholds: OptimizerThresholds
    candidate_supply_cluster_ids: tuple[str, ...]
```

`tariff_rows` is filtered to canonical resolved candidate-cluster identities and the tariff rows relevant to active product volume/price lookup; it is reusable route evidence, not a SKU affinity matrix.

Define planning output contracts:

```python
@dataclass(frozen=True, slots=True)
class OriginSupplyDestinationBreakdown:
    destination_cluster_id: str
    quantity: int


@dataclass(frozen=True, slots=True)
class OriginSupplyRow:
    sku: str
    origin_cluster_id: str
    total_qty: int
    own_destination_qty: int
    other_destination_qty: int
    destinations: tuple[OriginSupplyDestinationBreakdown, ...]


@dataclass(frozen=True, slots=True)
class DestinationPlanRow:
    sku: str
    destination_cluster_id: str
    target_qty: int
    covered_qty: int
    network_uncovered_qty: int
    allocation_blocked_qty: int
    stock_uncovered_qty: int
    origins: tuple[OriginSupplyDestinationBreakdown, ...]


@dataclass(frozen=True, slots=True)
class PlanFamilySnapshot:
    plan_family: PlanFamily
    final_legs: tuple[FinalCoverageLeg, ...]
    destination_rows: tuple[DestinationPlanRow, ...]
    origin_rows: tuple[OriginSupplyRow, ...]
    total_target_qty: int
    total_covered_qty: int
    total_network_uncovered_qty: int
    total_allocation_blocked_qty: int
    total_stock_uncovered_qty: int
    objective_profit: Decimal


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    planning_snapshot_id: str
    analysis_snapshot_id: str
    created_at: str
    applied_supply_cluster_ids: tuple[str, ...]
    reconciliation_warnings: tuple[str, ...]
    safe: PlanFamilySnapshot
    calculated: PlanFamilySnapshot
```

Append to `AnalysisSnapshot`:

```python
planning_basis: PlanningBasis
```

Use exact repository dataclass validation style; no raw orders/daily facts belong in PlanningBasis.

- [ ] **Step 1: Write failing contract/wire-shape test**

```python
def test_analysis_snapshot_exposes_bounded_planning_basis(...):
    payload = run_analysis_request(...)
    basis = payload["planning_basis"]
    assert "targets" in basis
    assert "products" in basis
    assert "origins" in basis
    assert "tariff_rows" in basis
    serialized = json.dumps(basis, ensure_ascii=False)
    assert "buyer_name" not in serialized
    assert "daily_facts" not in serialized
    assert "orders" not in basis
```

- [ ] **Step 2: Run focused API test and verify RED**

```bash
python -m pytest tests/api/test_analysis.py -q
```

Expected: PlanningBasis fields are absent.

- [ ] **Step 3: Implement contracts only**

Add the dataclasses and validations, but do not assemble them yet. Keep existing AnalysisSnapshot fields in place for compatibility.

- [ ] **Step 4: Commit contract slice**

```bash
git add backend/decision/contracts.py tests/api/test_analysis.py
git commit -m "feat: define planning snapshot contracts"
```

---

### Task 3: Build candidate universe and reconcile requested/persisted network

**Files:**
- Create: `backend/decision/planning.py`
- Create/Modify: `tests/api/test_replan.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class SupplyNetworkResolution:
    candidate_cluster_ids: tuple[str, ...]
    applied_cluster_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def resolve_supply_network(
    *,
    restrictions: Iterable[RestrictionRecord],
    requested_cluster_ids: Iterable[str] | None,
    persisted_cluster_ids: tuple[str, ...] | None,
) -> SupplyNetworkResolution:
    ...
```

Precedence:
1. Explicit request if supplied.
2. Persisted network if not `None`.
3. First-run default: all current candidate clusters.

- [ ] **Step 1: Write failing first-run/default test**

```python
def test_first_run_defaults_to_all_current_allowed_clusters():
    result = resolve_supply_network(
        restrictions=(allowed("SKU-1", "W1", "Москва"), allowed("SKU-2", "W2", "Казань")),
        requested_cluster_ids=None,
        persisted_cluster_ids=None,
    )
    assert result.applied_cluster_ids == ("Казань", "Москва")
```

Candidate clusters require at least one resolved `RestrictionState.ALLOWED` row with nonblank cluster identity.

- [ ] **Step 2: Write failing persisted-network reconciliation tests**

```python
def test_new_candidate_cluster_is_not_silently_added_to_persisted_network():
    result = resolve_supply_network(
        restrictions=current_allowed_clusters("Москва", "Казань"),
        requested_cluster_ids=None,
        persisted_cluster_ids=("Москва",),
    )
    assert result.applied_cluster_ids == ("Москва",)


def test_disappeared_persisted_cluster_is_removed_with_warning():
    result = resolve_supply_network(
        restrictions=current_allowed_clusters("Казань"),
        requested_cluster_ids=None,
        persisted_cluster_ids=("Москва", "Казань"),
    )
    assert result.applied_cluster_ids == ("Казань",)
    assert result.warnings


def test_explicit_empty_network_is_not_replaced_with_all_candidates():
    result = resolve_supply_network(
        restrictions=current_allowed_clusters("Москва", "Казань"),
        requested_cluster_ids=(),
        persisted_cluster_ids=("Москва",),
    )
    assert result.applied_cluster_ids == ()
```

- [ ] **Step 3: Run focused tests and verify RED**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: module/function absent.

- [ ] **Step 4: Implement deterministic reconciliation**

Normalize requested IDs by stripping, reject blanks/duplicates at API parsing, then in domain reconciliation intersect with current candidate universe. Unknown requested IDs are excluded with a warning rather than fabricated as candidates.

Use stable sorted tuples throughout.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: network reconciliation tests pass.

- [ ] **Step 6: Commit network-resolution slice**

```bash
git add backend/decision/planning.py tests/api/test_replan.py
git commit -m "feat: reconcile applied supply network"
```

---

### Task 4: Build bounded PlanningBasis from full-analysis facts

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/decision/planning.py`
- Modify: `backend/decision/snapshot.py`
- Modify: `backend/decision/__init__.py`
- Modify: `tests/api/test_analysis.py`

**Interfaces:**

```python
def build_planning_basis(
    *,
    needs,
    demand_estimates,
    distortions,
    products,
    seller_stock_by_sku,
    feasibility_by_sku_origin,
    route_confidence_by_sku_origin,
    tariffs: ImportResult[TariffRow],
    economics_settings: EconomicsSettings,
    optimizer_thresholds: OptimizerThresholds,
    candidate_supply_cluster_ids: tuple[str, ...],
    product_identities,
) -> PlanningBasis:
    ...
```

- [ ] **Step 1: Write failing target-semantics tests**

Assert basis targets are destination-owned and physical capacity is absent from target formulas:

```python
def test_planning_basis_safe_and_calculated_targets_are_destination_owned(...):
    basis = build_basis_from_fixture(
        calculated_need=100,
        ozon_recommendation=80,
        origin_capacity=10,
    )
    target = basis.targets[0]
    assert target.calculated_target_qty == 100
    assert target.safe_target_qty == 80
```

A destination target must not become 10 because an origin capacity is 10.

- [ ] **Step 2: Write tariff-basis reuse test**

Two SKUs in the same volume band must not cause duplicated identical persisted route-affinity rows. PlanningBasis may carry the resolved reusable TariffRows, but not one copied quote matrix per SKU.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
python -m pytest tests/api/test_analysis.py -q
```

Expected: basis is not assembled yet.

- [ ] **Step 4: Expose required normalized full-analysis evidence from `analyze()`**

Do not recompute demand. Extend `AnalysisResult` only with bounded planning source structures that are already known during analysis, such as:
- seller stock by SKU;
- feasibility by `SKU × origin` for candidate origins;
- route confidence by `SKU × origin`;
- product map / resolved tariffs already present in the API orchestration.

Prefer returning the exact maps/tuples already computed in `analyze()` over re-reading source files in snapshot assembly.

- [ ] **Step 5: Build targets exactly from NeedComparison**

```python
calculated = need.calculated_need_qty
safe = (
    min(need.ozon_recommended_qty, need.calculated_need_qty)
    if need.ozon_recommended_qty is not None
    and need.calculated_need_qty is not None
    else None
)
```

No physical feasibility in either formula.

- [ ] **Step 6: Filter reusable tariff evidence without SKU duplication**

Keep only tariff rows whose resolved origin/destination are in the current planning cluster universe and whose volume interval can apply to at least one active product volume. Preserve source lookup dimensions (including price interval) exactly; do not collapse ambiguous rows.

PlanningBasis does not contain observed route quantities or daily facts.

- [ ] **Step 7: Attach PlanningBasis to AnalysisSnapshot**

Extend `assemble_snapshot(...)` with a required `planning_basis` argument and store it on the immutable AnalysisSnapshot. Do not yet remove legacy `safe_allocations`, `calculated_allocations`, summary or decision-row plan fields.

- [ ] **Step 8: Export planning contracts/functions**

Update `backend/decision/__init__.py` in its existing explicit style.

- [ ] **Step 9: Run analysis/API regressions**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; existing payload fields remain available and PlanningBasis is additive.

- [ ] **Step 10: Commit planning-basis slice**

```bash
git add backend/application.py backend/decision/planning.py backend/decision/snapshot.py backend/decision/__init__.py tests/api/test_analysis.py
git commit -m "feat: expose bounded planning basis"
```

---

### Task 5: Build Safe and Calculated PlanningSnapshots from one basis

**Files:**
- Modify: `backend/decision/planning.py`
- Modify: `tests/api/test_replan.py`
- Modify: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**

```python
def build_planning_snapshot(
    *,
    analysis_snapshot_id: str,
    basis: PlanningBasis,
    selected_supply_cluster_ids: tuple[str, ...],
    reconciliation_warnings: tuple[str, ...] = (),
) -> PlanningSnapshot:
    ...
```

For each SKU and each PlanFamily:
1. create `DestinationTarget`s from PlanningBasis targets;
2. generate direct route quotes from reusable tariff rows for needed candidate routes;
3. call PR-B `plan_coverage_for_sku()`;
4. calculate direct route economics for every desired leg;
5. call PR-C `allocate_coverage_legs()`;
6. combine network gaps + allocation gaps into destination rows;
7. roll final legs up by physical origin.

- [ ] **Step 1: Write failing end-to-end one-SKU planning test**

Use:
- Moscow destination target 500;
- Kazan destination target 100;
- selected network Moscow only;
- sufficient Moscow capacity and seller stock;
- matched Moscow→Kazan route.

Assert:

```python
assert destination_row("Москва").target_qty == 500
assert destination_row("Казань").target_qty == 100
assert origin_row("Москва").total_qty == 600
assert origin_row("Москва").own_destination_qty == 500
assert origin_row("Москва").other_destination_qty == 100
```

Moscow demand never becomes 600.

- [ ] **Step 2: Write failing Safe-vs-Calculated separation test**

If Kazan calculated need=100 and Ozon recommendation=60:

```python
assert planning.calculated.destination_rows[...] .target_qty == 100
assert planning.safe.destination_rows[...] .target_qty == 60
```

Never sum both families into one rollup.

- [ ] **Step 3: Write failing three-gap conservation test**

Construct a fixture where one destination has network gap, one desired leg is allocation-blocked, and another eligible leg is stock-limited. Assert for every destination:

```python
covered + network + blocked + stock == target
```

- [ ] **Step 4: Run focused tests and verify RED**

```bash
python -m pytest tests/api/test_replan.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PlanningSnapshot builder absent.

- [ ] **Step 5: Implement per-SKU plan-family orchestration**

Do not put business formulas in API routes. `build_planning_snapshot()` owns the deterministic orchestration and returns immutable backend presentation rows.

Generate direct quotes on demand from `basis.tariff_rows`; the reusable basis is not expanded into a persisted SKU affinity matrix.

For LOCAL legs, resolve direct route economics using an exact local `origin == destination` quote for economics only. LOCAL placement preference does not require that quote, but economics eligibility still fails closed if local tariff evidence is incomplete.

- [ ] **Step 6: Build deterministic destination and origin rollups**

Destination row:

```python
covered_qty = sum(final_allocated_qty to destination)
network_uncovered_qty = matching PR-B gaps
allocation_blocked_qty = matching PR-C gaps
stock_uncovered_qty = matching PR-C gaps
```

Origin row derives only from final allocated legs. `own_destination_qty` is where `origin == destination`; `other_destination_qty = total - own`.

All rows are stable-sorted by SKU then cluster identity.

- [ ] **Step 7: Assert conservation inside the builder**

After building each family, verify in code (raise `AssertionError` for invariant violation during development/runtime):

```python
covered + network + blocked + stock == target
```

and:

```python
sum(final legs for sku) <= seller stock
```

when seller stock is known.

- [ ] **Step 8: Run planning builder tests and verify GREEN**

```bash
python -m pytest tests/api/test_replan.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit PlanningSnapshot builder**

```bash
git add backend/decision/planning.py tests/api/test_replan.py tests/api/test_product_completion_acceptance.py
git commit -m "feat: build immutable planning snapshots"
```

---

### Task 6: Add full-analysis selected-network input and initial PlanningSnapshot

**Files:**
- Modify: `backend/api.py`
- Modify: `tests/api/test_analysis.py`
- Modify: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**

Optional multipart field on full analysis:

```text
selected_supply_cluster_ids = JSON array of strings
```

Response remains API v1-compatible and additive:

```json
{
  "api_version": 1,
  ...existing AnalysisSnapshot fields...,
  "planning_snapshot": { ...new PlanningSnapshot... }
}
```

The existing top-level analysis fields remain available until PR-E migration.

- [ ] **Step 1: Write failing request validation tests**

Reject malformed JSON, non-list value, non-string IDs, blank IDs and duplicates with a 400 field-specific error.

- [ ] **Step 2: Write failing first-run full-analysis test**

With Project `applied_supply_cluster_ids=None` and no multipart network field, assert initial PlanningSnapshot uses all current candidate clusters.

- [ ] **Step 3: Write failing explicit-network full-analysis test**

Pass `selected_supply_cluster_ids='["Москва"]'`; assert initial PlanningSnapshot applied network is only Moscow even if Kazan is a candidate.

- [ ] **Step 4: Run focused API tests and verify RED**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: network input/planning output absent.

- [ ] **Step 5: Parse network IDs in `prepare_analysis()`**

Keep parsing transport-only. Return the optional tuple alongside existing scenario request. Do not perform candidate-universe business logic in API parsing.

- [ ] **Step 6: Resolve network after cluster resolution/restriction import**

In `run_analysis_pipeline()`:
1. load Project;
2. resolve canonical clusters as today;
3. call `resolve_supply_network()` with resolved restrictions, explicit request and persisted Project network;
4. run `analyze()` unchanged for upstream analysis;
5. build PlanningBasis + AnalysisSnapshot;
6. build initial PlanningSnapshot for the resolved applied network.

- [ ] **Step 7: Persist network only after full result is successfully built**

Use `dataclasses.replace(project, applied_supply_cluster_ids=planning_snapshot.applied_supply_cluster_ids)` and `save_project_atomic()` only after all calculation/serialization preconditions succeed.

If analysis fails, Project JSON must retain the previous applied network.

- [ ] **Step 8: Add PlanningSnapshot to both normal and stream result paths**

`/api/analysis` and the `type=result` event from `/api/analysis/stream` must expose the same data shape. Do not create separate business execution paths.

- [ ] **Step 9: Run full-analysis API tests and verify GREEN**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit full-analysis integration**

```bash
git add backend/api.py tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py
git commit -m "feat: return initial selected-network plan"
```

---

### Task 7: Add stateless `POST /api/replan`

**Files:**
- Modify: `backend/api.py`
- Modify: `tests/api/test_replan.py`

**Interfaces:**

JSON request:

```json
{
  "api_version": 1,
  "analysis_snapshot_id": "...",
  "planning_basis": { ...exact wire PlanningBasis... },
  "selected_supply_cluster_ids": ["Москва", "Питер"]
}
```

JSON response:

```json
{
  "api_version": 1,
  "kind": "planning",
  ...PlanningSnapshot fields...
}
```

- [ ] **Step 1: Write failing successful-replan API test**

Take a PlanningBasis from a full-analysis fixture, post a narrower network, and assert:
- HTTP 200;
- new `planning_snapshot_id`;
- same `analysis_snapshot_id`;
- new applied network;
- changed origin rollup;
- unchanged base analysis ID.

- [ ] **Step 2: Prove replan does not call upstream analysis**

Monkeypatch/import-spy the upstream functions invoked by full analysis (`import_*`, `build_daily_order_facts`, or `analyze`) to raise if called during `/api/replan`:

```python
def forbidden(*args, **kwargs):
    raise AssertionError("upstream analysis must not run during replan")
```

The replan request must still return 200.

- [ ] **Step 3: Write malformed/stale-base validation tests**

The server cannot know browser-active state in a stateless call, so stale-base protection is identity-based:
- response must echo the supplied valid `analysis_snapshot_id` exactly;
- reject blank/malformed ID;
- reject PlanningBasis whose embedded/reference identity, when represented, conflicts with the supplied ID.

The frontend will discard a valid response if that analysis ID is no longer active in PR-E.

- [ ] **Step 4: Run replan tests and verify RED**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: route absent (404) / parser absent.

- [ ] **Step 5: Implement strict PlanningBasis wire parser**

Do not deserialize arbitrary dataclass payloads generically. Parse the exact allowed fields and enums/Decimals, reject unknown fields, negative quantities, duplicate identities and forbidden/raw data keys.

Reuse project/domain validation helpers where sensible, but do not make Project JSON the transport contract.

- [ ] **Step 6: Implement thin API route over `build_planning_snapshot()`**

```python
@router.post("/api/replan")
async def replan(request: Request):
    payload = await request.json()
    parsed = parse_replan_request(payload)
    planning = build_planning_snapshot(
        analysis_snapshot_id=parsed.analysis_snapshot_id,
        basis=parsed.planning_basis,
        selected_supply_cluster_ids=parsed.selected_supply_cluster_ids,
    )
    persist_successfully_applied_network(planning.applied_supply_cluster_ids)
    return response("planning", planning)
```

Candidate reconciliation uses `basis.candidate_supply_cluster_ids`; do not reload/import restrictions.

- [ ] **Step 7: Persist only after successful planning build**

If parsing, route quoting, coverage, allocation or invariant validation fails, return a stable error and leave Project JSON unchanged.

- [ ] **Step 8: Run replan tests and verify GREEN**

```bash
python -m pytest tests/api/test_replan.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit replan endpoint**

```bash
git add backend/api.py tests/api/test_replan.py
git commit -m "feat: add stateless selected-network replan"
```

---

### Task 8: Verify migration compatibility and backend end-state

**Files:**
- Regression: `tests/test_project.py`
- Regression: `tests/api/test_analysis.py`
- Regression: `tests/api/test_replan.py`
- Regression: `tests/api/test_product_completion_acceptance.py`
- Regression: `tests/api/test_project_mappings.py`
- Regression: `tests/supply/test_coverage.py`
- Regression: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add failure-persistence test**

Start with Project applied network `("Москва",)`, post a replan for `("Питер",)` that is forced to fail before result completion, reload Project and assert it is still `("Москва",)`.

- [ ] **Step 2: Add no-silent-expansion full lifecycle test**

1. First successful analysis applies Moscow only.
2. Later restrictions basis gains Kazan.
3. Full analysis without explicit network request reconciles persisted state.
4. Assert Moscow remains applied and Kazan is candidate but unselected.

- [ ] **Step 3: Add explicit-empty lifecycle test**

Persist/apply empty network successfully, then rerun with candidate clusters available and no explicit network. Assert applied network remains empty; all destination target becomes network-uncovered rather than silently defaulting to all clusters.

- [ ] **Step 4: Run selected-network backend suite**

```bash
python -m pytest \
  tests/test_project.py \
  tests/api/test_analysis.py \
  tests/api/test_replan.py \
  tests/api/test_product_completion_acceptance.py \
  tests/api/test_project_mappings.py \
  tests/supply/test_coverage.py \
  tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full repository verification**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit final backend acceptance slice**

```bash
git add tests/test_project.py tests/api/test_analysis.py tests/api/test_replan.py tests/api/test_product_completion_acceptance.py tests/api/test_project_mappings.py
git commit -m "test: verify planning snapshot lifecycle"
```

---

## PR-D Acceptance Gate

Before opening PR-D, verify from fresh output:

```bash
python -m pytest -q
```

Required proofs:

- Project schema v1 loads into v2 with `applied_supply_cluster_ids=None`.
- `None` (never applied) and `()` (explicit empty network) survive round-trip distinctly.
- First run defaults to all current candidate clusters only when persisted network is None and no explicit request exists.
- Persisted network is intersected with current candidates; newly appearing clusters are not silently selected.
- Removed/unresolved persisted clusters produce reconciliation warning.
- AnalysisSnapshot contains bounded PlanningBasis and no raw orders/PII/unbounded daily route matrix.
- PlanningBasis stores reusable tariff evidence, not a persisted SKU affinity matrix.
- Full analysis returns existing compatible analysis fields plus an initial immutable PlanningSnapshot for the same requested/resolved network.
- Safe target is `min(Ozon, calculated need)`; Calculated target is own need; physical capacity is downstream only.
- PlanningSnapshot preserves destination identity while origin rollup reflects physical placement.
- Calculated and Safe families remain separate.
- `/api/replan` returns a new PlanningSnapshot referencing the same AnalysisSnapshot and never reruns upstream analysis/imports.
- Network-only replan persists the draft network only after successful plan creation.
- Failed full analysis/replan leaves previous applied network unchanged.
- Final destination conservation includes all three unmet causes.
- Transitional legacy AnalysisSnapshot plan fields remain available for pre-PR-E frontend compatibility but are never mutated by replan.
