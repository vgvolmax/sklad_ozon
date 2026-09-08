# PR-C Coverage-Aware MAX_MARGIN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing allocation eligibility and `MAX_MARGIN` scarcity policy at `SKU × origin × destination` coverage-leg granularity, producing final coverage legs plus causally distinct allocation-blocked and seller-stock-uncovered quantities.

**Architecture:** Do not invent a second optimizer. Extract the current threshold classification and deterministic MAX_MARGIN ordering from `backend/supply/optimizer.py` into reusable pure helpers, keep the legacy `optimize_allocations()` behavior covered by existing tests, and add one coverage-leg allocator that treats every `DesiredCoverageLeg.desired_qty` as a hard ceiling. Eligibility is classified before scarcity; seller stock is then consumed only by eligible legs.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; PR-A direct route economics + PR-B coverage contracts; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Coverage Planner remains the only owner of desired route placement. PR-C must not re-rank routes by tariff or fabricate alternate desired legs.
- Existing optimizer thresholds remain unchanged: economics complete, positive profit, minimum profit/unit, minimum margin rate, minimum ROI.
- Product allocation objective remains fixed `MAX_MARGIN`; do not add a new user-selectable objective.
- Reuse one threshold classifier and one MAX_MARGIN ordering policy. Do not fork legacy and coverage implementations.
- Each desired coverage leg has a hard ceiling equal to `desired_qty`.
- Classification is causal and non-overlapping:
  1. PR-B network gaps stay network gaps.
  2. Ineligible desired leg quantity becomes `allocation_blocked_qty`.
  3. Seller-stock scarcity runs only over eligible desired quantities.
  4. Eligible desired quantity left unfilled because stock is exhausted becomes `stock_uncovered_qty`.
- Seller stock is one quantity per SKU, shared across all origins/destinations.
- Direct route economics is route-specific `origin → destination`; historical expected logistics must not be substituted.
- Final allocation never changes destination demand/target identity.
- Keep legacy `optimize_allocations()` passing until later migration removes its callers; this PR adds the new path beside it.
- No application/snapshot/API/frontend integration in PR-C.
- Use TDD and no new dependencies.

---

## File Structure

- Modify `backend/supply/contracts.py` — coverage allocation candidate/decision/gap/result contracts.
- Modify `backend/supply/optimizer.py` — extract reusable eligibility/order helpers and add `allocate_coverage_legs()` while preserving legacy optimizer behavior.
- Modify `backend/supply/__init__.py` — export approved coverage-allocation API.
- Modify `tests/supply/test_optimizer.py` — regression-prove legacy behavior plus new coverage allocation semantics.
- Modify `tests/supply/test_coverage.py` only for helper fixtures/contracts shared with PR-C if necessary; route selection behavior remains PR-B-owned.

No `backend/application.py`, `backend/api.py`, decision snapshot, project persistence or frontend files belong in PR-C.

---

### Task 1: Define coverage allocation contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Test: `tests/supply/test_optimizer.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CoverageAllocationCandidate:
    leg: DesiredCoverageLeg
    economics: UnitEconomicsResult
    destination_target_qty: int
    demand_confidence: SignalConfidence
    distortion_signal: RecommendationDistortionSignal | None


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

`NetworkCoverageGap` remains owned by PR-B and is not duplicated here.

- [ ] **Step 1: Write failing identity/validation tests**

```python
def test_coverage_allocation_candidate_preserves_leg_identity():
    candidate = CoverageAllocationCandidate(
        leg=desired_leg("SKU-1", "Москва", "Казань", 50),
        economics=complete_economics("SKU-1", "Москва", margin="0.2"),
        destination_target_qty=100,
        demand_confidence=SignalConfidence.HIGH,
        distortion_signal=None,
    )
    assert candidate.leg.origin_cluster_id == "Москва"
    assert candidate.leg.destination_cluster_id == "Казань"


def test_final_coverage_leg_cannot_exceed_desired_quantity():
    with pytest.raises(ValueError, match="final_allocated_qty"):
        FinalCoverageLeg(
            "SKU-1", "Москва", "Казань", CoverageType.ROUTE,
            50, 51, Decimal("10"), Decimal("510"), True, (),
        )
```

Also validate candidate economics identity (`economics.sku == leg.sku` and `economics.placement_cluster_id == leg.origin_cluster_id`), nonnegative quantities and one plan family per result.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new contract imports fail.

