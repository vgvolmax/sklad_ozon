# PR-B Restrictions Capacity & Coverage Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make restriction capacity unambiguous and add a pure deterministic Coverage Planner that converts destination targets into desired `origin → destination` legs inside a user-selected supply network.

**Architecture:** Normalize `FINITE / UNLIMITED / UNKNOWN` capacity at ingestion, carry that evidence through supply feasibility, and replace the current cluster `min(max_supply_qty)` rule with the approved non-additive best-single-receiving-option rule. Add `backend/supply/coverage.py` as a dependency-free functional core: LOCAL first, then iterative constrained-destination selection and direct-fee sequential fill with one shared capacity ledger per `SKU × origin`.

**Tech Stack:** Python 3, frozen dataclasses/enums, `Decimal`, pytest; PR-A `DirectRouteQuote`; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Destination identity never changes.
- Restrictions report is the only physical feasibility/capacity source for this feature.
- `FINITE(value)`, `UNLIMITED`, and `UNKNOWN` are distinct. Unknown is never interpreted as unlimited.
- Malformed nonblank capacity remains `INVALID_MAX_SUPPLY_QTY`; it is not downgraded to UNKNOWN.
- Multiple warehouse maxima inside one cluster are never summed.
- Cluster capacity = UNLIMITED if any explicitly allowed receiving option is known unlimited; otherwise max known FINITE; otherwise UNKNOWN.
- An unknown allowed warehouse does not invalidate another independently known allowed warehouse.
- Capacity is shared across all destinations served through one `SKU × origin`.
- LOCAL is assigned before non-local and requires no historical route evidence.
- Non-local candidate requires: globally selected origin, explicit physical allowance, known usable remaining capacity, MATCHED direct tariff quote.
- Non-local ranking = lower direct fee; exact-fee tie = higher route confidence; final tie = stable origin ID.
- Historical route quantity/share is never used as a coverage weight.
- Sequential fill only; no proportional split.
- Residual destinations are chosen iteratively by fewer currently feasible origins, then larger residual target, then stable destination ID.
- No geographic fallback and no LP/min-cost-flow solver.
- Seller-stock scarcity/economics eligibility is not part of PR-B; PR-C owns it.
- Do not connect this planner to `backend/application.py`, snapshot/API or frontend yet.

---

## File Structure

- Modify `backend/ingestion/restrictions.py` — explicit capacity state in normalized restriction rows.
- Modify `backend/supply/contracts.py` — capacity-aware supply contracts and desired coverage contracts.
- Modify `backend/supply/feasibility.py` — canonical cluster-capacity aggregation.
- Create `backend/supply/coverage.py` — pure Coverage Planner.
- Modify `backend/supply/__init__.py` — public coverage exports.
- Modify `tests/ingestion/test_restrictions.py` — capacity parsing tests.
- Modify `tests/supply/test_placement.py` — feasibility aggregation regressions.
- Create `tests/supply/test_coverage.py` — Coverage Planner tests.
- Run existing `tests/supply/test_optimizer.py` unchanged as a compatibility regression.

---

### Task 1: Preserve explicit capacity state during restriction ingestion

**Files:**
- Modify: `backend/ingestion/restrictions.py`
- Modify: `tests/ingestion/test_restrictions.py`

**Interfaces:**

```python
class RestrictionCapacityKind(str, Enum):
    FINITE = "finite"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"
```

Append to the existing `RestrictionRecord` without reordering its current positional fields:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- [ ] **Step 1: Add exact CSV fixture helper to the existing restriction test file**

If `tests/ingestion/test_restrictions.py` already has a helper that creates the same real-format columns, reuse that helper by name. Otherwise add exactly:

```python
def _real_restriction_csv(*rows: tuple[str, str, str, str, str]) -> bytes:
    header = (
        "SKU;Кластер;Склад;Возможно ли поставить товар;"
        "Максимальный размер поставки\n"
    )
    body = "".join(";".join(row) + "\n" for row in rows)
    return (header + body).encode("utf-8")
```

Each row is `(sku, cluster, warehouse, allowed, maximum)`.

- [ ] **Step 2: Add failing FINITE / UNLIMITED / UNKNOWN tests**

