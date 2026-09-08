# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing economics eligibility and deterministic `MAX_MARGIN` scarcity policy for desired `SKU × origin × destination` coverage legs, producing final allocated legs plus distinct allocation-blocked and seller-stock-uncovered quantities.

**Architecture:** Keep PR-B as the sole owner of route choice. Refactor the current optimizer mechanically: extract the economics-only eligibility block and the current stable MAX_MARGIN tie-break ordering into shared helpers, prove legacy `optimize_allocations()` remains behaviorally identical, then add `allocate_coverage_legs()` that treats each desired leg quantity as a hard ceiling. Eligibility is classified before seller-stock scarcity, so blocked quantity never consumes stock.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; PR-A route economics + PR-B coverage contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- PR-C never creates, removes, re-ranks or reroutes desired coverage legs.
- Existing economics gates remain unchanged: complete economics, positive profit, min profit/unit, min margin rate, min ROI.
- `MAX_MARGIN` is the only new coverage allocator objective. Do not expose MAX_PROFIT as a new product choice.
- Legacy `optimize_allocations()` keeps current MAX_PROFIT compatibility because existing tests/API still reference the enum.
- One economics classifier and one MAX_MARGIN ordering implementation must serve both legacy and coverage paths.
- Each final leg allocation is `0 <= final_allocated_qty <= desired_qty`.
- `allocation_blocked_qty` is classified before scarcity and consumes zero seller stock.
- `stock_uncovered_qty` exists only for an economics-eligible desired quantity that was not filled because known seller stock was exhausted.
- Unknown seller stock must not be passed as zero to this allocator. PR-D handles unknown seller stock as an explicit incomplete planning case.
- Seller stock is shared across all eligible desired legs for one SKU.
- Direct route economics identity is `SKU × origin`; coverage identity additionally preserves destination.
- No application, snapshot, API or frontend integration belongs in PR-C.

---

## File Structure

- Modify `backend/supply/contracts.py` — coverage allocation contracts.
- Modify `backend/supply/optimizer.py` — shared eligibility/order helpers and `allocate_coverage_legs()`.
- Modify `backend/supply/__init__.py` — public coverage-allocation exports.
- Modify `tests/supply/test_optimizer.py` — legacy characterization + coverage allocation tests.
- Run `tests/supply/test_coverage.py` unchanged as PR-B route-choice regression.
- Run `tests/api/test_product_completion_acceptance.py` unchanged as legacy end-to-end regression.

---

### Task 1: Add coverage allocation contracts and exact test builder

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CoverageAllocationCandidate:
    leg: DesiredCoverageLeg
    economics: UnitEconomicsResult
    destination_target_qty: int
    demand_confidence: SignalConfidence
    distortion_confidence: SignalConfidence | None


@dataclass(frozen=True, slots=True)
class FinalCoverageLeg:
    leg: DesiredCoverageLeg
    final_allocated_qty: int
    expected_profit_per_unit: Decimal | None
    expected_profit: Decimal
    eligible: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DestinationAllocationGap:
    sku: str
    destination_cluster_id: str
    allocation_blocked_qty: int
    stock_uncovered_qty: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageAllocationResult:
    sku: str
    plan_family: PlanFamily
    available_stock: int
    allocated_qty: int
    unallocated_stock: int
    final_legs: tuple[FinalCoverageLeg, ...]
    allocation_gaps: tuple[DestinationAllocationGap, ...]
    objective_profit: Decimal
```

`NetworkCoverageGap` stays in PR-B and is not duplicated.

- [ ] **Step 1: Extend test imports and add an exact coverage candidate builder**

Reuse the existing `thresholds()` and `candidate()` helpers already present in `tests/supply/test_optimizer.py`. Add imports for PR-B contracts and PR-A VolumeBand, then add:

```python
from backend.economics import VolumeBand
from backend.supply import (
    CoverageAllocationCandidate,
    CoverageType,
    DesiredCoverageLeg,
    allocate_coverage_legs as _allocate_coverage_legs,
)


