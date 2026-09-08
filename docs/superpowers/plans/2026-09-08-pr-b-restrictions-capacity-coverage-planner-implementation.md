# PR-B Restrictions Capacity & Coverage Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make restrictions capacity unambiguous and add a deterministic pure Coverage Planner that converts destination targets into desired `origin → destination` legs inside a user-selected supply network, using exact direct tariffs as the primary non-local ranking signal and `RouteCostIndex` as secondary structural evidence.

**Architecture:** Extend normalized restriction evidence with explicit `FINITE / UNLIMITED / UNKNOWN` capacity semantics. Add a pure planner that owns LOCAL-first assignment, iterative constrained-destination ordering, exact direct-fee ranking, SKU-independent route-index tie-breaks and shared `SKU × origin` capacity consumption. Historical flow remains explanatory evidence only. Keep this PR disconnected from `backend/application.py`, seller-stock allocation, snapshots, API and frontend.

**Tech Stack:** Python 3, frozen dataclasses/enums, `Decimal`, pytest; PR-A `DirectRouteQuote`, `RouteCostIndex`, `TariffClass`; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** `RouteCostIndex` is topology evidence derived from the whole Ozon tariff matrix. It does not replace the direct fee for a concrete SKU. Coverage ranking is therefore `LOCAL first`, then for non-local candidates exact current direct fee ASC, then known lower `RouteCostIndex`, then route-evidence confidence, then stable origin ID.

## Global Constraints

- `destination_cluster` remains the owner of demand; Coverage Planner never rewrites demand/need geography.
- Restrictions report is the only physical eligibility/capacity source for this feature.
- Capacity evidence distinguishes explicit `FINITE`, explicit `UNLIMITED` and `UNKNOWN`; unknown is never treated as unlimited.
- Malformed nonblank numeric capacity remains an ingestion error.
- Multiple allowed warehouse limits inside one cluster are not summed.
- Cluster capacity is the best independently proven single receiving option: any known UNLIMITED wins; otherwise max known FINITE; if no known capacity exists, UNKNOWN.
- Capacity is shared by all destinations served through one `SKU × origin`; it is never reset per destination.
- LOCAL assignment is attempted before non-local routes and does not require historical route evidence or a `RouteCostIndex`.
- Non-local assignment requires a selected physically feasible origin, known usable capacity and a MATCHED `DirectRouteQuote` for the concrete SKU.
- Primary non-local ordering is exact `DirectRouteQuote.matched_fee ASC`.
- `RouteCostIndex` is only a secondary tie-break when direct fees are exactly equal; missing index evidence sorts after known index evidence.
- Historical route share/quantity never enters coverage quantities or primary ranking.
- Route-evidence confidence may break a remaining exact tie; stable origin ID is final.
- No proportional split, geographic-distance fallback or LP/min-cost-flow solver.
- No backend thresholds such as `<0.8 good` / `>1.3 bad`.
- This PR does not apply seller-stock scarcity or allocation economics; those belong to PR-C.
- Use TDD; no `backend/application.py`, snapshot/API/frontend changes in PR-B.

---

## File Structure

- Modify `backend/ingestion/restrictions.py` — preserve explicit warehouse capacity state at ingestion.
- Modify `backend/supply/contracts.py` — capacity state, destination-target, desired coverage and route-evidence contracts.
- Modify `backend/supply/feasibility.py` — canonical non-additive cluster capacity aggregation.
- Create `backend/supply/coverage.py` — pure deterministic Coverage Planner.
- Modify `backend/supply/__init__.py` — export coverage contracts/functions.
- Modify `tests/ingestion/test_restrictions.py` — finite/unlimited/unknown/malformed parsing.
- Modify `tests/supply/test_placement.py` — feasibility aggregation and legacy placement regression.
- Create `tests/supply/test_coverage.py` — LOCAL-first, exact-fee ranking, route-index tie-break, capacity spillover, constrained-first, network-gap and conservation tests.

---

### Task 1: Preserve explicit capacity evidence in restriction ingestion

**Files:**
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

- [ ] **Step 1: Add exact CSV fixtures for all states**

```python
def _restriction_csv(maximum: str) -> bytes:
    return (
        "SKU;Кластер;Склад;Возможно ли поставить товар;Максимальный размер поставки\n"
        f"SKU-1;Москва;W1;Да;{maximum}\n"
    ).encode("utf-8")
```

Add tests:

