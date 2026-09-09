# PR-API2 Ozon API Data Sources & Explicit Excel Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace routine Ozon report uploads with an immutable API source snapshot while preserving existing file importers as an explicit non-mixing fallback.

**Architecture:** Backend adapters fetch current Ozon API domains and normalize them into the existing `OrderRecord` / `AvailabilityRecord` / seller-stock evidence contracts before analysis. `OzonSourceSnapshotStore` keeps PII-safe snapshots in process memory. Full analysis accepts either one API snapshot or the legacy file bundle; source domains are never merged.

**Tech Stack:** Python 3.13.14, existing OzonClient, frozen dataclasses, FastAPI, pytest; no database and no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- `source_mode` is exactly `API` or `FILES` for one analysis run.
- Never silently fill missing API data from files or vice versa.
- API adapters target existing analysis contracts; do not rewrite analytics.
- Discard buyer/address/phone/email payload fields before source snapshot assembly.
- Exact 56-day Ozon recommendation is not fabricated in API mode.
- Current FBO stock and inbound remain distinct; prove no double counting.
- Source refresh is explicit; changing horizon/inbound settings does not refetch Ozon.
- API snapshots are memory-only in this milestone.

---

### Task 1: Define API source snapshot and in-memory store

**Files:**
- Create: `backend/ozon/source_contracts.py`
- Create: `backend/ozon/source_store.py`
- Create: `tests/ozon/test_source_store.py`

**Interfaces:**

```python
class SourceMode(str, Enum):
    API = "api"
    FILES = "files"

@dataclass(frozen=True, slots=True)
class EndpointEvidence:
    name: str
    fetched_at_utc: str
    record_count: int
    complete: bool
    diagnostics: tuple[ImportDiagnostic, ...]

@dataclass(frozen=True, slots=True)
class OzonSourceSnapshot:
    source_snapshot_id: str
    synced_at_utc: str
    as_of: date
    history_from: date
    history_to: date
    orders: tuple[OrderRecord, ...]
    availability: tuple[AvailabilityRecord, ...]
    operational_seller_stock: tuple[AvailabilityRecord, ...]
    clusters: tuple
    handoff_points: tuple
    placement_zones: tuple
    endpoint_evidence: tuple[EndpointEvidence, ...]
    diagnostics: tuple[ImportDiagnostic, ...]
```

```python
class OzonSourceSnapshotStore:
    def put(self, snapshot: OzonSourceSnapshot) -> None: ...
    def get(self, snapshot_id: str) -> OzonSourceSnapshot: ...
    def latest(self) -> OzonSourceSnapshot | None: ...
```

- [ ] **Step 1: Write immutability/identity/not-found tests and prove the store is memory-only.**
- [ ] **Step 2: Run RED, implement bounded store retaining only a small fixed number of recent snapshots (for example 3) for stale-response safety, run GREEN.**

```bash
python -m pytest tests/ozon/test_source_store.py -q
```

- [ ] **Step 3: Commit.**

```bash
git add backend/ozon/source_contracts.py backend/ozon/source_store.py tests/ozon/test_source_store.py
git commit -m "feat: define Ozon API source snapshots"
```

---

### Task 2: Normalize FBO/FBS postings into existing OrderRecord

**Files:**
- Create: `backend/ozon/adapters/__init__.py`
- Create: `backend/ozon/adapters/orders.py`
- Create: `tests/ozon/adapters/test_orders.py`

**Interfaces:**

```python
def fetch_fbo_orders(client: OzonClient, *, since: datetime, to: datetime) -> tuple[OrderRecord, ...]: ...
def fetch_fbs_orders(client: OzonClient, *, since: datetime, to: datetime) -> tuple[OrderRecord, ...]: ...
def fetch_orders(...) -> tuple[OrderRecord, ...]: ...
```

Endpoint registry:

```text
POST /v3/posting/fbo/list
POST /v4/posting/fbs/list
```

- [ ] **Step 1: Add pagination fixtures with at least two pages and assert destination/origin cluster, SKU/article/name, quantity, lifecycle timestamps/status and seller price normalize to the existing whitelist.**
- [ ] **Step 2: Add a PII fixture containing buyer/address/phone/email-like fields and assert none survive `OrderRecord` or logs.**
- [ ] **Step 3: Add parity fixture: normalize a representative API response and equivalent current orders file, then assert equality for every field consumed by current analytics.**
- [ ] **Step 4: Run RED, implement adapters/pagination, run GREEN.**

