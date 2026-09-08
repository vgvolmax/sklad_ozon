# PR-B Restrictions Capacity & Coverage Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make restrictions capacity unambiguous and add a deterministic pure Coverage Planner that converts destination targets into desired `origin → destination` legs inside a user-selected supply network.

**Architecture:** Put the shared capacity-state enum at the normalized domain boundary so ingestion and supply can use it without layering cycles. Coverage Planner receives only primitive route evidence: exact direct fee/completeness, pair-level `RouteCostIndex` values, historical evidence and confidence. It does **not** import `backend.economics`; rich `DirectRouteQuote`, `RouteCostIndex` and direct economics objects remain owned by PR-A/PR-D. The planner owns LOCAL-first assignment, iterative constrained-destination ordering, exact-fee ranking, route-index tie-breaks and shared `SKU × origin` capacity consumption.

**Tech Stack:** Python 3, frozen dataclasses/enums, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** For non-local coverage the concrete SKU's complete direct tariff is primary. `RouteCostIndex` is secondary topology evidence and breaks only an exact direct-fee tie. Historical Flow remains informational. A missing direct tariff is never rescued by a favorable index.

## Global Constraints

- `destination_cluster` remains the owner of demand; Coverage Planner never rewrites demand/need geography.
- Restrictions report is the only physical eligibility/capacity source for this feature.
- Capacity evidence is exactly `FINITE / UNLIMITED / UNKNOWN`; unknown never means unlimited.
- Malformed nonblank numeric capacity remains an ingestion error.
- Multiple allowed warehouse limits inside one cluster are not summed.
- Cluster capacity is the best independently proven single receiving option: any known UNLIMITED wins; otherwise max known FINITE; if no known capacity exists, UNKNOWN.
- One `SKU × origin` capacity is shared by all destination legs through that origin.
- LOCAL is attempted before any non-local route and needs no external route tariff/index.
- Non-local candidates require selected origin, physical feasibility, known usable capacity and complete direct tariff evidence.
- Primary non-local ranking is `direct_route_fee ASC`.
- Exact-fee tie-breaks are: known lower `route_cost_index`, then higher `route_confidence`, then stable origin ID.
- Historical route share/quantity never changes coverage quantities or ranking.
- No proportional split, geographic fallback, LP or min-cost-flow solver.
- No numeric index thresholds such as `0.8` / `1.3` belong in planning logic.
- PR-B does not apply seller-stock scarcity or margin eligibility; PR-C owns that.
- PR-B does not modify `backend/application.py`, decision snapshots, API or frontend.
- `backend/supply` MUST NOT import `backend.economics` in this PR.
- Use TDD and keep every task independently green.

---

## File Structure

- Modify `backend/domain/contracts.py` — add shared `RestrictionCapacityKind` enum.
- Modify `backend/ingestion/restrictions.py` — preserve explicit capacity kind on every normalized restriction record.
- Modify `backend/supply/contracts.py` — extend feasibility contracts and add primitive coverage contracts.
- Modify `backend/supply/feasibility.py` — canonical non-additive cluster-capacity aggregation.
- Create `backend/supply/coverage.py` — pure deterministic Coverage Planner.
- Modify `backend/supply/__init__.py` — export coverage contracts/functions.
- Modify `tests/ingestion/test_restrictions.py` — finite/unlimited/unknown/malformed parsing.
- Modify `tests/supply/test_placement.py` — cluster-capacity aggregation and legacy placement regression.
- Create `tests/supply/test_coverage.py` — planner contracts, ordering, LOCAL-first, shared capacity, constrained-first, gap and conservation tests.

---

### Task 1: Preserve explicit capacity state at the normalized domain boundary

**Files:**
- Modify: `backend/domain/contracts.py`
- Modify: `backend/ingestion/restrictions.py`
- Test: `tests/ingestion/test_restrictions.py`

**Interfaces:**

```python
class RestrictionCapacityKind(str, Enum):
    FINITE = "finite"
    UNLIMITED = "unlimited"
    UNKNOWN = "unknown"
```

Append to `RestrictionRecord`:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

