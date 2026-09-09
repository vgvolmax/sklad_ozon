# PR-D Shipment Orchestration & Ozon XLSX/ZIP Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn candidate/live-validation evidence into ranked operational shipment options and exact manual Ozon export files without recalculating demand or creating a real Ozon supply.

**Architecture:** A pure ranking layer consumes immutable `ShippablePlan`, scenario and `ValidatedShipmentOption` evidence. It derives explainable urgency from the parent analysis, ranks only with operational criteria, preserves rejected/unscheduled evidence and returns a `ShipmentPlan`. Export renders accepted assignments exactly into one three-column XLSX per cluster, ZIP for multi-cluster options.

**Tech Stack:** Python 3.13.14, Decimal, openpyxl, zipfile, FastAPI, pytest; no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Never rerun demand/stockout/Flow/economics from shipment orchestration.
- Use immutable `analysis_as_of` from parent ShippablePlan; browser cannot override it.
- Ranking is operational/service-level, not seller→Ozon cost optimization.
- Never use RouteCostIndex/DirectRouteQuote for this ranking.
- Rejected/no-slot/throttled/unavailable candidates remain visible; do not silently drop them.
- Export only accepted assignment quantities produced by backend validation and preserves pack multiples.
- XLSX headers exactly: `артикул`, `имя (необязательно)`, `количество`.
- No helper cluster/zone/SKU columns in exported workbook.
- No call to real Ozon supply create.

---

### Task 1: Define ranked ShipmentPlan contracts

**Files:**
- Create: `backend/shipment/plan.py`
- Create: `tests/shipment/test_plan_contracts.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ShipmentUrgency:
    sku: str
    destination_cluster_id: str
    latest_recommended_ship_date: date | None
    quality: str
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class RankedShipmentOption:
    rank: int
    option: ValidatedShipmentOption
    selected_timeslot: OzonTimeslot | None
    on_time: bool | None
    days_late: int | None
    reason_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShipmentPlan:
    analysis_snapshot_id: str
    source_snapshot_id: str | None
    analysis_as_of: date
    scenario_fingerprint: str
    ranked_options: tuple[RankedShipmentOption, ...]
    rejected_or_unavailable: tuple[ValidatedShipmentOption, ...]
    unscheduled_assignments: tuple
    calculated_at_utc: str
```

- [ ] **Step 1: Add invariant tests for unique rank sequence, parent identity, selected timeslot belonging to option and explicit unresolved states.**
- [ ] **Step 2: Run RED, implement immutable contracts, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_plan_contracts.py -q
git add backend/shipment/plan.py tests/shipment/test_plan_contracts.py
git commit -m "feat: define ranked shipment plan"
```

---

### Task 2: Derive explainable urgency from existing analysis evidence

**Files:**
- Create: `backend/shipment/urgency.py`
- Create: `tests/shipment/test_urgency.py`

**Interfaces:**

```python
def derive_shipment_urgencies(plan: ShippablePlan) -> tuple[ShipmentUrgency, ...]: ...
```

Rules use only propagated current weekly rate, current FBO and known inbound evidence from the analysis that produced the plan. Current inbound has quantity but no independently guaranteed ETA; do not fabricate arrival timing from it.

- [ ] **Step 1: Add complete fixture with positive weekly rate/current FBO and assert deterministic depletion/latest-ship calculation anchored to `analysis_as_of`.**
- [ ] **Step 2: Add zero/unknown rate, unknown stock and missing evidence fixtures; return unknown quality/date, not far-future placeholders.**
- [ ] **Step 3: Add test proving browser/request date is not an input to this function.**
- [ ] **Step 4: Run RED, implement pure urgency, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_urgency.py -q
git add backend/shipment/urgency.py tests/shipment/test_urgency.py
git commit -m "feat: derive shipment urgency"
```

---

### Task 3: Rank validated Ozon options without supply-cost fiction

**Files:**
- Create: `backend/shipment/ranking.py`
- Create: `tests/shipment/test_ranking.py`

**Interface:**

```python
def build_shipment_plan(
    *,
    shippable_plan: ShippablePlan,
    scenario: ShipmentScenario,
    options: Iterable[ValidatedShipmentOption],
    preferred_handoff_point_ids: tuple[int, ...] = (),
) -> ShipmentPlan: ...
```

Canonical rank keys, in order:

```text
1 accepted by Ozon
2 has timeslot inside requested range
3 protects earliest known urgency
4 latest still-on-time slot among equivalent choices
5 lower fragmentation / more useful covered assignment volume
6 user hand-off point priority
7 stable candidate ID
```