```bash
python -m pytest tests/ozon/adapters/test_orders.py -q
```

- [ ] **Step 5: Commit.**

```bash
git add backend/ozon/adapters tests/ozon/adapters/test_orders.py
git commit -m "feat: ingest Ozon postings from API"
```

---

### Task 3: Normalize current FBO stock and seller stock

**Files:**
- Create: `backend/ozon/adapters/stocks.py`
- Create: `tests/ozon/adapters/test_stocks.py`

**Interfaces:**

```python
def fetch_fbo_stock(client: OzonClient, cluster_catalog) -> tuple[AvailabilityRecord, ...]: ...
def fetch_seller_stock(client: OzonClient) -> tuple[AvailabilityRecord, ...]: ...
```

Current endpoint registry:

```text
POST /v1/analytics/stocks
POST /v1/product/info/stocks-by-warehouse/fbs
```

- [ ] **Step 1: Add FBO stock fixture and prove `available_stock_count` is mapped by canonical cluster/warehouse to `fbo_quantity`, not to seller stock.**
- [ ] **Step 2: Add seller-stock fixture and prove values reach the same evidence shape used by current seller-stock resolver, including explicit zero.**
- [ ] **Step 3: Add conflict fixture proving duplicate positive seller-stock evidence remains visible to the existing resolver rather than being silently summed/maxed.**
- [ ] **Step 4: Add API-vs-file parity fixture for FBO/FBS fields actually consumed by analysis.**
- [ ] **Step 5: Run RED, implement, run GREEN and commit.**

```bash
python -m pytest tests/ozon/adapters/test_stocks.py -q
git add backend/ozon/adapters/stocks.py tests/ozon/adapters/test_stocks.py
git commit -m "feat: ingest Ozon stocks from API"
```

---

### Task 4: Build inbound from active supply orders without double counting

**Files:**
- Create: `backend/ozon/adapters/inbound.py`
- Create: `tests/ozon/adapters/test_inbound.py`

**Interfaces:**

```python
class SupplyOrderState(str, Enum): ...

def fetch_inbound(client: OzonClient, cluster_catalog) -> tuple[AvailabilityRecord, ...]: ...
```

Endpoint registry:

```text
POST /v3/supply-order/list
POST /v3/supply-order/get
POST /v1/supply-order/bundle
```

- [ ] **Step 1: Characterize all currently reviewed supply-order states in one explicit classifier. Count only states where quantity is still inbound and not yet available FBO stock. Exclude `COMPLETED`, `CANCELLED`, rejected/final states. Unknown states remain diagnostic/incomplete rather than silently counted.**
- [ ] **Step 2: Add fixture with one active, one completed, one cancelled and one unknown-state order; assert only active quantity becomes `inbound_quantity`.**
- [ ] **Step 3: Add warehouse→cluster resolution test and duplicate bundle-line aggregation test keyed by `SKU × destination cluster`.**
- [ ] **Step 4: Add no-double-subtraction acceptance fixture: existing FBO quantity plus active inbound produces exactly the same Need result as an equivalent current availability file.**
- [ ] **Step 5: Run RED, implement, run GREEN and commit.**

```bash
python -m pytest tests/ozon/adapters/test_inbound.py tests/decision/test_need.py -q
git add backend/ozon/adapters/inbound.py tests/ozon/adapters/test_inbound.py
git commit -m "feat: derive inbound stock from Ozon supplies"
```

---

### Task 5: Fetch canonical clusters, warehouses, hand-off points and placement zones

**Files:**
- Create: `backend/ozon/adapters/catalog.py`
- Create: `backend/ozon/adapters/placement_zones.py`
- Create: `tests/ozon/adapters/test_catalog.py`
- Create: `tests/ozon/adapters/test_placement_zones.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OzonCluster: ...
@dataclass(frozen=True, slots=True)
class HandoffPoint:
    warehouse_id: int
    name: str
    address: str
    point_type: str
    cluster_id: str | None

def fetch_cluster_catalog(client: OzonClient) -> tuple[OzonCluster, ...]: ...
def fetch_handoff_points(client: OzonClient) -> tuple[HandoffPoint, ...]: ...
def fetch_placement_zones(client: OzonClient, sku_ids: Iterable[str]) -> tuple: ...
```

Endpoint registry:

```text
POST /v2/cluster/list
POST /v1/cluster/list
POST /v1/warehouse/fbo/list
POST /v1/product/placement-zone/info
```