```python
def test_finite_capacity_is_explicit(report_meta):
    row = import_restrictions(_restriction_csv("120"), report_meta).records[0]
    assert row.max_supply_qty == 120
    assert row.capacity_kind is RestrictionCapacityKind.FINITE


def test_unlimited_capacity_is_explicit(report_meta):
    row = import_restrictions(_restriction_csv("Без ограничений"), report_meta).records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNLIMITED


def test_blank_allowed_capacity_is_unknown(report_meta):
    row = import_restrictions(_restriction_csv(""), report_meta).records[0]
    assert row.max_supply_qty is None
    assert row.capacity_kind is RestrictionCapacityKind.UNKNOWN


def test_malformed_nonblank_capacity_is_rejected(report_meta):
    result = import_restrictions(_restriction_csv("сто двадцать"), report_meta)
    assert result.records == ()
    assert any(d.code == "INVALID_MAX_SUPPLY_QTY" for d in result.diagnostics)
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: new state assertions fail because `capacity_kind` is absent.

- [ ] **Step 3: Implement explicit parsing**

Keep `max_supply_qty: int | None`; only FINITE carries an integer. Parse:

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

PROHIBITED rows remain prohibited regardless of capacity text.

- [ ] **Step 4: Run and verify GREEN**

```bash
python -m pytest tests/ingestion/test_restrictions.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py
git commit -m "feat: preserve restriction capacity state"
```

---

### Task 2: Carry explicit capacity through cluster feasibility

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/feasibility.py`
- Test: `tests/supply/test_placement.py`

**Interfaces:**

Append to `WarehouseCapability` and `SupplyFeasibility`:

```python
capacity_kind: RestrictionCapacityKind = RestrictionCapacityKind.UNKNOWN
```

- [ ] **Step 1: Add failing aggregation tests**

Use explicit capabilities to prove:

```text
FINITE 100 + FINITE 300 -> cluster FINITE 300
FINITE 120 + UNKNOWN -> cluster FINITE 120
FINITE 120 + UNLIMITED -> cluster UNLIMITED
UNKNOWN + UNKNOWN -> cluster UNKNOWN
```

Also preserve existing fail-closed behavior for no explicitly allowed warehouse, conflicting restriction state and finite zero capacity.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

Expected: new aggregation tests fail under current `min(explicit_maxima)` semantics.

- [ ] **Step 3: Add consistency validation**

For `WarehouseCapability`:

```python
if self.capacity_kind is RestrictionCapacityKind.FINITE:
    if self.max_supply_qty is None:
        raise ValueError("finite capacity requires max_supply_qty")
elif self.max_supply_qty is not None:
    raise ValueError("non-finite capacity must not contain max_supply_qty")
```

- [ ] **Step 4: Implement non-additive cluster rule**

After current restriction-state screening, derive capacity only from explicitly allowed eligible warehouse alternatives:

```python
known = [
    item for item in eligible
    if item.capacity_kind in {
        RestrictionCapacityKind.FINITE,
        RestrictionCapacityKind.UNLIMITED,
    }
]

if not eligible:
    cluster_kind = RestrictionCapacityKind.FINITE
    cluster_max = 0
elif not known:
    cluster_kind = RestrictionCapacityKind.UNKNOWN
    cluster_max = None
elif any(item.capacity_kind is RestrictionCapacityKind.UNLIMITED for item in known):
    cluster_kind = RestrictionCapacityKind.UNLIMITED
    cluster_max = None
else:
    cluster_kind = RestrictionCapacityKind.FINITE
    cluster_max = max(
        item.max_supply_qty for item in known if item.max_supply_qty is not None
    )
```

Do not sum warehouses.

- [ ] **Step 5: Run feasibility + legacy optimizer regressions**

```bash
python -m pytest tests/supply/test_placement.py tests/supply/test_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

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
    direct_quote: DirectRouteQuote
    route_cost_index: RouteCostIndex | None
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
    tariff_class: TariffClass | None
    route_cost_index: Decimal | None
    route_cost_index_coverage: Decimal | None
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

Use `TYPE_CHECKING` for economics imports if needed to avoid a runtime cycle. Do not embed an entire route-index matrix in every leg; only copy the numeric evidence for that chosen route.

- [ ] **Step 1: Add contract validation tests**

Test nonblank identities, nonnegative target/gap quantities, positive `desired_qty`, route fee/index nonnegative, observed share in `[0,1]`, and identity alignment between `RoutePlanningEvidence` and `DirectRouteQuote`/`RouteCostIndex`.

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: contract imports fail.

- [ ] **Step 3: Implement contracts exactly as declared**

For LOCAL legs require `origin == destination`, `direct_route_fee is None`, `tariff_class is None`; LOCAL does not need external route-index evidence.

For ROUTE legs require `origin != destination` and a nonnegative direct fee from a MATCHED quote.

- [ ] **Step 4: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/contracts.py tests/supply/test_coverage.py
git commit -m "feat: define coverage planning contracts"
```

