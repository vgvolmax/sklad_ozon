# PR-API2 Ozon API Data Sources & Explicit FILES Fallback Implementation Plan

> **Required process:** implement task-by-task with TDD. Read `AGENTS.md` and the canonical 2026-09-09 API-first shipment design first.

**Goal:** replace routine Ozon orders/availability/restrictions uploads with one immutable API source snapshot while preserving existing file importers as an explicit, non-mixing analytical fallback.

**Architecture:** backend adapters fetch Ozon domains and normalize them into existing analytics contracts. `OzonSourceSnapshotStore` is process-memory-only. API mode and FILES mode feed the same existing analysis orchestration; analytics formulas are not forked.

**No new dependency.** Uses PR-API1 `OzonClient`/vault.

## Global invariants

- `source_mode` is exactly `api` or `files` for one analysis run.
- Never fill missing API rows/domains from files.
- Raw buyer/address/phone/email data never enters source snapshots/logs/frontend.
- API `source_as_of` is backend-owned; browser cannot relabel current evidence.
- Every successful `AnalysisSnapshot` persists `analysis_as_of`, `source_mode`, and `source_snapshot_id` provenance.
- API history depth is backend-owned; default 12 completed ISO weeks, bounded backfill only for source-wide gaps, max 52 weeks.
- Exact Ozon recommendation is not fabricated in API mode.
- FBO and inbound remain distinct and parity-tested against existing Need semantics.
- Handoff points are remote search results, **not** source-sync catalog data.
- Seller warehouses are a small source-sync catalog.
- Canonical seller/FBS stock endpoint is `/v2/product/info/stocks-by-warehouse/fbs`; do not implement v1.
- FILES remains a reserve analytical mode only; do not introduce hybrid FILES analysis + live Ozon operational validation in this PR.

---

## Task 1 — immutable source-mode/API source contracts and store

**Modify:**
- `backend/domain/contracts.py`

**Create:**
- `backend/ozon/source_contracts.py`
- `backend/ozon/source_store.py`
- `tests/ozon/test_source_store.py`

`SourceMode` is neutral analysis provenance, not an Ozon-adapter-owned type. Define it in the existing domain boundary so `AnalysisSnapshot` never needs to import from `backend.ozon`:

```python
# backend/domain/contracts.py
class SourceMode(str, Enum):
    API = "api"
    FILES = "files"
```

`backend/ozon/source_contracts.py` imports that neutral enum and defines API-specific source records:

```python
@dataclass(frozen=True, slots=True)
class EndpointEvidence:
    name: str
    fetched_at_utc: str
    record_count: int
    complete: bool
    diagnostics: tuple

@dataclass(frozen=True, slots=True)
class SellerWarehouse:
    seller_warehouse_id: int
    name: str | None
    address: str | None
    is_active: bool
    is_pickup: bool | None

@dataclass(frozen=True, slots=True)
class OzonSourceSnapshot:
    source_snapshot_id: str
    synced_at_utc: str
    source_as_of: date
    source_timezone: str
    history_from: date
    history_to: date
    orders: tuple
    availability: tuple
    operational_seller_stock: tuple
    clusters: tuple
    seller_warehouses: tuple[SellerWarehouse, ...]
    placement_zones: tuple
    endpoint_evidence: tuple[EndpointEvidence, ...]
    diagnostics: tuple
```

There is no `handoff_points` field.

Canonical business-date implementation is dependency-free:

```python
MOSCOW_BUSINESS_TZ = timezone(timedelta(hours=3))
source_timezone = "UTC+03:00"
source_as_of = synced_at_utc.astimezone(MOSCOW_BUSINESS_TZ).date()
```

Do not require `zoneinfo`/IANA tzdata merely to compute the current Moscow business date in the portable Windows runtime.

Tests:
- stable neutral `SourceMode` values;
- frozen/immutable contracts;
- bounded store (for example latest 3 snapshots);
- not-found identity;
- source_as_of around UTC+03:00 midnight boundary;
- seller contacts/courier comments cannot appear in normalized snapshot.

Run:

```bash
python -m pytest tests/ozon/test_source_store.py -q
```

---

## Task 2 — backend-owned history window + FBO/FBS postings

**Create:**
- `backend/ozon/history.py`
- `backend/ozon/adapters/orders.py`
- `tests/ozon/test_history.py`
- `tests/ozon/adapters/test_orders.py`

Endpoints:

```text
POST /v3/posting/fbo/list
POST /v4/posting/fbs/list
```

