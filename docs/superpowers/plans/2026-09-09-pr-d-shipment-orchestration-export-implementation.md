# PR-D Shipment Orchestration, Ranking & Exact Ozon Export Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** rank backend-validated shipment options using operational/service-level evidence, preserve all rejected/unscheduled causes, and render exact Ozon XLSX/ZIP bytes without creating a real supply request.

## Global invariants

- Ranking never recalculates demand, Need, seller stock or whole-pack quantities.
- Ranking uses Ozon validation/timeslots + immutable analytical urgency only.
- `RouteCostIndex` / `DirectRouteQuote` are not seller→FBO supply-cost evidence and must not influence rank.
- Rejected/unscheduled quantities never disappear.
- Export is backend-only and fail-closed on identity/pack conflicts.
- Browser never repairs/generates XLSX quantities.
- Real `/v2/draft/supply/create` remains forbidden.

---

## Task 1 — ranking contracts

Create/extend immutable shipment-plan contracts, for example:

```python
@dataclass(frozen=True, slots=True)
class RankedShipmentOption:
    option_id: str
    validated_option: ValidatedShipmentOption
    selected_timeslot: OzonTimeslot | None
    urgency_date: date | None
    days_late: int | None
    rank_reasons: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ShipmentPlan:
    shipment_plan_id: str
    source_snapshot_id: str | None
    analysis_snapshot_id: str
    shippable_plan_id: str
    analysis_as_of: date
    scenario_fingerprint: str
    ranked_options: tuple[RankedShipmentOption, ...]
    rejected_or_unavailable: tuple
    diagnostics: tuple
```

All parent identities are immutable/backend-owned.

---

## Task 2 — operational ranking

Canonical keys, in order:

```text
1 accepted by Ozon
2 has timeslot inside requested range
3 protects earliest known urgency
4 latest still-on-time slot among equivalent choices
5 lower fragmentation / more useful covered assignment volume
6 user seller-warehouse/handoff preference where applicable
7 stable candidate ID
```

Tests:
- accepted+slot outranks accepted+no-slot and rejected;
- later but still-on-time slot wins among equivalent options;
- late-only option exposes days late, never labelled safe;
- seller warehouse/handoff user priority only breaks otherwise equivalent choices;
- stable candidate ID final tie-break;
- source guard proves no route-cost imports.

---

## Task 3 — preserve residual/rejection causes

For every validated candidate prove quantity conservation:

```text
accepted + rejected/unavailable = candidate input
```

Partial rejection retains rejected SKU/article/cluster/qty/cause while accepted assignments remain rankable.

If every option fails externally, return a valid ShipmentPlan with zero accepted ranked options plus exact causes, not a generic business HTTP failure.

---

## Task 4 — exact XLSX renderer

Create `backend/shipment/export.py` + tests.

Canonical headers exactly:

```python
OZON_TEMPLATE_HEADERS = (
    "артикул",
    "имя (необязательно)",
    "количество",
)
```

Assert `A1:C1` exact and `D1` empty.

Before aggregating duplicate rows for one `article + destination_cluster`, prove all rows agree on:

```text
sku
article
pack_multiple
```

Product name may differ as display data; canonical identity is SKU/article.

If same article+cluster conflicts on SKU or pack multiple:

```text
EXPORT_IDENTITY_CONFLICT
→ fail closed
→ no workbook/ZIP bytes for that option
```

Never silently choose one SKU, sum across conflicting identities or repair pack multiple.

Every exported quantity must be positive integer and divisible by serialized pack multiple.

---

## Task 5 — XLSX/ZIP packaging

Rules:

```text
one destination cluster → one XLSX
multiple destination clusters → ZIP, one XLSX per cluster
```

Each workbook contains only its cluster assignments and only the three Ozon columns. Placement zones, seller warehouse, handoff and diagnostics remain in app/manifest, not helper columns.

Use safe deterministic filenames; prevent path traversal.

Rejected/unknown/unvalidated assignments are never exported.

---

## Task 6 — orchestration/export endpoints

Modify `backend/api.py`, shipment wire code, add:

```text
POST /api/shipment/plan
POST /api/shipment/export
```

`/api/shipment/plan` consumes backend-produced validated options + immutable parent identities and ranks them. It must reject source/analysis/ShippablePlan/scenario mismatch.

`analysis_as_of` comes only from parent analysis; request cannot override it.

`/api/shipment/export` accepts only backend-produced ranked/exportable option identity, rechecks identity/pack invariants and returns bytes + media type + Content-Disposition.

No endpoint calls Ozon real supply creation.

---

## Task 7 — regression gate

Tests must cover:
- accepted/no-slot/rejected ordering;
- residual quantity conservation;
- late-only explanation;
- seller warehouse/handoff tie-break;
- exact workbook headers;
- same article+cluster duplicate with same SKU/pack aggregates correctly;
- same article+cluster conflicting SKU blocks export;
- conflicting pack multiple blocks export;
- blank article, zero/negative qty, pack violation, rejected line blocks export;
- single-cluster XLSX and multi-cluster ZIP;
- parent identity tampering;
- no `/v2/draft/supply/create` reference/call.

Run:

```bash
python -m pytest tests/shipment tests/api/test_shipment_candidates.py tests/api/test_shipment_validate.py tests/api/test_shipment_plan.py tests/api/test_shipment_export.py -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Acceptance: validated options are ranked operationally and explainably, every input quantity has a causal outcome, export is exact/fail-closed, and no real Ozon supply is created.