```python
from backend.ingestion.restrictions import (
    RestrictionCapacityKind,
    import_restrictions,
)


def test_real_restriction_finite_capacity(report_meta):
    result = import_restrictions(
        _real_restriction_csv(("SKU-1", "Москва", "W1", "Да", "120")),
        report_meta,
    )
    assert result.records[0].max_supply_qty == 120
    assert result.records[0].capacity_kind is RestrictionCapacityKind.FINITE


def test_real_restriction_explicit_unlimited_capacity(report_meta):
    result = import_restrictions(
        _real_restriction_csv(
            ("SKU-1", "Москва", "W1", "Да", "Без ограничений")
        ),
        report_meta,
    )
    assert result.records[0].max_supply_qty is None
    assert result.records[0].capacity_kind is RestrictionCapacityKind.UNLIMITED


def test_real_restriction_blank_allowed_capacity_is_unknown(report_meta):
    result = import_restrictions(
        _real_restriction_csv(("SKU-1", "Москва", "W1", "Да", "")),
        report_meta,
    )
    assert result.records[0].max_supply_qty is None
    assert result.records[0].capacity_kind is RestrictionCapacityKind.UNKNOWN
```

- [ ] **Step 3: Add malformed-capacity regression**

```python
def test_real_restriction_malformed_nonblank_capacity_is_rejected(report_meta):
    result = import_restrictions(
        _real_restriction_csv(
            ("SKU-1", "Москва", "W1", "Да", "сто двадцать")
        ),
        report_meta,
    )
    assert result.records == ()
    assert [item.code for item in result.diagnostics] == ["INVALID_MAX_SUPPLY_QTY"]
```

If the existing importer test intentionally produces an additional adapter diagnostic for the same fixture, assert the presence of `INVALID_MAX_SUPPLY_QTY` instead of exact-list equality; do not weaken the capacity assertion itself.

- [ ] **Step 4: Run tests and verify RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: import/attribute failure for `RestrictionCapacityKind` / `capacity_kind`.

- [ ] **Step 5: Implement explicit capacity parsing**

Add the enum near `RestrictionState`. Append the new field to `RestrictionRecord`. Replace the current capacity parsing block with:

```python
maximum = row.get("максимальный размер поставки")
maximum_text = normalize_text(maximum).casefold()
max_qty = None
capacity_kind = RestrictionCapacityKind.UNKNOWN

if maximum_text == "без ограничений":
    capacity_kind = RestrictionCapacityKind.UNLIMITED
elif maximum in (None, "") or maximum_text in {"", "-"}:
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

Build the record with keyword arguments for the new fields so positional meaning is explicit:

```python
records.append(RestrictionRecord(
    sku=sku,
    warehouse=warehouse,
    state=state,
    reason=normalize_text(row.get("причина")),
    source_value=raw,
    cluster=normalize_text(row.get("кластер")),
    max_supply_qty=max_qty,
    capacity_kind=capacity_kind,
))
```

Restriction state still controls permission. A PROHIBITED row never becomes usable because its capacity text says unlimited.

- [ ] **Step 6: Run tests and verify GREEN**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction capacity state"
```

---

### Task 2: Carry capacity state through `WarehouseCapability` and `SupplyFeasibility`

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Modify: `tests/supply/test_placement.py`

**Interfaces:**

Append to `WarehouseCapability`:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

Append to `SupplyFeasibility`:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

Keep the public function signature unchanged:

```python
def assess_feasibility(
    sku: str,
    cluster_id: str,
    restrictions: Iterable[RestrictionRecord],
    warehouses: Iterable[WarehouseCapability],
) -> SupplyFeasibility:
```

- [ ] **Step 1: Add exact test builders in `tests/supply/test_placement.py`**

```python
from backend.ingestion.restrictions import (
    RestrictionCapacityKind,
    RestrictionRecord,
    RestrictionState,
)


def _allowed(
    sku: str,
    warehouse: str,
    cluster: str,
    kind: RestrictionCapacityKind,
    maximum: int | None,
) -> RestrictionRecord:
    return RestrictionRecord(
        sku=sku,
        warehouse=warehouse,
        state=RestrictionState.ALLOWED,
        reason="",
        source_value="Да",
        cluster=cluster,
        max_supply_qty=maximum,
        capacity_kind=kind,
    )


def _warehouse(
    warehouse: str,
    cluster: str,
    kind: RestrictionCapacityKind,
    maximum: int | None,
) -> WarehouseCapability:
    return WarehouseCapability(
        warehouse=warehouse,
        cluster_id=cluster,
        max_supply_qty=maximum,
        capacity_kind=kind,
    )
```

- [ ] **Step 2: Add failing aggregation tests**