---

### Task 4: Add pure route candidate ordering

**Files:**
- Create: `backend/supply/coverage.py`
- Test: `tests/supply/test_coverage.py`

**Interfaces:**

```python
def _route_order_key(evidence: RoutePlanningEvidence) -> tuple:
    index = evidence.route_cost_index
    return (
        evidence.direct_quote.matched_fee,
        index is None,
        Decimal("0") if index is None else index.index_value,
        -_ROUTE_RANK[evidence.route_confidence],
        evidence.origin_cluster_id,
    )
```

- [ ] **Step 1: Add exact fee-priority test**

```python
def test_lower_direct_fee_wins_even_when_route_index_is_worse():
    winner = choose_nonlocal_origin(
        destination="Казань",
        evidences=(
            evidence("Москва", "Казань", fee="47", index="1.10"),
            evidence("Питер", "Казань", fee="52", index="0.70"),
        ),
    )
    assert winner == "Москва"
```

- [ ] **Step 2: Add route-index exact-fee tie test**

```python
def test_lower_route_index_breaks_equal_direct_fee_tie():
    winner = choose_nonlocal_origin(
        destination="Казань",
        evidences=(
            evidence("Москва", "Казань", fee="50", index="0.95"),
            evidence("Питер", "Казань", fee="50", index="0.72"),
        ),
    )
    assert winner == "Питер"
```

Add cases proving known index sorts before missing index only when fees tie, and observed flow share/quantity never changes the winner.

- [ ] **Step 3: Implement `_route_order_key` and one small public-test helper only through planner-visible behavior**

Do not expose a permanent `choose_nonlocal_origin()` production API if the planner can test ordering through `plan_coverage()` in Task 5. The test helper may remain test-local; production owns only `_route_order_key`.

- [ ] **Step 4: Run and verify GREEN**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: ordering tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: rank planned routes deterministically"
```

---

### Task 5: Implement LOCAL-first and shared capacity ledger

**Files:**
- Modify: `backend/supply/coverage.py`
- Test: `tests/supply/test_coverage.py`

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

All targets must share the same SKU and plan family.

- [ ] **Step 1: Add LOCAL-first test**

```text
Kazan target 50
Kazan selected + FINITE 100
Moscow->Kazan cheaper than any hypothetical local external comparison
Expected: Kazan->Kazan LOCAL 50
```

Assert LOCAL does not require a direct route quote or route index.

- [ ] **Step 2: Add shared capacity test**

```text
Moscow FINITE capacity 70
Kazan residual 50
Tver residual 50
Expected total desired legs through Moscow <= 70, not 70 per destination
```

- [ ] **Step 3: Implement capacity ledger**

Normalize each selected origin to:

```python
remaining_capacity[origin] = (
    feasibility.max_supply_qty
    if feasibility.capacity_kind is RestrictionCapacityKind.FINITE
    else None
)
```

`None` means explicit UNLIMITED only. UNKNOWN origins are not candidates. FINITE zero origins are not candidates.

Use a helper:

```python
def _consume_capacity(origin: str, requested: int, remaining: dict[str, int | None]) -> int:
    value = remaining[origin]
    if value is None:
        return requested
    allocated = min(requested, value)
    remaining[origin] = value - allocated
    return allocated
```

- [ ] **Step 4: Implement LOCAL pass**

Iterate targets in stable `(destination_cluster_id)` order. For a selected, allowed, known-capacity destination origin, allocate locally up to remaining capacity and store residual target separately.

- [ ] **Step 5: Run LOCAL/capacity tests**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS for LOCAL and capacity ledger cases.

- [ ] **Step 6: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: allocate local coverage before routed demand"
```

---

### Task 6: Implement iterative constrained-first non-local assignment

**Files:**
- Modify: `backend/supply/coverage.py`
- Test: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add constrained-first regression**

