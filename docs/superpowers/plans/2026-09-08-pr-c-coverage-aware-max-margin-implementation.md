# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing allocation eligibility and `MAX_MARGIN` scarcity policy at `SKU × origin × destination` coverage-leg granularity, while introducing a compact supply-owned economics boundary suitable for immutable planning snapshots and stateless replan.

**Architecture:** PR-B owns desired topology. PR-C adds `AllocationEconomics`, a minimal immutable projection containing only the fields scarcity policy actually consumes: completeness, profit/unit, margin, ROI and blocker evidence. Legacy `PlacementAssessment.economics` is projected into this same contract before classification, so there is still one threshold policy. New coverage candidates already carry this compact contract. Numeric `RouteCostIndex` stays topology metadata and is absent from the scarcity ordering interface.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- PR-C never creates, replaces or re-ranks desired routes.
- PR-C never ranks by direct tariff, numeric `RouteCostIndex`, historical Flow or geography.
- Existing economics eligibility semantics remain unchanged: complete economics, positive profit, minimum profit/unit, minimum margin rate and minimum ROI.
- New coverage allocation is fixed `MAX_MARGIN`; no new objective is added.
- One `AllocationEconomics` classifier and one MAX_MARGIN ordering implementation serve legacy and coverage paths.
- `DesiredCoverageLeg.desired_qty` is a hard ceiling.
- Gap causality is fixed: network gap → allocation eligibility → seller-stock scarcity.
- Ineligible desired quantity is `allocation_blocked_qty`; only eligible unfilled quantity may be `stock_uncovered_qty`.
- Seller stock is one quantity per SKU across all origins/destinations.
- Full direct/local unit economics remains calculated by `backend.economics`; PR-C only consumes its compact projection.
- `backend/supply/contracts.py` does not import `backend.economics` at module import time.
- Legacy `optimize_allocations()` remains regression-green.
- PR-C does not modify application orchestration, snapshots, API or frontend.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/supply/contracts.py` — `AllocationEconomics` and coverage-allocation contracts.
- Modify `backend/supply/optimizer.py` — projection helper, shared economics classifier, shared MAX_MARGIN ordering, `allocate_coverage_legs()`.
- Modify `backend/supply/__init__.py` — export compact economics and coverage allocation API.
- Modify `tests/supply/test_optimizer.py` — legacy characterization, projection parity and new coverage allocation tests.
- Run `tests/supply/test_coverage.py` unchanged as topology regression.

---

### Task 1: Define compact `AllocationEconomics` and coverage allocation contracts

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

- [ ] **Step 1: Add exact compact economics helper**

In `tests/supply/test_optimizer.py` add:

```python
def allocation_economics(
    origin="Москва",
    *,
    sku="SKU-1",
    complete=True,
    profit="30",
    margin="0.30",
    roi="0.40",
):
    return AllocationEconomics(
        sku,
        origin,
        complete,
        None if profit is None else Decimal(profit),
        None if margin is None else Decimal(margin),
        None if roi is None else Decimal(roi),
        () if complete else ("fixture",),
    )
```

Reuse PR-B `DesiredCoverageLeg` shape:

```python
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
```

Add candidate helper:

```python
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
    return CoverageAllocationCandidate(
        desired_leg(
            origin, destination, qty, sku=sku, index=index,
            route_confidence=route_confidence,
        ),
        allocation_economics(
            origin, sku=sku, complete=complete,
            profit=profit, margin=margin, roi=roi,
        ),
        qty if target_qty is None else target_qty,
        demand_confidence,
        distortion_confidence,
    )
```

- [ ] **Step 2: Add failing validation tests**

```python
def test_allocation_economics_rejects_blank_origin():
    with pytest.raises(ValueError, match="origin_cluster_id"):
        allocation_economics(origin="")


