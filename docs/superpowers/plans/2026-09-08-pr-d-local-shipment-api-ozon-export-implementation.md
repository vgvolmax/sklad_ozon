# PR-D Local Shipment API & Ozon Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire PR-A/B/C into the local FastAPI application, expose downstream shipment recalculation, and generate exact Ozon-format XLSX/ZIP files for manual upload without calling Ozon Seller API.

**Architecture:** Full analysis remains the owner of source-file ingestion and analytical demand/plan calculation. It optionally ingests the supplier packaging workbook and appends an immutable `ShippablePlan` to the existing `AnalysisSnapshot`; missing packaging data blocks shipment execution only, not analytics. `/api/shipment-plan` is a stateless local downstream endpoint that filters the existing shippable plan to the selected cluster scope, derives urgencies, and runs PR-C scheduling. `/api/shipment-export` validates a backend-produced planned shipment and renders workbook bytes only; it never recalculates demand.

**Tech Stack:** Python 3, FastAPI, openpyxl (existing dependency), `zipfile`, `io.BytesIO`, strict JSON parsing, pytest; no new dependency and no external network call.

**Spec:** `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`

## Global Constraints

- Existing `/api/analysis` and `/api/analysis/stream` remain valid for analytical use when `supplier_packaging_file` is absent.
- Supplier packaging is optional for full analysis transport so old workflows do not break; shipment execution is marked incomplete until the file is supplied.
- Do not add or call any `api-seller.ozon.ru` endpoint.
- Do not restore the superseded selected-network `/api/replan` design.
- `ShippablePlan` references one immutable `AnalysisSnapshot.snapshot_id`; shipment planning never mutates the analysis.
- V1 selected cluster scope is **filter-only** over the already-calculated all-cluster `ShippablePlan`; it does not move stock or quantities from an unselected cluster into a selected one.
- Shipment opportunity changes never rerun orders ingestion, demand, stockout, Flow, route economics or Product Completion allocation.
- Export uses the operational Calculated Plan assignments only.
- One Ozon XLSX corresponds to one cluster within one planned shipment.
- Exact workbook headers/order are `артикул`, `имя (необязательно)`, `количество`.
- Do not add cluster, SKU, volume, zone or diagnostic helper columns to the Ozon workbook.
- Every exported quantity is positive integer and satisfies pack multiplicity.
- Files are generated in memory; no server-side permanent export directory or history database.
- Use safe deterministic filenames; no user-provided path traversal.

---

## File Structure

- Modify `backend/api.py` — supplier-packaging upload/import, operational plan attachment, `/api/shipment-plan`, `/api/shipment-export`.
- Modify `backend/decision/contracts.py` — append optional shippable-plan/input-status fields to `AnalysisSnapshot` with backwards-safe defaults.
- Create `backend/shipment/wire.py` — strict parsers for local shipment-plan/export JSON contracts.
- Create `backend/shipment/export.py` — Ozon XLSX and multi-cluster ZIP rendering.
- Modify `backend/shipment/__init__.py` — public exports.
- Modify `tests/api/test_analysis.py` — optional supplier packaging and nested shippable plan.
- Create `tests/api/test_shipment_plan.py` — downstream stateless scheduling API.
- Create `tests/api/test_shipment_export.py` — XLSX/ZIP wire and content tests.
- Create `tests/shipment/test_export.py` — pure exporter tests.
- Run existing Product Completion API/stream acceptance unchanged.

---

### Task 1: Add supplier packaging as an optional full-analysis input

**Files:**
- Modify: `backend/api.py`
- Modify: `tests/api/test_analysis.py`

**Transport contract:**

Existing required fields stay unchanged. Add optional multipart field:

```text
supplier_packaging_file
```

When present:

```python
packaging = import_supplier_packaging(
    bytes,
    meta(upload),
)
```

When absent, create an explicit shipment-planning input status:

```text
ok = false for shipment execution
code = SUPPLIER_PACKAGING_MISSING
```

but do **not** return HTTP 400 and do not block analytical `AnalysisSnapshot` creation.

- [ ] **Step 1: Add legacy request compatibility test**

Submit the current valid analysis multipart without `supplier_packaging_file`. Assert HTTP success and all existing analytical snapshot fields remain available. Assert shipment-planning readiness is false/missing-pack reason is explicit.

- [ ] **Step 2: Add packaging-present test**

Submit a small XLSX/XLSM fixture with `Прайс списком` rows. Assert the input status reports imported pack records and the full analysis continues.

- [ ] **Step 3: Add malformed packaging test**

A present file whose relevant rows are invalid does not silently default pack multiples. Analytical result remains available; shipment plan carries blocking packaging diagnostics for affected products.

- [ ] **Step 4: Run RED, extend `prepare_analysis()` without reordering legacy raw inputs**

Do not index optional packaging through positional assumptions shared by existing availability/restrictions/orders/economics import. Prefer a named prepared structure or a separately named optional tuple so adding this input cannot shift the current `raw[0..]` semantics accidentally.

- [ ] **Step 5: Run focused tests and commit**

