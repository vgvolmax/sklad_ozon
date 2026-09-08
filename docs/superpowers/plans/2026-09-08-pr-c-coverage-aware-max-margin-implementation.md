# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing allocation eligibility and `MAX_MARGIN` scarcity policy at `SKU × origin × destination` coverage-leg granularity, with a compact supply-owned economics contract that PR-D can serialize/reuse without importing the full economics result.

**Architecture:** PR-B owns desired route topology. PR-C introduces `AllocationEconomics`, projects existing `UnitEconomicsResult` into it through one public helper, extracts the current economics threshold classifier and MAX_MARGIN ordering once, keeps legacy `optimize_allocations()` behavior regression-green, and adds `allocate_coverage_legs()`. RouteCostIndex remains topology metadata only; scarcity uses exact route economics already projected for each leg.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- PR-C never creates, replaces or reranks desired routes.
- PR-C never ranks scarcity by direct tariff, numeric RouteCostIndex, historical Flow or geography.
- Existing allocation eligibility semantics stay unchanged: economics complete, positive profit, minimum profit/unit, minimum margin rate and minimum ROI.
- New coverage allocation objective is fixed `MAX_MARGIN`.
- One compact economics projection, one threshold classifier and one MAX_MARGIN ordering implementation serve both legacy and coverage paths.
- `DesiredCoverageLeg.desired_qty` is a hard ceiling.
- Causal order is fixed: PR-B network gap → allocation eligibility → seller-stock scarcity.
- Ineligible desired quantity becomes `allocation_blocked_qty`.
- Only eligible quantity unfilled because proven seller stock is exhausted becomes `stock_uncovered_qty`.
- Seller stock is one quantity per SKU shared across all origins/destinations.
- `backend/supply` does not import `backend.economics` at module import time; `project_allocation_economics()` accepts an object contract and validates required fields.
- Legacy `optimize_allocations()` remains supported and behavior-compatible.
- No application, snapshot, API or frontend change belongs in PR-C.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/supply/contracts.py` — add compact economics and coverage-allocation result contracts.
- Modify `backend/supply/optimizer.py` — public economics projection, shared eligibility/order helpers and `allocate_coverage_legs()`.
- Modify `backend/supply/__init__.py` — export new public coverage-allocation surface including `project_allocation_economics`.
- Modify `tests/supply/test_optimizer.py` — projection, legacy characterization, coverage allocation, conservation and deterministic-order tests.
- Run `tests/supply/test_coverage.py` unchanged as PR-B topology regression.

---

### Task 1: Define compact allocation economics and result contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AllocationEconomics:
    sku: str
    origin_cluster_id: str
    complete: bool
    profit_per_unit: Decimal | None
    margin_rate: Decimal | None
    roi: Decimal | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageAllocationCandidate:
    leg: DesiredCoverageLeg
    economics: AllocationEconomics
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

- [ ] **Step 1: Add exact fixture helpers**

In `tests/supply/test_optimizer.py` add:

```python
def compact_economics(
    origin="Москва",
    *,
    sku="SKU-1",
    complete=True,
    profit="30",
    margin="0.30",
    roi="0.40",
):
    return AllocationEconomics(
        sku=sku,
        origin_cluster_id=origin,
        complete=complete,
        profit_per_unit=None if profit is None else Decimal(profit),
        margin_rate=None if margin is None else Decimal(margin),
        roi=None if roi is None else Decimal(roi),
        reason_codes=() if complete else ("fixture",),
    )