Scenario:

```text
Destination A residual 50; only Moscow is feasible
Destination B residual 50; Moscow or Peter are feasible
Moscow remaining capacity 50
Peter remaining capacity 50
```

Expected:

```text
Moscow -> A 50
Peter -> B 50
network_uncovered = 0
```

- [ ] **Step 2: Add exact route ranking spillover test**

```text
Kazan residual 100
Moscow fee 47, index .90, remaining 70
Peter fee 52, index .70, remaining 100
Expected Moscow->Kazan 70; Peter->Kazan 30
```

- [ ] **Step 3: Add historical-flow non-weight test**

Give Moscow observed share `0.01` and Peter observed share `0.99`, but Moscow fee lower. Assert Moscow fills first. Historical evidence remains copied to the chosen leg only.

- [ ] **Step 4: Implement dynamic feasible-candidate recomputation**

For every residual destination on every loop iteration, candidate origins must satisfy all:

```text
selected
feasibility.allowed
capacity_kind != UNKNOWN
remaining capacity > 0 or UNLIMITED
origin != destination
RoutePlanningEvidence exists
DirectRouteQuote.lookup_status == MATCHED
```

Compute `candidate_count` after current capacity state. Choose the next destination by:

```python
(min candidate_count, -residual_qty, destination_cluster_id)
```

If candidate count is zero, emit a network gap immediately and remove that destination from residual work.

For a chosen destination, sort candidates by `_route_order_key`, consume each sequentially until residual becomes zero or candidates are exhausted.

- [ ] **Step 5: Emit deterministic gap reasons**

Use only these planner-level codes:

```text
NO_SELECTED_FEASIBLE_ORIGIN
UNKNOWN_OR_EXHAUSTED_ORIGIN_CAPACITY
NO_COMPLETE_DIRECT_TARIFF
SELECTED_NETWORK_CAPACITY_EXHAUSTED
```

When several facts apply, preserve a stable explicit tuple order defined in `coverage.py`.

- [ ] **Step 6: Run focused tests**

```bash
python -m pytest tests/supply/test_coverage.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/supply/coverage.py tests/supply/test_coverage.py
git commit -m "feat: plan routed coverage across selected network"
```

---

### Task 7: Prove conservation, determinism and public exports

**Files:**
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_coverage.py`

- [ ] **Step 1: Add per-destination conservation test**

For every target returned by fixture scenarios assert:

```python
covered = sum(
    leg.desired_qty for leg in result.desired_legs
    if leg.destination_cluster_id == target.destination_cluster_id
)
gap = sum(
    item.quantity for item in result.network_gaps
    if item.destination_cluster_id == target.destination_cluster_id
)
assert covered + gap == target.quantity
```

- [ ] **Step 2: Add per-origin finite-capacity invariant**

```python
assert sum(
    leg.desired_qty for leg in result.desired_legs
    if leg.origin_cluster_id == "Москва"
) <= 70
```

- [ ] **Step 3: Add input permutation determinism test**

Permute targets, selected origins and mapping insertion order; assert identical `CoveragePlanResult`.

- [ ] **Step 4: Export public coverage surface**

Export from `backend/supply/__init__.py`:

```text
CoverageType
DestinationTarget
RoutePlanningEvidence
DesiredCoverageLeg
NetworkCoverageGap
CoveragePlanResult
plan_coverage
```

Do not export `_route_order_key` or capacity-ledger helpers.

- [ ] **Step 5: Run focused + regression suites**

```bash
python -m pytest tests/ingestion/test_restrictions.py tests/supply/test_placement.py tests/supply/test_coverage.py tests/supply/test_optimizer.py -q
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; PR-B remains disconnected from current application orchestration.

- [ ] **Step 6: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

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
4. LOCAL is always attempted first when selected and physically feasible.
5. Exact direct tariff for the concrete SKU remains primary non-local ranking evidence.
6. `RouteCostIndex` only breaks exact direct-fee ties and never substitutes for missing direct tariff evidence.
7. Historical flow share/quantity never changes planned quantities or primary route ranking.
8. One `SKU × origin` capacity is shared across all destination legs.
9. Constrained destinations are recomputed iteratively against remaining capacity.
10. Sequential fill is used; no proportional route split exists.
11. Every destination target conserves into desired legs + network gap.
12. Inputs are permutation-deterministic.
13. No seller-stock scarcity, snapshots, API or UI behavior changed yet.
