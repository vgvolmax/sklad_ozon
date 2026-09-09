# PR-C Shipment Batching & Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn whole-pack `ShippableLine`s into an explainable recommended shipment calendar using operator-selected clusters, dates, methods, cluster-count limits, volume rules and demand urgency.

**Architecture:** Add a dependency-free scheduling core under `backend/shipment/`. The core knows nothing about HTTP or XLSX; it consumes immutable shippable lines plus explicit shipment opportunities and one centralized method-rule registry. Scheduling is a bounded deterministic heuristic, not live Ozon slot discovery and not a general optimization solver.

**Tech Stack:** Python 3, frozen dataclasses/enums, `date`, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Global Constraints

- No Ozon Seller API call belongs in PR-C.
- A scheduled date is a recommendation, never a confirmed/booked slot.
- Only selected destination clusters participate in the current shipment run.
- Selecting clusters never rewrites upstream demand or another cluster's analytical need.
- Every scheduled quantity stays divisible by its SKU pack multiple.
- One line may split across opportunities only in whole packs.
- Product volume is the existing canonical `ProductEconomicsInput.volume_liters` propagated through `ShippableLine`.
- PVZ V1 total planned volume ceiling defaults to `1000 L`; actual point capacity may be lower and remains a manual Ozon check.
- V1 does not claim validation of box count, per-box weight, pallet count or a live point's slot capacity.
- KGT and unknown/multiple placement-zone evidence are not auto-assigned to PVZ.
- Inbound quantity has no ETA in the current availability source. It MUST NOT move the depletion date later by itself. Preserve it as evidence/warning only unless a future source supplies arrival timing.
- Unknown weekly demand rate or current FBO stock yields unknown urgency; never invent a distant date.
- Missing lead days for a method that requires transit means date safety is incomplete; do not label the recommendation `safe`.
- Determinism is required: same inputs produce same shipment IDs/order/quantities.
- No frontend/API/export change belongs in PR-C.

---

## File Structure

- Create `backend/shipment/__init__.py` — public shipment-planning surface.
- Create `backend/shipment/contracts.py` — methods, opportunities, urgency, scheduled/unscheduled result contracts.
- Create `backend/shipment/rules.py` — centralized/versioned method compatibility and physical caps.
- Create `backend/shipment/urgency.py` — depletion/latest-ship derivation from existing evidence.
- Create `backend/shipment/scheduler.py` — deterministic whole-pack batching algorithm.
- Create `tests/shipment/test_rules.py` — method/zone/volume policy tests.
- Create `tests/shipment/test_urgency.py` — FBO/rate/inbound timing tests.
- Create `tests/shipment/test_scheduler.py` — date, capacity, cluster-count, split, late/unscheduled and determinism tests.

---

### Task 1: Define shipment scenario contracts

**Files:**
- Create: `backend/shipment/contracts.py`
- Create: `tests/shipment/test_scheduler.py`

**Interfaces:**

```python
class ShipmentMethod(str, Enum):
    PVZ_CROSSDOCK = "pvz_crossdock"
    SC_CROSSDOCK = "sc_crossdock"
    DIRECT = "direct"

class ScheduleStatus(str, Enum):
    ON_TIME = "on_time"
    LATE = "late"
    DATE_QUALITY_INCOMPLETE = "date_quality_incomplete"
    UNSCHEDULED = "unscheduled"

@dataclass(frozen=True, slots=True)
class ShipmentOpportunity:
    opportunity_id: str
    ship_date: date
    method: ShipmentMethod
    max_clusters: int
    max_volume_l: Decimal | None
    lead_days: int | None
    enabled: bool = True

@dataclass(frozen=True, slots=True)
class ShipmentScenario:
    selected_cluster_ids: tuple[str, ...]
    opportunities: tuple[ShipmentOpportunity, ...]
```

Validation:

- IDs and selected clusters are nonblank and unique;
- `max_clusters >= 1`;
- finite `max_volume_l > 0`;
- `lead_days >= 0` when present;
- at least one enabled opportunity is not required for parsing, but scheduling with none returns explicit unscheduled lines.

- [ ] **Step 1: Write validation tests**

