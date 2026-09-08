# PR-B Multiplicity-Aware Shippable Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing Calculated Plan into an operational whole-pack plan that respects supplier multiplicity, seller stock, Ozon cluster capacity and product volume without changing upstream demand semantics.

**Architecture:** Keep the current `optimize_allocations()` and analytical `AnalysisSnapshot` behavior intact. Extract the existing deterministic per-SKU eligibility/ranking policy into reusable helpers, then add a pure whole-pack operationalizer that takes the already-calculated per-cluster allocation as its desired baseline. A thin decision adapter builds UI-ready `ShippableLine` views; API wiring comes later in PR-D.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Global Constraints

- Do not change `DemandEstimate`, `NeedComparison`, stockout, Flow or route economics.
- Current FBO/inbound remain part of upstream need only.
- Seller available stock remains a shared ceiling per SKU and is never converted into demand.
- Existing Calculated Plan stays the analytical baseline; Safe Plan remains an analytical reference.
- Every positive operational quantity is divisible by `pack_multiple`.
- Pack rounding is explicit and never re-labelled as demand.
- Finite capacity is converted to complete packs with `floor(capacity / pack_multiple)`.
- Seller stock is converted to complete packs with `floor(available_stock / pack_multiple)`.
- `UNLIMITED` capacity is not treated as a large synthetic integer.
- Missing/conflicting pack multiplicity, seller stock, volume or required physical evidence remains incomplete; do not silently default.
- Reuse the existing per-SKU allocation eligibility and priority. Do not add a portfolio/global objective.
- Keep legacy `optimize_allocations()` behavior regression-identical.
- No HTTP/frontend/export behavior belongs in PR-B.

---

## File Structure

- Modify `backend/supply/contracts.py` — whole-pack candidate/result contracts.
- Modify `backend/supply/optimizer.py` — extract shared eligibility/ranking helpers without changing legacy output.
- Create `backend/supply/shippable.py` — pure whole-pack operationalizer.
- Modify `backend/supply/__init__.py` — public exports.
- Create `backend/decision/shippable.py` — adapter to presentation-ready `ShippableLine` / SKU summaries.
- Modify `backend/decision/contracts.py` — operational presentation contracts only; do not mutate existing `DecisionRow` fields.
- Modify `backend/decision/__init__.py` — exports.
- Modify `tests/supply/test_optimizer.py` — legacy characterization around extracted ordering.
- Create `tests/supply/test_shippable.py` — multiplicity/capacity/stock conservation tests.
- Create `tests/decision/test_shippable.py` — adapter, aggregation and incompleteness tests.

---

### Task 1: Extract the current allocation policy without changing behavior

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

Create internal helpers used by both legacy pieces-allocation and PR-B pack allocation:

```python
def allocation_eligibility(
    candidate: PlacementAssessment,
    ceiling: int,
    thresholds: OptimizerThresholds,
    plan_family: PlanFamily,
) -> tuple[bool, set[str]]: ...


def sort_allocation_candidates(
    candidates: Iterable[PlacementAssessment],
    *,
    objective: AllocationObjective,
) -> list[PlacementAssessment]: ...
```

The ordering must remain exactly the current stable least-significant-first policy:

```text
stable cluster ID
larger eligible need
lower distortion risk
higher demand confidence
higher route confidence
then MAX_MARGIN margin_rate descending
(or MAX_PROFIT profit/unit for the legacy alternative)
```

- [ ] **Step 1: Add characterization test with at least four candidates**

Build candidates where each tie-break is exercised and assert the exact legacy `OptimizationResult.decisions` quantities before refactor.

- [ ] **Step 2: Run the characterization test and record GREEN baseline**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: current suite including the new characterization passes before code extraction.

- [ ] **Step 3: Extract helpers and make `optimize_allocations()` call them**

Do not alter `_ceiling()` or reason vocabulary. Preserve exact stable sorting semantics rather than replacing the sequence with arithmetic composite scores.

- [ ] **Step 4: Re-run optimizer tests**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

Expected: byte-for-business-output behavior remains unchanged for existing cases.

- [ ] **Step 5: Commit**

```bash
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share supply allocation policy"
```

---

### Task 2: Define whole-pack operational contracts

