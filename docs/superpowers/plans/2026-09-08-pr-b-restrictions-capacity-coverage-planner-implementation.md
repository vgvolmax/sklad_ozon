# PR-B Restrictions Capacity & Coverage Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make restrictions capacity unambiguous and add a deterministic pure Coverage Planner that converts destination targets into desired `origin → destination` legs inside a user-selected supply network.

**Architecture:** Extend normalized restriction evidence with explicit `FINITE / UNLIMITED / UNKNOWN` capacity semantics while preserving existing restriction-state fail-closed behavior. Add a new pure `backend/supply/coverage.py` planner that owns LOCAL-first assignment, iterative constrained-destination ordering, direct-fee route ranking and shared `SKU × origin` capacity consumption. Keep this PR disconnected from `backend/application.py`, seller-stock allocation, snapshots, API and frontend so the planner can be proven independently.

**Tech Stack:** Python 3, frozen dataclasses/enums, `Decimal`, pytest; PR-A direct-route quote API; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- `destination_cluster` remains the owner of demand; Coverage Planner must never rewrite demand/need geography.
- Restrictions report is the only physical eligibility/capacity source for this feature.
- Capacity evidence must distinguish explicit finite, explicit unlimited and unknown; unknown is never treated as unlimited.
- Malformed nonblank numeric capacity remains an ingestion error and must not be silently converted to UNKNOWN.
- Multiple allowed warehouse limits inside one cluster are not summed.
- Cluster capacity is the best independently proven single receiving option: any known UNLIMITED wins; otherwise max known FINITE; if no known capacity exists, UNKNOWN.
- Capacity is shared by all destinations served through one `SKU × origin`; it is not reset per destination.
- LOCAL assignment is attempted before non-local routes and does not require historical route evidence.
- Non-local assignment requires a user-selected physically feasible origin, known usable capacity and a MATCHED direct tariff quote.
- Historical route quantity/share must never enter coverage quantities or route ranking.
- Non-local ranking is direct fee ascending; exact-fee ties may use route-confidence, then stable origin ID.
- Residual destinations are chosen iteratively with currently fewer feasible origins first, then larger residual target, then stable destination ID.
- No proportional route split, geographic-distance fallback or LP/min-cost-flow solver.
- This PR does not apply seller-stock scarcity or economics eligibility; those belong to PR-C.
- Use TDD; no application orchestration, snapshot/API/frontend changes in PR-B.

---

## File Structure

- Modify `backend/ingestion/restrictions.py` — preserve explicit warehouse capacity state at ingestion.
- Modify `backend/supply/contracts.py` — add capacity state, destination-target and desired coverage contracts.
- Modify `backend/supply/feasibility.py` — replace ambiguous/minimum capacity aggregation with the canonical non-additive cluster rule while keeping restriction-state safeguards.
- Create `backend/supply/coverage.py` — pure deterministic planner for one SKU and one plan family.
- Modify `backend/supply/__init__.py` — export approved coverage contracts/functions.
- Modify `tests/ingestion/test_restrictions.py` — finite/unlimited/unknown/malformed parsing.
- Modify `tests/supply/test_placement.py` — feasibility aggregation and legacy placement regression.
- Create `tests/supply/test_coverage.py` — destination identity, LOCAL-first, fee ranking, capacity spillover, constrained-first and conservation tests.

No `backend/application.py`, `backend/api.py`, `backend/project.py`, decision snapshot or frontend changes belong in PR-B.

---

### Task 1: Preserve explicit capacity evidence in restriction ingestion

**Files:**
- Modify: `backend/ingestion/restrictions.py`
- Test: `tests/ingestion/test_restrictions.py`

**Interfaces:**
- Produces:

```python
class RestrictionCapacityKind(str, Enum):
    FINITE = "finite"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"
```

- Extends `RestrictionRecord` with a final backwards-compatible field:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- `max_supply_qty` remains `int | None`; only `FINITE` may carry an integer value.

- [ ] **Step 1: Write failing ingestion tests for all three known states**

Add explicit real-format row cases:

```python
def test_restrictions_preserve_finite_capacity(report_meta):
    data = b"sku;cluster;warehouse;..."  # use the existing test helper/adapter format
    result = import_restrictions(make_restrictions_bytes(
        sku="SKU-1", cluster="Москва", warehouse="Хоругвино",
        allowed="Да", maximum="120",
    ), report_meta)
    row = result.records[0]
    assert row.max_supply_qty == 120
    assert row.capacity_kind is RestrictionCapacityKind.FINITE


def test_restrictions_preserve_explicit_unlimited_capacity(report_meta):
    result = import_restrictions(make_restrictions_bytes(
        sku="SKU-1", cluster="Москва", warehouse="Хоругвино",
        allowed="Да", maximum="Без ограничений",
    ), report_meta)
    row = result.records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNLIMITED


def test_allowed_blank_capacity_is_unknown_not_unlimited(report_meta):
    result = import_restrictions(make_restrictions_bytes(
        sku="SKU-1", cluster="Москва", warehouse="Хоругвино",
        allowed="Да", maximum="",
    ), report_meta)
    row = result.records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNKNOWN
```

Use the actual existing fixture/helper style in `tests/ingestion/test_restrictions.py`; do not introduce a second spreadsheet builder if that file already has one.

- [ ] **Step 2: Add malformed-capacity regression before implementation**

```python
def test_malformed_nonblank_capacity_remains_ingestion_error(report_meta):
    result = import_restrictions(make_restrictions_bytes(
        sku="SKU-1", cluster="Москва", warehouse="Хоругвино",
        allowed="Да", maximum="сто двадцать",
    ), report_meta)
    assert result.records == ()
    assert any(d.code == "INVALID_MAX_SUPPLY_QTY" for d in result.diagnostics)
```

- [ ] **Step 3: Run focused ingestion tests and verify RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: the new state assertions fail because `RestrictionCapacityKind` / `capacity_kind` do not exist.

- [ ] **Step 4: Implement explicit parsing without changing malformed-row policy**

Append the enum and field without reordering existing positional fields:

```python
class RestrictionCapacityKind(str, Enum):
    FINITE = "finite"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RestrictionRecord:
    sku: str
    warehouse: str
    state: RestrictionState
    reason: str
    source_value: str
    cluster: str = ""
    max_supply_qty: int | None = None
    capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

In the row parser derive the state explicitly:

```python
capacity_kind = RestrictionCapacityKind.UNKNOWN
max_qty = None

if maximum_text == "без ограничений":
    capacity_kind = RestrictionCapacityKind.UNLIMITED
elif maximum in (None, "") or maximum_text == "-":
    capacity_kind = RestrictionCapacityKind.UNKNOWN
else:
    try:
        value = float(maximum)
        max_qty = int(value)
        if value != max_qty or max_qty < 0:
            raise ValueError
        capacity_kind = RestrictionCapacityKind.FINITE
    except (ValueError, TypeError):
        diagnostics.append(_diag(
            "INVALID_MAX_SUPPLY_QTY",
            "Maximum supply quantity is invalid.",
            row=row_number,
        ))
        continue
```

For PROHIBITED rows the capacity evidence is informational only and must not make them feasible; keep restriction-state behavior unchanged.

- [ ] **Step 5: Run focused ingestion tests and verify GREEN**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit ingestion evidence slice**

```bash
git add backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction capacity state"
```

---

### Task 2: Carry capacity state through supply feasibility

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Test: `tests/supply/test_placement.py`

**Interfaces:**
- Extends `WarehouseCapability` with final defaulted field:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- Extends `SupplyFeasibility` with final field:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- Existing call remains:

```python
assess_feasibility(
    sku: str,
    cluster_id: str,
    restrictions: Iterable[RestrictionRecord],
    warehouses: Iterable[WarehouseCapability],
) -> SupplyFeasibility
```

- [ ] **Step 1: Write failing cluster-capacity aggregation tests**

Add tests proving the canonical non-additive rule:

```python
def test_feasibility_uses_max_known_finite_warehouse_not_sum():
    result = assess_feasibility(
        "SKU-1", "Москва",
        restrictions=(
            allowed_restriction("SKU-1", "W1", "Москва", 100),
            allowed_restriction("SKU-1", "W2", "Москва", 300),
        ),
        warehouses=(
            WarehouseCapability("W1", "Москва", 100, RestrictionCapacityKind.FINITE),
            WarehouseCapability("W2", "Москва", 300, RestrictionCapacityKind.FINITE),
        ),
    )
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 300


def test_feasibility_known_warehouse_survives_unknown_alternative():
    result = assess_feasibility(... W1 FINITE 120, W2 UNKNOWN ...)
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 120