Cover duplicate selected clusters/opportunity IDs, bool-as-int rejection, zero/negative max clusters, non-finite/zero volume and negative lead days.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/shipment/test_scheduler.py -q
```

- [ ] **Step 3: Implement immutable contracts**

Use frozen dataclasses and existing project validation style.

- [ ] **Step 4: Run GREEN and commit**

```bash
python -m pytest tests/shipment/test_scheduler.py -q
git add backend/shipment/contracts.py tests/shipment/test_scheduler.py
git commit -m "feat: define shipment schedule contracts"
```

---

### Task 2: Centralize V1 hand-off method rules

**Files:**
- Create: `backend/shipment/rules.py`
- Create: `tests/shipment/test_rules.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ShipmentMethodRule:
    method: ShipmentMethod
    default_max_volume_l: Decimal | None
    allowed_zone_kinds: tuple[str, ...]
    allowed_zone_labels: tuple[str, ...]
    requires_lead_days_for_safe_date: bool
    manual_checks: tuple[str, ...]
    evidence_reviewed_at: str
    evidence_reference: str


def default_method_rules() -> dict[ShipmentMethod, ShipmentMethodRule]: ...


def resolve_effective_volume_limit(
    opportunity: ShipmentOpportunity,
    rule: ShipmentMethodRule,
) -> Decimal | None: ...


def method_compatibility(
    line: ShippableLine,
    opportunity: ShipmentOpportunity,
    rule: ShipmentMethodRule,
) -> tuple[bool, tuple[str, ...]]: ...
```

PVZ default rule:

```python
default_max_volume_l = Decimal("1000")
requires_lead_days_for_safe_date = True
```

If the operator provides `max_volume_l = 500`, effective PVZ max is `500`, not `1000`. If they enter a value above 1000, effective cap remains 1000 in V1.

PVZ zone behavior:

- KNOWN sortable/non-sortable source labels may pass;
- KGT label is blocked;
- MULTIPLE or UNKNOWN zone evidence is blocked from automatic PVZ assignment;
- explicit restriction/capacity infeasibility has already removed the line upstream.

SC/direct V1 do not gain fabricated hard volume caps from this PR; user opportunity caps may still be provided and enforced.

- [ ] **Step 1: Add PVZ 1000 L/default override tests**

Assert effective limits:

```text
PVZ + no explicit max -> 1000
PVZ + 500 -> 500
PVZ + 1500 -> 1000
DIRECT + no configured/default max -> None
```

- [ ] **Step 2: Add placement-zone compatibility tests**

Test sortable, non-sortable, KGT, MULTIPLE, UNKNOWN with exact reason codes.

- [ ] **Step 3: Add manual-check contract test**

PVZ rule must include user-facing evidence that actual point capacity/packaging/slot are confirmed manually in Ozon. The scheduler does not silently claim these checks passed.

- [ ] **Step 4: Run RED, implement, run GREEN**

```bash
python -m pytest tests/shipment/test_rules.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/shipment/rules.py tests/shipment/test_rules.py
git commit -m "feat: add shipment method rules"
```

---

### Task 3: Derive explainable urgency without inventing inbound arrival

**Files:**
- Modify: `backend/shipment/contracts.py`
- Create: `backend/shipment/urgency.py`
- Create: `tests/shipment/test_urgency.py`

**Contracts:**

```python
@dataclass(frozen=True, slots=True)
class ShipmentUrgency:
    sku: str
    destination_cluster_id: str
    as_of: date
    current_weekly_rate: Decimal | None
    current_fbo_stock: int | None
    inbound_qty: int | None
    depletion_date: date | None
    quality_complete: bool
    reason_codes: tuple[str, ...]