`max_supply_qty` remains `int | None`. Only FINITE may carry an integer.

- [ ] **Step 1: Add exact CSV helper and failing parsing tests**

In `tests/ingestion/test_restrictions.py` add:

```python
def _capacity_csv(maximum: str) -> bytes:
    return (
        "SKU;Кластер;Склад;Возможно ли поставить товар;Максимальный размер поставки\n"
        f"SKU-1;Москва;W1;Да;{maximum}\n"
    ).encode("utf-8")
```

Add:

```python
def test_allowed_finite_capacity_is_explicit(report_meta):
    row = import_restrictions(_capacity_csv("120"), report_meta).records[0]
    assert row.max_supply_qty == 120
    assert row.capacity_kind is RestrictionCapacityKind.FINITE


def test_allowed_unlimited_capacity_is_explicit(report_meta):
    row = import_restrictions(
        _capacity_csv("Без ограничений"), report_meta
    ).records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNLIMITED


def test_allowed_blank_capacity_is_unknown(report_meta):
    row = import_restrictions(_capacity_csv(""), report_meta).records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNKNOWN


def test_malformed_nonblank_capacity_remains_error(report_meta):
    result = import_restrictions(_capacity_csv("сто двадцать"), report_meta)
    assert result.records == ()
    assert any(x.code == "INVALID_MAX_SUPPLY_QTY" for x in result.diagnostics)
```

Import `RestrictionCapacityKind` from `backend.domain.contracts` in the test.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: import/attribute failure because capacity kind is not modeled.

- [ ] **Step 3: Add enum to `backend/domain/contracts.py` and extend `RestrictionRecord`**

`backend/ingestion/restrictions.py` imports the enum from `backend.domain.contracts`; it does not define a duplicate enum.

- [ ] **Step 4: Replace ambiguous capacity parsing**

Use exactly:

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

Pass `capacity_kind` as the final `RestrictionRecord` field. PROHIBITED/UNKNOWN restriction state remains physically unusable regardless of capacity text.

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/domain/contracts.py backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction capacity state"
```

---

### Task 2: Carry capacity state through cluster feasibility

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Modify: `tests/supply/test_placement.py`

**Interfaces:**

Append to both existing dataclasses:

```python
WarehouseCapability.capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
SupplyFeasibility.capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- [ ] **Step 1: Add exact helper constructors in `tests/supply/test_placement.py`**

```python
def capability(name, qty, kind):
    return WarehouseCapability(name, "Москва", qty, kind)


def allowed_record(name, qty, kind):
    return RestrictionRecord(
        "SKU-1", name, RestrictionState.ALLOWED, "", "Да",
        "Москва", qty, kind,
    )
```

- [ ] **Step 2: Add failing aggregation tests**

```python
def test_cluster_uses_max_finite_alternative_not_sum_or_min():
    rows = (
        allowed_record("W1", 100, RestrictionCapacityKind.FINITE),
        allowed_record("W2", 300, RestrictionCapacityKind.FINITE),
    )
    warehouses = (
        capability("W1", 100, RestrictionCapacityKind.FINITE),
        capability("W2", 300, RestrictionCapacityKind.FINITE),
    )
    result = assess_feasibility("SKU-1", "Москва", rows, warehouses)
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 300


def test_known_finite_survives_unknown_alternative():
    rows = (
        allowed_record("W1", 120, RestrictionCapacityKind.FINITE),
        allowed_record("W2", None, RestrictionCapacityKind.UNKNOWN),
    )
    warehouses = (
        capability("W1", 120, RestrictionCapacityKind.FINITE),
        capability("W2", None, RestrictionCapacityKind.UNKNOWN),
    )
    result = assess_feasibility("SKU-1", "Москва", rows, warehouses)
    assert result.capacity_kind is RestrictionCapacityKind.FINITE
    assert result.max_supply_qty == 120


def test_unlimited_alternative_wins_over_finite():
    rows = (
        allowed_record("W1", 120, RestrictionCapacityKind.FINITE),
        allowed_record("W2", None, RestrictionCapacityKind.UNLIMITED),
    )
    warehouses = (
        capability("W1", 120, RestrictionCapacityKind.FINITE),
        capability("W2", None, RestrictionCapacityKind.UNLIMITED),
    )
    result = assess_feasibility("SKU-1", "Москва", rows, warehouses)
    assert result.capacity_kind is RestrictionCapacityKind.UNLIMITED
    assert result.max_supply_qty is None


def test_all_allowed_capacity_unknown_stays_unknown():
    rows = (allowed_record("W1", None, RestrictionCapacityKind.UNKNOWN),)
    warehouses = (capability("W1", None, RestrictionCapacityKind.UNKNOWN),)
    result = assess_feasibility("SKU-1", "Москва", rows, warehouses)
    assert result.allowed is True
    assert result.capacity_kind is RestrictionCapacityKind.UNKNOWN
    assert result.max_supply_qty is None
```

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

