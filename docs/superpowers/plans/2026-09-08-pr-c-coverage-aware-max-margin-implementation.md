# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing allocation eligibility and `MAX_MARGIN` scarcity policy at `SKU × origin × destination` coverage-leg granularity, producing final coverage legs plus causally distinct allocation-blocked and seller-stock-uncovered quantities.

**Architecture:** PR-B has already decided the desired physical topology. PR-C must not choose routes again. Extract the current economics-threshold classifier and exact MAX_MARGIN ordering from `backend/supply/optimizer.py`, preserve the legacy optimizer as a compatibility path, and add one coverage-leg allocator whose ceiling is `DesiredCoverageLeg.desired_qty`. Eligibility is classified before scarcity; seller stock is then consumed only by eligible legs.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; PR-A direct-route economics + PR-B coverage contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** `RouteCostIndex` is topology evidence owned by PR-A/PR-B. It MUST NOT become a MAX_MARGIN allocation key. Scarcity allocation uses direct route economics already calculated for each desired coverage leg. Existing `route_confidence` remains a tie-break exactly as today, but the raw numeric route index is not a scarcity objective.

## Global Constraints

- Coverage Planner is the only owner of desired route placement.
- PR-C must not re-rank origins by direct tariff, `RouteCostIndex`, historical flow or geography.
- Existing optimizer thresholds remain unchanged: economics complete, positive profit, minimum profit/unit, minimum margin rate, minimum ROI.
- Product allocation objective remains fixed `MAX_MARGIN` for the new path.
- Reuse one threshold classifier and one MAX_MARGIN ordering policy. Do not fork legacy and coverage implementations.
- Each desired coverage leg has a hard ceiling equal to `desired_qty`.
- Classification is causal and non-overlapping:
  1. PR-B `network_gaps` stay network gaps.
  2. Ineligible desired leg quantity becomes `allocation_blocked_qty`.
  3. Seller-stock scarcity runs only over eligible desired quantities.
  4. Eligible desired quantity left unfilled because stock is exhausted becomes `stock_uncovered_qty`.
- Seller stock is one quantity per SKU shared across all origins/destinations.
- Direct route economics is route-specific `origin → destination`; historical expected logistics and `RouteCostIndex` are not substituted.
- Final allocation never changes destination target identity.
- Keep legacy `optimize_allocations()` passing until later migration removes its callers.
- No `backend/application.py`, snapshot/API/frontend integration in PR-C.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/supply/contracts.py` — coverage allocation candidate/decision/gap/result contracts.
- Modify `backend/supply/optimizer.py` — shared eligibility/order helpers and `allocate_coverage_legs()`.
- Modify `backend/supply/__init__.py` — export coverage allocation API.
- Modify `tests/supply/test_optimizer.py` — legacy characterization + coverage allocator tests.
- Run `tests/supply/test_coverage.py` unchanged as PR-B topology regression.

---

### Task 1: Define coverage allocation contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Test: `tests/supply/test_optimizer.py`

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

`NetworkCoverageGap` remains PR-B-owned and is not duplicated.

- [ ] **Step 1: Add validation tests**

```python
def test_candidate_preserves_origin_destination_identity():
    item = CoverageAllocationCandidate(
        leg=DesiredCoverageLeg(
            "SKU-1", "Москва", "Казань", 50, CoverageType.ROUTE,
            Decimal("47"), None, Decimal("0.8"), Decimal("1"),
            RouteConfidence.HIGH, 0, None, (),
        ),
        economics=complete_economics("SKU-1", "Москва", margin="0.20"),
        destination_target_qty=50,
        demand_confidence=SignalConfidence.HIGH,
        distortion_confidence=None,
    )
    assert item.leg.origin_cluster_id == "Москва"
    assert item.leg.destination_cluster_id == "Казань"


def test_final_leg_cannot_exceed_desired_quantity():
    with pytest.raises(ValueError, match="final_allocated_qty"):
        FinalCoverageLeg(
            "SKU-1", "Москва", "Казань", CoverageType.ROUTE,
            50, 51, Decimal("10"), Decimal("510"), True, (),
        )
