# PR-C Candidate Shipment Builder Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** build a pure deterministic bounded set of local shipment candidates from immutable ShippablePlan + user shipment intent, without calling Ozon or claiming timeslot availability.

## Global invariants

- Selected clusters are filter-only over ShippablePlan.
- No demand/seller-stock/economics reallocation.
- DIRECT hard max = 1 cluster.
- Multi-cluster cross-dock hard max = 20 clusters.
- Cross-dock requires a resolved handoff point and a resolved active seller warehouse.
- Seller warehouses come from current API source snapshot; handoff points come from process-memory HandoffPointStore.
- PVZ 1000 L is candidate-total estimated item volume, never per-line.
- Preserve exact `placement_zones` into candidates.
- Candidate generation is deterministic/bounded; no cluster-subset brute force.
- No network call in this PR.

---

## Task 1 — shipment intent and candidate contracts

Create `backend/shipment/contracts.py` + tests.

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
    seller_warehouse_id: int | None
    selected_handoff_point_ids: tuple[int, ...]

@dataclass(frozen=True, slots=True)
class MethodRule:
    method: ShipmentMethod
    hard_max_clusters: int
    requires_handoff_point: bool
    requires_seller_warehouse: bool
    preliminary_max_shipment_item_volume_l: Decimal | None

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
    placement_zones: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class CandidateShipment:
    candidate_id: str
    method: ShipmentMethod
    seller_warehouse_id: int | None
    handoff_point_id: int | None
    handoff_warehouse_type: str | None
    cluster_ids: tuple[str, ...]
    assignments: tuple[CandidateAssignment, ...]
    total_qty: int
    total_volume_l: Decimal
    reason_codes: tuple[str, ...]
```

Validate unique IDs, dates, positive preferred/max counts, preferred≤max and bool-as-int rejection.

Default rules:

```text
DIRECT: hard_max_clusters=1, no crossdock seller/handoff requirement
PVZ_CROSSDOCK: hard_max_clusters=20, seller warehouse + handoff required, max item volume=1000 L
SC_CROSSDOCK: hard_max_clusters=20, seller warehouse + handoff required
```

---

## Task 2 — filter-only shipment scope

Create pure `select_shipment_scope(plan, selected_cluster_ids)`.

Tests:
- selecting Moscow+Perm returns exact original line quantities;
- Kazan disappears without redistribution;
- selected lines never increase;
- no positive selected scope → `EMPTY_SHIPMENT_SCOPE`.

---

## Task 3 — resolve seller warehouse

Create `backend/shipment/seller_warehouse.py` + tests.

Resolution inputs:
- scenario `seller_warehouse_id`;
- current `OzonSourceSnapshot.seller_warehouses`.

Rules for cross-dock:

```text
0 active warehouses → SELLER_WAREHOUSE_UNAVAILABLE
1 active + scenario None → auto-resolve that one
>1 active + scenario None → SELLER_WAREHOUSE_REQUIRED
explicit unknown/inactive → SELLER_WAREHOUSE_INVALID
explicit active → use it
```

DIRECT returns no cross-dock seller warehouse and ignores the field for draft purposes.

Stable resolved record retains ID/name/address summary only.

---

## Task 4 — resolve handoff points from HandoffPointStore

Create `backend/shipment/handoff.py` + tests.

Do not read handoff points from source snapshot.

Resolve scenario IDs against PR-API2 process-memory store and preserve user priority order.

Rules:
- duplicate IDs rejected/normalized deterministically;
- unknown/stale ID → `HANDOFF_POINT_UNRESOLVED`;
- cross-dock with none → `HANDOFF_POINT_REQUIRED`;
- DIRECT ignores cross-dock point requirement;
- retain exact Ozon `warehouse_type` evidence for later draft payload.

No free-form frontend ID becomes trusted merely because it is syntactically integer.

---

## Task 5 — local compatibility rules

Create `backend/shipment/rules.py` + tests.

Line-level rules may inspect placement-zone evidence, but PVZ volume is checked only after candidate aggregation.

Conservative zone behavior:
- known compatible sortable/non-sortable evidence may remain candidate-eligible;
- KGT/UNKNOWN/MULTIPLE follows canonical conservative method rules;
- unknown evidence is not rewritten from dimensions;
- multiple zones remain preserved for later manual packing guidance.

Stable reason vocabulary includes e.g.:

```text
METHOD_CLUSTER_LIMIT
PVZ_PRELIMINARY_VOLUME_LIMIT
PLACEMENT_ZONE_UNSUPPORTED
PLACEMENT_ZONE_INCOMPLETE
SELLER_WAREHOUSE_REQUIRED
SELLER_WAREHOUSE_INVALID
HANDOFF_POINT_REQUIRED
HANDOFF_POINT_UNRESOLVED
```

---

## Task 6 — deterministic bounded grouping

Create `backend/shipment/candidates.py` + tests.

Public interface:

```python
def build_candidate_shipments(
    *,
    plan: ShippablePlan,
    scenario: ShipmentScenario,
    seller_warehouses,
    handoff_store,
    max_candidates: int = 12,
) -> tuple[CandidateShipment, ...]: ...
```

Strategy:

```text
1 filter selected positive ShippableLines
2 resolve seller warehouse/handoff requirements per method
3 derive urgency from existing analytical evidence only
4 stable-sort clusters urgent first + stable ID tie-break
5 greedily group up to min(user max, hard max)
6 preserve exact line whole-pack quantities
7 compute candidate total volume
8 if PVZ candidate total >1000 L, split/block deterministically; never pass because each line <1000
9 apply placement-zone method rules
10 fan out across selected handoff points only in user priority order
11 stop at max_candidates; never enumerate subsets
```

Candidate ID is stable fingerprint of immutable plan identity + method + seller warehouse + handoff + cluster IDs + SKU quantities.

Tests:
- repeat-run exact IDs/order;
- DIRECT=1;
- crossdock max 20 and user max lowering it;
- every line <1000 L but candidate aggregate >1000 L is blocked/split;
- whole-pack quantity conservation;
- multiple placement zones survive in assignments;
- two handoff points remain bounded;
- 20+ clusters stop at max candidates.

---

## Task 7 — local candidate API

Modify `backend/api.py`, create/modify `backend/shipment/wire.py`, add `tests/api/test_shipment_candidates.py`.

Endpoint:

```text
POST /api/shipment/candidates
```

Request contains immutable analysis/ShippablePlan identity + ShipmentScenario.

Backend:
- resolves current source snapshot seller warehouses;
- resolves handoff IDs from HandoffPointStore;
- validates `analysis_as_of`/snapshot identity;
- performs no OzonClient call.

Response contains local candidates only; no `timeslot`, `accepted_by_ozon`, `booked` or real-supply language.

Add no-network guard.

---

## Task 8 — regression/scale gate

Run:

```bash
python -m pytest tests/shipment tests/api/test_shipment_candidates.py -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Also run a realistic 100+ SKU / 20+ cluster fixture and assert bounded candidate count/time.

Acceptance: candidate generation is pure, deterministic, filter-only, whole-pack preserving, seller/handoff identities are resolved before external validation, PVZ 1000 L applies to candidate total, and placement-zone evidence remains available for manifests.