Expected: new state/aggregation tests fail against current `min(explicit_maxima)` behavior.

- [ ] **Step 4: Add contract consistency validation**

In `WarehouseCapability.__post_init__`:

```python
if not isinstance(self.capacity_kind, RestrictionCapacityKind):
    raise TypeError("capacity_kind must be RestrictionCapacityKind")
if self.capacity_kind is RestrictionCapacityKind.FINITE:
    if self.max_supply_qty is None:
        raise ValueError("finite capacity requires max_supply_qty")
elif self.max_supply_qty is not None:
    raise ValueError("non-finite capacity must not contain max_supply_qty")
```

Validate `SupplyFeasibility.capacity_kind` similarly when adding its `__post_init__` or extending existing validation.

- [ ] **Step 5: Replace only capacity aggregation inside `assess_feasibility()`**

Keep current restriction-state screening. For eligible warehouses:

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
elif any(
    item.capacity_kind is RestrictionCapacityKind.UNLIMITED
    for item in known
):
    maximum = None
    capacity_kind = RestrictionCapacityKind.UNLIMITED
else:
    maximum = max(
        item.max_supply_qty for item in known
        if item.max_supply_qty is not None
    )
    capacity_kind = RestrictionCapacityKind.FINITE
```

Replace old reason `CONSERVATIVE_WAREHOUSE_MAXIMUM` with `MULTIPLE_WAREHOUSE_ALTERNATIVES` when more than one eligible warehouse exists. Preserve `ZERO_PHYSICAL_CEILING` and `ELIGIBLE_WAREHOUSE_FOUND` semantics.

- [ ] **Step 6: Run feasibility + legacy optimizer regressions**

```bash
python -m pytest tests/supply/test_placement.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/contracts.py backend/supply/feasibility.py tests/supply/test_placement.py
git commit -m "feat: model cluster capacity explicitly"
```

---

### Task 3: Define primitive coverage contracts with no economics dependency

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
class RoutePlanningEvidence:
    origin_cluster_id: str
    destination_cluster_id: str
    direct_tariff_complete: bool
    direct_route_fee: Decimal | None
    direct_tariff_reason_code: str | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
    route_cost_index_spread: Decimal | None
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None


@dataclass(frozen=True, slots=True)
class DesiredCoverageLeg:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    desired_qty: int
    coverage_type: CoverageType
    direct_route_fee: Decimal | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
    route_cost_index_spread: Decimal | None
    route_confidence: RouteConfidence
    observed_flow_qty: int
    observed_flow_share: Decimal | None
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

- [ ] **Step 1: Add exact test helpers**

At the top of `tests/supply/test_coverage.py` add:

```python
def route_evidence(
    origin="Москва",
    destination="Казань",
    *,
    fee="50",
    index="1",
    confidence=RouteConfidence.MEDIUM,
    observed_qty=0,
    observed_share=None,
):
    return RoutePlanningEvidence(
        origin,
        destination,
        True,
        Decimal(fee),
        None,
        None if index is None else Decimal(index),
        Decimal("1") if index is not None else None,
        Decimal("0") if index is not None else None,
        confidence,
        observed_qty,
        None if observed_share is None else Decimal(observed_share),
    )