History policy:

```text
initial = 12 completed ISO weeks before source_as_of business week
fetch current partial week as needed for current lifecycle/Flow evidence
backfill increment = 4 weeks
max lookback = 52 weeks
```

Only source-wide unusable/missing completed-week coverage may trigger bounded backfill. Do not backfill indefinitely because a particular new/slow SKU has <8 weeks; existing 4–7/1–3 demand fallback owns that case.

Adapters may split requests into endpoint-compatible date chunks/pages internally.

Normalize into existing `OrderRecord` fields consumed by analysis. Add fixtures proving:
- two-page pagination;
- destination/origin/SKU/article/name/qty/lifecycle/time normalization;
- PII fields are discarded;
- equivalent API/file fixture produces equal analytical order evidence;
- shallow UI-supplied history cannot override backend policy.

Run:

```bash
python -m pytest tests/ozon/test_history.py tests/ozon/adapters/test_orders.py -q
```

---

## Task 3 — canonical clusters and active seller warehouses

**Create:**
- `backend/ozon/adapters/catalog.py`
- `tests/ozon/adapters/test_catalog.py`

Endpoints:

```text
POST /v2/cluster/list
POST /v1/cluster/list
POST /v1/warehouse/fbo/seller/list
```

Requirements:
- canonical identity uses Ozon IDs, not fuzzy display-name matching;
- normalize active seller warehouses into `SellerWarehouse`;
- discard seller-warehouse contacts/courier comments;
- preserve enough name/address/is_active/is_pickup evidence for UI selection;
- duplicate/conflicting IDs are diagnostics, not silent merge.

Tests include one active warehouse, multiple active warehouses, inactive warehouse and PII/contact stripping.

Run:

```bash
python -m pytest tests/ozon/adapters/test_catalog.py -q
```

---

## Task 4 — current FBO stock and seller/FBS stock

**Create:**
- `backend/ozon/adapters/stocks.py`
- `tests/ozon/adapters/test_stocks.py`

Endpoints:

```text
POST /v1/analytics/stocks
POST /v2/product/info/stocks-by-warehouse/fbs
```

Explicit guard: repository source for the new adapter must not contain the deprecated `/v1/product/info/stocks-by-warehouse/fbs` path.

Requirements:
- FBO maps by canonical warehouse/cluster to existing `AvailabilityRecord.fbo_quantity` semantics;
- seller stock reaches the same evidence shape consumed by the existing seller-stock resolver;
- explicit zero stays zero;
- conflicting positive seller-stock evidence remains visible to existing resolver; do not sum/max it away;
- API-vs-file parity tests cover all fields consumed by analysis.

Run:

```bash
python -m pytest tests/ozon/adapters/test_stocks.py -q
```

---

## Task 5 — inbound from active FBO supply orders

**Create:**
- `backend/ozon/adapters/inbound.py`
- `tests/ozon/adapters/test_inbound.py`

Endpoints:

```text
POST /v3/supply-order/list
POST /v3/supply-order/get
POST /v1/supply-order/bundle
```

Implement one explicit supply-state classifier. Count only quantity that is still inbound and not yet available FBO stock. Completed/cancelled/rejected/final states do not count. Unknown new Ozon state → diagnostic/incomplete, never silently counted or zeroed.

Tests:
- active/completed/cancelled/unknown states;
- warehouse→cluster identity;
- bundle pagination/aggregation by `SKU × destination`;
- no-double-subtraction acceptance against equivalent availability file;
- inbound failure blocks Need only when `include_inbound=true`.

Run:

```bash
python -m pytest tests/ozon/adapters/test_inbound.py tests/decision/test_need.py -q
```

---

## Task 6 — placement-zone evidence

**Create:**
- `backend/ozon/adapters/placement_zones.py`
- `tests/ozon/adapters/test_placement_zones.py`

Endpoint:

```text
POST /v1/product/placement-zone/info
```

Preserve exact normalized zone/unknown/multiple evidence. Do not infer replacement zones from dimensions.

Placement-zone failure affects shipment-method compatibility only; it does not block demand/Need.

Run:

```bash
python -m pytest tests/ozon/adapters/test_placement_zones.py -q
```

---

## Task 7 — remote handoff search and process-memory store

**Create:**
- `backend/ozon/handoff.py`
- `tests/ozon/test_handoff_search.py`
- `tests/api/test_ozon_handoff.py`
- modify `backend/api.py`

Endpoint registry:

```text
POST /v1/warehouse/fbo/list
```

Local endpoint:

```text
POST /api/ozon/handoff/search
```

Request:

```text
query: string          # trimmed, min 4 chars
supply_types: tuple
```

Normalized `HandoffPoint` contains:

```text
warehouse_id: int
name
address
warehouse_type / point_type exactly from Ozon evidence
```

Results populate process-memory `HandoffPointStore` keyed by warehouse ID.

Rules:
- requires unlocked vault;
- `<4` trimmed chars rejected/short-circuited locally;
- no bulk handoff fetch during source sync;
- persisted IDs are preferences only; after restart they must be resolved again;
- unknown/stale IDs fail before candidate/draft use;
- secrets never exposed.

Run:

```bash
python -m pytest tests/ozon/test_handoff_search.py tests/api/test_ozon_handoff.py -q
```

---

## Task 8 — assemble API sync with capability matrix

**Create/modify:**
- `backend/ozon/sync.py`
- `backend/api.py`
- `tests/api/test_ozon_sync.py`

Canonical interface:

```python
def sync_ozon_source(
    client: OzonClient,
    *,
    progress_callback=None,
) -> OzonSourceSnapshot: ...
```

Do **not** accept arbitrary `as_of`/`history_from` from browser as source truth.

Local endpoints:

```text
POST /api/ozon/sync
GET  /api/ozon/source/{source_snapshot_id}/status
```

Progress stages may be:

```text
orders → clusters/seller_warehouses → stocks → inbound → zones → complete
```

Capability consequences are fixed:
- postings missing blocks demand/Flow for missing history;
- unresolved cluster blocks affected evidence;
- FBO missing makes affected Need incomplete;
- inbound missing matters only when inbound enabled;
- seller stock missing blocks operational allocation only;
- exact Ozon recommendation missing only disables comparison/Safe;
- zone missing limits shipment compatibility only;
- handoff search is not source-sync completeness.

Failed refresh preserves previous valid snapshot.

Run:

```bash
python -m pytest tests/api/test_ozon_sync.py -q
```

---

## Task 9 — existing analysis consumes API snapshot OR FILES and persists provenance

**Modify:**
- `backend/decision/contracts.py`
- `backend/api.py`
- `backend/application.py` only for thin prepared-source adaptation if needed
- `tests/api/test_analysis.py`
- `tests/api/test_product_completion_acceptance.py`

Import neutral `SourceMode` from `backend.domain.contracts` and extend the immutable `AnalysisSnapshot` contract with:

```python
analysis_as_of: date
source_mode: SourceMode
source_snapshot_id: str | None
```

Canonical provenance:

```text
API mode:
  analysis_as_of = source_snapshot.source_as_of
  source_mode = SourceMode.API
  source_snapshot_id = source_snapshot.source_snapshot_id

FILES mode:
  analysis_as_of = existing historically consistent FILES as_of
  source_mode = SourceMode.FILES
  source_snapshot_id = None
```

API mode sends source snapshot identity plus local seller inputs/settings. If a legacy request contains `as_of`, exact mismatch is a stable 400; prefer no mutable API-mode `as_of` in target contract.

Reject mixed-source requests:
- API snapshot + orders file;
- API snapshot + availability/restrictions file;
- missing/stale source snapshot ID.

Downstream code must read provenance from the resulting parent `AnalysisSnapshot`; it must not reconstruct `analysis_as_of` or source identity from a later shipment request.

Acceptance fixture must prove semantically equivalent API/FILES inputs produce equal DemandEstimate, FBO/inbound Need, Flow and seller-stock resolution while preserving different source provenance.

Exact Ozon recommendation absent → Calculated Plan remains available, Safe/Ozon comparison explicit incomplete.

Run:

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

---

## Task 10 — PR-API2 full gate

Run:

```bash
python -m pytest tests/ozon tests/api/test_ozon_sync.py tests/api/test_ozon_handoff.py -q
python -m pytest tests/analytics tests/decision tests/supply -q
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
python -m pytest -q
```

Acceptance:

```text
routine orders/availability/restrictions uploads not required in API mode
FILES fallback explicit, analytical-only and non-mixing
source_as_of deterministic/server-owned without tzdata dependency
AnalysisSnapshot provenance explicit, immutable and domain-neutral
order history sufficient by backend policy without per-SKU infinite backfill
FBS stock uses v2 endpoint
seller warehouses available in source snapshot
handoff points remote-search only
existing analytics parity preserved
```