```python
def test_cluster_capacity_uses_max_single_finite_option_not_min_or_sum():
    result = assess_feasibility(
        "SKU-1",
        "Москва",
        (
            _allowed("SKU-1", "W1", "Москва", RestrictionCapacityKind.FINITE, 100),
            _allowed("SKU-1", "W2", "Москва", RestrictionCapacityKind.FINITE, 300),
        ),
        (
            _warehouse("W1", "Москва", RestrictionCapacityKind.FINITE, 100),
            _warehouse("W2", "Москва", RestrictionCapacityKind.FINITE, 300),
        ),
    )
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 300


def test_known_finite_option_survives_unknown_alternative():
    result = assess_feasibility(
        "SKU-1",
        "Москва",
        (
            _allowed("SKU-1", "W1", "Москва", RestrictionCapacityKind.FINITE, 120),
            _allowed("SKU-1", "W2", "Москва", RestrictionCapacityKind.UNKNOWN, None),
        ),
        (
            _warehouse("W1", "Москва", RestrictionCapacityKind.FINITE, 120),
            _warehouse("W2", "Москва", RestrictionCapacityKind.UNKNOWN, None),
        ),
    )
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 120


def test_unlimited_option_wins_over_finite_option():
    result = assess_feasibility(
        "SKU-1",
        "Москва",
        (
            _allowed("SKU-1", "W1", "Москва", RestrictionCapacityKind.FINITE, 120),
            _allowed("SKU-1", "W2", "Москва", RestrictionCapacityKind.UNLIMITED, None),
        ),
        (
            _warehouse("W1", "Москва", RestrictionCapacityKind.FINITE, 120),
            _warehouse("W2", "Москва", RestrictionCapacityKind.UNLIMITED, None),
        ),
    )
    assert result.capacity_kind is RestrictionCapacityKind.UNLIMITED
    assert result.max_supply_qty is None


def test_all_allowed_options_unknown_leave_cluster_capacity_unknown():
    result = assess_feasibility(
        "SKU-1",
        "Москва",
        (_allowed("SKU-1", "W1", "Москва", RestrictionCapacityKind.UNKNOWN, None),),
        (_warehouse("W1", "Москва", RestrictionCapacityKind.UNKNOWN, None),),
    )
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.UNKNOWN
    assert result.max_supply_qty is None
```

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

Expected: new field/aggregation assertions fail under current contracts and `min()` behavior.

- [ ] **Step 4: Extend contract validation**

Import `RestrictionCapacityKind` into `backend/supply/contracts.py`. Append `capacity_kind` to `WarehouseCapability`, then add:

```python
if not isinstance(self.capacity_kind, RestrictionCapacityKind):
    raise TypeError("capacity_kind must be RestrictionCapacityKind")
if self.capacity_kind is RestrictionCapacityKind.FINITE:
    if self.max_supply_qty is None:
        raise ValueError("finite capacity requires max_supply_qty")
elif self.max_supply_qty is not None:
    raise ValueError("non-finite capacity must not contain max_supply_qty")
```

Append `capacity_kind` to `SupplyFeasibility` and validate its enum type wherever that dataclass is constructed/tested.

- [ ] **Step 5: Replace only the multi-warehouse capacity aggregation in feasibility**

After current restriction-state/eligible-warehouse filtering, derive:

```python
known = tuple(
    item for item in eligible_capabilities
    if item.capacity_kind in {
        RestrictionCapacityKind.FINITE,
        RestrictionCapacityKind.UNLIMITED,
    }
)
if not known:
    maximum = None
    capacity_kind = RestrictionCapacityKind.UNKNOWN
elif any(
    item.capacity_kind is RestrictionCapacityKind.UNLIMITED
    for item in known
):
    maximum = None
    capacity_kind = RestrictionCapacityKind.UNLIMITED
else:
    maximum = max(
        item.max_supply_qty
        for item in known
        if item.max_supply_qty is not None
    )
    capacity_kind = RestrictionCapacityKind.FINITE
```

If no warehouse is explicitly eligible at all, keep current fail-closed `allowed=False` behavior and use `capacity_kind=UNKNOWN`; do not represent “not allowed” as a finite zero capacity.

Return:

```python
SupplyFeasibility(
    sku=sku,
    cluster_id=cluster_id,
    allowed=allowed,
    max_supply_qty=maximum,
    eligible_warehouses=tuple(sorted(eligible_names)),
    reasons=tuple(reasons),
    capacity_kind=capacity_kind,
)
```