def missing_tariff(origin="Москва", destination="Казань"):
    return RoutePlanningEvidence(
        origin, destination, False, None, "MISSING_TARIFF",
        Decimal("0.8"), Decimal("1"), Decimal("0.1"),
        RouteConfidence.LOW, 0, None,
    )
```

- [ ] **Step 2: Add failing validation tests**

```python
def test_incomplete_tariff_cannot_carry_direct_fee():
    with pytest.raises(ValueError, match="direct_route_fee"):
        RoutePlanningEvidence(
            "Москва", "Казань", False, Decimal("50"), "MISSING_TARIFF",
            None, None, None, RouteConfidence.LOW, 0, None,
        )


def test_observed_share_must_be_fraction():
    with pytest.raises(ValueError, match="observed_flow_share"):
        route_evidence(observed_share="1.1")


def test_destination_target_rejects_negative_quantity():
    with pytest.raises(ValueError, match="quantity"):
        DestinationTarget("SKU-1", "Казань", -1, PlanFamily.CALCULATED)


def test_routed_leg_requires_nonlocal_identity_and_fee():
    with pytest.raises(ValueError):
        DesiredCoverageLeg(
            "SKU-1", "Москва", "Москва", 1, CoverageType.ROUTE,
            Decimal("50"), Decimal("1"), Decimal("1"), Decimal("0"),
            RouteConfidence.MEDIUM, 0, None, (),
        )
```

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: coverage contracts do not exist.

- [ ] **Step 4: Implement contracts and validation**

Rules:

```text
all identities nonblank
all integer quantities nonnegative; DesiredCoverageLeg.desired_qty strictly positive
complete tariff -> direct_route_fee is nonnegative Decimal and reason is None
incomplete tariff -> direct_route_fee is None and reason code nonblank
index absent -> coverage/spread both absent
index present -> index/spread nonnegative; coverage in [0,1]
observed_flow_share absent or Decimal in [0,1]
LOCAL leg -> origin == destination and direct_route_fee/index fields are None
ROUTE leg -> origin != destination and direct_route_fee nonnegative
```

`backend/supply/contracts.py` imports only `Decimal`, domain signals/contracts and supply-owned enums. It does not import `backend.economics`.

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_coverage.py
git commit -m "feat: define primitive coverage contracts"
```

---

### Task 4: Add deterministic non-local route ordering

**Files:**
- Create: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Private interface:**

```python
_ROUTE_RANK = {
    RouteConfidence.LOW: 1,
    RouteConfidence.MEDIUM: 2,
    RouteConfidence.HIGH: 3,
}


def _route_order_key(item: RoutePlanningEvidence) -> tuple:
    return (
        item.direct_route_fee,
        item.route_cost_index is None,
        Decimal("0") if item.route_cost_index is None else item.route_cost_index,
        -_ROUTE_RANK[item.route_confidence],
        item.origin_cluster_id,
    )
```

The helper is called only for evidence where `direct_tariff_complete=True` and fee is non-None.

- [ ] **Step 1: Add exact fee-priority test using the defined helper**

```python
def test_lower_direct_fee_wins_even_when_index_is_worse():
    rows = (
        route_evidence("Москва", "Казань", fee="47", index="1.10"),
        route_evidence("Питер", "Казань", fee="52", index="0.70"),
    )
    assert sorted(rows, key=_route_order_key)[0].origin_cluster_id == "Москва"
```

Import `_route_order_key` directly in this focused unit test even though it is private; the export gate later confirms it is not part of `backend.supply` public facade.

- [ ] **Step 2: Add exact-fee index tie test**

```python
def test_lower_index_breaks_exact_fee_tie():
    rows = (
        route_evidence("Москва", "Казань", fee="50", index="0.95"),
        route_evidence("Питер", "Казань", fee="50", index="0.72"),
    )
    assert sorted(rows, key=_route_order_key)[0].origin_cluster_id == "Питер"
```

- [ ] **Step 3: Add known-index and history non-influence tests**