def coverage_candidate(
    origin: str,
    destination: str,
    desired: int,
    *,
    sku: str = "SKU-1",
    target: int | None = None,
    profit: str | None = "30",
    margin: str | None = "0.30",
    roi: str | None = "0.40",
    complete: bool = True,
    route: RouteConfidence = RouteConfidence.MEDIUM,
    demand: SignalConfidence = SignalConfidence.MEDIUM,
    distortion_confidence: SignalConfidence | None = None,
) -> CoverageAllocationCandidate:
    legacy = candidate(
        origin,
        sku=sku,
        recommendation=max(desired, 1),
        need=max(desired, 1),
        complete=complete,
        profit=profit,
        margin=margin,
        roi=roi,
        route=route,
        demand=demand,
    )
    leg = DesiredCoverageLeg(
        sku=sku,
        origin_cluster_id=origin,
        destination_cluster_id=destination,
        desired_qty=desired,
        coverage_type=(
            CoverageType.LOCAL if origin == destination else CoverageType.ROUTE
        ),
        direct_route_fee=(None if origin == destination else Decimal("47")),
        volume_band=(None if origin == destination else VolumeBand(Decimal("0"), Decimal("1"))),
        route_confidence=route,
        reason_codes=("fixture",),
    )
    return CoverageAllocationCandidate(
        leg=leg,
        economics=legacy.economics,
        destination_target_qty=desired if target is None else target,
        demand_confidence=demand,
        distortion_confidence=distortion_confidence,
    )


def allocate_coverage_legs(
    candidates,
    stock,
    limits,
    *,
    plan_family=PlanFamily.CALCULATED,
):
    return _allocate_coverage_legs(
        candidates,
        stock,
        limits,
        plan_family=plan_family,
    )
```

- [ ] **Step 2: Add failing contract validation tests**

```python
def test_coverage_candidate_requires_economics_origin_identity():
    item = coverage_candidate("Москва", "Казань", 10)
    wrong = replace(item, economics=candidate("Питер").economics)
    with pytest.raises(ValueError, match="economics identity"):
        CoverageAllocationCandidate(
            wrong.leg,
            wrong.economics,
            wrong.destination_target_qty,
            wrong.demand_confidence,
            wrong.distortion_confidence,
        )


def test_final_leg_cannot_exceed_desired_qty():
    item = coverage_candidate("Москва", "Казань", 10)
    with pytest.raises(ValueError, match="final_allocated_qty"):
        FinalCoverageLeg(
            item.leg,
            11,
            Decimal("30"),
            Decimal("330"),
            True,
            ("ALLOCATED",),
        )
```

Also add one `DestinationAllocationGap` test asserting negative blocked/stock quantities are rejected and a zero+zero gap row is rejected.

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new contract imports fail.

- [ ] **Step 4: Implement contract validation in `backend/supply/contracts.py`**

Use existing `_require_nonblank()` / `_require_nonnegative_int()` helpers. In `CoverageAllocationCandidate.__post_init__`:

```python
from backend.economics import UnitEconomicsResult

if not isinstance(self.leg, DesiredCoverageLeg):
    raise TypeError("leg must be DesiredCoverageLeg")
if not isinstance(self.economics, UnitEconomicsResult):
    raise TypeError("economics must be UnitEconomicsResult")
if self.economics.sku != self.leg.sku:
    raise ValueError("economics identity must match coverage leg SKU")
if self.economics.placement_cluster_id != self.leg.origin_cluster_id:
    raise ValueError("economics identity must match coverage leg origin")
_require_nonnegative_int(self.destination_target_qty, "destination_target_qty")
if self.destination_target_qty < self.leg.desired_qty:
    raise ValueError("destination_target_qty must cover desired leg quantity")
if not isinstance(self.demand_confidence, SignalConfidence):
    raise TypeError("demand_confidence must be SignalConfidence")
if self.distortion_confidence is not None and not isinstance(
    self.distortion_confidence, SignalConfidence
):
    raise TypeError("distortion_confidence must be SignalConfidence or None")
```

In `FinalCoverageLeg.__post_init__`, require nonnegative allocation and `final_allocated_qty <= leg.desired_qty`; expected profit must be a finite Decimal.

In `DestinationAllocationGap.__post_init__`, require nonnegative quantities and reject both zero.

In `CoverageAllocationResult.__post_init__`, validate nonnegative stock/allocation fields and exact `allocated_qty + unallocated_stock == available_stock`.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_optimizer.py
git commit -m "feat: add coverage allocation contracts"
```

---

### Task 2: Extract the economics-only eligibility policy without changing legacy behavior

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

```python
def _classify_economics(
    economics: UnitEconomicsResult,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
```

- [ ] **Step 1: Run the current optimizer suite as a characterization baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before refactor.

- [ ] **Step 2: Add a parameterized characterization test for economics reasons**

Use the existing `candidate()` helper:

```python
@pytest.mark.parametrize("changes,expected", [
    ({"complete": False}, ("ECONOMICS_INCOMPLETE",)),
    ({"profit": "0"}, ("NON_POSITIVE_PROFIT", "BELOW_MIN_PROFIT_PER_UNIT")),
    ({"profit": "9"}, ("BELOW_MIN_PROFIT_PER_UNIT",)),
    ({"margin": None}, ("MARGIN_RATE_UNAVAILABLE",)),
    ({"margin": "0.09"}, ("BELOW_MIN_MARGIN_RATE",)),
    ({"roi": None}, ("ROI_UNAVAILABLE",)),
    ({"roi": "0.19"}, ("BELOW_MIN_ROI",)),
])
def test_legacy_economics_reason_characterization(changes, expected):
    decision = optimize_allocations(
        [candidate(**changes)],
        10,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
        objective=AllocationObjective.MAX_MARGIN,
    ).decisions[0]
    assert tuple(code for code in decision.reason_codes if code in expected) == expected
```

This supplements, not replaces, existing exact reason-order tests.

- [ ] **Step 3: Extract `_classify_economics()` mechanically**

Move the current block beginning `economics = candidate.economics` through the final ROI threshold check into:

```python
def _classify_economics(
    economics,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
    reasons: set[str] = set()
    if not economics.complete:
        reasons.add("ECONOMICS_INCOMPLETE")
    else:
        profit = economics.profit_per_unit
        margin = economics.margin_rate
        roi = economics.roi
        if margin is None:
            reasons.add("MARGIN_RATE_UNAVAILABLE")
        if roi is None:
            reasons.add("ROI_UNAVAILABLE")
        if profit is None or profit <= _ZERO:
            reasons.add("NON_POSITIVE_PROFIT")
        if profit is not None and profit < thresholds.min_profit_per_unit:
            reasons.add("BELOW_MIN_PROFIT_PER_UNIT")
        if margin is not None and margin < thresholds.min_margin_rate:
            reasons.add("BELOW_MIN_MARGIN_RATE")
        if roi is not None and roi < thresholds.min_roi:
            reasons.add("BELOW_MIN_ROI")
    return not reasons, reasons
```

In legacy `_classify()` replace the moved block with:

```python
economics_eligible, economics_reasons = _classify_economics(
    candidate.economics,
    thresholds,
)
reasons.update(economics_reasons)
eligible = not reasons and economics_eligible and ceiling > 0
```

Keep all legacy ceiling/feasibility reasons and `ELIGIBLE_FOR_ALLOCATION` behavior unchanged.

- [ ] **Step 4: Run optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS with no changed legacy decision/reason output.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 3: Extract the current deterministic MAX_MARGIN ordering

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

```python
def _max_margin_order(
    items,
    *,
    margin_rate,
    route_confidence,
    demand_confidence,
    distortion_confidence,
    target_quantity,
    stable_key,
):
```

- [ ] **Step 1: Add exact tie-break characterization using current helpers**

```python
def test_max_margin_tie_break_order_is_characterized():
    route_winner = optimize_allocations(
        [
            candidate("A", margin="0.30", route=RouteConfidence.HIGH),
            candidate("B", margin="0.30", route=RouteConfidence.LOW),
        ],
        1,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
        objective=AllocationObjective.MAX_MARGIN,
    )
    assert allocations(route_winner) == {"A": 1, "B": 0}

    demand_winner = optimize_allocations(
        [
            candidate("A", margin="0.30", demand=SignalConfidence.HIGH),
            candidate("B", margin="0.30", demand=SignalConfidence.LOW),
        ],
        1,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
        objective=AllocationObjective.MAX_MARGIN,
    )
    assert allocations(demand_winner) == {"A": 1, "B": 0}

    distortion_winner = optimize_allocations(
        [
            candidate("A", margin="0.30", distortion=distortion("A", SignalConfidence.HIGH)),
            candidate("B", margin="0.30", distortion=distortion("B", SignalConfidence.LOW)),
        ],
        1,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
        objective=AllocationObjective.MAX_MARGIN,
    )
    assert allocations(distortion_winner) == {"A": 0, "B": 1}
```

Existing tests already cover larger need and stable cluster ID; keep them.

- [ ] **Step 2: Run characterization baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 3: Add shared ordering helper with the exact current stable-sort order**