```bash
python -m pytest tests/api/test_analysis.py -q
git add backend/api.py tests/api/test_analysis.py
git commit -m "feat: accept optional supplier packaging"
```

---

### Task 2: Attach immutable ShippablePlan to full analysis

**Files:**
- Modify: `backend/decision/contracts.py`
- Modify: `backend/api.py`
- Modify: `tests/api/test_analysis.py`

**Contract extension:**

Append defaulted fields at the end of `AnalysisSnapshot`:

```python
shipment_input_statuses: dict[str, InputStatusView] | None = None
shippable_plan: ShippablePlan | None = None
```

Do not rename/remove existing fields.

Full-analysis integration order after current Product Completion allocation:

```text
existing AnalysisSnapshot evidence
+ enriched restriction records
+ supplier pack records when present
+ canonical ProductEconomicsInput seller stock/volume
→ build all-cluster PackOptimizationResults
→ assemble_shippable_plan(...)
→ attach to returned immutable snapshot
```

If one SKU lacks pack/volume/stock/capacity evidence, keep other SKU lines valid and report the affected SKU as incomplete. Do not fail the entire analysis merely because export is incomplete.

- [ ] **Step 1: Add all-cluster operational plan API test**

For a fixture where article `40750` has analytical plan `17` and pack `6`, assert wire output contains `analytical_plan_qty: 17`, `shippable_qty: 18`, `rounding_delta_qty: 1` when stock/capacity permit.

- [ ] **Step 2: Add existing FBO/inbound non-double-subtraction test**

Assert the same existing `DecisionRow.need.calculated_need_qty` and `DecisionRow.current_fbo_stock/inbound_qty` values before and after operational attachment; PR-D only adds downstream fields.

- [ ] **Step 3: Add missing-pack partial-incompleteness test**

One SKU missing packaging must not suppress other complete SKU operational lines.

- [ ] **Step 4: Implement attachment after existing analytical computation**

Do not add operational calculations to frontend serialization code; call PR-A/B pure functions from backend.

- [ ] **Step 5: Run focused + acceptance tests and commit**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
git add backend/decision/contracts.py backend/api.py tests/api/test_analysis.py
git commit -m "feat: attach shippable plan to analysis"
```

---

### Task 3: Define strict shipment-plan JSON parsing

**Files:**
- Create: `backend/shipment/wire.py`
- Create: `tests/api/test_shipment_plan.py`

**Request wire:**

```json
{
  "analysis_snapshot_id": "...",
  "shippable_plan": {"...": "wire(ShippablePlan)"},
  "as_of": "2026-09-08",
  "scenario": {
    "selected_cluster_ids": ["Москва", "Пермь"],
    "opportunities": [
      {
        "opportunity_id": "2026-09-16-pvz-1",
        "ship_date": "2026-09-16",
        "method": "pvz_crossdock",
        "max_clusters": 3,
        "max_volume_l": "1000",
        "lead_days": 2,
        "enabled": true
      }
    ]
  }
}
```

Parser requirements:

- reject unknown enum values;
- reject bool where integer is required;
- parse `Decimal` from JSON strings without float round-trip;
- require request `analysis_snapshot_id == shippable_plan.analysis_snapshot_id`;
- reject duplicate cluster/opportunity identities;
- ignore no unknown extra business fields silently: reject malformed schema with stable error code.

- [ ] **Step 1: Add valid round-trip test**

Wire existing dataclasses through current `wire()`, parse them back and assert equality of business fields.

- [ ] **Step 2: Add malformed/identity-mismatch tests**

Cover invalid method/date/Decimal, duplicate IDs and snapshot mismatch.

- [ ] **Step 3: Run RED, implement parser, run GREEN**

```bash
python -m pytest tests/api/test_shipment_plan.py -q
```

- [ ] **Step 4: Commit**

```bash
git add backend/shipment/wire.py tests/api/test_shipment_plan.py
git commit -m "feat: parse shipment plan requests"
```

---

### Task 4: Add stateless local `/api/shipment-plan`

**Files:**
- Modify: `backend/api.py`
- Modify: `tests/api/test_shipment_plan.py`

**Endpoint:**

```text
POST /api/shipment-plan
Content-Type: application/json
```

Behavior:

1. parse strict request via `backend.shipment.wire`;
2. filter `ShippablePlan.lines` to selected cluster IDs; do not change any line quantity;
3. derive `ShipmentUrgency` for each selected line from its propagated current weekly rate/FBO/inbound evidence;
4. run `build_shipment_plan()` with default method rules;
5. return `{"api_version":1,"shipment_plan": wire(result)}`;
6. no Project JSON write and no external network request.

If `shippable_plan` is incomplete for selected positive lines, return a valid plan with those lines unscheduled/blocking reasons where possible; use HTTP 400 only for malformed request contract, not ordinary business infeasibility.

- [ ] **Step 1: Add selected-scope API test**

A basis containing Moscow/Kazan/Perm with selected `[Moscow, Perm]` returns no Kazan assignment and does not mutate/renormalize Moscow/Perm quantities.

- [ ] **Step 2: Add PVZ/date behavior API test**

Prove endpoint preserves PR-C's <=1000 L and latest-on-time behavior through JSON wire.

- [ ] **Step 3: Add no-network-call guard**

Use monkeypatch/socket or source-level test consistent with repo practice to ensure this endpoint never opens an outbound HTTP client/request. It uses only local pure functions.

- [ ] **Step 4: Run RED, implement endpoint, run GREEN**

```bash
python -m pytest tests/api/test_shipment_plan.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/api.py tests/api/test_shipment_plan.py
git commit -m "feat: add local shipment planning API"
```

---

### Task 5: Implement exact Ozon XLSX renderer

**Files:**
- Create: `backend/shipment/export.py`
- Create: `tests/shipment/test_export.py`

**Pure interfaces:**

```python
OZON_TEMPLATE_HEADERS = (
    "артикул",
    "имя (необязательно)",
    "количество",
)