```

Public function:

```python
def derive_shipment_urgency(
    *,
    line: ShippableLine,
    current_weekly_rate: Decimal | None,
    as_of: date,
) -> ShipmentUrgency: ...
```

Canonical calculation when rate and current FBO are known:

```python
daily_rate = current_weekly_rate / Decimal(7)
coverage_days = Decimal(current_fbo_stock) / daily_rate
```

For zero weekly rate, there is no evidence of a finite depletion date; return `None` with `ZERO_CURRENT_DEMAND_RATE` rather than divide by zero.

Date rounding is conservative: if stock coverage is any positive fractional day, use floor of coverage days for the last fully-covered day and document/test the exact conversion. The implementation must not round depletion later than the evidence supports.

Inbound rule:

```text
inbound_qty > 0 AND no inbound ETA source
→ keep depletion based on current FBO only
→ add INBOUND_ETA_UNKNOWN
→ quality_complete may remain false for a "safe date" claim
```

- [ ] **Step 1: Add known-rate/FBO test**

Example:

```text
as_of 2026-09-08
weekly rate 14 => 2/day
FBO 10 => 5 days coverage
```

Assert the exact documented depletion date.

- [ ] **Step 2: Add inbound-no-ETA regression**

Same line with inbound 100 must NOT move the computed depletion date later; assert reason `INBOUND_ETA_UNKNOWN`.

- [ ] **Step 3: Add unknown/zero evidence tests**

Unknown rate, unknown FBO and zero rate all return no fabricated date with distinct reasons.

- [ ] **Step 4: Run RED, implement Decimal-based calculation, run GREEN**

```bash
python -m pytest tests/shipment/test_urgency.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/shipment/contracts.py backend/shipment/urgency.py tests/shipment/test_urgency.py
git commit -m "feat: derive shipment urgency"
```

---

### Task 4: Define scheduled shipment result contracts

**Files:**
- Modify: `backend/shipment/contracts.py`
- Modify: `tests/shipment/test_scheduler.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ShipmentAssignment:
    sku: str
    article: str
    product_name: str
    destination_cluster_id: str
    quantity: int
    pack_multiple: int
    volume_l: Decimal
    urgency_date: date | None
    latest_recommended_ship_date: date | None
    status: ScheduleStatus
    days_late: int | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PlannedShipment:
    shipment_id: str
    opportunity_id: str
    ship_date: date
    method: ShipmentMethod
    assignments: tuple[ShipmentAssignment, ...]
    cluster_ids: tuple[str, ...]
    total_qty: int
    total_volume_l: Decimal
    status: ScheduleStatus
    manual_checks: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class UnscheduledLine:
    sku: str
    article: str
    destination_cluster_id: str
    residual_qty: int
    pack_multiple: int
    residual_volume_l: Decimal
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShipmentPlan:
    analysis_snapshot_id: str
    selected_cluster_ids: tuple[str, ...]
    shipments: tuple[PlannedShipment, ...]
    unscheduled: tuple[UnscheduledLine, ...]
    total_scheduled_qty: int
    total_unscheduled_qty: int
    total_scheduled_volume_l: Decimal