def test_feasibility_explicit_unlimited_wins_over_finite():
    result = assess_feasibility(... W1 FINITE 120, W2 UNLIMITED ...)
    assert result.capacity_kind is RestrictionCapacityKind.UNLIMITED
    assert result.max_supply_qty is None


def test_feasibility_all_allowed_capacities_unknown():
    result = assess_feasibility(... W1 UNKNOWN, W2 UNKNOWN ...)
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.UNKNOWN
    assert result.max_supply_qty is None
```

Also retain fail-closed tests for no explicit allowed warehouse, conflicting restriction state and zero finite ceiling.

- [ ] **Step 2: Run placement/feasibility tests and verify RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

Expected: new aggregation/state tests fail under the current `min(explicit_maxima)` behavior.

- [ ] **Step 3: Extend supply contracts without breaking existing positional constructors**

Import `RestrictionCapacityKind` and append the new fields at the end of the dataclasses. Validate consistency in `WarehouseCapability.__post_init__`:

```python
if self.capacity_kind is RestrictionCapacityKind.FINITE:
    if self.max_supply_qty is None:
        raise ValueError("finite capacity requires max_supply_qty")
elif self.max_supply_qty is not None:
    raise ValueError("non-finite capacity must not contain max_supply_qty")
```

Existing tests/builders that omit the field become UNKNOWN explicitly; update production construction in the next step before Coverage Planner consumes it.

- [ ] **Step 4: Replace only cluster capacity aggregation semantics**

In `assess_feasibility()` preserve current restriction-state screening, then derive capacity from eligible capabilities:

```python
known = [
    item for item in eligible
    if item.capacity_kind in {
        RestrictionCapacityKind.FINITE,
        RestrictionCapacityKind.UNLIMITED,
    }
]

if not eligible:
    maximum = 0
    capacity_kind = RestrictionCapacityKind.FINITE
elif not known:
    maximum = None
    capacity_kind = RestrictionCapacityKind.UNKNOWN
elif any(item.capacity_kind is RestrictionCapacityKind.UNLIMITED for item in known):
    maximum = None
    capacity_kind = RestrictionCapacityKind.UNLIMITED
else:
    maximum = max(item.max_supply_qty for item in known if item.max_supply_qty is not None)
    capacity_kind = RestrictionCapacityKind.FINITE
```

Replace `CONSERVATIVE_WAREHOUSE_MAXIMUM` with reason codes that describe the new evidence, e.g. `MULTIPLE_WAREHOUSE_ALTERNATIVES` and `UNKNOWN_CAPACITY_ALTERNATIVE_PRESENT`; do not expose “sum” semantics.

Return the explicit `capacity_kind` on `SupplyFeasibility`.

- [ ] **Step 5: Run placement and optimizer regression tests**

```bash
python -m pytest tests/supply/test_placement.py tests/supply/test_optimizer.py -q
```

Expected: PASS. Existing optimizer behavior is not yet redesigned in this PR; these tests prove the capacity-contract extension does not accidentally break it.

- [ ] **Step 6: Commit feasibility slice**

```bash
git add backend/supply/contracts.py backend/supply/feasibility.py tests/supply/test_placement.py
git commit -m "feat: model cluster supply capacity explicitly"
```

---

### Task 3: Define destination-target and desired-coverage contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Create: `tests/supply/test_coverage.py`

**Interfaces:**
- Produces:

```python
class CoverageType(str, Enum):
    LOCAL = "local"
    ROUTE = "route"


@dataclass(frozen=True, slots=True)
class DestinationTarget:
    sku: str
    destination_cluster_id: str
    quantity: int
    plan_family: PlanFamily


@dataclass(frozen=True, slots=True)
class DesiredCoverageLeg:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    desired_qty: int
    coverage_type: CoverageType
    direct_route_fee: Decimal | None
    volume_band: object | None
    route_confidence: RouteConfidence
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NetworkCoverageGap:
    sku: str
    destination_cluster_id: str
    quantity: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoveragePlanResult:
    sku: str
    plan_family: PlanFamily
    targets: tuple[DestinationTarget, ...]
    desired_legs: tuple[DesiredCoverageLeg, ...]
    network_gaps: tuple[NetworkCoverageGap, ...]
