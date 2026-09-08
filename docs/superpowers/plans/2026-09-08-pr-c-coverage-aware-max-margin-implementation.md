# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing allocation eligibility and `MAX_MARGIN` scarcity policy at `SKU × origin × destination` coverage-leg granularity, producing final coverage legs plus causally distinct allocation-blocked and seller-stock-uncovered quantities.

**Architecture:** PR-B already owns desired topology. PR-C extracts the current economics threshold classifier and exact MAX_MARGIN ordering from `backend/supply/optimizer.py`, preserves legacy `optimize_allocations()` behavior, and adds `allocate_coverage_legs()`. Every desired leg has a hard ceiling of `desired_qty`; eligibility is classified before scarcity, and seller stock is consumed only by eligible legs. Numeric `RouteCostIndex` remains metadata and never becomes a scarcity key.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; PR-B primitive coverage contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** `RouteCostIndex` belongs to topology selection/explanation. Scarcity allocation uses direct route economics already resolved for each desired leg. Existing route/demand/distortion confidence tie-break semantics remain unchanged.

## Global Constraints

- PR-C never creates, replaces or re-ranks desired routes.
- PR-C never ranks by direct tariff, numeric `RouteCostIndex`, historical Flow or geography.
- Existing economics eligibility rules remain unchanged: complete economics, positive profit, minimum profit/unit, minimum margin rate and minimum ROI.
- New coverage allocation is fixed `MAX_MARGIN`; no second user-selectable objective is added.
- Reuse one economics classifier and one MAX_MARGIN ordering implementation across legacy/new paths.
- `DesiredCoverageLeg.desired_qty` is a hard allocation ceiling.
- Causal gap order is fixed: PR-B network gap first; then allocation eligibility; then seller-stock scarcity.
- Ineligible desired quantity is `allocation_blocked_qty` even when seller stock is abundant.
- Only eligible unfilled quantity may become `stock_uncovered_qty`.
- Seller stock is one quantity per SKU across all origins/destinations.
- Direct route economics remains specific to the leg's origin/destination decision; no origin-average economics.
- Legacy `optimize_allocations()` stays regression-green until later migration.
- PR-C does not modify application orchestration, snapshots, API or frontend.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/supply/contracts.py` — coverage-allocation contracts.
- Modify `backend/supply/optimizer.py` — shared economics classifier, shared MAX_MARGIN ordering, `allocate_coverage_legs()`.
- Modify `backend/supply/__init__.py` — public coverage-allocation exports.
- Modify `tests/supply/test_optimizer.py` — legacy characterization and new allocation tests.
- Run `tests/supply/test_coverage.py` unchanged as topology regression.

---

### Task 1: Define coverage allocation contracts

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
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    coverage_type: CoverageType
    desired_qty: int
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

`UnitEconomicsResult` stays a TYPE_CHECKING/runtime-local validation dependency exactly as current `PlacementInput` already handles it; do not add a new module-level economics import if it creates a cycle.

- [ ] **Step 1: Add exact test helpers in `tests/supply/test_optimizer.py`**

Reuse existing imports `CalculationBases`, `RoundingMetadata`, `UnitEconomicsResult`. Add:

```python
def coverage_economics(
    origin="Москва",
    *,
    sku="SKU-1",
    complete=True,
    profit="30",
    margin="0.30",
    roi="0.40",
):
    return UnitEconomicsResult(
        sku,
        origin,
        Decimal("100"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        None if profit is None else Decimal(profit),
        None if margin is None else Decimal(margin),
        None if roi is None else Decimal(roi),
        complete,
        () if complete else ("fixture",),
        CalculationBases(),
        (),
        RoundingMetadata(),
    )


def desired_leg(
    origin="Москва",
    destination="Казань",
    qty=50,
    *,
    sku="SKU-1",
    index="1",
    route_confidence=RouteConfidence.MEDIUM,
):
    return DesiredCoverageLeg(
        sku,
        origin,
        destination,
        qty,
        CoverageType.ROUTE,
        Decimal("50"),
        None if index is None else Decimal(index),
        Decimal("1") if index is not None else None,
        Decimal("0") if index is not None else None,
        route_confidence,
        0,
        None,
        (),
    )


def coverage_candidate(
    origin="Москва",
    destination="Казань",
    qty=50,
    *,
    sku="SKU-1",
    complete=True,
    profit="30",
    margin="0.30",
    roi="0.40",
    index="1",
    route_confidence=RouteConfidence.MEDIUM,
    demand_confidence=SignalConfidence.MEDIUM,
    distortion_confidence=None,
    target_qty=None,
):
    leg = desired_leg(
        origin, destination, qty, sku=sku, index=index,
        route_confidence=route_confidence,
    )
    return CoverageAllocationCandidate(
        leg,
        coverage_economics(
            origin, sku=sku, complete=complete,
            profit=profit, margin=margin, roi=roi,
        ),
        qty if target_qty is None else target_qty,
        demand_confidence,
        distortion_confidence,
    )
```

- [ ] **Step 2: Add failing contract validation tests**

```python
def test_coverage_candidate_preserves_leg_identity():
    item = coverage_candidate("Москва", "Казань", 50)
    assert item.leg.origin_cluster_id == "Москва"
    assert item.leg.destination_cluster_id == "Казань"
    assert item.economics.placement_cluster_id == "Москва"


def test_candidate_rejects_economics_origin_mismatch():
    with pytest.raises(ValueError, match="economics identity"):
        CoverageAllocationCandidate(
            desired_leg("Москва", "Казань", 50),
            coverage_economics("Питер"),
            50,
            SignalConfidence.MEDIUM,
            None,
        )


def test_final_leg_cannot_exceed_desired_quantity():
    with pytest.raises(ValueError, match="final_allocated_qty"):
        FinalCoverageLeg(
            "SKU-1", "Москва", "Казань", CoverageType.ROUTE,
            50, 51, Decimal("10"), Decimal("510"), True, (),
        )
```

Also reject negative quantities and `destination_target_qty < leg.desired_qty`.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new contracts are absent.

- [ ] **Step 4: Implement contracts and validation**

Validate `CoverageAllocationCandidate.economics.sku == leg.sku` and `economics.placement_cluster_id == leg.origin_cluster_id`. Validate confidence enum types. `DestinationAllocationGap` must have at least one positive gap component when emitted. `FinalCoverageLeg` must satisfy `0 <= final_allocated_qty <= desired_qty`.

- [ ] **Step 5: Run and verify GREEN**

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

### Task 2: Extract one reusable economics eligibility classifier

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Private interface:**

```python
def _classify_economics(
    economics: UnitEconomicsResult,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
```

- [ ] **Step 1: Add/retain legacy characterization assertions before refactor**

The existing test suite already asserts the canonical codes. Add one table-driven characterization test if any code is not independently asserted:

```text
ECONOMICS_INCOMPLETE
MARGIN_RATE_UNAVAILABLE
ROI_UNAVAILABLE
NON_POSITIVE_PROFIT
BELOW_MIN_PROFIT_PER_UNIT
BELOW_MIN_MARGIN_RATE
BELOW_MIN_ROI
ELIGIBLE_FOR_ALLOCATION
```

- [ ] **Step 2: Run baseline and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before refactor.

- [ ] **Step 3: Extract only the economics block from current `_classify()`**

Implement:

```python
def _classify_economics(economics, thresholds):
    reasons = set()
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

Legacy `_classify()` keeps its current physical/need/Ozon rules and merges these reasons. Do not change `_REASON_ORDER`.

- [ ] **Step 4: Run regression suite**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS with unchanged legacy decisions/reasons.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 3: Extract exact current MAX_MARGIN ordering

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Private interface:**

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

- [ ] **Step 1: Add exact hierarchy characterization**

Using current legacy `candidate()` fixture and `objective=AllocationObjective.MAX_MARGIN`, isolate and assert:

```text
higher margin wins first
then higher route confidence
then higher demand confidence
then current lower distortion-rank behavior
then larger calculated need
after all ties stable cluster ID
```

Do not change the existing distortion-rank direction.

- [ ] **Step 2: Add explicit RouteCostIndex non-influence test for the new path**

```python
def test_route_cost_index_is_not_a_scarcity_key():
    a = coverage_candidate(
        "Москва", "Казань", 1, index="9",
        margin="0.30", route_confidence=RouteConfidence.MEDIUM,
    )
    b = coverage_candidate(
        "Питер", "Тверь", 1, index="0.1",
        margin="0.20", route_confidence=RouteConfidence.HIGH,
    )
    result = allocate_coverage_legs(
        (a, b), 1, thresholds(), plan_family=PlanFamily.CALCULATED
    )
    allocated = {
        (x.origin_cluster_id, x.destination_cluster_id): x.final_allocated_qty
        for x in result.final_legs
    }
    assert allocated[("Москва", "Казань")] == 1
    assert allocated[("Питер", "Тверь")] == 0
```

This test will remain RED until `allocate_coverage_legs()` is implemented in Task 4; add it now but mark it with the same module test run after Task 4. The hierarchy characterization itself must remain GREEN before refactor.

- [ ] **Step 3: Extract stable least-significant-first ordering**

```python
def _max_margin_order(items, *, margin_rate, route_confidence,
                      demand_confidence, distortion_confidence,
                      target_quantity, stable_key):
    ordered = list(items)
    ordered.sort(key=stable_key)
    ordered.sort(key=target_quantity, reverse=True)
    ordered.sort(key=lambda item: _DISTORTION_RANK[distortion_confidence(item)])
    ordered.sort(key=lambda item: _DEMAND_RANK[demand_confidence(item)], reverse=True)
    ordered.sort(key=lambda item: _ROUTE_RANK[route_confidence(item)], reverse=True)
    ordered.sort(key=margin_rate, reverse=True)
    return ordered
```

Legacy MAX_MARGIN path delegates to this helper. Legacy MAX_PROFIT path keeps profit as the top objective but reuses the same subordinate stable ordering where practical without changing outputs.

- [ ] **Step 4: Run legacy hierarchy tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "tie_break or confidence or objective"
```

Expected: all legacy characterization tests PASS; new allocation test remains unavailable until Task 4 implementation and should not be selected by this focused expression.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 4: Implement coverage eligibility and seller-stock scarcity

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Public interface:**

```python
def allocate_coverage_legs(
    candidates: Iterable[CoverageAllocationCandidate],
    available_stock: int,
    thresholds: OptimizerThresholds,
    *,
    plan_family: PlanFamily,
) -> CoverageAllocationResult:
```

- [ ] **Step 1: Add abundant-stock allocation-blocked test**

```python
def test_ineligible_leg_is_blocked_not_stock_shortage():
    result = allocate_coverage_legs(
        (coverage_candidate(complete=False),),
        100,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    assert result.allocated_qty == 0
    assert result.allocation_gaps[0].allocation_blocked_qty == 50
    assert result.allocation_gaps[0].stock_uncovered_qty == 0
    assert "ECONOMICS_INCOMPLETE" in result.final_legs[0].reason_codes
```

Add the same causal assertion for `margin="0.05"` with thresholds margin `0.10`.

- [ ] **Step 2: Add scarce-stock MAX_MARGIN test**

```python
def test_scarcity_prefers_higher_margin_leg():
    result = allocate_coverage_legs(
        (
            coverage_candidate("Москва", "Казань", 50, margin="0.20"),
            coverage_candidate("Питер", "Тверь", 50, margin="0.30"),
        ),
        60,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    allocated = {
        (x.origin_cluster_id, x.destination_cluster_id): x.final_allocated_qty
        for x in result.final_legs
    }
    assert allocated == {
        ("Москва", "Казань"): 10,
        ("Питер", "Тверь"): 50,
    }
    assert sum(x.stock_uncovered_qty for x in result.allocation_gaps) == 40
    assert sum(x.allocation_blocked_qty for x in result.allocation_gaps) == 0
```

- [ ] **Step 3: Add same-origin/different-destination economics test**

```python
def test_same_origin_legs_keep_destination_specific_economics():
    result = allocate_coverage_legs(
        (
            coverage_candidate(
                "Москва", "Казань", 10, margin="0.20", profit="20"
            ),
            coverage_candidate(
                "Москва", "Тверь", 10, margin="0.40", profit="35"
            ),
        ),
        10,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    allocated = {
        x.destination_cluster_id: x.final_allocated_qty
        for x in result.final_legs
    }
    assert allocated == {"Казань": 0, "Тверь": 10}
```

- [ ] **Step 4: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "coverage or scarcity or route_cost_index"
```

Expected: `allocate_coverage_legs()` absent.

- [ ] **Step 5: Implement input validation**

Validate:

```text
available_stock int, not bool, >= 0
thresholds via existing _validate_thresholds
plan_family is PlanFamily
nonempty candidates
all CoverageAllocationCandidate
all same SKU
duplicate (origin,destination) rejected
```

- [ ] **Step 6: Classify economics before scarcity**

For each candidate:

```python
eligible, reasons = _classify_economics(item.economics, thresholds)
if eligible:
    reasons.add("ELIGIBLE_FOR_ALLOCATION")
else:
    blocked[item.leg.destination_cluster_id] += item.leg.desired_qty
```

Do not use `available_stock` in this phase.

- [ ] **Step 7: Order only eligible legs with `_max_margin_order()`**

```python
ordered = _max_margin_order(
    eligible_items,
    margin_rate=lambda x: x.economics.margin_rate,
    route_confidence=lambda x: x.leg.route_confidence,
    demand_confidence=lambda x: x.demand_confidence,
    distortion_confidence=lambda x: x.distortion_confidence,
    target_quantity=lambda x: x.destination_target_qty,
    stable_key=lambda x: (
        x.leg.origin_cluster_id,
        x.leg.destination_cluster_id,
    ),
)
```

There is intentionally no route-index projection.

- [ ] **Step 8: Allocate stock with desired-leg ceilings**

```python
remaining = available_stock
allocated_by_key = {}
for item in ordered:
    key = (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    quantity = min(remaining, item.leg.desired_qty)
    allocated_by_key[key] = quantity
    remaining -= quantity
```

- [ ] **Step 9: Build final legs and causal gaps**

For every desired candidate sorted by `(origin,destination)`:

```text
blocked leg -> final qty 0; blocked qty = desired qty
eligible leg -> final qty from allocated_by_key; stock gap = desired - final
```

Use existing reason codes `ELIGIBLE_FOR_ALLOCATION`, `SELLER_STOCK_EXHAUSTED`, `PARTIAL_BY_SELLER_STOCK`, `ALLOCATED` as applicable, preserving `_REASON_ORDER`. Aggregate gap quantities/reasons by destination.

- [ ] **Step 10: Reconcile profit with Decimal precision 40**

Use `localcontext()` with `ROUND_HALF_EVEN`, same as legacy optimizer:

```python
expected_profit = (
    Decimal("0")
    if profit_per_unit is None
    else Decimal(quantity) * profit_per_unit
)
```

`objective_profit` is the sum of final-leg expected profits.

- [ ] **Step 11: Run focused tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS including the RouteCostIndex non-influence test from Task 3.

- [ ] **Step 12: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate scarce stock across coverage legs"
```

---

### Task 5: Prove conservation and export public API

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`
- Regression: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add allocation-only conservation test**

For every `CoverageAllocationResult` fixture assert:

```python
assert result.allocated_qty == sum(
    x.final_allocated_qty for x in result.final_legs
)
assert result.allocated_qty <= result.available_stock
assert all(x.final_allocated_qty <= x.desired_qty for x in result.final_legs)
```

For each destination represented by candidates:

```python
desired = sum(
    x.leg.desired_qty for x in candidates
    if x.leg.destination_cluster_id == destination
)
allocated = sum(
    x.final_allocated_qty for x in result.final_legs
    if x.destination_cluster_id == destination
)
gap = next(
    (x for x in result.allocation_gaps
     if x.destination_cluster_id == destination),
    None,
)
blocked = 0 if gap is None else gap.allocation_blocked_qty
stock = 0 if gap is None else gap.stock_uncovered_qty
assert allocated + blocked + stock == desired
```

- [ ] **Step 2: Add combined PR-B + PR-C conservation test**

Use a PR-B result with one network gap and allocate its desired legs. Assert for each destination:

```text
final allocated
+ PR-B network gap
+ PR-C allocation blocked
+ PR-C stock uncovered
= DestinationTarget.quantity
```

- [ ] **Step 3: Export public API**

From `backend/supply/__init__.py` export:

```text
CoverageAllocationCandidate
FinalCoverageLeg
DestinationAllocationGap
CoverageAllocationResult
allocate_coverage_legs
```

- [ ] **Step 4: Run topology + allocator + legacy acceptance**

```bash
python -m pytest tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/__init__.py tests/supply/test_optimizer.py
git commit -m "feat: expose coverage-aware MAX_MARGIN allocation"
```

---

## PR-C Acceptance Gate

PR-C is complete only when all are true:

1. Desired topology from PR-B is never recomputed in allocator.
2. Numeric `RouteCostIndex` cannot affect scarcity ordering.
3. Route-specific economics is retained per desired leg, including same-origin/different-destination legs.
4. Existing threshold semantics and reason ordering remain unchanged.
5. New path uses existing MAX_MARGIN hierarchy and adds no new objective.
6. Ineligible desired quantity is allocation-blocked, never stock shortage.
7. Only eligible unfilled quantity becomes stock-uncovered.
8. Final allocation never exceeds seller stock or any desired-leg ceiling.
9. Per-destination allocation conservation holds.
10. Combined network + allocation + stock conservation holds with PR-B.
11. Legacy optimizer tests remain green.
12. No application/snapshot/API/frontend integration occurs in PR-C.