```

- [ ] **Step 1: Add conservation validation tests**

Every assignment quantity is positive, integer and divisible by pack multiple. Shipment totals equal assignment sums. `cluster_ids` equals sorted unique assignment clusters.

- [ ] **Step 2: Add stable shipment ID contract**

Use deterministic IDs from the opportunity ID, e.g. `shipment:<opportunity_id>`, not random UUIDs.

- [ ] **Step 3: Run RED, implement contracts, run GREEN**

```bash
python -m pytest tests/shipment/test_scheduler.py -q
```

- [ ] **Step 4: Commit**

```bash
git add backend/shipment/contracts.py tests/shipment/test_scheduler.py
git commit -m "feat: define planned shipment results"
```

---

### Task 5: Implement deterministic whole-pack scheduler

**Files:**
- Create: `backend/shipment/scheduler.py`
- Create: `backend/shipment/__init__.py`
- Modify: `tests/shipment/test_scheduler.py`

**Public interface:**

```python
def build_shipment_plan(
    *,
    shippable_plan: ShippablePlan,
    urgencies: Mapping[tuple[str, str], ShipmentUrgency],
    scenario: ShipmentScenario,
    method_rules: Mapping[ShipmentMethod, ShipmentMethodRule] | None = None,
) -> ShipmentPlan: ...
```

Scope filter first:

```python
lines = [
    line for line in shippable_plan.lines
    if line.destination_cluster_id in selected_cluster_ids
    and line.shippable_qty > 0
]
```

For one line/opportunity derive latest recommended ship date only when urgency date exists and lead days are usable:

```python
latest = urgency.depletion_date - timedelta(days=opportunity.lead_days)
```

Opportunity ranking for each residual line:

1. compatible enabled opportunities only;
2. on-time (`ship_date <= latest`) before late when latest is known;
3. among on-time, later `ship_date` first;
4. among late, earlier `ship_date` first;
5. fewer unique clusters already occupying the shipment;
6. lower residual-volume waste after fitting whole packs;
7. stable opportunity ID.

Unknown urgency keeps date quality incomplete; use earliest compatible enabled opportunity as the deterministic fallback and never label it `ON_TIME`.

Maximum quantity that fits one opportunity:

```python
packs_remaining = residual_qty // pack_multiple
packs_by_volume = (
    packs_remaining
    if effective_volume_limit is None
    else floor((limit - used_volume) / (unit_volume_l * pack_multiple))
)
```

Also reject adding a new destination cluster when the opportunity already has `max_clusters` unique clusters.

- [ ] **Step 1: Add selected-cluster-scope test**

Unselected positive lines do not appear in scheduled or unscheduled output for this run. Their upstream `ShippablePlan` remains unchanged.

- [ ] **Step 2: Add "latest on-time" date test**

Given compatible opportunities 14, 16, 18 and latest recommended ship date 18, assert assignment goes to 18 rather than shipping early on 14.

- [ ] **Step 3: Add late fallback test**

If latest is 18 and only 20/22 are feasible, choose 20 and mark `LATE`, `days_late == 2`.

- [ ] **Step 4: Add max-cluster test**

An opportunity with `max_clusters=3` never gets a fourth unique cluster; the fourth moves to another opportunity or unscheduled.

- [ ] **Step 5: Add PVZ-volume split test**

Create a whole-pack line whose volume exceeds the remaining PVZ limit. Assert only the maximum complete packs that fit are assigned and residual packs continue to the next compatible opportunity. No assignment exceeds 1000 L total PVZ volume.

- [ ] **Step 6: Add method/zone fallback test**

A KGT line cannot be auto-assigned to PVZ but may be assigned to a compatible SC/direct opportunity according to rules.

- [ ] **Step 7: Add unknown urgency test**

Assign deterministically to earliest compatible opportunity with `DATE_QUALITY_INCOMPLETE`; no `ON_TIME` status.

- [ ] **Step 8: Add no-opportunity/constraint-reason tests**

Residual line becomes `UnscheduledLine` with causal reasons such as:

```text
NO_SELECTED_COMPATIBLE_OPPORTUNITY
MAX_CLUSTERS_EXHAUSTED
VOLUME_LIMIT_EXHAUSTED
PLACEMENT_ZONE_INCOMPATIBLE
```

Never collapse all cases to generic `UNSCHEDULED` only.

- [ ] **Step 9: Add determinism test**

Feed identical logical inputs in shuffled tuple order and assert identical normalized `ShipmentPlan` output.

- [ ] **Step 10: Run RED, implement bounded scheduler, run GREEN**

```bash
python -m pytest tests/shipment/test_scheduler.py tests/shipment/test_rules.py tests/shipment/test_urgency.py -q
```

No recursion over all cluster subsets and no combinatorial brute force.

- [ ] **Step 11: Commit**

```bash
git add backend/shipment/__init__.py backend/shipment/scheduler.py tests/shipment/test_scheduler.py
git commit -m "feat: schedule whole-pack shipments"
```

---

### Task 6: PR-C regression and acceptance gate

- [ ] **Step 1: Run shipment suites**

```bash
python -m pytest tests/shipment -q
```

- [ ] **Step 2: Run upstream shippable/supply regression**

```bash
python -m pytest tests/supply/test_shippable.py tests/supply/test_optimizer.py tests/decision/test_shippable.py -q
```

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

- [ ] **Step 4: Acceptance checklist**

Prove with tests:

```text
same inputs -> same schedule
all quantities are whole packs
PVZ never exceeds effective <=1000 L cap
max cluster count is respected
current FBO drives urgency when rate is known
inbound without ETA never postpones depletion
latest on-time opportunity is preferred
late and unscheduled quantities remain explicit
no Ozon API call exists
```

PR-D begins only after these invariants are green.