def desired_leg(
    origin="Москва",
    destination="Казань",
    qty=50,
    *,
    sku="SKU-1",
    route_confidence=RouteConfidence.MEDIUM,
):
    return DesiredCoverageLeg(
        sku=sku,
        origin_cluster_id=origin,
        destination_cluster_id=destination,
        desired_qty=qty,
        coverage_type=(
            CoverageType.LOCAL if origin == destination else CoverageType.ROUTE
        ),
        direct_route_fee=None if origin == destination else Decimal("50"),
        route_cost_index=None if origin == destination else Decimal("1"),
        route_cost_index_coverage=None if origin == destination else Decimal("1"),
        route_cost_index_spread=None if origin == destination else Decimal("0"),
        route_confidence=route_confidence,
        observed_flow_qty=0,
        observed_flow_share=None,
        reason_codes=(),
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
    route_confidence=RouteConfidence.MEDIUM,
    demand_confidence=SignalConfidence.MEDIUM,
    distortion_confidence=None,
    target_qty=None,
):
    leg = desired_leg(
        origin, destination, qty,
        sku=sku,
        route_confidence=route_confidence,
    )
    return CoverageAllocationCandidate(
        leg=leg,
        economics=compact_economics(
            origin,
            sku=sku,
            complete=complete,
            profit=profit,
            margin=margin,
            roi=roi,
        ),
        destination_target_qty=qty if target_qty is None else target_qty,
        demand_confidence=demand_confidence,
        distortion_confidence=distortion_confidence,
    )
```

- [ ] **Step 2: Add contract validation tests**

Assert:

```python
def test_candidate_requires_matching_economics_identity():
    leg = desired_leg("Москва", "Казань", 50)
    with pytest.raises(ValueError, match="economics identity"):
        CoverageAllocationCandidate(
            leg=leg,
            economics=compact_economics("Питер"),
            destination_target_qty=50,
            demand_confidence=SignalConfidence.MEDIUM,
            distortion_confidence=None,
        )


def test_final_leg_cannot_exceed_desired_quantity():
    with pytest.raises(ValueError, match="final_allocated_qty"):
        FinalCoverageLeg(
            "SKU-1", "Москва", "Казань", CoverageType.ROUTE,
            50, 51, Decimal("10"), Decimal("510"), True, (),
        )
```

Also reject negative quantities, non-Decimal economics metrics, nonmatching SKU, and a `DestinationAllocationGap` where both gap quantities are zero.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new contract imports fail.

- [ ] **Step 4: Implement immutable contracts and validation**

Use existing `_require_nonblank()` / `_require_nonnegative_int()` helpers. `CoverageAllocationCandidate.destination_target_qty` must be at least its leg desired quantity. `FinalCoverageLeg.final_allocated_qty <= desired_qty`.

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_optimizer.py
git commit -m "feat: add compact coverage allocation contracts"
```

---

### Task 2: Add the public `project_allocation_economics()` boundary

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Public interface:**

```python
def project_allocation_economics(economics: object) -> AllocationEconomics:
```

The function intentionally accepts `object`; this keeps `backend/supply` free of a runtime import from `backend.economics` while still validating the exact required surface.

- [ ] **Step 1: Add projection parity test using current `UnitEconomicsResult` fixture**

Use the existing `candidate()` helper’s `candidate.economics` and assert:

```python
projected = project_allocation_economics(item.economics)
assert projected == AllocationEconomics(
    sku=item.economics.sku,
    origin_cluster_id=item.economics.placement_cluster_id,
    complete=item.economics.complete,
    profit_per_unit=item.economics.profit_per_unit,
    margin_rate=item.economics.margin_rate,
    roi=item.economics.roi,
    reason_codes=item.economics.blockers,
)
```

- [ ] **Step 2: Add malformed-object tests**

```python
class MissingMargin:
    sku = "SKU-1"
    placement_cluster_id = "Москва"
    complete = True
    profit_per_unit = Decimal("10")
    roi = Decimal("0.2")
    blockers = ()

with pytest.raises(TypeError, match="margin_rate"):
    project_allocation_economics(MissingMargin())
```

Also reject blank `sku`, blank `placement_cluster_id`, non-bool `complete`, non-Decimal non-null profit/margin/ROI, and non-tuple blockers.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: projection function absent.