Remove the old `CONSERVATIVE_WAREHOUSE_MAXIMUM` reason from this new aggregation path. Add `MULTIPLE_WAREHOUSE_ALTERNATIVES` when more than one allowed receiving option exists and `UNKNOWN_CAPACITY_ALTERNATIVE_PRESENT` when a known cluster ceiling coexists with an unknown alternative.

- [ ] **Step 6: Run placement + legacy optimizer regressions**

```bash
python -m pytest tests/supply/test_placement.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/contracts.py backend/supply/feasibility.py tests/supply/test_placement.py
git commit -m "feat: model cluster supply capacity explicitly"
```

---

### Task 3: Add desired coverage contracts and exact test builders

**Files:**
- Modify: `backend/supply/contracts.py`
- Create: `tests/supply/test_coverage.py`

**Interfaces:**

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
    volume_band: "VolumeBand | None"
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

Use `TYPE_CHECKING` for `VolumeBand` so `supply/contracts.py` does not create a runtime economics import cycle.

- [ ] **Step 1: Create `tests/supply/test_coverage.py` with exact builders**

```python
from decimal import Decimal

from backend.economics.tariffs import (
    DirectRouteQuote,
    TariffLookupStatus,
    VolumeBand,
)
from backend.ingestion.restrictions import RestrictionCapacityKind
from backend.supply.contracts import (
    CoverageType,
    DestinationTarget,
    PlanFamily,
    RouteConfidence,
    SupplyFeasibility,
)


def _finite(sku: str, origin: str, maximum: int) -> SupplyFeasibility:
    return SupplyFeasibility(
        sku=sku,
        cluster_id=origin,
        allowed=True,
        max_supply_qty=maximum,
        eligible_warehouses=(f"{origin}-W1",),
        reasons=(),
        capacity_kind=RestrictionCapacityKind.FINITE,
    )


def _unlimited(sku: str, origin: str) -> SupplyFeasibility:
    return SupplyFeasibility(
        sku=sku,
        cluster_id=origin,
        allowed=True,
        max_supply_qty=None,
        eligible_warehouses=(f"{origin}-W1",),
        reasons=(),
        capacity_kind=RestrictionCapacityKind.UNLIMITED,
    )


def _unknown(sku: str, origin: str) -> SupplyFeasibility:
    return SupplyFeasibility(
        sku=sku,
        cluster_id=origin,
        allowed=True,
        max_supply_qty=None,
        eligible_warehouses=(f"{origin}-W1",),
        reasons=(),
        capacity_kind=RestrictionCapacityKind.UNKNOWN,
    )


def _matched(origin: str, destination: str, fee: str) -> DirectRouteQuote:
    return DirectRouteQuote(
        origin,
        destination,
        VolumeBand(Decimal("0"), Decimal("1")),
        TariffLookupStatus.MATCHED,
        Decimal(fee),
        10,
        None,
    )


def _missing(origin: str, destination: str) -> DirectRouteQuote:
    return DirectRouteQuote(
        origin,
        destination,
        None,
        TariffLookupStatus.MISSING,
        None,
        None,
        "MISSING_TARIFF",
    )
```

- [ ] **Step 2: Add failing contract validation tests**

```python
def test_destination_target_preserves_destination_identity():
    target = DestinationTarget("SKU-1", "Казань", 100, PlanFamily.CALCULATED)
    assert target.destination_cluster_id == "Казань"
    assert target.quantity == 100


def test_destination_target_rejects_negative_quantity():
    with pytest.raises(ValueError, match="quantity"):
        DestinationTarget("SKU-1", "Казань", -1, PlanFamily.CALCULATED)
```

After adding `DesiredCoverageLeg`, also assert zero `desired_qty` is rejected and ROUTE requires `direct_route_fee`, while LOCAL requires `direct_route_fee is None`.

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: contract imports fail.

- [ ] **Step 4: Implement contracts with repository validation helpers**

Use `_require_nonblank()` and `_require_nonnegative_int()` already present in `backend/supply/contracts.py`.

`DestinationTarget.quantity` may be zero. `DesiredCoverageLeg.desired_qty` and `NetworkCoverageGap.quantity` must be positive integers. ROUTE leg validation:

```python
if self.coverage_type is CoverageType.ROUTE:
    if self.direct_route_fee is None:
        raise ValueError("route coverage requires direct_route_fee")
    if not isinstance(self.direct_route_fee, Decimal):
        raise TypeError("direct_route_fee must be Decimal")
    if not self.direct_route_fee.is_finite() or self.direct_route_fee < Decimal("0"):
        raise ValueError("direct_route_fee must be finite and nonnegative")
elif self.direct_route_fee is not None:
    raise ValueError("local coverage must not contain direct_route_fee")
```