```python
def _max_margin_order(
    items,
    *,
    margin_rate,
    route_confidence,
    demand_confidence,
    distortion_confidence,
    target_quantity,
    stable_key,
):
    ordered = list(items)
    ordered.sort(key=stable_key)
    ordered.sort(key=target_quantity, reverse=True)
    ordered.sort(
        key=lambda item: _DISTORTION_RANK[distortion_confidence(item)]
    )
    ordered.sort(
        key=lambda item: _DEMAND_RANK[demand_confidence(item)],
        reverse=True,
    )
    ordered.sort(
        key=lambda item: _ROUTE_RANK[route_confidence(item)],
        reverse=True,
    )
    ordered.sort(key=margin_rate, reverse=True)
    return ordered
```

Replace only the MAX_MARGIN path's six stable sorts in `optimize_allocations()` with:

```python
if objective is AllocationObjective.MAX_MARGIN:
    eligible = _max_margin_order(
        eligible,
        margin_rate=lambda item: item.economics.margin_rate,
        route_confidence=lambda item: item.route_confidence,
        demand_confidence=lambda item: item.demand_confidence,
        distortion_confidence=lambda item: (
            None
            if item.distortion_signal is None
            else item.distortion_signal.confidence
        ),
        target_quantity=lambda item: item.calculated_need_qty,
        stable_key=lambda item: item.cluster_id,
    )
else:
    eligible.sort(key=lambda item: item.cluster_id)
    eligible.sort(key=lambda item: item.calculated_need_qty, reverse=True)
    eligible.sort(key=lambda item: _DISTORTION_RANK[
        None if item.distortion_signal is None else item.distortion_signal.confidence
    ])
    eligible.sort(key=lambda item: _DEMAND_RANK[item.demand_confidence], reverse=True)
    eligible.sort(key=lambda item: _ROUTE_RANK[item.route_confidence], reverse=True)
    eligible.sort(key=lambda item: item.economics.profit_per_unit, reverse=True)
```

This deliberately leaves legacy MAX_PROFIT compatibility intact while sharing the product's MAX_MARGIN path.

- [ ] **Step 4: Run optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 4: Classify desired coverage legs before scarcity

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

```python
def allocate_coverage_legs(
    candidates: Iterable[CoverageAllocationCandidate],
    available_stock: int,
    thresholds: OptimizerThresholds,
    *,
    plan_family: PlanFamily,
) -> CoverageAllocationResult:
```

- [ ] **Step 1: Add failing allocation-blocked test**

```python
def test_ineligible_desired_leg_is_allocation_blocked_with_abundant_stock():
    result = allocate_coverage_legs(
        [coverage_candidate(
            "Москва",
            "Казань",
            50,
            complete=False,
        )],
        100,
        thresholds(),
    )
    assert result.allocated_qty == 0
    assert result.unallocated_stock == 100
    assert result.final_legs[0].final_allocated_qty == 0
    assert result.final_legs[0].eligible is False
    assert result.final_legs[0].reason_codes == ("ECONOMICS_INCOMPLETE",)
    assert result.allocation_gaps == (
        DestinationAllocationGap(
            "SKU-1",
            "Казань",
            50,
            0,
            ("ECONOMICS_INCOMPLETE",),
        ),
    )
```

- [ ] **Step 2: Add failing threshold-block test**

Use desired=30, profit `9`, margin/ROI above thresholds, seller stock=100. Assert blocked=30, stock gap=0, reason `BELOW_MIN_PROFIT_PER_UNIT`.

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: `allocate_coverage_legs()` absent.

- [ ] **Step 4: Implement exact validation and pre-scarcity classification**

At function start:

```python
if isinstance(available_stock, bool) or not isinstance(available_stock, int):
    raise TypeError("available_stock must be an int")
if available_stock < 0:
    raise ValueError("available_stock must be nonnegative")
if not isinstance(plan_family, PlanFamily):
    raise TypeError("plan_family must be PlanFamily")
thresholds = _validate_thresholds(thresholds)
items = tuple(candidates)
if not items:
    raise ValueError("candidates must not be empty")
if any(not isinstance(item, CoverageAllocationCandidate) for item in items):
    raise TypeError("candidates must contain CoverageAllocationCandidate values")
sku = items[0].leg.sku
if any(item.leg.sku != sku for item in items):
    raise ValueError("all candidates must have the same SKU")
keys = [
    (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    for item in items
]
if len(keys) != len(set(keys)):
    raise ValueError("duplicate origin and destination coverage leg")
```

Classify:

```python
classified = {
    (item.leg.origin_cluster_id, item.leg.destination_cluster_id):
        _classify_economics(item.economics, thresholds)
    for item in items
}
blocked_by_destination: dict[str, int] = {}
blocked_reasons: dict[str, set[str]] = {}
eligible: list[CoverageAllocationCandidate] = []
for item in items:
    key = (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    is_eligible, reasons = classified[key]
    if is_eligible:
        eligible.append(item)
    else:
        destination = item.leg.destination_cluster_id
        blocked_by_destination[destination] = (
            blocked_by_destination.get(destination, 0) + item.leg.desired_qty
        )
        blocked_reasons.setdefault(destination, set()).update(reasons)
```

Do not inspect seller stock during this phase.

- [ ] **Step 5: Build blocked final legs with zero allocation**

Use `_ordered(reasons)` for canonical reason order. The scarcity phase in Task 5 fills eligible legs; blocked legs always stay zero.

- [ ] **Step 6: Run blocking tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new blocked tests pass. Existing legacy tests remain green.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: classify coverage allocation eligibility"
```

---

### Task 5: Apply known seller-stock scarcity over eligible legs only

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add failing MAX_MARGIN scarcity test**

```python
def test_coverage_scarcity_prefers_higher_margin_leg():
    result = allocate_coverage_legs(
        [
            coverage_candidate("Москва", "Казань", 50, margin="0.20"),
            coverage_candidate("Питер", "Тверь", 50, margin="0.30"),
        ],
        60,
        thresholds(),
    )
    allocated = {
        (item.leg.origin_cluster_id, item.leg.destination_cluster_id):
            item.final_allocated_qty
        for item in result.final_legs
    }
    assert allocated == {
        ("Москва", "Казань"): 10,
        ("Питер", "Тверь"): 50,
    }
```

- [ ] **Step 2: Add failing mixed blocked + scarce causal test**

```python
def test_blocked_quantity_never_consumes_stock_and_stock_gap_is_separate():
    result = allocate_coverage_legs(
        [
            coverage_candidate("A", "D1", 30, complete=False),
            coverage_candidate("B", "D2", 50, margin="0.30"),
            coverage_candidate("C", "D3", 50, margin="0.20"),
        ],
        60,
        thresholds(),
    )
    gaps = {item.destination_cluster_id: item for item in result.allocation_gaps}
    assert gaps["D1"].allocation_blocked_qty == 30
    assert gaps["D1"].stock_uncovered_qty == 0
    assert gaps["D3"].allocation_blocked_qty == 0
    assert gaps["D3"].stock_uncovered_qty == 40
    assert result.allocated_qty == 60