**Files:**
- Modify: `backend/supply/contracts.py`
- Create: `tests/supply/test_shippable.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class PackPlanCandidate:
    assessment: PlacementAssessment
    analytical_plan_qty: int

@dataclass(frozen=True, slots=True)
class PackAllocationDecision:
    sku: str
    cluster_id: str
    pack_multiple: int
    analytical_plan_qty: int
    desired_pack_count: int
    capacity_pack_count: int | None  # None only for explicit UNLIMITED
    allocation_pack_count: int
    shippable_qty: int
    rounding_delta_qty: int
    eligible: bool
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PackOptimizationResult:
    sku: str
    pack_multiple: int
    seller_available_qty: int
    seller_available_pack_count: int
    allocated_pack_count: int
    allocated_qty: int
    unshippable_remainder_qty: int
    decisions: tuple[PackAllocationDecision, ...]
    binding_reasons: tuple[str, ...]
```

Validation:

- `pack_multiple > 0` integer;
- `analytical_plan_qty >= 0`;
- all candidates are one SKU and unique clusters;
- `seller_available_qty >= 0`;
- output `shippable_qty == allocation_pack_count * pack_multiple`.

- [ ] **Step 1: Write contract validation tests**

Assert bools/non-integers/zero multiplicity fail; mixed SKU and duplicate cluster fail; negative quantities fail.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/supply/test_shippable.py -q
```

- [ ] **Step 3: Add dataclasses and validation**

Keep contracts immutable with `frozen=True, slots=True`, matching existing supply contracts.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/supply/test_shippable.py -q
git add backend/supply/contracts.py tests/supply/test_shippable.py
git commit -m "feat: define whole-pack supply contracts"
```

---

### Task 3: Implement whole-pack allocation

**Files:**
- Create: `backend/supply/shippable.py`
- Modify: `backend/supply/__init__.py`
- Modify: `tests/supply/test_shippable.py`

**Public interface:**

```python
def build_pack_plan(
    candidates: Iterable[PackPlanCandidate],
    *,
    seller_available_qty: int,
    pack_multiple: int,
    thresholds: OptimizerThresholds,
    objective: AllocationObjective = AllocationObjective.MAX_MARGIN,
) -> PackOptimizationResult: ...
```

The active product caller passes `MAX_MARGIN`; the objective parameter exists only to reuse exact legacy policy and test parity, not to create a new UI choice.

For each candidate:

```python
desired_packs = ceil_div(analytical_plan_qty, pack_multiple)
```

Physical pack ceiling:

```python
if capacity_kind is UNLIMITED:
    capacity_packs = None
elif capacity_kind is FINITE:
    capacity_packs = max_supply_qty // pack_multiple
else:
    candidate is blocked with CAPACITY_UNKNOWN
```

Effective pack ceiling:

```python
candidate_pack_ceiling = min(
    desired_packs,
    capacity_packs if capacity_packs is not None else desired_packs,
)
```

Global SKU pack pool:

```python
seller_available_packs = seller_available_qty // pack_multiple
unshippable_remainder = seller_available_qty % pack_multiple
```

Allocate complete packs in `sort_allocation_candidates(... MAX_MARGIN)` order.

- [ ] **Step 1: Add canonical rounding test**

```text
analytical Moscow = 17
pack_multiple = 6
seller stock = 100
capacity = unlimited
→ desired packs 3
→ shippable 18
→ rounding_delta +1
```

- [ ] **Step 2: Add finite-capacity floor test**

```text
analytical = 17
multiple = 6
finite capacity = 17
→ capacity packs = 2
→ shippable = 12
→ never 18
```

- [ ] **Step 3: Add seller-stock whole-pack test**

```text
seller stock = 20
multiple = 6
→ seller pack pool = 3
→ total positive allocation <= 18
→ unshippable remainder = 2
```

Use at least two clusters and assert the same higher-priority cluster wins as the legacy MAX_MARGIN ordering.

- [ ] **Step 4: Add zero/unknown/incomplete tests**

- analytical plan `0` → `0` packs;
- `FINITE(0)` → `0` packs + physical ceiling reason;
- UNKNOWN capacity → blocked, never treated unlimited;
- missing pack evidence is rejected before `build_pack_plan`, never encoded as `1`.

- [ ] **Step 5: Run RED**

```bash
python -m pytest tests/supply/test_shippable.py -q
```

- [ ] **Step 6: Implement minimal deterministic allocator**

Use integer pack counts only. Do not allocate pieces and then repair modulo afterward.

Reason codes must distinguish at minimum:

```text
PACK_MULTIPLE_APPLIED
ROUNDED_UP_TO_PACK
CAPACITY_PACK_FLOOR
SELLER_STOCK_PACK_LIMIT
SELLER_STOCK_REMAINDER
CAPACITY_UNKNOWN
ALLOCATED
```