Validate enum types and tuple types explicitly following existing contract style.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_coverage.py
git commit -m "feat: add coverage planning contracts"
```

---

### Task 4: Implement LOCAL-first assignment with one shared capacity ledger

**Files:**
- Create: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Interfaces:**

```python
def plan_coverage_for_sku(
    *,
    targets: Iterable[DestinationTarget],
    selected_origin_cluster_ids: Iterable[str],
    feasibility_by_origin: Mapping[str, SupplyFeasibility],
    direct_quotes: Mapping[tuple[str, str], DirectRouteQuote],
    route_confidence_by_route: Mapping[tuple[str, str], RouteConfidence] | None = None,
) -> CoveragePlanResult:
```

All targets in one call must share one SKU and one PlanFamily.

- [ ] **Step 1: Add failing LOCAL-first test**

```python
def test_local_is_assigned_before_cheaper_nonlocal_route():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 50, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Казань", "Москва"),
        feasibility_by_origin={
            "Казань": _finite("SKU-1", "Казань", 50),
            "Москва": _finite("SKU-1", "Москва", 100),
        },
        direct_quotes={
            ("Москва", "Казань"): _matched("Москва", "Казань", "1"),
        },
    )
    assert [
        (leg.origin_cluster_id, leg.destination_cluster_id, leg.desired_qty, leg.coverage_type)
        for leg in result.desired_legs
    ] == [("Казань", "Казань", 50, CoverageType.LOCAL)]
    assert result.network_gaps == ()
```

- [ ] **Step 2: Add failing shared-capacity test**

```python
def test_one_origin_capacity_is_shared_across_destinations():
    result = plan_coverage_for_sku(
        targets=(
            DestinationTarget("SKU-1", "A", 60, PlanFamily.CALCULATED),
            DestinationTarget("SKU-1", "B", 60, PlanFamily.CALCULATED),
        ),
        selected_origin_cluster_ids=("Москва",),
        feasibility_by_origin={"Москва": _finite("SKU-1", "Москва", 100)},
        direct_quotes={
            ("Москва", "A"): _matched("Москва", "A", "10"),
            ("Москва", "B"): _matched("Москва", "B", "10"),
        },
    )
    assert sum(
        leg.desired_qty
        for leg in result.desired_legs
        if leg.origin_cluster_id == "Москва"
    ) == 100
    assert sum(gap.quantity for gap in result.network_gaps) == 20
```

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: `plan_coverage_for_sku` import failure.

- [ ] **Step 4: Implement input normalization and capacity helpers**

Create `backend/supply/coverage.py` with imports from `collections.abc`, PR-A tariffs, capacity enum and supply contracts. Add:

```python
def _capacity_value(feasibility: SupplyFeasibility | None) -> int | None | object:
    if feasibility is None or not feasibility.allowed:
        return _UNUSABLE
    if feasibility.capacity_kind is RestrictionCapacityKind.UNKNOWN:
        return _UNUSABLE
    if feasibility.capacity_kind is RestrictionCapacityKind.UNLIMITED:
        return None
    return feasibility.max_supply_qty


def _take(remaining: int | None, requested: int) -> tuple[int, int | None]:
    if remaining is None:
        return requested, None
    quantity = min(remaining, requested)
    return quantity, remaining - quantity
```

Define module sentinel:

```python
_UNUSABLE = object()
```

Validate selected IDs as stripped unique strings; reject blanks and duplicates rather than silently deduplicating caller errors. Stable-sort after validation.

Validate nonempty targets, one SKU, one PlanFamily and unique destinations.

- [ ] **Step 5: Implement the LOCAL pass**

Initialize:

```python
residual = {target.destination_cluster_id: target.quantity for target in target_items}
remaining = {
    origin: _capacity_value(feasibility_by_origin.get(origin))
    for origin in selected_origins
}
legs: list[DesiredCoverageLeg] = []
gaps: list[NetworkCoverageGap] = []
```

For each target sorted by destination ID, when destination is selected and its remaining capacity is usable, take from that same origin. If quantity is positive, append:

```python
DesiredCoverageLeg(
    sku=sku,
    origin_cluster_id=destination,
    destination_cluster_id=destination,
    desired_qty=quantity,
    coverage_type=CoverageType.LOCAL,
    direct_route_fee=None,
    volume_band=None,
    route_confidence=RouteConfidence.HIGH,
    reason_codes=("LOCAL_FIRST",),
)
```

Update the one shared `remaining[destination]` and `residual[destination]`.

Do not create gaps yet; Task 5 owns non-local/gap completion.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: LOCAL-first test passes. Shared-capacity test may still fail until non-local/gap completion in Task 5.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: assign local coverage with shared capacity"
```

