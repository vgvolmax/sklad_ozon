# PR-API3 Live Ozon Draft Validation & Timeslots Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** validate bounded local `CandidateShipment` objects with temporary Ozon drafts and retrieve current timeslots, without creating a real supply request.

## Global invariants

- Temporary draft creation is allowed; real `/v2/draft/supply/create` is forbidden.
- Use only current method-specific draft endpoints plus `/v2/draft/create/info` and `/v2/draft/timeslot/info`.
- `draft_id` is integer/int64 identity.
- Draft-create requests are not blindly retried after ambiguous transport failure.
- Default max new drafts per user run = 6 plus external Ozon limits.
- DIRECT=1 cluster; multi-cluster cross-dock≤20.
- Cross-dock candidate already contains resolved active `seller_warehouse_id`, resolved handoff `warehouse_id` and exact Ozon `warehouse_type`.
- Product rejection, no slot, throttling, transport failure and unknown create outcome stay distinct.
- Observed timeslot is not a booking.

---

## Task 1 — immutable validation contracts

Create `backend/ozon/draft_contracts.py` + tests.

```python
class ValidationState(str, Enum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    REJECTED = "rejected"
    NO_TIMESLOT = "no_timeslot"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"

@dataclass(frozen=True, slots=True)
class OzonRejectedAssignment:
    sku: str
    article: str
    destination_cluster_id: str
    quantity: int
    code: str
    message: str

@dataclass(frozen=True, slots=True)
class OzonTimeslot:
    from_dt: datetime
    to_dt: datetime

@dataclass(frozen=True, slots=True)
class ValidatedShipmentOption:
    candidate_id: str
    draft_id: int | None
    state: ValidationState
    method: ShipmentMethod
    seller_warehouse_id: int | None
    handoff_point_id: int | None
    accepted_assignments: tuple[CandidateAssignment, ...]
    rejected_assignments: tuple[OzonRejectedAssignment, ...]
    warehouse_evidence: tuple
    travel_time_days: int | None
    timeslots: tuple[OzonTimeslot, ...]
    checked_at_utc: str
    reason_codes: tuple[str, ...]
```

Reject bool-as-int, non-positive invalid draft IDs and malformed timeslots.

Stable high-level reasons:

```text
OZON_REJECTED_CANDIDATE
NO_TIMESLOT
OZON_RATE_LIMITED
OZON_UNAVAILABLE
DRAFT_CREATE_OUTCOME_UNKNOWN
```

---

## Task 2 — exact candidate→draft payload mapping

Create `backend/ozon/supply_drafts.py` + tests.

Endpoints:

```text
POST /v1/draft/crossdock/create
POST /v1/draft/direct/create
POST /v1/draft/multi-cluster/create
```

### DIRECT

Use one `cluster_info`, exact candidate SKU quantities, no cross-dock `delivery_info`.

### single-cluster cross-dock

Payload must include:

```text
cluster_info
items exact from candidate
delivery_info:
  seller_warehouse_id = candidate.seller_warehouse_id
  drop_off_warehouse:
    warehouse_id = candidate.handoff_point_id
    warehouse_type = candidate.handoff_warehouse_type
```

### multi-cluster cross-dock

Use `clusters_info` (≤20) and the same resolved `delivery_info` contract.

Never invent warehouse type from UI labels; use PR-API2 search evidence preserved by PR-C.

Do not modify quantities, article/SKU identity or cluster assignment during payload mapping.

Client policy for create = `retry_safe=False`.

Source guard tests must prove active code does not call deprecated generic `/v1/draft/create` and does not reference real `/v2/draft/supply/create`.

---

## Task 3 — normalize immediate create response and draft ID

Current method-specific create calls return integer `draft_id` and may return errors immediately.

Normalize:
- valid positive `draft_id: int`;
- immediate rejected-item/error evidence;
- ambiguous transport failure → `DRAFT_CREATE_OUTCOME_UNKNOWN`, no automatic retry.

If Ozon returns an invalid/non-positive ID when a valid draft is required, surface normalized invalid-response error rather than stringifying it.

---

## Task 4 — fetch `/v2/draft/create/info`

Poll/fetch current draft information using integer draft ID.

Normalize:
- accepted/rejected SKU evidence;
- per-cluster available storage warehouses/scoring;
- travel-time evidence;
- terminal/in-progress/failure status;
- causal errors.

Bound polling by attempts/deadline and cancellation. No infinite loop.

Conservation tests:

```text
accepted qty + rejected/unavailable qty
reconciles to candidate input qty
```

Partial acceptance remains PARTIAL and retains rejected rows.

---

## Task 5 — choose eligible storage warehouse evidence and fetch `/v2/draft/timeslot/info`

Endpoint:

```text
POST /v2/draft/timeslot/info
```

Build request only from Ozon-returned valid storage warehouse evidence.

Use:

```text
draft_id: int
supply_type: CROSSDOCK | DIRECT | MULTI_CLUSTER
selected_cluster_warehouses[]
date_from/date_to
```

Date range is user intent clamped/rejected to current Ozon maximum (28 days from current date under reviewed contract). Never fabricate farther availability.

Normalize ordered timeslots and observed warehouse timezone evidence.

No slots in requested range → `NO_TIMESLOT`, not product rejection.

---

## Task 6 — bounded validation service and cache

Create `DraftValidationService` + tests.

Responsibilities:
- maximum 6 newly created temporary drafts per explicit user run by default;
- external minute/hour/day budget accounting;
- deterministic candidate order from PR-C;
- short-lived process-memory cache keyed by candidate fingerprint while draft evidence is still valid;
- cache never survives restart;
- rate-limit state returned causally, not as generic unavailable;
- ambiguous create outcome never retried automatically;
- cancellation between candidates/poll calls.

The service may return fewer validated options when external budget is insufficient.

---

## Task 7 — local validation endpoint

Modify `backend/api.py`, shipment wire/service code, add `tests/api/test_shipment_validate.py`.

Endpoint:

```text
POST /api/shipment/validate
```

Request references backend-produced candidate IDs/fingerprints and immutable parent source/analysis/ShippablePlan identity. Do not accept arbitrary client-crafted quantities as authoritative candidates.

Validate:
- source/analysis identity still matches;
- seller warehouse remains active in parent snapshot for cross-dock;
- handoff point remains resolved in backend HandoffPointStore;
- vault unlocked;
- scenario fingerprint unchanged.

Response contains `ValidatedShipmentOption[]` with temporary-draft evidence only.

No real-supply success fields/copy.

---

## Task 8 — regression and safety gate

Tests must cover:
- `draft_id` int contract and bool/string rejection;
- DIRECT payload;
- crossdock payload with both `seller_warehouse_id` and `drop_off_warehouse`;
- multi-cluster ≤20 payload;
- stale/invalid seller warehouse rejected before external create;
- stale handoff point rejected before external create;
- immediate Ozon rejection;
- partial acceptance;
- no slot;
- 429 budget behavior;
- transport unavailable;
- ambiguous create outcome with exactly one create attempt;
- no reference/call to `/v2/draft/supply/create`;
- quantity/identity conservation.

Run:

```bash
python -m pytest tests/ozon/test_draft_contracts.py tests/ozon/test_supply_drafts.py tests/ozon/test_draft_polling.py -q
python -m pytest tests/api/test_shipment_validate.py -q
python -m pytest tests/shipment tests/api/test_shipment_candidates.py -q
python -m pytest -q
```

Acceptance: bounded temporary draft validation uses exact resolved seller/handoff identities, current v2 info/timeslot flow, integer draft IDs and never creates a real Ozon supply request.