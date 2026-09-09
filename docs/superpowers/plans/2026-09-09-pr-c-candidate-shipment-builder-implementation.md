# PR-C Candidate Shipment Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure deterministic, bounded set of shipment candidates from the immutable `ShippablePlan` and user shipment intent, without calling Ozon or claiming timeslot availability.

**Architecture:** A new `backend/shipment` domain owns scenario, method rules, hand-off point selection and candidate grouping. The builder filters the already-calculated all-cluster `ShippablePlan`, applies local hard rules/whole-pack/volume/zone checks and emits a small ordered candidate set for PR-API3 to validate externally. No demand, seller-stock or route-economic reallocation occurs.

**Tech Stack:** Python 3.13.14, frozen dataclasses, Decimal, pytest; no network and no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Selected clusters are filter-only over `ShippablePlan`.
- Do not move quantity from unselected to selected clusters.
- Do not call Ozon from the candidate builder.
- DIRECT hard max = 1 cluster.
- Multi-cluster cross-dock hard max = 20 clusters; user max may only lower this.
- Cross-dock requires at least one concrete selected Ozon hand-off point ID.
- Local PVZ/item-volume checks are preliminary only.
- No RouteCostIndex or seller→Ozon cost optimization.
- Every candidate keeps complete-pack quantities.
- Candidate generation is deterministic and bounded; no subset brute force.

---

### Task 1: Define shipment intent, method and candidate contracts

**Files:**
- Create: `backend/shipment/__init__.py`
- Create: `backend/shipment/contracts.py`
- Create: `tests/shipment/test_contracts.py`

**Interfaces:**

```python
class ShipmentMethod(str, Enum):
    PVZ_CROSSDOCK = "pvz_crossdock"
    SC_CROSSDOCK = "sc_crossdock"
    DIRECT = "direct"

@dataclass(frozen=True, slots=True)
class ShipmentScenario:
    selected_cluster_ids: tuple[str, ...]
    date_from: date
    date_to: date
    allowed_methods: tuple[ShipmentMethod, ...]
    preferred_clusters_per_shipment: int
    max_clusters_per_shipment: int
    selected_handoff_point_ids: tuple[int, ...]

@dataclass(frozen=True, slots=True)
class MethodRule:
    method: ShipmentMethod
    hard_max_clusters: int
    requires_handoff_point: bool
    preliminary_max_item_volume_l: Decimal | None

@dataclass(frozen=True, slots=True)
class CandidateAssignment:
    sku: str
    article: str
    destination_cluster_id: str
    quantity: int
    pack_multiple: int
    unit_volume_l: Decimal
    total_volume_l: Decimal
    placement_zone_kind: str

@dataclass(frozen=True, slots=True)
class CandidateShipment:
    candidate_id: str
    method: ShipmentMethod
    handoff_point_id: int | None
    cluster_ids: tuple[str, ...]
    assignments: tuple[CandidateAssignment, ...]
    total_qty: int
    total_volume_l: Decimal
    reason_codes: tuple[str, ...]
```

- [ ] **Step 1: Add validation tests for nonempty selected clusters/methods, date order, positive preferred/max cluster counts, preferred≤max, unique IDs and valid hand-off IDs.**
- [ ] **Step 2: Add method-rule tests proving DIRECT=1 and cross-dock≤20 are backend hard rules.**
- [ ] **Step 3: Run RED, implement contracts and default rule registry, run GREEN.**

```bash
python -m pytest tests/shipment/test_contracts.py -q
```

- [ ] **Step 4: Commit.**

```bash
git add backend/shipment tests/shipment/test_contracts.py
git commit -m "feat: define shipment candidate contracts"
```

---

### Task 2: Build filter-only selected shipment scope

**Files:**
- Create: `backend/shipment/scope.py`
- Create: `tests/shipment/test_scope.py`

**Interfaces:**

```python
def select_shipment_scope(plan: ShippablePlan, selected_cluster_ids: Iterable[str]) -> tuple[ShippableLine, ...]: ...
```

- [ ] **Step 1: Add three-cluster fixture and assert selecting Moscow+Perm returns exact original line quantities and no Kazan lines.**
- [ ] **Step 2: Assert no selected line quantity increases relative to the all-cluster plan and total seller-stock allocation is not recomputed.**
- [ ] **Step 3: Add empty/no-positive scope validation with stable reason `EMPTY_SHIPMENT_SCOPE`.**
- [ ] **Step 4: Run RED, implement simple identity filter, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_scope.py -q
git add backend/shipment/scope.py tests/shipment/test_scope.py
git commit -m "feat: select filter-only shipment scope"
```

---

### Task 3: Resolve selected hand-off points against API catalog

**Files:**
- Create: `backend/shipment/handoff.py`
- Create: `tests/shipment/test_handoff.py`

**Interfaces:**

```python
def resolve_handoff_points(
    selected_ids: Iterable[int],
    catalog: Iterable[HandoffPoint],
) -> tuple[HandoffPoint, ...]: ...
```

- [ ] **Step 1: Add tests for selected point resolution, unknown/stale ID, duplicate IDs and stable user order.**
- [ ] **Step 2: Prove cross-dock candidate generation cannot proceed without a resolved compatible hand-off point; DIRECT ignores cross-dock point requirement.**
- [ ] **Step 3: Run RED, implement, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_handoff.py -q
git add backend/shipment/handoff.py tests/shipment/test_handoff.py
git commit -m "feat: resolve Ozon handoff points"
```