```

- [ ] **Step 3: Add failing zero-stock test**

Two eligible desired legs total 70, available stock 0. Assert final allocated=0 and stock_uncovered total=70; allocation_blocked total=0.

- [ ] **Step 4: Run tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: scarcity assertions fail before completion.

- [ ] **Step 5: Order eligible coverage candidates with the shared MAX_MARGIN helper**

```python
ordered_eligible = _max_margin_order(
    eligible,
    margin_rate=lambda item: item.economics.margin_rate,
    route_confidence=lambda item: item.leg.route_confidence,
    demand_confidence=lambda item: item.demand_confidence,
    distortion_confidence=lambda item: item.distortion_confidence,
    target_quantity=lambda item: item.destination_target_qty,
    stable_key=lambda item: (
        item.leg.origin_cluster_id,
        item.leg.destination_cluster_id,
    ),
)
```

- [ ] **Step 6: Allocate sequentially and classify stock gaps**

```python
remaining = available_stock
allocated_by_key: dict[tuple[str, str], int] = {}
stock_by_destination: dict[str, int] = {}
for item in ordered_eligible:
    key = (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    quantity = min(remaining, item.leg.desired_qty)
    allocated_by_key[key] = quantity
    remaining -= quantity
    missing = item.leg.desired_qty - quantity
    if missing:
        destination = item.leg.destination_cluster_id
        stock_by_destination[destination] = (
            stock_by_destination.get(destination, 0) + missing
        )
```

Build `FinalCoverageLeg` for every candidate in stable `(origin,destination)` order. For eligible legs start reasons with `ELIGIBLE_FOR_ALLOCATION`; add `SELLER_STOCK_EXHAUSTED` whenever allocation is below desired, `PARTIAL_BY_SELLER_STOCK` only when `0 < quantity < desired`, and `ALLOCATED` when quantity > 0. Blocked legs keep only their economics reasons and zero allocation.

- [ ] **Step 7: Build per-destination gap rows**

For the sorted union of blocked and stock destination IDs:

```python
DestinationAllocationGap(
    sku=sku,
    destination_cluster_id=destination,
    allocation_blocked_qty=blocked_by_destination.get(destination, 0),
    stock_uncovered_qty=stock_by_destination.get(destination, 0),
    reason_codes=_ordered(
        blocked_reasons.get(destination, set())
        | ({"SELLER_STOCK_EXHAUSTED"} if stock_by_destination.get(destination, 0) else set())
    ),
)
```

- [ ] **Step 8: Compute profit with current Decimal discipline**

Use the same `localcontext()` precision/rounding as legacy optimizer. For each final leg:

```python
profit_per_unit = item.economics.profit_per_unit
expected_profit = (
    _ZERO
    if profit_per_unit is None
    else Decimal(quantity) * profit_per_unit
)
```

`objective_profit` is the sum of final-leg expected profits. `allocated_qty` is the sum of final allocations. `unallocated_stock = available_stock - allocated_qty`.

- [ ] **Step 9: Run optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate seller stock across coverage legs"
```

---

### Task 6: Prove conservation, deterministic input order and public export

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`
- Regression: `tests/supply/test_coverage.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

- [ ] **Step 1: Add exact conservation test across all three unmet classes**

```python
def test_coverage_allocation_composes_with_network_gap_to_conserve_target():
    target_qty = 120
    network_uncovered = 20
    result = allocate_coverage_legs(
        [
            coverage_candidate("A", "Казань", 30, complete=False, target=120),
            coverage_candidate("B", "Казань", 70, margin="0.30", target=120),
        ],
        50,
        thresholds(),
    )
    final = sum(item.final_allocated_qty for item in result.final_legs)
    blocked = sum(item.allocation_blocked_qty for item in result.allocation_gaps)
    stock = sum(item.stock_uncovered_qty for item in result.allocation_gaps)
    assert final + network_uncovered + blocked + stock == target_qty
    assert final <= result.available_stock
    assert all(
        item.final_allocated_qty <= item.leg.desired_qty
        for item in result.final_legs
    )
```

Here desired legs total 100; 20 is the PR-B network gap; blocked 30; eligible 70 with stock 50; the invariant is 50 + 20 + 30 + 20 = 120.

- [ ] **Step 2: Add exact input-order invariance test**

Create three equal-margin eligible coverage candidates with distinct route/demand/distortion/tie values. Call `allocate_coverage_legs()` for every `itertools.permutations(items)` and assert the set of `CoverageAllocationResult` values has length 1.

- [ ] **Step 3: Add failing export smoke test**

```python
def test_coverage_allocator_is_exported():
    from backend.supply import CoverageAllocationResult, allocate_coverage_legs

    assert CoverageAllocationResult.__name__ == "CoverageAllocationResult"
    assert callable(allocate_coverage_legs)
```

- [ ] **Step 4: Run export test and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py::test_coverage_allocator_is_exported -q
```

Expected: import failure until exports are added.

- [ ] **Step 5: Export approved allocation surface**

Update `backend/supply/__init__.py` to export `CoverageAllocationCandidate`, `FinalCoverageLeg`, `DestinationAllocationGap`, `CoverageAllocationResult`, and `allocate_coverage_legs`. Do not export `_classify_economics` or `_max_margin_order`.

- [ ] **Step 6: Run PR-C regression suite**

```bash
python -m pytest \
  tests/supply/test_optimizer.py \
  tests/supply/test_coverage.py \
  tests/api/test_product_completion_acceptance.py -q
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
git add backend/supply/__init__.py tests/supply/test_optimizer.py
git commit -m "test: verify coverage MAX_MARGIN invariants"
```

---

## PR-C Acceptance Gate

Fresh `python -m pytest -q` output must prove:

- legacy optimizer outputs remain green after the shared eligibility/order refactor;
- coverage allocator never changes PR-B desired routes;
- existing economics completeness/profit/margin/ROI gates remain exact;
- ineligible desired quantity becomes allocation-blocked with abundant stock;
- blocked quantity consumes zero stock;
- only eligible desired quantity can become seller-stock-uncovered;
- known seller stock is shared across all origins/destinations for the SKU;
- MAX_MARGIN and the existing tie-break intent are preserved;
- final allocation never exceeds seller stock or a desired-leg ceiling;
- final + network-uncovered + allocation-blocked + stock-uncovered conserves the original destination target;
- input order cannot change the result;
- unknown seller stock is not coerced to zero in PR-C or its tests;
- application/snapshot/API/frontend are not switched in PR-C.
