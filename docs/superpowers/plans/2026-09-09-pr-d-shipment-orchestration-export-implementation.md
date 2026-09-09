# PR-D Shipment Orchestration, Ranking & Exact Ozon Export Implementation Plan

> Implement task-by-task with TDD. Read `AGENTS.md` and the canonical API-first shipment design first.

**Goal:** rank backend-validated shipment options using operational/service-level evidence, preserve all rejected/unscheduled causes, and render exact Ozon XLSX/ZIP bytes without creating a real supply request.

## Global invariants

- Ranking never recalculates demand, Need, seller stock or whole-pack quantities.
- Ranking uses Ozon validation/timeslots plus existing immutable plan/candidate evidence only.
- Shipment code does not invent `urgency_date`, stockout date, days-late or latest-still-on-time math.
- Timeslots remain observed evidence on `ValidatedShipmentOption`; PR-D does not select, reserve, rank or persist one canonical timeslot.
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

`ValidatedShipmentOption.timeslots` remains the complete normalized ordered evidence returned by PR-API3. Do not copy one element into `selected_timeslot`, `recommended_timeslot`, `best_timeslot` or an equivalent backend-owned field.

Do not add urgency/date-to-stockout fields merely because the ranking service could calculate them. Such a field may enter this contract only after a later approved upstream analytical design owns it.

---

## Task 2 — operational ranking

Canonical keys, in order:

```text
1 accepted by Ozon
2 has one or more timeslots inside requested range
3 lower fragmentation / more useful covered assignment volume
4 user seller-warehouse/handoff preference where applicable
5 stable candidate ID
```

`has timeslot` is a boolean capability/ranking signal only. When several current windows exist, their order/evidence remains attached to the validated option; PR-D must not infer that the first, earliest, latest or shortest window is the user's preferred final slot.

Tests:
- accepted+slot outranks accepted+no-slot and rejected;
- multiple timeslots do not create a backend `selected_timeslot` or change candidate quantities;
- among equivalent accepted+slot options, lower fragmentation/more covered assignment volume wins;
- seller warehouse/handoff user priority only breaks otherwise equivalent choices;
- stable candidate ID final tie-break;
- source guard proves no route-cost imports;
- source guard proves no shipment-layer urgency/stockout-date calculation;
- source/contract guard proves no `selected_timeslot`, `recommended_timeslot` or `best_timeslot` ownership is introduced.

If a future approved upstream contract exposes a canonical immutable urgency field, ranking changes require a separate design update; do not opportunistically infer one from `current_weekly_rate`, FBO, inbound or Need.

A future real-supply execution design may introduce explicit slot selection if the API action actually requires/owns it. That is outside this milestone.

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

`/api/shipment/plan` consumes backend-produced validated options + immutable parent identities and ranks shipment options. It must reject source/analysis/ShippablePlan/scenario mismatch.

`analysis_as_of` comes only from parent analysis; request cannot override it.

The endpoint returns each ranked option with all current `ValidatedShipmentOption.timeslots` evidence. It does not accept or return a backend-owned selected slot in this milestone.

`/api/shipment/export` accepts only backend-produced ranked/exportable option identity, rechecks identity/pack invariants and returns bytes + media type + Content-Disposition.

No endpoint calls Ozon real supply creation.

---

## Task 7 — regression gate

Tests must cover:
- accepted/no-slot/rejected ordering;
- multiple current timeslots preserved as evidence with no backend-selected slot;
- fragmentation/covered-volume ordering;
- residual quantity conservation;
- seller warehouse/handoff tie-break;
- no shipment-layer urgency/stockout-date calculation;
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

Acceptance: validated shipment options are ranked operationally and explainably without inventing urgency or selecting a timeslot, all current windows remain evidence for the user, every input quantity has a causal outcome, export is exact/fail-closed, and no real Ozon supply is created.
