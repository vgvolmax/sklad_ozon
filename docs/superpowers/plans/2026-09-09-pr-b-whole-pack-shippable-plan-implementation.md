# PR-B Whole-Pack Shippable Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing all-cluster Calculated Plan into an immutable whole-pack `ShippablePlan` using the already-resolved seller stock, supplier multiplicity and canonical unit volume, without changing analytical demand or allocation semantics.

**Architecture:** Preserve existing `optimize_allocations()` and current `AnalysisSnapshot`. Extract/reuse its deterministic per-SKU eligibility/priority as needed, but do not create a new seller-stock resolver. The operationalizer works in integer pack counts over the full analytical cluster set; later shipment cluster selection is filter-only and never reallocates quantities.

**Tech Stack:** Python 3.13.14, frozen dataclasses, Decimal, pytest; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Do not change DemandEstimate, Need, stockout, Flow, economics, Safe or Calculated analytical values.
- Consume the exact seller quantity already resolved by current analytical runtime.
- Positive operational quantity must be a complete pack multiple.
- Seller stock and desired quantity are handled in whole packs, never allocate pieces then repair modulo.
- Product volume remains `ProductEconomicsInput.volume_liters`.
- Build once across all clusters; selected shipment scope later only filters.
- In API mode, do not pre-cut future quantities using stale restrictions capacity; Ozon live draft is later final acceptance authority.
- FILES fallback may expose dated conservative physical blockers separately, but must not silently redefine analytical quantity.

---

### Task 1: Expose exact existing resolved seller-stock evidence

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/decision/contracts.py`
- Modify: `backend/decision/snapshot.py`
- Modify: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**

Append a backwards-safe immutable presentation field owned by analysis, for example:

```python
@dataclass(frozen=True, slots=True)
class ResolvedSellerStock:
    sku: str
    quantity: int | None
    complete: bool
    reason_codes: tuple[str, ...]
```

`AnalysisSnapshot` carries a bounded tuple/map of these resolved values.

- [ ] **Step 1: Characterize current seller-stock resolver with FBS positive, explicit zero, conflicting positives, no FBS + ProductEconomics fallback, and authoritative missing cases.**
- [ ] **Step 2: Assert current allocation outputs before adding the field.**
- [ ] **Step 3: Add the immutable resolved-stock field at the point where current runtime has already made the decision; do not duplicate its resolver.**
- [ ] **Step 4: Re-run characterization and prove all existing Calculated allocations are byte/business-equivalent except the additive presentation field.**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py tests/supply/test_optimizer.py -q
```

- [ ] **Step 5: Commit.**

```bash
git add backend/application.py backend/decision/contracts.py backend/decision/snapshot.py tests/api/test_product_completion_acceptance.py
git commit -m "refactor: expose resolved seller stock"
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
    allocation_pack_count: int
    shippable_qty: int
    rounding_delta_qty: int
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PackOptimizationResult:
    sku: str
    pack_multiple: int
    seller_available_qty: int
    seller_available_pack_count: int
    allocated_pack_count: int
    allocated_qty: int
    seller_remainder_qty: int
    decisions: tuple[PackAllocationDecision, ...]
    reason_codes: tuple[str, ...]
```

- [ ] **Step 1: Add contract validation tests: positive integer multiplicity, nonnegative quantities, one SKU, unique cluster IDs, bool rejected where int required.**
- [ ] **Step 2: Run RED, implement immutable contracts, run GREEN.**

```bash
python -m pytest tests/supply/test_shippable.py -q
```

- [ ] **Step 3: Commit.**

```bash
git add backend/supply/contracts.py tests/supply/test_shippable.py
git commit -m "feat: define whole-pack plan contracts"
```

---

### Task 3: Reuse current allocation eligibility/priority without changing legacy output

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `tests/supply/test_optimizer.py`

**Interfaces:**

Extract internal helpers with the exact current lexicographic policy, for example:

```python
def allocation_eligibility(candidate, ceiling, thresholds, plan_family) -> tuple[bool, set[str]]: ...
def sort_allocation_candidates(candidates, *, objective) -> list: ...
```

- [ ] **Step 1: Add a four-plus candidate characterization fixture exercising margin, route confidence, demand confidence, distortion, need and stable cluster tie-breaks.**
- [ ] **Step 2: Run GREEN before refactor and record exact legacy decision quantities/order.**
- [ ] **Step 3: Extract helpers and make existing `optimize_allocations()` use them without altering reason vocabulary/ordering.**
- [ ] **Step 4: Re-run all optimizer tests and commit only if outputs are unchanged.**

```bash
python -m pytest tests/supply/test_optimizer.py -q
git add backend/supply/optimizer.py tests/supply/test_optimizer.py
git commit -m "refactor: share allocation priority"
```