- [ ] **Step 1: Add catalog fixtures and prove stable cluster identity is separated from display name/address.**
- [ ] **Step 2: Add hand-off fixture and retain concrete Ozon warehouse ID required later for cross-dock draft creation.**
- [ ] **Step 3: Add placement-zone fixture preserving Ozon zone/unknown evidence without dimension-based inference.**
- [ ] **Step 4: Run RED, implement adapters, run GREEN and commit.**

```bash
python -m pytest tests/ozon/adapters/test_catalog.py tests/ozon/adapters/test_placement_zones.py -q
git add backend/ozon/adapters/catalog.py backend/ozon/adapters/placement_zones.py tests/ozon/adapters
git commit -m "feat: ingest Ozon supply catalogs"
```

---

### Task 6: Assemble one explicit API sync operation

**Files:**
- Create: `backend/ozon/sync.py`
- Modify: `backend/api.py`
- Create: `tests/api/test_ozon_sync.py`

**Interfaces:**

```python
def sync_ozon_source(client: OzonClient, *, as_of: date, history_from: date, progress_callback=None) -> OzonSourceSnapshot: ...
```

```text
POST /api/ozon/sync
GET  /api/ozon/source/{source_snapshot_id}/status
```

- [ ] **Step 1: Add sync test with fake client responses for all endpoint families and assert one immutable PII-safe snapshot is stored.**
- [ ] **Step 2: Add partial-domain failure test: endpoint diagnostics identify the failed source; do not silently borrow file data. Define which missing domains block full analysis and which only disable a comparison.**
- [ ] **Step 3: Add progress-stage test (`orders`, `stocks`, `inbound`, `catalog`, `zones`, `complete`) with stable sequence and previous snapshot preserved on failed refresh.**
- [ ] **Step 4: Run RED, implement sync endpoint/store wiring, run GREEN.**

```bash
python -m pytest tests/api/test_ozon_sync.py -q
```

- [ ] **Step 5: Commit.**

```bash
git add backend/ozon/sync.py backend/api.py tests/api/test_ozon_sync.py
git commit -m "feat: synchronize Ozon source data"
```

---

### Task 7: Let existing analysis consume API snapshot OR files, never both

**Files:**
- Modify: `backend/api.py`
- Modify: `backend/application.py` only if a thin prepared-input adapter is necessary; do not rewrite `analyze()` formulas.
- Modify: `tests/api/test_analysis.py`
- Modify: `tests/api/test_product_completion_acceptance.py`

**Wire contract:**

FILES keeps existing multipart behavior.

API mode sends a source snapshot identity plus Unitka/economics settings needed locally, for example:

```text
source_mode=api
source_snapshot_id=<id>
as_of=<must match snapshot basis>
unitka_file=<local seller economics>
...
```

- [ ] **Step 1: Add API-mode acceptance fixture and assert existing `DemandEstimate`, FBO/inbound Need, Flow and resolved seller stock equal a semantically equivalent FILES-mode fixture.**
- [ ] **Step 2: Add mixed-source rejection tests: API snapshot + `orders_file`, API snapshot + availability/restrictions files, and missing API snapshot ID return stable 400 errors.**
- [ ] **Step 3: Add exact-Ozon-recommendation-missing test proving Calculated Plan still works while Ozon/Safe comparison is explicit incomplete rather than replaced by another analytics metric.**
- [ ] **Step 4: Implement a prepared-source adapter that feeds existing domain tuples into current analysis orchestration. Do not fork analytics by source mode.**
- [ ] **Step 5: Run focused acceptance.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 6: Commit.**

```bash
git add backend/api.py backend/application.py tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py
git commit -m "feat: analyze from Ozon API snapshots"
```

---

### Task 8: PR-API2 regression/parity gate

- [ ] **Step 1: Run all Ozon source tests.**

```bash
python -m pytest tests/ozon tests/api/test_ozon_sync.py -q
```

- [ ] **Step 2: Run analytics/decision/supply regressions.**

```bash
python -m pytest tests/analytics tests/decision tests/supply -q
```

- [ ] **Step 3: Run existing analysis transports including `/api/analysis/stream` tests in `tests/api/test_analysis.py`.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 4: Run full suite.**

```bash
python -m pytest -q
```

Acceptance: normal API mode no longer needs routine Ozon orders/availability/restrictions report uploads; FILES remains explicit fallback; no API/file merge exists; existing analytics are parity-proven.