```

Use `TYPE_CHECKING` / forward annotation for `VolumeBand` if importing it at runtime would create an undesirable economics↔supply cycle. `direct_route_fee` is the planner decision evidence; the full `DirectRouteQuote` stays an input, not embedded as a persisted per-SKU matrix.

- [ ] **Step 1: Write failing validation tests**

```python
def test_destination_target_preserves_destination_identity():
    target = DestinationTarget("SKU-1", "Казань", 100, PlanFamily.CALCULATED)
    assert target.destination_cluster_id == "Казань"
    assert target.quantity == 100


def test_coverage_leg_requires_positive_desired_quantity():
    with pytest.raises(ValueError, match="desired_qty"):
        DesiredCoverageLeg(
            "SKU-1", "Москва", "Казань", 0, CoverageType.ROUTE,
            Decimal("47"), None, RouteConfidence.HIGH,
        )
```

Also validate nonblank identities, nonnegative target quantities, no negative route fee, and plan-family type.

- [ ] **Step 2: Run new coverage tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: import/attribute failures because the contracts do not exist.

- [ ] **Step 3: Implement the immutable contracts with explicit validation**

Use existing `_require_nonblank()` / `_require_nonnegative_int()` helpers. Permit zero `DestinationTarget.quantity` for conservation/input completeness but do not emit zero-quantity desired legs or gaps.

For LOCAL legs set `direct_route_fee=None`; for ROUTE legs require a nonnegative `Decimal` fee.

- [ ] **Step 4: Run contract tests and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS for contract-only cases.

- [ ] **Step 5: Commit coverage contracts**

```bash
git add backend/supply/contracts.py tests/supply/test_coverage.py
git commit -m "feat: add coverage planning contracts"
```

---

### Task 4: Implement LOCAL-first coverage with shared origin capacity

**Files:**
- Create: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Interfaces:**
- Consumes:

```python
DestinationTarget
SupplyFeasibility
DirectRouteQuote
RouteConfidence
```

- Produces:

```python
def plan_coverage_for_sku(
    *,
    targets: Iterable[DestinationTarget],
    selected_origin_cluster_ids: Iterable[str],
    feasibility_by_origin: Mapping[str, SupplyFeasibility],
    direct_quotes: Mapping[tuple[str, str], DirectRouteQuote],
    route_confidence_by_route: Mapping[tuple[str, str], RouteConfidence] | None = None,
) -> CoveragePlanResult:
    ...
```

All targets passed in one call must share one SKU and one PlanFamily.

- [ ] **Step 1: Write failing LOCAL-first and capacity-sharing tests**

```python
def test_local_is_assigned_before_nonlocal_even_if_nonlocal_fee_is_lower():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 50, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Казань", "Москва"),
        feasibility_by_origin={
            "Казань": finite_feasibility("SKU-1", "Казань", 50),
            "Москва": finite_feasibility("SKU-1", "Москва", 100),
        },
        direct_quotes={
            ("Москва", "Казань"): matched_quote("Москва", "Казань", "1"),
        },
    )
    assert [(x.origin_cluster_id, x.destination_cluster_id, x.desired_qty, x.coverage_type)
            for x in result.desired_legs] == [
        ("Казань", "Казань", 50, CoverageType.LOCAL),
    ]


def test_one_origin_capacity_is_shared_across_destinations():
    result = plan_coverage_for_sku(... target A=60, target B=60, origin Москва capacity=100 ...)
    assert sum(x.desired_qty for x in result.desired_legs if x.origin_cluster_id == "Москва") == 100
    assert sum(x.quantity for x in result.network_gaps) == 20
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: FAIL because the planner does not exist.

- [ ] **Step 3: Implement input normalization and remaining-capacity helpers**

In `backend/supply/coverage.py` create private helpers with no global state:

```python
def _remaining_capacity(feasibility: SupplyFeasibility) -> int | None:
    if not feasibility.allowed:
        return 0
    if feasibility.capacity_kind is RestrictionCapacityKind.UNKNOWN:
        return 0
    if feasibility.capacity_kind is RestrictionCapacityKind.UNLIMITED:
        return None
    return feasibility.max_supply_qty


def _take(remaining: int | None, requested: int) -> tuple[int, int | None]:
    if remaining is None:
        return requested, None
    quantity = min(remaining, requested)
    return quantity, remaining - quantity
```

`None` in this helper means explicit UNLIMITED only because `capacity_kind` has already disambiguated it.

Validate:
- at least one target;
- one SKU / one PlanFamily;
- no duplicate destination targets;
- selected origin IDs are nonblank and deduplicated deterministically.