- [ ] **Step 3: Implement immutable contracts and validation**

Keep new fields explicit; do not overload legacy `AllocationDecision.cluster_id`, because it cannot represent destination identity.

`DestinationAllocationGap` may contain both blocked and stock quantities for the same destination, but each component must be nonnegative and at least one must be positive when a gap row is emitted.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: contract tests pass while later allocator tests remain absent.

- [ ] **Step 5: Commit contract slice**

```bash
git add backend/supply/contracts.py tests/supply/test_optimizer.py
git commit -m "feat: add coverage allocation contracts"
```

---

### Task 2: Extract one reusable economics eligibility classifier

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**
- Existing legacy behavior to preserve:

```python
optimize_allocations(...)
```

- New private helper concept:

```python
def _classify_economics(
    economics: UnitEconomicsResult,
    thresholds: OptimizerThresholds,
) -> tuple[bool, set[str]]:
    ...
```

- Legacy candidate-specific ceiling/feasibility reasons remain in the legacy wrapper; economics threshold reasons come from the shared helper.

- [ ] **Step 1: Add parameterized legacy eligibility regression tests**

For the same complete base candidate, independently vary:
- incomplete economics;
- non-positive profit;
- profit below threshold;
- margin below threshold;
- ROI below threshold;
- valid economics.

Assert existing reason codes remain exactly:

```python
(
    "ECONOMICS_INCOMPLETE",
    "MARGIN_RATE_UNAVAILABLE",
    "ROI_UNAVAILABLE",
    "NON_POSITIVE_PROFIT",
    "BELOW_MIN_PROFIT_PER_UNIT",
    "BELOW_MIN_MARGIN_RATE",
    "BELOW_MIN_ROI",
    "ELIGIBLE_FOR_ALLOCATION",
)
```

as applicable under the existing `_REASON_ORDER`.

- [ ] **Step 2: Run regression tests before refactor and verify GREEN baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before refactor. This is the characterization baseline.

- [ ] **Step 3: Extract economics-only classification without changing semantics**

Move only the `candidate.economics` block from `_classify()` into `_classify_economics()`. The helper validates thresholds once through the existing threshold-validation path and emits the same reason codes.

Legacy `_classify()` becomes:

```python
def _classify(candidate, ceiling, thresholds, plan_family):
    reasons = _legacy_ceiling_and_feasibility_reasons(...)
    economics_eligible, economics_reasons = _classify_economics(
        candidate.economics, thresholds
    )
    reasons.update(economics_reasons)
    eligible = not reasons and economics_eligible and ceiling > 0
    if eligible:
        reasons.add("ELIGIBLE_FOR_ALLOCATION")
    return eligible, reasons
```

Do not alter ceiling semantics yet; legacy optimizer remains a compatibility path.

- [ ] **Step 4: Run optimizer regression tests and verify no output change**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit eligibility refactor**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation economics eligibility"
```

---

### Task 3: Extract deterministic MAX_MARGIN ordering policy

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**
- New private ordering helper takes a generic ranking projection rather than one concrete dataclass:

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
    ...
```

- [ ] **Step 1: Add exact legacy order characterization test**

Construct multiple eligible legacy candidates where each tie-break is isolated. Assert current `MAX_MARGIN` decision priority remains:

1. higher `margin_rate`;
2. higher `route_confidence`;
3. higher `demand_confidence`;
4. existing distortion-confidence ordering exactly as currently implemented;
5. larger calculated-need quantity;
6. stable cluster ID.

Do not “correct” the distortion tie-break in this PR; preserve current product behavior unless a separate approved design changes it.

- [ ] **Step 2: Run the characterization test and verify GREEN baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS before extraction.

- [ ] **Step 3: Extract the stable least-significant-first ordering implementation**

Move the current stable-sort sequence into `_max_margin_order()`. Keep `MAX_PROFIT` legacy compatibility inside `optimize_allocations()` if existing tests/API still reference the enum, but the new coverage allocator will call only MAX_MARGIN.

Example shape:

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

- [ ] **Step 4: Run legacy optimizer tests and verify unchanged output**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit ordering refactor**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share MAX_MARGIN ordering policy"
```

---

### Task 4: Classify coverage legs before seller-stock scarcity

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**
- Produces new public function:

```python
def allocate_coverage_legs(
    candidates: Iterable[CoverageAllocationCandidate],
    available_stock: int,
    thresholds: OptimizerThresholds,
    *,
    plan_family: PlanFamily,
) -> CoverageAllocationResult:
    ...