---

### Task 5: Implement iterative constrained-first non-local routing and network gaps

**Files:**
- Modify: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Interfaces:**
- Completes `plan_coverage_for_sku()`.

- [ ] **Step 1: Add failing direct-fee ordering test**

```python
def test_cheaper_route_beats_higher_confidence_expensive_route():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 50, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": _unlimited("SKU-1", "Москва"),
            "Питер": _unlimited("SKU-1", "Питер"),
        },
        direct_quotes={
            ("Москва", "Казань"): _matched("Москва", "Казань", "47"),
            ("Питер", "Казань"): _matched("Питер", "Казань", "52"),
        },
        route_confidence_by_route={
            ("Москва", "Казань"): RouteConfidence.LOW,
            ("Питер", "Казань"): RouteConfidence.HIGH,
        },
    )
    assert [(leg.origin_cluster_id, leg.desired_qty) for leg in result.desired_legs] == [
        ("Москва", 50)
    ]
```

- [ ] **Step 2: Add failing exact-fee confidence tie test**

Use the same target with both fees `47`, Moscow LOW and Peter HIGH. Assert Peter receives all 50. Then set both confidence HIGH and assert stable origin-ID order decides the tie.

- [ ] **Step 3: Add failing capacity-spillover test**

```python
def test_cheapest_route_fills_then_spills_to_next_route():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 100, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": _finite("SKU-1", "Москва", 70),
            "Питер": _finite("SKU-1", "Питер", 100),
        },
        direct_quotes={
            ("Москва", "Казань"): _matched("Москва", "Казань", "47"),
            ("Питер", "Казань"): _matched("Питер", "Казань", "52"),
        },
    )
    assert [(leg.origin_cluster_id, leg.desired_qty) for leg in result.desired_legs] == [
        ("Москва", 70),
        ("Питер", 30),
    ]
```

- [ ] **Step 4: Add failing constrained-destination test**

```python
def test_constrained_destination_is_not_stranded_by_flexible_destination():
    result = plan_coverage_for_sku(
        targets=(
            DestinationTarget("SKU-1", "A", 60, PlanFamily.CALCULATED),
            DestinationTarget("SKU-1", "B", 60, PlanFamily.CALCULATED),
        ),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": _finite("SKU-1", "Москва", 60),
            "Питер": _finite("SKU-1", "Питер", 60),
        },
        direct_quotes={
            ("Москва", "A"): _matched("Москва", "A", "10"),
            ("Москва", "B"): _matched("Москва", "B", "5"),
            ("Питер", "B"): _matched("Питер", "B", "6"),
        },
    )
    by_destination = {
        destination: sum(
            leg.desired_qty
            for leg in result.desired_legs
            if leg.destination_cluster_id == destination
        )
        for destination in ("A", "B")
    }
    assert by_destination == {"A": 60, "B": 60}
    assert result.network_gaps == ()
```

If B were processed by cheapest fee first it would consume Moscow and strand A; this test requires iterative constrained-first ordering.

- [ ] **Step 5: Add failing network-gap cause tests**

```python
def test_empty_selected_network_reports_no_selected_feasible_origin():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 40, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=(),
        feasibility_by_origin={},
        direct_quotes={},
    )
    assert result.network_gaps[0].quantity == 40
    assert result.network_gaps[0].reason_codes == ("NO_SELECTED_FEASIBLE_ORIGIN",)


def test_unknown_capacity_is_not_used_as_unlimited():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 40, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Москва",),
        feasibility_by_origin={"Москва": _unknown("SKU-1", "Москва")},
        direct_quotes={("Москва", "Казань"): _matched("Москва", "Казань", "47")},
    )
    assert result.network_gaps[0].reason_codes == (
        "ORIGIN_CAPACITY_EXHAUSTED_OR_UNKNOWN",
    )


def test_missing_tariff_does_not_fabricate_route():
    result = plan_coverage_for_sku(
        targets=(DestinationTarget("SKU-1", "Казань", 40, PlanFamily.CALCULATED),),
        selected_origin_cluster_ids=("Москва",),
        feasibility_by_origin={"Москва": _unlimited("SKU-1", "Москва")},
        direct_quotes={("Москва", "Казань"): _missing("Москва", "Казань")},
    )
    assert result.network_gaps[0].reason_codes == ("NO_COMPLETE_DIRECT_TARIFF",)
```