---

### Task 4: Implement deterministic local candidate compatibility

**Files:**
- Create: `backend/shipment/rules.py`
- Create: `tests/shipment/test_rules.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class LocalCompatibility:
    compatible: bool
    reason_codes: tuple[str, ...]


def check_local_compatibility(line: ShippableLine, method: ShipmentMethod, rule: MethodRule) -> LocalCompatibility: ...
```

- [ ] **Step 1: Add DIRECT tests: one destination cluster only, no cross-dock handoff dependency.**
- [ ] **Step 2: Add PVZ preliminary tests: known sortable/non-sortable evidence may pass local pre-check; KGT/UNKNOWN/MULTIPLE follows the canonical conservative rule and never displays as confirmed acceptance.**
- [ ] **Step 3: Add item-volume test where candidate clearly exceeds configured planning ceiling and is locally blocked; passing ceiling yields only preliminary compatibility.**
- [ ] **Step 4: Add exact reason codes (`METHOD_CLUSTER_LIMIT`, `PVZ_PRELIMINARY_VOLUME_LIMIT`, `PLACEMENT_ZONE_UNSUPPORTED`, etc.).**
- [ ] **Step 5: Run RED, implement pure rules, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_rules.py -q
git add backend/shipment/rules.py tests/shipment/test_rules.py
git commit -m "feat: add local shipment compatibility rules"
```

---

### Task 5: Implement bounded candidate grouping

**Files:**
- Create: `backend/shipment/candidates.py`
- Modify: `backend/shipment/__init__.py`
- Create: `tests/shipment/test_candidates.py`

**Public interface:**

```python
def build_candidate_shipments(
    *,
    plan: ShippablePlan,
    scenario: ShipmentScenario,
    handoff_points: Iterable[HandoffPoint],
    max_candidates: int = 12,
) -> tuple[CandidateShipment, ...]: ...
```

Deterministic strategy:

```text
1. filter selected positive ShippableLines only
2. derive urgency key from existing current_weekly_rate/FBO/inbound evidence where complete
3. order clusters urgent first; stable ID tie-break
4. for each allowed method in stable scenario order, pack clusters greedily up to min(user max, method hard max)
5. aim for preferred cluster count before opening another candidate when feasible
6. respect preliminary item-volume/zone rules
7. cross-dock candidates fan out only across explicitly selected hand-off points in user priority order
8. stop at max_candidates; never enumerate subsets
```

- [ ] **Step 1: Add deterministic fixture and assert exact candidate IDs/order for repeated runs. Candidate ID is a stable hash/fingerprint of method, handoff, cluster IDs and assignment quantities—not Python object identity.**
- [ ] **Step 2: Add cluster-limit tests for DIRECT=1, user max 5 and hard cross-dock 20.**
- [ ] **Step 3: Add split test where volume forces two whole-pack candidates without modifying line quantity.**
- [ ] **Step 4: Add hand-off priority fixture with two selected points and prove output stays bounded rather than multiplying every combinatorial option.**
- [ ] **Step 5: Add max-candidates fixture with 20+ clusters and assert builder stops deterministically at the configured bound.**
- [ ] **Step 6: Run RED, implement greedy bounded builder, run GREEN.**

```bash
python -m pytest tests/shipment/test_candidates.py -q
```

- [ ] **Step 7: Commit.**

```bash
git add backend/shipment/candidates.py backend/shipment/__init__.py tests/shipment/test_candidates.py
git commit -m "feat: build bounded shipment candidates"
```

---

### Task 6: Add local candidate endpoint without external validation

**Files:**
- Modify: `backend/api.py`
- Create: `backend/shipment/wire.py`
- Create: `tests/api/test_shipment_candidates.py`

**Endpoint:**

```text
POST /api/shipment/candidates
```

Request contains immutable `analysis_snapshot_id`/`ShippablePlan` identity plus `ShipmentScenario`. Backend resolves hand-off IDs from the source snapshot catalog.

- [ ] **Step 1: Add strict request parsing tests rejecting unknown methods, bool-as-int, duplicate IDs, stale source/snapshot identity and cross-dock with no selected hand-off point.**
- [ ] **Step 2: Add positive API fixture and assert endpoint returns local candidates only; response has no `timeslot`, `accepted_by_ozon` or booked language.**
- [ ] **Step 3: Add no-network guard proving this endpoint never invokes OzonClient.**
- [ ] **Step 4: Run RED, implement endpoint, run GREEN and commit.**

```bash
python -m pytest tests/api/test_shipment_candidates.py -q
git add backend/api.py backend/shipment/wire.py tests/api/test_shipment_candidates.py
git commit -m "feat: expose local shipment candidates"
```

---

### Task 7: PR-C regression and scale gate

- [ ] **Step 1: Run shipment candidate suites.**

```bash
python -m pytest tests/shipment tests/api/test_shipment_candidates.py -q
```

- [ ] **Step 2: Run realistic 100+ SKU / 20+ cluster fixture and assert bounded candidate count/time without subset explosion.**
- [ ] **Step 3: Run analysis/Product Completion regressions.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 4: Run full suite.**

```bash
python -m pytest -q
```

Acceptance: candidate generation is pure, bounded, deterministic, filter-only and honest about being unvalidated by Ozon.