def test_candidate_rejects_economics_origin_mismatch():
    with pytest.raises(ValueError, match="economics identity"):
        CoverageAllocationCandidate(
            desired_leg("Москва", "Казань", 50),
            allocation_economics("Питер"),
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

Also reject non-finite Decimal metrics, negative quantities and candidate target smaller than desired leg.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new contracts are absent.

- [ ] **Step 4: Implement contracts and validation**

`AllocationEconomics` validates identity and finite decimals when present but does not independently infer `complete`; it preserves the authoritative upstream flag/reasons. Candidate validates economics identity against leg identity. Gap rows require at least one positive component.

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: contract tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_optimizer.py
git commit -m "feat: add compact allocation economics contracts"
```

---

### Task 2: Project current `UnitEconomicsResult` into `AllocationEconomics`

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Public interface:**

```python
def to_allocation_economics(unit_economics) -> AllocationEconomics:
```

The function intentionally accepts the existing unit-economics object and performs a local runtime import for type validation, avoiding a module-level supply→economics cycle.

- [ ] **Step 1: Add projection parity test using existing legacy `candidate()` fixture**

```python
def test_unit_economics_projection_preserves_all_scarcity_fields():
    unit = candidate(
        "Москва", profit="23", margin="0.23", roi="0.46"
    ).economics
    projected = to_allocation_economics(unit)
    assert projected == AllocationEconomics(
        "SKU-1", "Москва", True,
        Decimal("23"), Decimal("0.23"), Decimal("0.46"), (),
    )
```

- [ ] **Step 2: Add incomplete projection test**

Use `candidate("Москва", complete=False).economics`; assert `complete=False`, all available metric values are preserved and `reason_codes == unit.blockers`.

- [ ] **Step 3: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "projection"
```

Expected: `to_allocation_economics` absent.

- [ ] **Step 4: Implement local-import projection**

```python
def to_allocation_economics(unit_economics):
    from backend.economics import UnitEconomicsResult

    if not isinstance(unit_economics, UnitEconomicsResult):
        raise TypeError("unit_economics must be UnitEconomicsResult")
    return AllocationEconomics(
        unit_economics.sku,
        unit_economics.placement_cluster_id,
        unit_economics.complete,
        unit_economics.profit_per_unit,
        unit_economics.margin_rate,
        unit_economics.roi,
        tuple(unit_economics.blockers),
    )
```

- [ ] **Step 5: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "projection"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: project unit economics for allocation"
```

---

### Task 3: Extract one reusable economics eligibility classifier

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Private interface:**

```python
def _classify_economics(
    economics: AllocationEconomics,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
```

- [ ] **Step 1: Run current legacy optimizer suite and verify GREEN baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

The suite already characterizes physical/need/economics reason codes and tie-break behavior.

- [ ] **Step 2: Implement classifier against compact contract**

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

Change legacy `_classify()` economics block to:

```python
economics_eligible, economics_reasons = _classify_economics(
    to_allocation_economics(candidate.economics),
    thresholds,
)
reasons.update(economics_reasons)
```

Keep all legacy physical/need/Ozon-ceiling reasons and `_REASON_ORDER` unchanged.

- [ ] **Step 3: Run legacy regression suite**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS with unchanged legacy decisions/reasons.

- [ ] **Step 4: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 4: Extract exact current MAX_MARGIN ordering

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

- [ ] **Step 1: Add/retain exact hierarchy characterization**

Current behavior must remain:

```text
higher margin
higher route confidence
higher demand confidence
current lower distortion-rank behavior
larger calculated need
after all ties stable cluster ID
```

- [ ] **Step 2: Extract stable least-significant-first sorts**

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

Legacy MAX_MARGIN delegates to this helper. Preserve MAX_PROFIT output behavior in its compatibility path.

- [ ] **Step 3: Run hierarchy tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "tie_break or confidence or objective"
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 5: Implement coverage eligibility and seller-stock scarcity

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

- [ ] **Step 1: Add abundant-stock blocked test**

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
```

Add below-margin-threshold case with abundant stock and the same causal expectation.

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
```

- [ ] **Step 3: Add RouteCostIndex non-influence test**

```python
def test_route_cost_index_is_not_a_scarcity_key():
    result = allocate_coverage_legs(
        (
            coverage_candidate(
                "Москва", "Казань", 1,
                index="9", margin="0.30",
                route_confidence=RouteConfidence.MEDIUM,
            ),
            coverage_candidate(
                "Питер", "Тверь", 1,
                index="0.1", margin="0.20",
                route_confidence=RouteConfidence.HIGH,
            ),
        ),
        1,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    allocated = {
        (x.origin_cluster_id, x.destination_cluster_id): x.final_allocated_qty
        for x in result.final_legs
    }
    assert allocated[("Москва", "Казань")] == 1
    assert allocated[("Питер", "Тверь")] == 0
```

- [ ] **Step 4: Add same-origin/different-destination economics test**

Two Moscow legs serve Kazan/Tver with margins `0.20` and `0.40`; stock covers one leg. Assert Tver receives allocation. This proves no origin-average economics is used.

- [ ] **Step 5: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q -k "coverage or scarcity or route_cost_index"
```

Expected: `allocate_coverage_legs()` absent.

- [ ] **Step 6: Implement validation and pre-scarcity classification**

Validate stock, thresholds, plan family, nonempty one-SKU candidate set and unique `(origin,destination)` identities. For every candidate:

```python
eligible, reasons = _classify_economics(item.economics, thresholds)
if eligible:
    reasons.add("ELIGIBLE_FOR_ALLOCATION")
else:
    blocked_by_destination[item.leg.destination_cluster_id] += item.leg.desired_qty
```

Do not inspect available stock during this phase.

- [ ] **Step 7: Order only eligible legs**

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

No numeric route-index projection exists.

- [ ] **Step 8: Allocate desired ceilings**

```python
remaining = available_stock
allocated_by_key = {}
for item in ordered:
    key = (item.leg.origin_cluster_id, item.leg.destination_cluster_id)
    quantity = min(remaining, item.leg.desired_qty)
    allocated_by_key[key] = quantity
    remaining -= quantity
```

- [ ] **Step 9: Build final legs, gaps and objective profit**

For every candidate sorted by `(origin,destination)`:
- blocked: final 0, blocked gap = desired;
- eligible: final from allocation map, stock gap = desired-final;
- reason codes reuse existing allocation reason order;
- expected profit uses `Decimal(final_qty) * profit_per_unit` under precision 40 / `ROUND_HALF_EVEN`.

Aggregate `DestinationAllocationGap` by destination. `unallocated_stock = available_stock - allocated_qty`.

- [ ] **Step 10: Run full optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate scarce stock across coverage legs"
```

---

### Task 6: Prove conservation and export public API

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`
- Regression: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add allocation conservation helper**

For every result fixture assert:

```python
assert result.allocated_qty == sum(
    x.final_allocated_qty for x in result.final_legs
)
assert result.allocated_qty <= result.available_stock
assert all(x.final_allocated_qty <= x.desired_qty for x in result.final_legs)
```

For each destination:

```text
final allocated + allocation blocked + stock uncovered = desired leg quantity
```

- [ ] **Step 2: Add combined PR-B + PR-C conservation test**

Use a PR-B result containing a network gap. Allocate its desired legs and assert:

```text
final allocated
+ network uncovered
+ allocation blocked
+ stock uncovered
= destination target
```

for every destination.

- [ ] **Step 3: Export public surface**

From `backend/supply/__init__.py` export:

```text
AllocationEconomics
to_allocation_economics
CoverageAllocationCandidate
FinalCoverageLeg
DestinationAllocationGap
CoverageAllocationResult
allocate_coverage_legs
```

- [ ] **Step 4: Run focused + legacy acceptance**

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
2. Supply-owned `AllocationEconomics` contains only fields scarcity needs.
3. Legacy UnitEconomicsResult projects to the compact contract without changing scarcity semantics.
4. Numeric `RouteCostIndex` cannot affect scarcity ordering.
5. Route-specific economics remains distinct for same-origin/different-destination legs.
6. Existing threshold semantics and reason ordering remain unchanged.
7. New path uses existing MAX_MARGIN hierarchy and adds no new objective.
8. Ineligible desired quantity is allocation-blocked, never stock shortage.
9. Only eligible unfilled quantity becomes stock-uncovered.
10. Final allocation never exceeds seller stock or desired-leg ceilings.
11. Combined conservation holds with PR-B network gaps.
12. Legacy optimizer tests remain green.
13. No application/snapshot/API/frontend integration occurs in PR-C.