```python
def test_known_index_beats_missing_index_only_when_fee_equal():
    rows = (
        route_evidence("Москва", "Казань", fee="50", index=None),
        route_evidence("Питер", "Казань", fee="50", index="1.20"),
    )
    assert sorted(rows, key=_route_order_key)[0].origin_cluster_id == "Питер"


def test_observed_flow_does_not_affect_route_order():
    rows = (
        route_evidence(
            "Москва", "Казань", fee="47", index="1.0",
            observed_qty=1, observed_share="0.01",
        ),
        route_evidence(
            "Питер", "Казань", fee="52", index="0.7",
            observed_qty=999, observed_share="0.99",
        ),
    )
    assert sorted(rows, key=_route_order_key)[0].origin_cluster_id == "Москва"
```

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: `backend/supply/coverage.py` / `_route_order_key` absent.

- [ ] **Step 5: Implement `_route_order_key` exactly as declared**

No route-index thresholds and no historical fields enter the tuple.

- [ ] **Step 6: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: rank coverage routes deterministically"
```

---

### Task 5: Implement LOCAL-first assignment and a shared `SKU × origin` capacity ledger

**Files:**
- Modify: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

**Public interface:**

```python
def plan_coverage(
    *,
    sku: str,
    targets: Iterable[DestinationTarget],
    selected_origin_cluster_ids: Iterable[str],
    feasibility_by_origin: Mapping[str, SupplyFeasibility],
    route_evidence_by_pair: Mapping[tuple[str, str], RoutePlanningEvidence],
) -> CoveragePlanResult:
```

- [ ] **Step 1: Add feasibility test helper**

```python
def feasibility(origin, *, qty=None, kind=RestrictionCapacityKind.UNLIMITED):
    return SupplyFeasibility(
        "SKU-1",
        origin,
        True,
        qty,
        (f"{origin}-W",),
        ("ELIGIBLE_WAREHOUSE_FOUND",),
        kind,
    )
```

For FINITE tests pass an integer `qty`; for UNLIMITED pass `None`.

- [ ] **Step 2: Add LOCAL-first test**

```python
def test_selected_destination_is_covered_locally_first():
    result = plan_coverage(
        sku="SKU-1",
        targets=(DestinationTarget(
            "SKU-1", "Казань", 50, PlanFamily.CALCULATED
        ),),
        selected_origin_cluster_ids=("Казань", "Москва"),
        feasibility_by_origin={
            "Казань": feasibility("Казань"),
            "Москва": feasibility("Москва"),
        },
        route_evidence_by_pair={
            ("Москва", "Казань"): route_evidence(
                "Москва", "Казань", fee="1", index="0.1"
            )
        },
    )
    assert [(x.origin_cluster_id, x.destination_cluster_id, x.desired_qty, x.coverage_type)
            for x in result.desired_legs] == [
        ("Казань", "Казань", 50, CoverageType.LOCAL)
    ]
```

- [ ] **Step 3: Add shared capacity test**

Use Moscow FINITE 70 with two residual destinations of 50 each and no other origins; assert:

```python
assert sum(x.desired_qty for x in result.desired_legs
           if x.origin_cluster_id == "Москва") == 70
assert sum(x.quantity for x in result.network_gaps) == 30
```

- [ ] **Step 4: Implement capacity normalization**

Reject selected UNKNOWN origins from candidate use. Create:

```python
remaining_capacity: dict[str, int | None] = {}
for origin in selected:
    item = feasibility_by_origin.get(origin)
    if item is None or not item.allowed:
        continue
    if item.capacity_kind is RestrictionCapacityKind.UNKNOWN:
        continue
    if item.capacity_kind is RestrictionCapacityKind.FINITE:
        if item.max_supply_qty is None:
            raise ValueError("finite feasibility requires max_supply_qty")
        remaining_capacity[origin] = item.max_supply_qty
    else:
        remaining_capacity[origin] = None
```

`None` in this ledger means **explicit UNLIMITED only**.

- [ ] **Step 5: Add and use capacity consumer**

```python
def _consume_capacity(
    origin: str,
    requested: int,
    remaining: dict[str, int | None],
) -> int:
    available = remaining[origin]
    if available is None:
        return requested
    allocated = min(requested, available)
    remaining[origin] = available - allocated
    return allocated