Keep existing eligibility reason codes when the shared classifier blocks a candidate.

- [ ] **Step 7: Run GREEN and commit**

```bash
python -m pytest tests/supply/test_shippable.py tests/supply/test_optimizer.py -q
git add backend/supply/shippable.py backend/supply/__init__.py tests/supply/test_shippable.py
git commit -m "feat: allocate supply in whole packs"
```

---

### Task 4: Build presentation-ready shippable lines without changing AnalysisSnapshot

**Files:**
- Modify: `backend/decision/contracts.py`
- Create: `backend/decision/shippable.py`
- Modify: `backend/decision/__init__.py`
- Create: `tests/decision/test_shippable.py`

**Presentation contracts:**

```python
@dataclass(frozen=True, slots=True)
class ShippableLine:
    sku: str
    article: str
    product_name: str
    destination_cluster_id: str
    analytical_plan_qty: int
    pack_multiple: int
    shippable_qty: int
    rounding_delta_qty: int
    current_fbo_stock: int | None
    inbound_qty: int | None
    seller_available_stock: int
    unit_volume_l: Decimal
    total_volume_l: Decimal
    capacity_kind: str
    capacity_qty: int | None
    placement_zone_kind: str
    placement_zones: tuple[str, ...]
    expected_profit: Decimal | None
    confidence: SignalConfidence
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShippableSkuSummary:
    sku: str
    article: str
    product_name: str
    pack_multiple: int
    seller_available_stock: int
    seller_shippable_stock: int
    unit_volume_l: Decimal
    analytical_plan_qty: int
    shippable_qty: int
    cluster_count: int
    incomplete: bool
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShippablePlan:
    analysis_snapshot_id: str
    lines: tuple[ShippableLine, ...]
    sku_summaries: tuple[ShippableSkuSummary, ...]
    total_qty: int
    total_volume_l: Decimal
    incomplete_sku_count: int
```

Pure adapter signature:

```python
def assemble_shippable_plan(
    *,
    analysis_snapshot: AnalysisSnapshot,
    pack_results: Iterable[PackOptimizationResult],
    pack_by_article: Mapping[str, int],
    product_inputs_by_sku: Mapping[str, ProductEconomicsInput],
    cluster_facts: Mapping[tuple[str, str], ClusterSupplyFacts],
) -> ShippablePlan: ...
```

- [ ] **Step 1: Add identity/join tests**

Assert `DecisionRow.article` joins supplier multiplicity by article and product economics by SKU. A missing/conflicting mapping makes the affected SKU summary incomplete rather than borrowing another product's pack.

- [ ] **Step 2: Add exact volume tests**

```python
assert line.total_volume_l == line.unit_volume_l * line.shippable_qty
assert plan.total_volume_l == sum(x.total_volume_l for x in plan.lines)
```

Use `Decimal`; no float conversion.

- [ ] **Step 3: Add FBO/inbound preservation test**

The adapter copies `current_fbo_stock` and `inbound_qty` from the existing `DecisionRow` unchanged. It never subtracts them again.

- [ ] **Step 4: Add article aggregation test**

Multiple cluster lines for SKU `40750` produce one `ShippableSkuSummary` with one product name/article, summed operational qty and positive cluster count.

- [ ] **Step 5: Run RED, implement adapter, run GREEN**

```bash
python -m pytest tests/decision/test_shippable.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/decision/contracts.py backend/decision/shippable.py backend/decision/__init__.py tests/decision/test_shippable.py
git commit -m "feat: assemble operational shippable plan"
```

---

### Task 5: Full PR-B regression and invariant gate

**Files:** no new production files.

- [ ] **Step 1: Run supply + decision focused suites**

```bash
python -m pytest tests/supply/test_optimizer.py tests/supply/test_shippable.py tests/decision/test_shippable.py -q
```

- [ ] **Step 2: Run Product Completion acceptance unchanged**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Existing analytical plan values must remain unchanged because PR-B adds a downstream operational layer rather than replacing `DecisionRow.calculated_plan_qty`.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

- [ ] **Step 4: Verify invariants manually from test fixtures**

For every positive output line assert:

```python
line.shippable_qty % line.pack_multiple == 0
line.total_volume_l == line.unit_volume_l * line.shippable_qty
```

For each SKU:

```python
sum(line.shippable_qty for line in sku_lines) <= seller_available_stock
```

For each finite-capacity `SKU × cluster`:

```python
line.shippable_qty <= capacity_qty
```

No PR-C scheduling code belongs in this PR.