- [ ] **Step 4: Implement LOCAL pass**

For targets sorted by stable destination ID, if the destination is selected and its feasibility is allowed with known usable capacity, take from that origin before any non-local assignment. Emit no zero-quantity leg.

Keep a `residual_by_destination` and `remaining_by_origin` dictionary. Do not consume a direct tariff for LOCAL.

- [ ] **Step 5: Run LOCAL/capacity tests and verify GREEN for the implemented slice**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: LOCAL tests pass; later non-local tests may still fail until Task 5.

- [ ] **Step 6: Commit LOCAL/core planner slice**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: assign local coverage with shared capacity"
```

---

### Task 5: Implement iterative constrained-first non-local routing

**Files:**
- Modify: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Interfaces:**
- Completes `plan_coverage_for_sku(...) -> CoveragePlanResult`
- Non-local quote eligibility: `quote.lookup_status is TariffLookupStatus.MATCHED`

- [ ] **Step 1: Write the historical-share trap and fee-order tests**

```python
def test_cheaper_route_wins_even_when_historical_confidence_is_lower():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 50, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": unlimited_feasibility("SKU-1", "Москва"),
            "Питер": unlimited_feasibility("SKU-1", "Питер"),
        },
        direct_quotes={
            ("Москва", "Казань"): matched_quote("Москва", "Казань", "47"),
            ("Питер", "Казань"): matched_quote("Питер", "Казань", "52"),
        },
        route_confidence_by_route={
            ("Москва", "Казань"): RouteConfidence.LOW,
            ("Питер", "Казань"): RouteConfidence.HIGH,
        },
    )
    assert result.desired_legs[0].origin_cluster_id == "Москва"
    assert result.desired_legs[0].desired_qty == 50
```

This test proves route confidence is only an exact-fee tie-break, not a replacement for fee ordering.

- [ ] **Step 2: Write capacity spillover test**

```python
def test_cheapest_route_fills_then_spills_to_next_route():
    result = plan_coverage_for_sku(...)
    assert [(x.origin_cluster_id, x.desired_qty) for x in result.desired_legs] == [
        ("Москва", 70),
        ("Питер", 30),
    ]
```

Use target Kazan=100, Moscow finite 70 fee 47, Peter finite 100 fee 52.

- [ ] **Step 3: Write iterative constrained-destination regression**

```python
def test_constrained_destination_is_not_stranded_by_flexible_destination():
    # A can only use Moscow. B can use Moscow or Peter.
    # Moscow capacity cannot cover both.
    result = plan_coverage_for_sku(...)
    covered = {
        d: sum(x.desired_qty for x in result.desired_legs if x.destination_cluster_id == d)
        for d in ("A", "B")
    }
    assert covered["A"] == target_a
    assert covered["B"] == target_b
    assert not result.network_gaps
```

Create a second regression where an earlier assignment exhausts one origin and assert the feasible-origin counts are recomputed before selecting the next residual destination.

- [ ] **Step 4: Write incomplete-route/network-gap tests**

Cover each causal network gap:

```python
def test_missing_tariffs_do_not_fabricate_route(): ...
def test_unknown_capacity_is_not_used_as_unlimited(): ...
def test_exhausted_selected_network_emits_gap(): ...
```

Expected reason families:
- `NO_SELECTED_FEASIBLE_ORIGIN`
- `NO_COMPLETE_DIRECT_TARIFF`
- `ORIGIN_CAPACITY_EXHAUSTED_OR_UNKNOWN`

The exact ordering must be deterministic.

- [ ] **Step 5: Run new tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: non-local/constrained/gap tests fail before implementation.

- [ ] **Step 6: Implement candidate discovery from current remaining state**

For each residual destination, compute candidates fresh:

```python
def _nonlocal_candidates(destination_id):
    result = []
    for origin_id in selected_origins:
        if origin_id == destination_id:
            continue
        feasibility = feasibility_by_origin.get(origin_id)
        if not _has_known_usable_remaining(feasibility, remaining_by_origin.get(origin_id)):
            continue
        quote = direct_quotes.get((origin_id, destination_id))
        if quote is None or quote.lookup_status is not TariffLookupStatus.MATCHED:
            continue
        confidence = route_confidence_by_route.get(
            (origin_id, destination_id), RouteConfidence.LOW
        )
        result.append((origin_id, quote, confidence))
    result.sort(key=lambda item: item[0])
    result.sort(key=lambda item: _ROUTE_RANK[item[2]], reverse=True)
    result.sort(key=lambda item: item[1].matched_fee)
    return result