```

All candidates must share one SKU. Duplicate `(origin, destination)` legs are rejected.

- [ ] **Step 1: Write failing allocation-blocked tests**

```python
def test_ineligible_desired_leg_becomes_allocation_blocked_not_stock_shortage():
    result = allocate_coverage_legs(
        candidates=(coverage_candidate(
            origin="Москва", destination="Казань", desired=50,
            economics=incomplete_economics("SKU-1", "Москва"),
        ),),
        available_stock=100,
        thresholds=thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    assert result.allocated_qty == 0
    assert result.allocation_gaps[0].allocation_blocked_qty == 50
    assert result.allocation_gaps[0].stock_uncovered_qty == 0
    assert "ECONOMICS_INCOMPLETE" in result.final_legs[0].reason_codes
```

Add a threshold-failure case with abundant stock and assert it is also blocked, never seller-stock shortage.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: FAIL because `allocate_coverage_legs` is absent.

- [ ] **Step 3: Implement validation and pre-scarcity classification**

For every candidate:

```python
eligible, reasons = _classify_economics(candidate.economics, thresholds)
if eligible:
    reasons.add("ELIGIBLE_FOR_ALLOCATION")
else:
    blocked_by_destination[candidate.leg.destination_cluster_id] += candidate.leg.desired_qty
```

Do not classify `available_stock == 0` here; stock is the later scarcity phase.

Create a `FinalCoverageLeg` for every desired leg, including blocked legs with `final_allocated_qty=0`, so plan evidence remains inspectable.

- [ ] **Step 4: Run blocking tests and verify GREEN for classification slice**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: blocked-cause tests pass; scarcity tests are added next.

- [ ] **Step 5: Commit coverage eligibility slice**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: classify coverage allocation eligibility"
```

---

### Task 5: Allocate scarce seller stock across eligible coverage legs

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**
- Completes `allocate_coverage_legs(...)` using `_max_margin_order()`.

- [ ] **Step 1: Write failing MAX_MARGIN scarce-stock test**

```python
def test_coverage_scarcity_prefers_higher_margin_leg():
    result = allocate_coverage_legs(
        candidates=(
            coverage_candidate("Москва", "Казань", 50, margin="0.20"),
            coverage_candidate("Питер", "Тверь", 50, margin="0.30"),
        ),
        available_stock=60,
        thresholds=thresholds(),
        plan_family=PlanFamily.CALCULATED,
    )
    allocated = {
        (x.origin_cluster_id, x.destination_cluster_id): x.final_allocated_qty
        for x in result.final_legs
    }
    assert allocated[("Питер", "Тверь")] == 50
    assert allocated[("Москва", "Казань")] == 10
```

- [ ] **Step 2: Write seller-stock-only gap test**

```python
def test_eligible_unfilled_quantity_is_stock_uncovered():
    result = allocate_coverage_legs(... desired total 100, available_stock=60 ...)
    assert sum(g.allocation_blocked_qty for g in result.allocation_gaps) == 0
    assert sum(g.stock_uncovered_qty for g in result.allocation_gaps) == 40
```

- [ ] **Step 3: Write mixed blocked+scarce causal test**

Use three legs for one SKU:
- destination A desired 30, economics blocked;
- destination B desired 50, eligible high margin;
- destination C desired 50, eligible lower margin;
- seller stock 60.

Assert:
- blocked = 30;
- B gets 50;
- C gets 10;
- stock uncovered = 40;
- blocked quantity never consumes seller stock.

- [ ] **Step 4: Run focused tests and verify RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: new scarcity/gap tests fail before implementation.

- [ ] **Step 5: Implement MAX_MARGIN scarcity only over eligible candidates**

Order eligible candidates with the extracted helper:

```python
eligible = _max_margin_order(
    eligible,
    margin_rate=lambda item: item.economics.margin_rate,
    route_confidence=lambda item: item.leg.route_confidence,
    demand_confidence=lambda item: item.demand_confidence,
    distortion_confidence=lambda item: (
        None if item.distortion_signal is None else item.distortion_signal.confidence
    ),
    target_quantity=lambda item: item.destination_target_qty,
    stable_key=lambda item: (
        item.leg.origin_cluster_id,
        item.leg.destination_cluster_id,
    ),
)
```

Then sequentially allocate:

```python
remaining = available_stock
for item in eligible:
    quantity = min(remaining, item.leg.desired_qty)
    remaining -= quantity
```

For every eligible leg:

```python
stock_gap = item.leg.desired_qty - quantity
```

Aggregate stock gaps by destination. Add `PARTIAL_BY_SELLER_STOCK`, `SELLER_STOCK_EXHAUSTED` and `ALLOCATED` using the existing reason vocabulary where applicable.

- [ ] **Step 6: Calculate expected profit with existing Decimal discipline**

Within the existing `localcontext(prec=40, rounding=ROUND_HALF_EVEN)` pattern:

```python
expected_profit = (
    Decimal("0")
    if economics.profit_per_unit is None
    else Decimal(quantity) * economics.profit_per_unit
)
```

`objective_profit` is the sum of final-leg expected profits.

- [ ] **Step 7: Run optimizer tests and verify GREEN**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit scarcity slice**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "feat: allocate seller stock across coverage legs"
```

---

### Task 6: Prove conservation, deterministic ties and legacy compatibility

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_optimizer.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**
- Public exports: `CoverageAllocationCandidate`, `FinalCoverageLeg`, `DestinationAllocationGap`, `CoverageAllocationResult`, `allocate_coverage_legs`.

- [ ] **Step 1: Add conservation test joining PR-B network gaps with PR-C gaps**

The allocator does not own network gaps, so prove composition explicitly in the test:

```python
def test_final_coverage_conservation_with_all_gap_classes():
    target_qty = 120
    network_uncovered = 20
    result = allocate_coverage_legs(... desired legs total 100 ...)
    final = sum(x.final_allocated_qty for x in result.final_legs)
    blocked = sum(x.allocation_blocked_qty for x in result.allocation_gaps)
    stock = sum(x.stock_uncovered_qty for x in result.allocation_gaps)
    assert final + network_uncovered + blocked + stock == target_qty
```

Also assert:

```python
sum(x.final_allocated_qty for x in result.final_legs) <= result.available_stock
```

and every final leg is `<= desired_qty`.

- [ ] **Step 2: Add stable-tie/input-order invariance test**

Reverse candidate input order while keeping facts equal and assert the same final legs/gaps/result ordering.

- [ ] **Step 3: Add public export smoke test and verify RED**

```python
def test_coverage_allocator_is_exported():
    from backend.supply import allocate_coverage_legs
    assert callable(allocate_coverage_legs)
```

- [ ] **Step 4: Export only the approved coverage allocation surface**

Update `backend/supply/__init__.py`. Do not export internal eligibility/order helpers.

- [ ] **Step 5: Run PR-C regression suite**

```bash
python -m pytest \
  tests/supply/test_optimizer.py \
  tests/supply/test_coverage.py \
  tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS, including all existing legacy optimizer Product Completion behavior.

- [ ] **Step 6: Run full repository verification**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit export/acceptance slice**

```bash
git add backend/supply/__init__.py tests/supply/test_optimizer.py
git commit -m "test: verify coverage MAX_MARGIN invariants"
```

---

## PR-C Acceptance Gate

Before opening PR-C, verify from fresh output:

```bash
python -m pytest -q
```

Required proofs:

- Existing legacy `optimize_allocations()` tests remain green; one eligibility/order policy is reused rather than duplicated.
- Coverage allocator never re-ranks or creates routes; every final leg corresponds to one PR-B desired leg.
- Existing economics completeness/profit/margin/ROI thresholds remain eligibility gates.
- Ineligible desired quantity becomes `allocation_blocked_qty` even when seller stock is abundant.
- Seller-stock scarcity runs only over eligible desired quantities.
- Eligible unfilled quantity becomes `stock_uncovered_qty`, never allocation-blocked.
- MAX_MARGIN remains primary ranking; current deterministic tie-break intent is preserved.
- Blocked legs consume zero seller stock.
- Sum of final allocation never exceeds seller available stock or any desired-leg ceiling.
- Final + network-uncovered + allocation-blocked + stock-uncovered can conserve the original destination target exactly.
- No application orchestration, snapshot/API or frontend behavior is switched in PR-C.