def render_cluster_xlsx(
    assignments: Iterable[ShipmentAssignment],
    *,
    cluster_id: str,
) -> bytes: ...


def render_shipment_export(shipment: PlannedShipment) -> tuple[str, str, bytes]:
    """Return filename, media_type, bytes; XLSX for one cluster, ZIP for >1."""
```

Workbook contract:

- active sheet starts at row 1 with exactly the three headers above in exact order;
- rows contain seller `article`, current `product_name` or blank, integer quantity;
- no index/helper columns;
- aggregate multiple assignments for same article+cluster within one shipment before writing;
- sort rows by natural/stable article text;
- validate positive quantity and `qty % pack_multiple == 0` before writing;
- use openpyxl already pinned in runtime.

- [ ] **Step 1: Add exact header/order test**

Load generated bytes in test and assert `A1:C1` equals the supplied Ozon template contract and `D1` is empty.

- [ ] **Step 2: Add exact row/aggregation test**

Two assignments for article `40750` in the same cluster aggregate into one row; different articles remain separate.

- [ ] **Step 3: Add invalid export invariant tests**

Reject zero/negative quantity, blank article and non-multiple quantity rather than producing a bad Ozon workbook.

- [ ] **Step 4: Add one-cluster vs multi-cluster packaging tests**

One cluster → media type XLSX and one `.xlsx` filename.

Three clusters → ZIP with exactly three `.xlsx` members, each containing only its cluster's rows and no cluster helper column.

- [ ] **Step 5: Add filename sanitization test**

Cluster names containing slash/backslash/path tokens cannot escape archive or output path. Use a deterministic safe filename mapping while keeping recognizable Cyrillic text where safe.

- [ ] **Step 6: Run RED, implement renderer, run GREEN**

```bash
python -m pytest tests/shipment/test_export.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/shipment/export.py tests/shipment/test_export.py
git commit -m "feat: render Ozon shipment templates"
```

---

### Task 6: Add `/api/shipment-export`

**Files:**
- Modify: `backend/shipment/wire.py`
- Modify: `backend/api.py`
- Create: `tests/api/test_shipment_export.py`

**Endpoint:**

```text
POST /api/shipment-export
Content-Type: application/json
```

Request contains exactly one `PlannedShipment` wire object returned by `/api/shipment-plan`.

Behavior:

1. strict parse/validate planned shipment invariants;
2. call `render_shipment_export()`;
3. return bytes with exact media type and `Content-Disposition: attachment` filename;
4. no demand recalculation, Project JSON mutation or external network request.

- [ ] **Step 1: Add single-cluster response test**

Assert status 200, XLSX media type, attachment filename and loadable workbook headers/content.

- [ ] **Step 2: Add multi-cluster ZIP response test**

Assert status 200, ZIP media type, safe attachment filename and exact member set.

- [ ] **Step 3: Add malformed/tampered plan test**

A quantity violating its serialized pack multiple returns stable 400 error; endpoint does not "repair" it.

- [ ] **Step 4: Run RED, implement, run GREEN**

```bash
python -m pytest tests/api/test_shipment_export.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/shipment/wire.py backend/api.py tests/api/test_shipment_export.py
git commit -m "feat: add Ozon template export API"
```

---

### Task 7: PR-D regression and transport gate

- [ ] **Step 1: Run all shipment/API focused tests**

```bash
python -m pytest tests/shipment tests/api/test_shipment_plan.py tests/api/test_shipment_export.py tests/api/test_analysis.py -q
```

- [ ] **Step 2: Run both existing analysis transports**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_analysis_stream.py -q
```

If the exact stream-test filename differs, run the repository's current test covering `/api/analysis/stream`; do not skip streaming compatibility.

- [ ] **Step 3: Run Product Completion acceptance**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 4: Run full suite**

```bash
python -m pytest -q
```

- [ ] **Step 5: Acceptance checklist**

Verify:

```text
old analysis request without supplier file still succeeds
supplier file enables whole-pack operational plan
shipment-plan does not rerun analysis
selected clusters filter only; no stock moves from unselected clusters
shipment export is exact 3-column Ozon format
multi-cluster shipment -> ZIP of per-cluster XLSX
no Ozon external API/network call exists
no selected-network /api/replan was introduced
```

PR-E begins only after API contracts are stable.