```

The fee sort is most significant; confidence only resolves equal fees.

- [ ] **Step 7: Implement iterative destination selection and sequential fill**

While any residual is positive:

```python
while positive_residual_destinations:
    ranked = []
    for destination_id, residual in positive_residual_destinations:
        candidates = _nonlocal_candidates(destination_id)
        ranked.append((len(candidates), -residual, destination_id, candidates))
    _, _, destination_id, candidates = min(ranked, key=lambda item: item[:3])
```

If candidates exist, fill sequentially in candidate order and update `remaining_by_origin` after each leg. Then restart the outer loop so feasible-origin counts are recomputed from the new state.

If no candidate exists, classify the network gap by inspecting selected feasibility and quote evidence; emit one `NetworkCoverageGap` for the full residual and remove that destination from the loop.

- [ ] **Step 8: Run coverage tests and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit non-local planner slice**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: route residual demand through selected network"
```

---

### Task 6: Prove conservation, determinism and public export

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_coverage.py`
- Regression: `tests/supply/test_placement.py`
- Regression: `tests/supply/test_optimizer.py`

**Interfaces:**
- Public exports: `RestrictionCapacityKind` remains from ingestion; supply exports `CoverageType`, `DestinationTarget`, `DesiredCoverageLeg`, `NetworkCoverageGap`, `CoveragePlanResult`, `plan_coverage_for_sku`.

- [ ] **Step 1: Add conservation/determinism tests**

```python
def test_coverage_conserves_every_destination_target():
    result = plan_coverage_for_sku(...)
    for target in result.targets:
        covered = sum(
            leg.desired_qty for leg in result.desired_legs
            if leg.destination_cluster_id == target.destination_cluster_id
        )
        uncovered = sum(
            gap.quantity for gap in result.network_gaps
            if gap.destination_cluster_id == target.destination_cluster_id
        )
        assert covered + uncovered == target.quantity


def test_input_order_does_not_change_coverage_result():
    first = plan_coverage_for_sku(... targets/origins in order A ...)
    second = plan_coverage_for_sku(... same facts reversed ...)
    assert first == second
```

Also assert finite origin capacity across all desired legs is never exceeded.

- [ ] **Step 2: Add export smoke test and verify RED**

```python
def test_coverage_planner_is_exported():
    from backend.supply import CoveragePlanResult, plan_coverage_for_sku
    assert CoveragePlanResult is not None
    assert callable(plan_coverage_for_sku)
```

Run:

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: export test fails until `backend/supply/__init__.py` is updated.

- [ ] **Step 3: Export only the approved planner surface**

Update `backend/supply/__init__.py` following its existing explicit-export style. Do not export private capacity/candidate helpers.

- [ ] **Step 4: Run PR-B regression suite**

```bash
python -m pytest \
  tests/ingestion/test_restrictions.py \
  tests/supply/test_coverage.py \
  tests/supply/test_placement.py \
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

- [ ] **Step 6: Commit export/acceptance slice**

```bash
git add backend/supply/__init__.py tests/supply/test_coverage.py
git commit -m "test: verify selected network coverage invariants"
```

---

## PR-B Acceptance Gate

Before opening PR-B, verify from fresh output:

```bash
python -m pytest -q
```

Required proofs:

- Explicit `Без ограничений` is UNLIMITED; blank allowed capacity is UNKNOWN; malformed nonblank value remains an ingestion error.
- Restriction-state fail-closed semantics still work.
- Multi-warehouse finite maxima use max single independently proven ceiling, not min and not sum.
- Unknown warehouse alternative does not erase a separate known allowed receiving option.
- One `SKU × origin` capacity is shared across all destinations.
- LOCAL is attempted before any non-local route.
- A historically weak/low-confidence cheap route beats a more expensive route; historical share is absent entirely.
- Cheapest route fills sequentially to capacity, then spills to next route.
- Destination with fewer currently feasible origins is selected iteratively before flexible destinations.
- Missing tariff, unknown capacity and exhausted selected network create explicit network gaps, not fabricated placement.
- Per-destination conservation holds exactly: desired legs + network gap = destination target.
- Input ordering cannot change the result.
- Current application/optimizer/snapshot/API/frontend behavior is not yet switched to Coverage Planner in PR-B.
