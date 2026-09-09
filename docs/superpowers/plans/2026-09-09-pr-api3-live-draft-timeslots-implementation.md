# PR-API3 Live Ozon Draft Validation & Timeslots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate a bounded set of local `CandidateShipment` objects with temporary Ozon drafts and retrieve current timeslots without creating a real supply request.

**Architecture:** `backend/ozon/supply_drafts.py` maps candidate method/cluster/handoff structure to the current direct/crossdock/multi-cluster draft endpoints. `DraftValidationService` owns rate budgets, ambiguous-create safety, polling and short-lived in-memory candidate-fingerprint cache. The service returns normalized `ValidatedShipmentOption` evidence; it never calls `/v2/draft/supply/create`.

**Tech Stack:** Python 3.13.14, existing OzonClient, frozen dataclasses, datetime/Decimal, pytest with fake transport; no real network in automated tests.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Temporary draft creation is allowed; real supply creation is forbidden.
- Never call deprecated generic `/v1/draft/create` for new work.
- Use current method-specific draft creation and `/v2/draft/create/info`, `/v2/draft/timeslot/info`.
- New draft calls are not blindly retried after ambiguous transport failure.
- `max_new_drafts_per_user_run = 6` by default and external Ozon rate budgets are enforced.
- Multi-cluster cross-dock ≤20 clusters; DIRECT=1.
- Timeslot window must obey the current Ozon API maximum; do not fabricate farther dates.
- Product rejection, no-slot, throttling, transport failure and unknown draft-create outcome are distinct.
- Returned timeslot is observed availability, not a booked supply slot.

---

### Task 1: Define draft-validation contracts and error vocabulary

**Files:**
- Create: `backend/ozon/draft_contracts.py`
- Create: `tests/ozon/test_draft_contracts.py`

**Interfaces:**

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
    draft_id: str | None
    state: ValidationState
    method: ShipmentMethod
    handoff_point_id: int | None
    accepted_assignments: tuple[CandidateAssignment, ...]
    rejected_assignments: tuple[OzonRejectedAssignment, ...]
    warehouse_evidence: tuple
    travel_time_days: int | None
    timeslots: tuple[OzonTimeslot, ...]
    checked_at_utc: str
    reason_codes: tuple[str, ...]
```

Stable high-level reasons:

```text
OZON_REJECTED_CANDIDATE
NO_TIMESLOT
OZON_RATE_LIMITED
OZON_UNAVAILABLE
DRAFT_CREATE_OUTCOME_UNKNOWN
```

- [ ] **Step 1: Add validation tests for accepted/rejected assignment conservation, ordered non-overlapping timeslots and valid checked timestamp.**
- [ ] **Step 2: Run RED, implement immutable contracts, run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_draft_contracts.py -q
git add backend/ozon/draft_contracts.py tests/ozon/test_draft_contracts.py
git commit -m "feat: define Ozon draft validation contracts"
```

---

### Task 2: Map candidates to current Ozon draft-create payloads

**Files:**
- Create: `backend/ozon/supply_drafts.py`
- Create: `tests/ozon/test_supply_drafts.py`

**Endpoint registry:**

```text
POST /v1/draft/crossdock/create
POST /v1/draft/direct/create
POST /v1/draft/multi-cluster/create
```

**Interfaces:**

```python
def build_draft_request(candidate: CandidateShipment) -> tuple[str, dict]: ...
def create_temporary_draft(client: OzonClient, candidate: CandidateShipment) -> str: ...
```