- [ ] **Step 4: Implement the projection without economics import**

```python
def project_allocation_economics(economics: object) -> AllocationEconomics:
    required = (
        "sku", "placement_cluster_id", "complete",
        "profit_per_unit", "margin_rate", "roi", "blockers",
    )
    for name in required:
        if not hasattr(economics, name):
            raise TypeError(f"economics.{name} is required")
    sku = getattr(economics, "sku")
    origin = getattr(economics, "placement_cluster_id")
    complete = getattr(economics, "complete")
    profit = getattr(economics, "profit_per_unit")
    margin = getattr(economics, "margin_rate")
    roi = getattr(economics, "roi")
    blockers = getattr(economics, "blockers")
    _require_nonblank(sku, "economics.sku")
    _require_nonblank(origin, "economics.placement_cluster_id")
    if not isinstance(complete, bool):
        raise TypeError("economics.complete must be bool")
    for name, value in (
        ("profit_per_unit", profit),
        ("margin_rate", margin),
        ("roi", roi),
    ):
        if value is not None and not isinstance(value, Decimal):
            raise TypeError(f"economics.{name} must be Decimal or None")
    if not isinstance(blockers, tuple):
        raise TypeError("economics.blockers must be tuple")
    return AllocationEconomics(
        sku, origin, complete, profit, margin, roi, blockers
    )
```

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: project unit economics for allocation"
```

---

### Task 3: Extract one economics eligibility classifier

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Private interface:**

```python
def _classify_allocation_economics(
    economics: AllocationEconomics,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
```

- [ ] **Step 1: Characterize existing legacy reasons before refactor**

Use current legacy candidates to assert exact codes for:

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

Keep the existing `_REASON_ORDER` output order.

- [ ] **Step 2: Run baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before extraction.

- [ ] **Step 3: Implement compact classifier**

```python
def _classify_allocation_economics(economics, thresholds):
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

- [ ] **Step 4: Make legacy `_classify()` project and delegate**

Replace only its economics block with:

```python
economics_eligible, economics_reasons = _classify_allocation_economics(
    project_allocation_economics(candidate.economics), thresholds
)
reasons.update(economics_reasons)
```

Keep all legacy physical/Need/Ozon ceiling conditions unchanged. Legacy eligibility remains `not reasons and ceiling > 0`; add `ELIGIBLE_FOR_ALLOCATION` exactly as before.

- [ ] **Step 5: Run regression tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: all pre-existing legacy optimizer tests pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 4: Extract the exact current MAX_MARGIN ordering policy

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

- [ ] **Step 1: Add characterization tests for every tie-break**

Prove current order is:

1. higher margin rate;
2. higher route confidence;
3. higher demand confidence;
4. lower current distortion rank according to existing stable sort;
5. larger Calculated Need / target quantity;
6. stable key.

Use current `candidate()` helper so these tests pass before refactor.

- [ ] **Step 2: Run baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 3: Extract stable least-significant-first sort**

```python
def _max_margin_order(items, *, margin_rate, route_confidence,
                      demand_confidence, distortion_confidence,
                      target_quantity, stable_key):
    ordered = list(items)
    ordered.sort(key=stable_key)
    ordered.sort(key=target_quantity, reverse=True)
    ordered.sort(key=lambda item: _DISTORTION_RANK[distortion_confidence(item)])
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

Legacy MAX_MARGIN calls this helper. Keep legacy MAX_PROFIT compatibility in `optimize_allocations()` exactly as today.

- [ ] **Step 4: Add explicit RouteCostIndex non-influence test**

Create two equal coverage candidates whose `DesiredCoverageLeg.route_cost_index` metadata differs. Give all ordering projections equal values. Assert stable origin/destination key decides the winner. `_max_margin_order()` has no RouteCostIndex projection argument.

- [ ] **Step 5: Run tests and commit**

```bash
python -m pytest tests/supply/test_optimizer.py -q
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 5: Classify desired coverage legs before stock scarcity

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
def test_ineligible_leg_is_blocked_before_scarcity():
    result = allocate_coverage_legs(
        candidates=(coverage_candidate(complete=False),),
        available_stock=100,
        thresholds=thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    gap = result.allocation_gaps[0]
    assert result.allocated_qty == 0
    assert gap.allocation_blocked_qty == 50
    assert gap.stock_uncovered_qty == 0
```

- [ ] **Step 2: Add threshold-blocked test**

Use complete economics with margin `0.05` and threshold `0.10`. With stock 100 assert the desired quantity is allocation-blocked and not stock-uncovered.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: `allocate_coverage_legs` absent.

- [ ] **Step 4: Validate call boundary**

Require:

- integer nonnegative stock;
- valid `PlanFamily`;
- nonempty candidate collection;
- one SKU across candidates;
- unique `(origin,destination)` leg key;
- candidate economics identity equals leg SKU/origin.

Validate thresholds through existing `_validate_thresholds()`.

- [ ] **Step 5: Classify every desired leg**

```python
classified = {}
for item in items:
    eligible, reasons = _classify_allocation_economics(
        item.economics, thresholds
    )
    if eligible:
        reasons.add("ELIGIBLE_FOR_ALLOCATION")
    classified[(item.leg.origin_cluster_id, item.leg.destination_cluster_id)] = (
        eligible, reasons
    )
```

Blocked desired quantities are accumulated by destination before any stock is consumed.

- [ ] **Step 6: Run tests and commit**

```bash
python -m pytest tests/supply/test_optimizer.py -q
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: classify coverage allocation eligibility"
```

---

### Task 6: Allocate eligible legs under seller-stock scarcity

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add MAX_MARGIN scarcity test**

```python
def test_scarcity_prefers_higher_margin_leg():
    result = allocate_coverage_legs(
        candidates=(
            coverage_candidate(
                "Москва", "Казань", 50, margin="0.20", profit="20"
            ),
            coverage_candidate(
                "Питер", "Тверь", 50, margin="0.30", profit="15"
            ),
        ),
        available_stock=60,
        thresholds=thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    by_leg = {
        (x.origin_cluster_id, x.destination_cluster_id): x.final_allocated_qty
        for x in result.final_legs
    }
    assert by_leg[("Питер", "Тверь")] == 50
    assert by_leg[("Москва", "Казань")] == 10
```

- [ ] **Step 2: Add stock-only gap test**

Two eligible desired legs total 100, stock 60. Assert total `allocation_blocked_qty == 0` and `stock_uncovered_qty == 40`.

- [ ] **Step 3: Add same-origin/different-destination economics test**

Both desired legs originate in Moscow but serve different destinations and have different margins. Assert scarcity follows each leg economics, proving no origin-average economics is used.

- [ ] **Step 4: Order eligible candidates**

```python
eligible_items = [
    item for item in items
    if classified[(item.leg.origin_cluster_id, item.leg.destination_cluster_id)][0]
]
ordered = _max_margin_order(
    eligible_items,
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

- [ ] **Step 5: Consume stock using leg ceilings**

```python
remaining = available_stock
allocated_by_leg = {}
for item in ordered:
    key = (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    quantity = min(remaining, item.leg.desired_qty)
    allocated_by_leg[key] = quantity
    remaining -= quantity
```

Eligible residual `desired_qty - allocated` is accumulated into `stock_uncovered_qty` by destination.

- [ ] **Step 6: Build final legs and exact expected profit**

Use local Decimal context precision 40 / `ROUND_HALF_EVEN` as current optimizer. For every desired leg, including blocked/zero legs:

```python
expected_profit = (
    Decimal("0")
    if item.economics.profit_per_unit is None
    else Decimal(quantity) * item.economics.profit_per_unit
)
```

Preserve current reason vocabulary where applicable:
`ELIGIBLE_FOR_ALLOCATION`, `SELLER_STOCK_EXHAUSTED`, `PARTIAL_BY_SELLER_STOCK`, `ALLOCATED`.

- [ ] **Step 7: Run tests and commit**

```bash
python -m pytest tests/supply/test_optimizer.py -q
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate scarce stock across coverage legs"
```

---

### Task 7: Reconcile destination gaps, profit and determinism

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add mixed causal-gap test**

One destination has two desired legs: one blocked 20 and one eligible 30, with stock only 10. Assert its single `DestinationAllocationGap` is:

```text
allocation_blocked_qty = 20
stock_uncovered_qty = 20
```

and final allocated is 10. Network gap is intentionally not part of PR-C result.

- [ ] **Step 2: Add seller-stock conservation**

```python
assert result.allocated_qty == sum(x.final_allocated_qty for x in result.final_legs)
assert result.allocated_qty <= result.available_stock
assert result.unallocated_stock == result.available_stock - result.allocated_qty
assert result.objective_profit == sum(
    (x.expected_profit for x in result.final_legs), Decimal("0")
)
```

- [ ] **Step 3: Add candidate permutation determinism**

For every permutation of a small candidate tuple, assert identical `CoverageAllocationResult`.

- [ ] **Step 4: Canonical output order**

Return final legs sorted by `(origin_cluster_id,destination_cluster_id)` and gaps sorted by `destination_cluster_id` independent of ranking order.

- [ ] **Step 5: Run focused suites**

```bash
python -m pytest tests/supply/test_optimizer.py tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "test: reconcile coverage allocation causes"
```

---

### Task 8: Export public coverage allocation API and run regressions

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`

**Public exports:**

```text
AllocationEconomics
CoverageAllocationCandidate
FinalCoverageLeg
DestinationAllocationGap
CoverageAllocationResult
project_allocation_economics
allocate_coverage_legs
```

- [ ] **Step 1: Add import smoke test**

```python
def test_coverage_allocation_api_is_exported():
    from backend.supply import (
        AllocationEconomics,
        CoverageAllocationCandidate,
        CoverageAllocationResult,
        DestinationAllocationGap,
        FinalCoverageLeg,
        allocate_coverage_legs,
        project_allocation_economics,
    )
    assert all((
        AllocationEconomics,
        CoverageAllocationCandidate,
        CoverageAllocationResult,
        DestinationAllocationGap,
        FinalCoverageLeg,
        allocate_coverage_legs,
        project_allocation_economics,
    ))
```

- [ ] **Step 2: Export exactly those names**

Do not export private classifier/order helpers.

- [ ] **Step 3: Run focused regressions**

```bash
python -m pytest tests/supply/test_optimizer.py tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 4: Run Product Completion acceptance**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; PR-C has not changed application orchestration.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/__init__.py tests/supply/test_optimizer.py
git commit -m "feat: expose coverage allocation API"
```

---

## PR-C Acceptance Gate

PR-C is complete only when all are true:

1. Legacy allocation eligibility results remain unchanged.
2. Legacy MAX_MARGIN tie order remains unchanged.
3. `project_allocation_economics()` is public and supplies the exact compact contract used by PR-D.
4. `backend/supply` has no runtime import of `backend.economics`.
5. RouteCostIndex is absent from scarcity ordering inputs.
6. Desired route topology is never recomputed by PR-C.
7. Every desired leg is classified before stock scarcity.
8. Ineligible quantity is allocation-blocked, never stock-uncovered.
9. Eligible residual caused by proven stock exhaustion is stock-uncovered.
10. Seller stock is shared across all legs of one SKU.
11. Each leg is capped at `desired_qty`.
12. Same-origin/different-destination legs keep separate economics.
13. Allocated quantity and expected profit reconcile exactly.
14. Input permutations produce identical output.
15. Existing Product Completion acceptance and full suite stay green.