```

Also validate economics identity equals `leg.sku` and `leg.origin_cluster_id`; all quantities are nonnegative integers; candidate target is at least desired quantity; result uses one plan family.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: contract imports fail.

- [ ] **Step 3: Implement contracts exactly as declared**

Do not add a `route_cost_index` field to `CoverageAllocationCandidate`; it is intentionally absent from the scarcity boundary.

- [ ] **Step 4: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_optimizer.py
git commit -m "feat: add coverage allocation contracts"
```

---

### Task 2: Extract one reusable economics eligibility classifier

**Files:**
- Modify: `backend/supply/optimizer.py`
- Test: `tests/supply/test_optimizer.py`

**Interface:**

```python
def _classify_economics(
    economics: UnitEconomicsResult,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
```

- [ ] **Step 1: Characterize current legacy eligibility before refactor**

Use the existing `candidate()` fixture and assert unchanged reason codes for:

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

- [ ] **Step 2: Run baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before extraction.

- [ ] **Step 3: Extract only the economics block from `_classify()`**

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

Legacy `_classify()` keeps all old physical/need/Ozon-ceiling rules and merges these economics reasons unchanged.

- [ ] **Step 4: Run legacy optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS with byte-for-byte-equivalent business outputs.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 3: Extract exact current MAX_MARGIN ordering

**Files:**
- Modify: `backend/supply/optimizer.py`
- Test: `tests/supply/test_optimizer.py`

**Interface:**

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

- [ ] **Step 1: Add tie-break characterization tests**

Assert existing order remains:

1. higher `margin_rate`;
2. higher `route_confidence`;
3. higher `demand_confidence`;
4. lower distortion-risk rank exactly as current stable-sort behavior implements it;
5. larger target/calculated need;
6. stable cluster/key.

- [ ] **Step 2: Add explicit RouteCostIndex non-influence test at boundary level**

Because `CoverageAllocationCandidate` contains no numeric index, construct two otherwise equal desired legs with different `DesiredCoverageLeg.route_cost_index` metadata and then project candidates. Assert `_max_margin_order()` receives no index projection and the winner is determined only by the documented ordering fields.

- [ ] **Step 3: Run baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before extraction.

- [ ] **Step 4: Extract stable least-significant-first sorts**

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

Keep legacy `MAX_PROFIT` compatibility inside the legacy optimizer only.

- [ ] **Step 5: Run regression tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 4: Classify desired legs before scarcity

**Files:**
- Modify: `backend/supply/optimizer.py`
- Test: `tests/supply/test_optimizer.py`

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

All candidates share one SKU; duplicate `(origin, destination)` legs are rejected.

- [ ] **Step 1: Add abundant-stock blocked test**

```python
def test_ineligible_leg_is_allocation_blocked_not_stock_shortage():
    result = allocate_coverage_legs(
        (coverage_candidate(
            origin="Москва", destination="Казань", desired=50,
            economics_complete=False,
        ),),
        100,
        thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    assert result.allocated_qty == 0
    assert result.allocation_gaps[0].allocation_blocked_qty == 50
    assert result.allocation_gaps[0].stock_uncovered_qty == 0
```

Add a below-margin-threshold case with abundant stock and assert the same causal classification.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: `allocate_coverage_legs()` absent.

- [ ] **Step 3: Validate input and classify economics**

For every candidate:

```python
eligible, reasons = _classify_economics(candidate.economics, thresholds)
if eligible:
    reasons.add("ELIGIBLE_FOR_ALLOCATION")
else:
    blocked_by_destination[candidate.leg.destination_cluster_id] += candidate.leg.desired_qty
```

Create a `FinalCoverageLeg` for every desired leg, including blocked legs with zero final allocation.