```

- [ ] **Step 6: Implement LOCAL pass**

Iterate targets sorted by destination ID. If destination is selected and present in `remaining_capacity`, consume local capacity and emit a LOCAL `DesiredCoverageLeg` with all non-local tariff/index fields `None`, preserving route confidence LOW and historical fields zero/None because no external evidence is required for the local product rule. Record only the residual quantity for Task 6.

- [ ] **Step 7: Run focused tests**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: LOCAL and shared-capacity tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: allocate local coverage before routed demand"
```

---

### Task 6: Implement iterative constrained-first non-local assignment

**Files:**
- Modify: `backend/supply/coverage.py`
- Modify: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add constrained-first test**

```python
def test_constrained_destination_reserves_scarce_origin():
    targets = (
        DestinationTarget("SKU-1", "A", 50, PlanFamily.CALCULATED),
        DestinationTarget("SKU-1", "B", 50, PlanFamily.CALCULATED),
    )
    result = plan_coverage(
        sku="SKU-1",
        targets=targets,
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": feasibility(
                "Москва", qty=50, kind=RestrictionCapacityKind.FINITE
            ),
            "Питер": feasibility(
                "Питер", qty=50, kind=RestrictionCapacityKind.FINITE
            ),
        },
        route_evidence_by_pair={
            ("Москва", "A"): route_evidence("Москва", "A", fee="50"),
            ("Москва", "B"): route_evidence("Москва", "B", fee="40"),
            ("Питер", "B"): route_evidence("Питер", "B", fee="60"),
        },
    )
    assert {(x.origin_cluster_id, x.destination_cluster_id, x.desired_qty)
            for x in result.desired_legs} == {
        ("Москва", "A", 50),
        ("Питер", "B", 50),
    }
    assert result.network_gaps == ()
```

- [ ] **Step 2: Add sequential fee/capacity spillover test**

```python
def test_cheapest_route_fills_then_spills_to_next_origin():
    result = plan_coverage(
        sku="SKU-1",
        targets=(DestinationTarget(
            "SKU-1", "Казань", 100, PlanFamily.CALCULATED
        ),),
        selected_origin_cluster_ids=("Москва", "Питер"),
        feasibility_by_origin={
            "Москва": feasibility(
                "Москва", qty=70, kind=RestrictionCapacityKind.FINITE
            ),
            "Питер": feasibility(
                "Питер", qty=100, kind=RestrictionCapacityKind.FINITE
            ),
        },
        route_evidence_by_pair={
            ("Москва", "Казань"): route_evidence(
                "Москва", "Казань", fee="47", index="0.90"
            ),
            ("Питер", "Казань"): route_evidence(
                "Питер", "Казань", fee="52", index="0.70"
            ),
        },
    )
    assert [(x.origin_cluster_id, x.desired_qty) for x in result.desired_legs] == [
        ("Москва", 70), ("Питер", 30)
    ]
```

- [ ] **Step 3: Add missing-direct-tariff test**

Use only `missing_tariff("Москва", "Казань")` for a selected feasible origin and target 50. Assert no desired leg and one gap quantity 50 containing `NO_COMPLETE_DIRECT_TARIFF`. This proves favorable route index inside missing evidence cannot make the route usable.

- [ ] **Step 4: Implement candidate recomputation per residual destination**

For every residual destination on every loop iteration, a non-local candidate must satisfy:

```text
origin selected and present in remaining_capacity
origin != destination
remaining finite capacity > 0 or explicit unlimited
route evidence exists
route evidence.direct_tariff_complete is True
route evidence.direct_route_fee is not None
```

Compute current candidate count for every residual destination. Choose the next destination by:

```python
(candidate_count, -residual_qty, destination_cluster_id)
```

If candidate count is zero, classify and emit its gap, remove it from residual work, and continue.

- [ ] **Step 5: Implement sequential candidate fill**

Sort current candidate evidence by `_route_order_key`. For each candidate, consume capacity and emit a ROUTE `DesiredCoverageLeg` copying its primitive fee/index/history/confidence evidence. Stop when destination residual is zero or candidates are exhausted.