- [ ] **Step 6: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: non-local and gap tests fail.

- [ ] **Step 7: Implement candidate discovery from current capacity state**

Add:

```python
_ROUTE_RANK = {
    RouteConfidence.LOW: 1,
    RouteConfidence.MEDIUM: 2,
    RouteConfidence.HIGH: 3,
}


def _matched_candidates(
    destination: str,
    selected_origins: tuple[str, ...],
    remaining: dict[str, int | None | object],
    direct_quotes: Mapping[tuple[str, str], DirectRouteQuote],
    route_confidence_by_route: Mapping[tuple[str, str], RouteConfidence],
) -> list[tuple[str, DirectRouteQuote, RouteConfidence]]:
    candidates: list[tuple[str, DirectRouteQuote, RouteConfidence]] = []
    for origin in selected_origins:
        if origin == destination:
            continue
        capacity = remaining[origin]
        if capacity is _UNUSABLE or capacity == 0:
            continue
        quote = direct_quotes.get((origin, destination))
        if quote is None or quote.lookup_status is not TariffLookupStatus.MATCHED:
            continue
        confidence = route_confidence_by_route.get(
            (origin, destination), RouteConfidence.LOW
        )
        candidates.append((origin, quote, confidence))
    candidates.sort(key=lambda item: item[0])
    candidates.sort(key=lambda item: _ROUTE_RANK[item[2]], reverse=True)
    candidates.sort(key=lambda item: item[1].matched_fee)
    return candidates
```

Because Python sort is stable, direct fee is primary, confidence resolves equal fees, and origin ID resolves the final tie.

- [ ] **Step 8: Implement iterative destination choice**

After LOCAL pass:

```python
route_confidence = route_confidence_by_route or {}
while any(quantity > 0 for quantity in residual.values()):
    ranked: list[tuple[int, int, str, list[tuple[str, DirectRouteQuote, RouteConfidence]]]] = []
    for destination, quantity in residual.items():
        if quantity <= 0:
            continue
        candidates = _matched_candidates(
            destination,
            selected_origins,
            remaining,
            direct_quotes,
            route_confidence,
        )
        ranked.append((len(candidates), -quantity, destination, candidates))
    feasible_ranked = [item for item in ranked if item[0] > 0]
    if not feasible_ranked:
        break
    _, _, destination, candidates = min(
        feasible_ranked,
        key=lambda item: (item[0], item[1], item[2]),
    )
    for origin, quote, confidence in candidates:
        if residual[destination] == 0:
            break
        capacity = remaining[origin]
        if capacity is _UNUSABLE:
            continue
        quantity, next_capacity = _take(capacity, residual[destination])
        if quantity == 0:
            continue
        legs.append(DesiredCoverageLeg(
            sku=sku,
            origin_cluster_id=origin,
            destination_cluster_id=destination,
            desired_qty=quantity,
            coverage_type=CoverageType.ROUTE,
            direct_route_fee=quote.matched_fee,
            volume_band=quote.volume_band,
            route_confidence=confidence,
            reason_codes=("DIRECT_TARIFF_ROUTE",),
        ))
        remaining[origin] = next_capacity
        residual[destination] -= quantity
```

The outer loop restarts after each selected destination so candidate counts are recomputed from the new remaining-capacity state.

- [ ] **Step 9: Classify remaining residual into deterministic network gaps**

For every positive residual after no matched feasible destination remains, inspect the selected network in this order:

```python
selected_feasibilities = [
    feasibility_by_origin.get(origin) for origin in selected_origins
]
physically_allowed = [
    item for item in selected_feasibilities
    if item is not None and item.allowed
]
known_usable = [
    origin for origin in selected_origins
    if remaining[origin] is not _UNUSABLE and remaining[origin] != 0
]
matched_tariff_exists = any(
    (quote := direct_quotes.get((origin, destination))) is not None
    and quote.lookup_status is TariffLookupStatus.MATCHED
    for origin in known_usable
)
```