- [ ] **Step 4: Run blocked-cause tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS for eligibility classification.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: classify coverage allocation eligibility"
```

---

### Task 5: Allocate scarce seller stock by existing MAX_MARGIN policy

**Files:**
- Modify: `backend/supply/optimizer.py`
- Test: `tests/supply/test_optimizer.py`

- [ ] **Step 1: Add margin-priority scarcity test**

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
    assert allocated[("Питер", "Тверь")] == 50
    assert allocated[("Москва", "Казань")] == 10
```

- [ ] **Step 2: Add stock-only gap test**

For eligible desired total `100` and stock `60` assert blocked total `0`, stock-uncovered total `40`.

- [ ] **Step 3: Add same-origin different-destination economics test**

Two desired legs both originate in Moscow but serve different destinations and have different direct-route margins. Assert scarcity ranking uses each leg's own economics rather than an origin-average economics value.

- [ ] **Step 4: Implement scarcity loop**

Order only eligible candidates through `_max_margin_order()` with projections:

```python
ordered = _max_margin_order(
    eligible,
    margin_rate=lambda x: x.economics.margin_rate,
    route_confidence=lambda x: x.leg.route_confidence,
    demand_confidence=lambda x: x.demand_confidence,
    distortion_confidence=lambda x: x.distortion_confidence,
    target_quantity=lambda x: x.destination_target_qty,
    stable_key=lambda x: (x.leg.origin_cluster_id, x.leg.destination_cluster_id),
)
```

Then:

```python
remaining = available_stock
for item in ordered:
    qty = min(remaining, item.leg.desired_qty)
    allocated_by_leg[(item.leg.origin_cluster_id, item.leg.destination_cluster_id)] = qty
    remaining -= qty
```

Unfilled eligible `desired_qty - qty` is stock uncovered for that destination.

- [ ] **Step 5: Reconcile profit with Decimal precision 40**

Use the same `localcontext()` and `ROUND_HALF_EVEN` convention as legacy optimizer. `objective_profit` is the sum of `final_allocated_qty * economics.profit_per_unit` over final legs.

- [ ] **Step 6: Run focused tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate scarce stock across coverage legs"
```

---

### Task 6: Prove causal conservation and export public API

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`
- Regression: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add coverage+allocation conservation fixture**

Combine one PR-B `CoveragePlanResult` with allocation results and assert for every destination:

```text
final allocated
+ network_uncovered
+ allocation_blocked
+ stock_uncovered
= destination target
```

- [ ] **Step 2: Add seller-stock bound**

For every SKU fixture:

```python
assert sum(x.final_allocated_qty for x in result.final_legs) <= result.available_stock
```

- [ ] **Step 3: Add desired-leg hard ceiling invariant**

```python
assert all(x.final_allocated_qty <= x.desired_qty for x in result.final_legs)
```

- [ ] **Step 4: Export public API**

Export:

```text
CoverageAllocationCandidate
FinalCoverageLeg
DestinationAllocationGap
CoverageAllocationResult
allocate_coverage_legs
```

- [ ] **Step 5: Run focused regressions**

```bash
python -m pytest tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/__init__.py tests/supply/test_optimizer.py
git commit -m "feat: expose coverage-aware MAX_MARGIN allocation"
```

---

## PR-C Acceptance Gate

PR-C is complete only when all are true:

1. Desired route topology from PR-B is never recomputed in optimizer.
2. Numeric `RouteCostIndex` is not an allocation ranking key.
3. Direct route economics remains route-specific for each leg.
4. Existing threshold semantics and reason ordering remain unchanged.
5. New path is fixed MAX_MARGIN and reuses the exact current tie-break hierarchy.
6. Ineligible desired quantity is `allocation_blocked`, never stock shortage.
7. Only eligible unfilled quantity can become `stock_uncovered`.
8. Final allocation never exceeds seller stock or desired leg ceilings.
9. Same-origin/different-destination legs retain distinct economics.
10. Global destination conservation holds with PR-B network gaps.
11. Legacy optimizer tests remain green until later removal/migration.
12. No application/snapshot/API/frontend integration occurs in PR-C.