- [ ] **Step 6: Implement deterministic gap classification**

Define reason order:

```python
_NETWORK_GAP_REASON_ORDER = (
    "NO_SELECTED_FEASIBLE_ORIGIN",
    "UNKNOWN_OR_EXHAUSTED_ORIGIN_CAPACITY",
    "NO_COMPLETE_DIRECT_TARIFF",
    "SELECTED_NETWORK_CAPACITY_EXHAUSTED",
)
```

Classification rules:
- no selected `allowed` feasibility row at all -> `NO_SELECTED_FEASIBLE_ORIGIN`;
- selected allowed rows exist but all capacity UNKNOWN/zero before any use -> `UNKNOWN_OR_EXHAUSTED_ORIGIN_CAPACITY`;
- usable-capacity selected origins exist but none has complete direct tariff -> `NO_COMPLETE_DIRECT_TARIFF`;
- route candidates existed earlier/currently but finite capacity is exhausted before residual reaches zero -> `SELECTED_NETWORK_CAPACITY_EXHAUSTED`.

A gap may contain multiple applicable codes, emitted in the fixed order.

- [ ] **Step 7: Run focused tests**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: plan routed coverage across selected network"
```

---

### Task 7: Prove conservation, determinism and public API

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add per-destination conservation helper and test**

```python
def assert_destination_conservation(result):
    for target in result.targets:
        covered = sum(
            x.desired_qty for x in result.desired_legs
            if x.destination_cluster_id == target.destination_cluster_id
        )
        gap = sum(
            x.quantity for x in result.network_gaps
            if x.destination_cluster_id == target.destination_cluster_id
        )
        assert covered + gap == target.quantity
```

Call it for LOCAL, constrained-first, spillover and missing-tariff scenarios.

- [ ] **Step 2: Add finite origin-capacity invariant test**

For every FINITE fixture origin assert sum of desired legs through it does not exceed the fixture maximum.

- [ ] **Step 3: Add permutation determinism test**

Using the constrained-first scenario, permute target order, selected-origin order and dictionary insertion order. Collect returned `CoveragePlanResult` values in a set and assert its length is 1.

- [ ] **Step 4: Export only the public coverage surface**

From `backend/supply/__init__.py` export:

```text
CoverageType
DestinationTarget
RoutePlanningEvidence
DesiredCoverageLeg
NetworkCoverageGap
CoveragePlanResult
plan_coverage
```

Do not export `_route_order_key`, `_consume_capacity` or gap-order internals.

- [ ] **Step 5: Add import-cycle regression**

```python
def test_supply_public_facade_does_not_require_economics_import():
    import backend.supply
    assert backend.supply.plan_coverage is not None
```

Also statically assert `"backend.economics"` is absent from `backend/supply/contracts.py` and `backend/supply/coverage.py`.

- [ ] **Step 6: Run focused + regression suites**

```bash
python -m pytest tests/ingestion/test_restrictions.py tests/supply/test_placement.py tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/supply/__init__.py tests/supply/test_coverage.py
git commit -m "feat: expose deterministic coverage planner"
```

---

## PR-B Acceptance Gate

PR-B is complete only when all are true:

1. Blank/unknown capacity can never become unlimited.
2. Explicit `Без ограничений` remains distinguishable from unknown.
3. Multiple warehouse limits are not summed; max independently known finite alternative is used unless one is explicitly unlimited.
4. `backend/supply` does not import `backend.economics` for route evidence.
5. LOCAL is always attempted first when selected and physically feasible.
6. Complete exact direct fee remains primary non-local ranking evidence.
7. `RouteCostIndex` only breaks exact direct-fee ties and never substitutes for missing direct tariff evidence.
8. Historical Flow share/quantity never changes route quantities or ranking.
9. One `SKU × origin` capacity is shared across all destination legs.
10. Constrained destinations are recomputed iteratively against remaining capacity.
11. Sequential fill is used; no proportional route split exists.
12. Every destination target conserves into desired legs + network gap.
13. Input permutations produce identical output.
14. No seller-stock scarcity, application orchestration, snapshot, API or UI behavior changed yet.