- [ ] **Step 1: Add accepted+slot vs accepted+no-slot vs rejected fixture and assert causal ordering.**
- [ ] **Step 2: Add two on-time slots for same urgency and prove latest still-on-time is chosen.**
- [ ] **Step 3: Add late-only fixture and expose days-late rather than labelling safe.**
- [ ] **Step 4: Add hand-off priority/stable ID tie-break fixture.**
- [ ] **Step 5: Add source guard asserting RouteCostIndex/DirectRouteQuote are not imported into shipment ranking.**
- [ ] **Step 6: Run RED, implement deterministic ranker, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_ranking.py -q
git add backend/shipment/ranking.py tests/shipment/test_ranking.py
git commit -m "feat: rank validated shipment options"
```

---

### Task 4: Preserve rejected/unscheduled assignment coverage

**Files:**
- Modify: `backend/shipment/ranking.py`
- Modify: `tests/shipment/test_ranking.py`

- [ ] **Step 1: Add partial rejection fixture and prove rejected SKU/cluster/qty remains in `rejected_or_unavailable` or explicit unscheduled evidence while accepted assignments remain rankable.**
- [ ] **Step 2: Add scenario where every option fails and assert valid ShipmentPlan with zero ranked accepted options plus exact causes, not HTTP/business failure.**
- [ ] **Step 3: Prove total accepted + rejected/unscheduled quantities reconcile to candidate input for every backend-validated option.**
- [ ] **Step 4: Run tests and commit.**

```bash
python -m pytest tests/shipment/test_ranking.py -q
git add backend/shipment/ranking.py tests/shipment/test_ranking.py
git commit -m "feat: preserve shipment residual causes"
```

---

### Task 5: Render exact Ozon workbook/ZIP bytes

**Files:**
- Create: `backend/shipment/export.py`
- Create: `tests/shipment/test_export.py`

**Interfaces:**

```python
OZON_TEMPLATE_HEADERS = (
    "артикул",
    "имя (необязательно)",
    "количество",
)


def render_cluster_xlsx(assignments, *, cluster_id: str) -> bytes: ...
def render_option_export(option: RankedShipmentOption) -> tuple[str, str, bytes]: ...
```

- [ ] **Step 1: Add exact `A1:C1` header test and assert `D1` empty.**
- [ ] **Step 2: Add row test aggregating duplicate article+cluster assignments within one option while preserving integer positive pack-multiple quantity.**
- [ ] **Step 3: Add invalid export tests: blank article, zero/negative qty, qty violating serialized pack multiple or rejected assignment must fail rather than repair.**
- [ ] **Step 4: Add single-cluster→XLSX and multi-cluster→ZIP tests; every ZIP member contains only its cluster and no helper column.**
- [ ] **Step 5: Add safe deterministic filename/path traversal test.**
- [ ] **Step 6: Run RED, implement renderer, run GREEN and commit.**

```bash
python -m pytest tests/shipment/test_export.py -q
git add backend/shipment/export.py tests/shipment/test_export.py
git commit -m "feat: render Ozon shipment templates"
```

---

### Task 6: Wire orchestration/export local endpoints

**Files:**
- Modify: `backend/api.py`
- Modify: `backend/shipment/wire.py`
- Create: `tests/api/test_shipment_plan.py`
- Create: `tests/api/test_shipment_export.py`

**Endpoints:**

```text
POST /api/shipment/plan
POST /api/shipment/export
```

`/api/shipment/plan` consumes backend-validated options + immutable parent IDs and ranks them; it does not call Ozon again unless the request explicitly uses the combined orchestration convenience operation approved in this task. Keep pure ranker independently testable.

`/api/shipment/export` consumes one backend-produced ranked accepted option and renders bytes only.

- [ ] **Step 1: Add strict identity/tampering tests for source snapshot, analysis snapshot, ShippablePlan and scenario fingerprint.**
- [ ] **Step 2: Add plan API tests for accepted/no-slot/rejected combinations and immutable `analysis_as_of`.**
- [ ] **Step 3: Add export response tests for correct media type, Content-Disposition and loadable workbook/ZIP.**
- [ ] **Step 4: Add no-real-create guard proving neither endpoint references/calls `/v2/draft/supply/create`.**
- [ ] **Step 5: Run RED, implement thin endpoints, run GREEN and commit.**

```bash
python -m pytest tests/api/test_shipment_plan.py tests/api/test_shipment_export.py -q
git add backend/api.py backend/shipment/wire.py tests/api/test_shipment_plan.py tests/api/test_shipment_export.py
git commit -m "feat: orchestrate and export shipment options"
```

---

### Task 7: PR-D full regression gate

- [ ] **Step 1: Run shipment domain/API suites.**

```bash
python -m pytest tests/shipment tests/api/test_shipment_candidates.py tests/api/test_shipment_validate.py tests/api/test_shipment_plan.py tests/api/test_shipment_export.py -q
```

- [ ] **Step 2: Run analysis transports, including stream tests in `tests/api/test_analysis.py`.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 3: Run full suite.**

```bash
python -m pytest -q
```

Acceptance: validated options are ranked with real Ozon evidence and analytical urgency, causal failures stay visible, export is exact, and no real Ozon supply is created.