- [ ] **Step 1: Add payload fixture for DIRECT and assert one destination cluster, no cross-dock handoff misuse and exact candidate quantities.**
- [ ] **Step 2: Add single-cluster cross-dock fixture carrying the concrete selected `drop_off_point_warehouse_id`.**
- [ ] **Step 3: Add multi-cluster cross-dock fixture with ≤20 clusters and prove article/SKU quantities are unchanged.**
- [ ] **Step 4: Add source test ensuring no code path references deprecated `/v1/draft/create` or real `/v2/draft/supply/create`.**
- [ ] **Step 5: Run RED, implement payload mapper with `retry_safe=False`, run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_supply_drafts.py -q
git add backend/ozon/supply_drafts.py tests/ozon/test_supply_drafts.py
git commit -m "feat: create temporary Ozon supply drafts"
```

---

### Task 3: Poll draft creation info and normalize Ozon rejection evidence

**Files:**
- Modify: `backend/ozon/supply_drafts.py`
- Create: `tests/ozon/test_draft_polling.py`

**Interfaces:**

```python
def wait_for_draft_info(
    client: OzonClient,
    *,
    draft_id: str,
    candidate: CandidateShipment,
    timeout_seconds: float,
    poll_interval_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> ValidatedDraftInfo: ...
```

Endpoint:

```text
POST /v2/draft/create/info
```

- [ ] **Step 1: Add fake sequence `processing → ready` and assert bounded polling/timeout.**
- [ ] **Step 2: Add partial rejection fixture and preserve per-assignment code/message plus accepted assignments; do not silently drop rejected quantity.**
- [ ] **Step 3: Add Ozon business rejection vs 429/5xx transport tests; business rejection becomes validation evidence, transport error does not.**
- [ ] **Step 4: Add cancellation test between polls.**
- [ ] **Step 5: Run RED, implement polling/normalization, run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_draft_polling.py -q
git add backend/ozon/supply_drafts.py tests/ozon/test_draft_polling.py
git commit -m "feat: poll temporary Ozon draft status"
```

---

### Task 4: Fetch bounded timeslots and travel/warehouse evidence

**Files:**
- Modify: `backend/ozon/supply_drafts.py`
- Create: `tests/ozon/test_timeslots.py`

**Endpoint:**

```text
POST /v2/draft/timeslot/info
```

- [ ] **Step 1: Add valid requested date-range fixture and normalize timeslots to timezone-aware datetimes without changing their Ozon-local meaning.**
- [ ] **Step 2: Add no-timeslot fixture: valid draft + empty intervals → `NO_TIMESLOT`, not rejection.**
- [ ] **Step 3: Add range-over-limit test. Backend rejects/clamps according to explicit contract and never silently queries dates outside Ozon's current maximum window.**
- [ ] **Step 4: Preserve `travel_time_days` / warehouse evidence from draft info as optional evidence, never invent it.**
- [ ] **Step 5: Run RED, implement, run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_timeslots.py -q
git add backend/ozon/supply_drafts.py tests/ozon/test_timeslots.py
git commit -m "feat: fetch Ozon draft timeslots"
```

---

### Task 5: Add rate budget, ambiguous-create handling and temporary cache

**Files:**
- Create: `backend/ozon/draft_budget.py`
- Create: `backend/ozon/draft_cache.py`
- Create: `backend/ozon/validation.py`
- Create: `tests/ozon/test_draft_budget.py`
- Create: `tests/ozon/test_validation.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class DraftBudget:
    max_new_per_run: int = 6
    # tracks recent new-draft timestamps against current external limits

class DraftValidationService:
    def validate(
        self,
        candidates: Iterable[CandidateShipment],
        *,
        date_from: date,
        date_to: date,
    ) -> tuple[ValidatedShipmentOption, ...]: ...
```

Candidate fingerprint includes method, handoff ID, cluster IDs and exact assignment identities/quantities.

- [ ] **Step 1: Add max-new-per-run test with 10 candidates; at most 6 new draft creates occur and remainder has explicit budget/throttle evidence rather than disappearing.**
- [ ] **Step 2: Add sliding external budget tests matching the current method limits configured in one registry; budget code uses injectable clock.**
- [ ] **Step 3: Add short-lived cache test: same candidate fingerprint reuses still-valid temporary draft evidence; changed quantity/method/handoff invalidates fingerprint. Cache is memory-only.**
- [ ] **Step 4: Simulate timeout after POST bytes may have been sent; assert no automatic retry and state `OUTCOME_UNKNOWN`/reason `DRAFT_CREATE_OUTCOME_UNKNOWN`.**
- [ ] **Step 5: Simulate safe read-only info/timeslot 429 and prove bounded Retry-After behavior comes from OzonClient.**
- [ ] **Step 6: Run RED, implement budget/cache/service, run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_draft_budget.py tests/ozon/test_validation.py -q
git add backend/ozon/draft_budget.py backend/ozon/draft_cache.py backend/ozon/validation.py tests/ozon
git commit -m "feat: bound live Ozon draft validation"
```

---

### Task 6: Expose explicit live validation endpoint

**Files:**
- Modify: `backend/api.py`
- Modify: `backend/shipment/wire.py`
- Create: `tests/api/test_shipment_validate.py`

**Endpoint:**

```text
POST /api/shipment/validate
```

Request contains current source/analysis identity, current scenario date range, and backend-produced CandidateShipment wire objects. Endpoint requires unlocked vault.

- [ ] **Step 1: Add locked-vault rejection test with zero external calls.**
- [ ] **Step 2: Add candidate-tampering tests: quantity, method, handoff or snapshot mismatch is rejected before Ozon call.**
- [ ] **Step 3: Add success fixture returning accepted option/timeslots and partial/rejected/no-slot fixtures with stable causal state.**
- [ ] **Step 4: Add test proving response never says supply is created/booked and contains no secret headers.**
- [ ] **Step 5: Run RED, implement endpoint, run GREEN and commit.**

```bash
python -m pytest tests/api/test_shipment_validate.py -q
git add backend/api.py backend/shipment/wire.py tests/api/test_shipment_validate.py
git commit -m "feat: validate shipment candidates with Ozon"
```

---

### Task 7: PR-API3 safety/regression gate

- [ ] **Step 1: Run all Ozon draft tests.**

```bash
python -m pytest tests/ozon/test_supply_drafts.py tests/ozon/test_draft_polling.py tests/ozon/test_timeslots.py tests/ozon/test_draft_budget.py tests/ozon/test_validation.py -q
```

- [ ] **Step 2: Run shipment API tests.**

```bash
python -m pytest tests/api/test_shipment_candidates.py tests/api/test_shipment_validate.py -q
```

- [ ] **Step 3: Search production source for `/v2/draft/supply/create` and deprecated `/v1/draft/create`; both must be absent outside archived docs/tests that explicitly forbid them.**

- [ ] **Step 4: Run full suite.**

```bash
python -m pytest -q
```

Acceptance: app creates only bounded temporary drafts, finds current timeslots, preserves rejection/error causes, never blind-retries ambiguous create and never creates a real Ozon supply.