---

### Task 4: Implement integer-pack allocation across the full cluster set

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

Rules:

```text
desired_packs = ceil(analytical_plan_qty / pack_multiple)
seller_available_packs = seller_available_qty // pack_multiple
seller_remainder = seller_available_qty % pack_multiple
```

Allocate integer packs in current per-SKU priority order until seller pack pool is exhausted.

- [ ] **Step 1: Add canonical rounding test `17, multiple 6 → 18` with ample seller stock.**
- [ ] **Step 2: Add shared-stock test: seller stock 20, multiple 6, two clusters → total allocation ≤18 and remainder=2; higher-priority cluster receives packs first.**
- [ ] **Step 3: Add zero analytical plan, zero stock and missing-pack precondition tests.**
- [ ] **Step 4: Add all-cluster immutability test: running on three clusters produces fixed decisions; filtering one cluster afterward must not increase another line.**
- [ ] **Step 5: Run RED, implement minimal integer allocator, run GREEN.**

```bash
python -m pytest tests/supply/test_shippable.py tests/supply/test_optimizer.py -q
```

- [ ] **Step 6: Commit.**

```bash
git add backend/supply/shippable.py backend/supply/__init__.py tests/supply/test_shippable.py
git commit -m "feat: allocate supply in whole packs"
```

---

### Task 5: Assemble presentation-ready ShippablePlan

**Files:**
- Modify: `backend/decision/contracts.py`
- Create: `backend/decision/shippable.py`
- Modify: `backend/decision/__init__.py`
- Create: `tests/decision/test_shippable.py`

**Interfaces:**

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
    current_weekly_rate: Decimal | None
    current_fbo_stock: int | None
    inbound_qty: int | None
    seller_available_stock: int
    unit_volume_l: Decimal
    total_volume_l: Decimal
    placement_zone_kind: str
    placement_zones: tuple[str, ...]
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShippableSkuSummary: ...

@dataclass(frozen=True, slots=True)
class ShippablePlan:
    analysis_snapshot_id: str
    analysis_as_of: date
    lines: tuple[ShippableLine, ...]
    sku_summaries: tuple[ShippableSkuSummary, ...]
    total_qty: int
    total_volume_l: Decimal
    incomplete_sku_count: int
```

- [ ] **Step 1: Add join tests linking DecisionRow by SKU/article to `ProductPackFacts`, resolved stock, ProductEconomics volume and normalized SupplyFacts.**
- [ ] **Step 2: Prove FBO/inbound/current weekly rate are copied unchanged; they are not subtracted again.**
- [ ] **Step 3: Prove `total_volume_l = unit_volume_l × shippable_qty` with Decimal and plan totals exactly sum lines.**
- [ ] **Step 4: Prove one SKU with many clusters yields one summary and one product identity, while missing pack/volume/stock marks only that SKU incomplete.**
- [ ] **Step 5: Implement adapter and run focused tests.**

```bash
python -m pytest tests/decision/test_shippable.py -q
```

- [ ] **Step 6: Commit.**

```bash
git add backend/decision/contracts.py backend/decision/shippable.py backend/decision/__init__.py tests/decision/test_shippable.py
git commit -m "feat: assemble whole-pack shippable plan"
```

---

### Task 6: Attach ShippablePlan to analysis without changing upstream fields

**Files:**
- Modify: `backend/api.py`
- Modify: `backend/decision/contracts.py`
- Modify: `tests/api/test_analysis.py`

- [ ] **Step 1: Add fixture where analytical `17` + multiple `6` returns analytical 17 and operational 18 simultaneously.**
- [ ] **Step 2: Add missing packaging/stock fixture proving analytical snapshot still succeeds while operational readiness is incomplete.**
- [ ] **Step 3: Wire pack/supply inputs after existing analytical allocation; do not move operational formulas into serialization/frontend.**
- [ ] **Step 4: Run API acceptance and commit.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
git add backend/api.py backend/decision/contracts.py tests/api/test_analysis.py
git commit -m "feat: attach shippable plan to analysis"
```

---

### Task 7: PR-B invariant gate

- [ ] **Step 1: Run focused suites.**

```bash
python -m pytest tests/supply/test_optimizer.py tests/supply/test_shippable.py tests/decision/test_shippable.py -q
```

- [ ] **Step 2: Run Product Completion/API regressions.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 3: Run full suite.**

```bash
python -m pytest -q
```

Acceptance for every positive line:

```text
shippable_qty % pack_multiple == 0
total_volume_l == unit_volume_l * shippable_qty
sum(SKU lines) <= existing resolved seller stock
selected shipment scope has not participated in allocation
```