Choose exactly one reason:
- no `physically_allowed` → `NO_SELECTED_FEASIBLE_ORIGIN`;
- physically allowed exist but `known_usable` empty → `ORIGIN_CAPACITY_EXHAUSTED_OR_UNKNOWN`;
- known usable exists but `matched_tariff_exists` false → `NO_COMPLETE_DIRECT_TARIFF`;
- otherwise use `ORIGIN_CAPACITY_EXHAUSTED_OR_UNKNOWN` because candidate capacity was consumed during earlier assignments.

Append one positive `NetworkCoverageGap` per destination.

- [ ] **Step 10: Stable-sort output and run tests**

Before return:

```python
legs.sort(key=lambda item: (
    item.destination_cluster_id,
    item.coverage_type.value,
    item.origin_cluster_id,
))
gaps.sort(key=lambda item: item.destination_cluster_id)
```

Run:

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: route residual demand through selected network"
```

---

### Task 6: Prove conservation, input-order invariance and public export

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_coverage.py`
- Regression: `tests/supply/test_placement.py`
- Regression: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add exact conservation test**

```python
def test_coverage_conserves_every_destination_target():
    result = plan_coverage_for_sku(
        targets=(
            DestinationTarget("SKU-1", "A", 80, PlanFamily.CALCULATED),
            DestinationTarget("SKU-1", "B", 70, PlanFamily.CALCULATED),
        ),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": _finite("SKU-1", "Москва", 100),
            "Питер": _finite("SKU-1", "Питер", 30),
        },
        direct_quotes={
            ("Москва", "A"): _matched("Москва", "A", "10"),
            ("Москва", "B"): _matched("Москва", "B", "10"),
            ("Питер", "B"): _matched("Питер", "B", "11"),
        },
    )
    for target in result.targets:
        covered = sum(
            leg.desired_qty
            for leg in result.desired_legs
            if leg.destination_cluster_id == target.destination_cluster_id
        )
        uncovered = sum(
            gap.quantity
            for gap in result.network_gaps
            if gap.destination_cluster_id == target.destination_cluster_id
        )
        assert covered + uncovered == target.quantity
    assert sum(
        leg.desired_qty
        for leg in result.desired_legs
        if leg.origin_cluster_id == "Москва"
    ) <= 100
    assert sum(
        leg.desired_qty
        for leg in result.desired_legs
        if leg.origin_cluster_id == "Питер"
    ) <= 30
```

- [ ] **Step 2: Add exact input-order invariance test**

Call the same facts twice, reversing target order, selected-origin order and dictionary insertion order. Assert the two `CoveragePlanResult` objects are equal.

- [ ] **Step 3: Add failing export test**

```python
def test_coverage_planner_is_exported():
    from backend.supply import CoveragePlanResult, plan_coverage_for_sku

    assert CoveragePlanResult.__name__ == "CoveragePlanResult"
    assert callable(plan_coverage_for_sku)
```

- [ ] **Step 4: Run export test and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py::test_coverage_planner_is_exported -q
```

Expected: import failure until exports are added.

- [ ] **Step 5: Export approved coverage surface**

Update `backend/supply/__init__.py` in its current explicit style. Export `CoverageType`, `DestinationTarget`, `DesiredCoverageLeg`, `NetworkCoverageGap`, `CoveragePlanResult`, and `plan_coverage_for_sku`. Do not export `_UNUSABLE`, `_take`, `_capacity_value`, `_matched_candidates`, or ranking dictionaries.

- [ ] **Step 6: Run PR-B regressions**

```bash
python -m pytest \
  tests/ingestion/test_restrictions.py \
  tests/supply/test_placement.py \
  tests/supply/test_coverage.py \
  tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full repository verification**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: every command exits 0.

- [ ] **Step 8: Commit**

```bash
git add backend/supply/__init__.py tests/supply/test_coverage.py
git commit -m "test: verify selected network coverage invariants"
```

---

## PR-B Acceptance Gate

Fresh `python -m pytest -q` output must prove:

- explicit unlimited, unknown and finite capacity are distinguishable;
- malformed nonblank capacity remains an ingestion error;
- cluster capacity uses best single known option, never min and never sum;
- one shared `SKU × origin` capacity ledger is enforced;
- LOCAL-first is independent of non-local tariff ranking;
- lower fee beats higher route confidence unless fees are equal;
- sequential spillover respects capacity;
- constrained destination is not stranded by a flexible destination;
- empty network, unknown/exhausted capacity and missing tariffs produce distinct explicit network gaps;
- desired legs + network gap conserve every destination target exactly;
- input order cannot change the planner result;
- current application/optimizer/snapshot/API/frontend path is not switched in PR-B.
