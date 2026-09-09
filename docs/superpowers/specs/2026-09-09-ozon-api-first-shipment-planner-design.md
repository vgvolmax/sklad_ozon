# Ozon API-First Shipment Planner — Canonical Design

**Date:** 2026-09-09  
**Status:** APPROVED / ACTIVE SOURCE OF TRUTH  
**Scope:** API-first data acquisition and operational FBO shipment planning downstream of the already-built Product Completion analytics.

This document is self-contained for the active roadmap. Archived shipment/network designs and prior correction overlays are historical only.

## 1. Product outcome

The application must answer with minimal manual Ozon-report work:

> what quantity to ship, to which destination clusters, through which Ozon hand-off point/method, from which seller warehouse where required, and which currently observed Ozon timeslot is the best operational option.

The application does **not** create the final Ozon supply request in this milestone. Temporary Ozon drafts are allowed only for validation and timeslot discovery. The user remains the final actor who creates/confirms the real supply in Ozon. XLSX/ZIP export remains the manual hand-off.

Canonical flow:

```text
Ozon API sync
→ immutable normalized source snapshot
→ existing Product Completion analysis
→ Calculated Plan
→ existing resolved seller stock + pack multiplicity + unit volume
→ all-cluster whole-pack ShippablePlan
→ shipment intent (scope/date/method/seller warehouse/handoff)
→ bounded CandidateShipment set
→ temporary Ozon draft validation
→ /v2 draft info + warehouse/travel evidence
→ /v2 live timeslots
→ ranked ValidatedShipmentOptions
→ exact XLSX/ZIP
→ user performs final real Ozon action manually
```

## 2. Non-goals — do not implement

Active PRs MUST NOT:

- rewrite destination demand, DemandEstimate, stockout, clean-route history, historical Flow or route economics;
- change current FBO/inbound Need semantics;
- change Safe/Calculated Plan meaning;
- create a second seller-stock resolver;
- merge API and FILES evidence inside one analysis run;
- use `RouteCostIndex` / `DirectRouteQuote` as seller→Ozon inbound-cost evidence;
- brute-force all cluster subsets with Ozon drafts;
- call Ozon Seller API from frontend JavaScript;
- expose Client-Id/API-Key/password to URLs, logs, snapshots, Project JSON or persistent frontend state;
- create the real supply request (`POST /v2/draft/supply/create`);
- create cargo places, pallets, labels, passes or other post-creation logistics artifacts;
- claim a temporary draft/timeslot is booked or confirmed;
- add a database, cloud service, frontend framework or background worker architecture.

Future `PR-F — Ozon Supply Execution` requires a separate approved design.

## 3. Upstream analytical ownership stays unchanged

### 3.1 Destination owns demand

`destination_cluster` is customer-demand geography. Fulfillment origin never creates destination demand.

### 3.2 Need

Existing formula remains authoritative:

```text
raw_need = raw_demand_forecast
         - current_fbo_stock
         - inbound_qty          # only when include_inbound=true

calculated_need_qty = max(0, ceil(raw_need))
```

Missing evidence remains unknown; it is never coerced to zero for convenience.

### 3.3 Plan families

- Calculated Plan remains primary `Наш план`.
- Safe Plan remains a conservative comparison only when exact comparable Ozon recommendation evidence exists.
- API mode must not substitute turnover or another metric for the exact Ozon recommendation merely to make Safe Plan complete.
- If that signal is absent, the comparison is explicitly incomplete; Calculated Plan remains usable.

### 3.4 Seller stock

The existing runtime resolution is authoritative. Operational/FBS evidence wins when present; conflicting positive evidence remains blocking; explicit zero remains known zero; `ProductEconomicsInput.available_qty` is only the already-permitted fallback.

Shipment code consumes the resolved result. It does not resolve seller stock again.

### 3.5 Product volume

`ProductEconomicsInput.volume_liters` remains canonical unit volume.

## 4. Source architecture: API first, FILES explicit fallback

Exactly one source mode owns a full analysis run:

```text
API
or
FILES
```

No row/domain/SKU/cluster merge is allowed between modes. API failure never silently switches to FILES.

### 4.1 Immutable API source snapshot

`POST /api/ozon/sync` creates a PII-safe in-memory snapshot:

```text
OzonSourceSnapshot
  source_snapshot_id
  synced_at_utc
  source_as_of
  source_timezone = "UTC+03:00"
  history_from
  history_to
  orders
  availability
  operational_seller_stock
  cluster_catalog
  seller_warehouses
  placement_zone_evidence
  endpoint_evidence
  diagnostics
```

There is intentionally **no bulk handoff-point catalog** in the source snapshot.

Raw buyer/address/phone/email payload fields are discarded before snapshot assembly. Seller-warehouse contacts/courier comments are also discarded; only fields needed for identity/presentation are retained.

Snapshots are process-memory only. Restart requires unlock + sync again.

### 4.2 `source_as_of` ownership and timezone

Current Ozon stock/inbound evidence must never be relabelled with an arbitrary browser date.

Canonical dependency-free policy:

```text
synced_at_utc = backend UTC timestamp when sync evidence is assembled
business offset = UTC+03:00
source_timezone = "UTC+03:00"
source_as_of = calendar date of synced_at_utc converted using datetime.timezone(timedelta(hours=3))
```

Do not add `zoneinfo`/IANA `tzdata` merely to compute this fixed-offset Moscow business date in the portable Windows runtime.

For API mode:

```text
analysis_as_of = source_snapshot.source_as_of
```

The browser does not choose a historical `as_of`. If a compatibility request still contains `as_of`, backend requires exact equality or rejects it.

Arbitrary historical `as_of` belongs only to a historically consistent source workflow (currently FILES), never to current API stock.

### 4.3 Order-history depth

The demand engine needs up to eight eligible completed weeks and already has 4–7 / 1–3 week fallbacks.

API sync owns the historical window; the browser does not pick an arbitrary shallow range.

Default policy:

```text
initial completed-week lookback = 12 ISO weeks
current partial week may also be fetched for lifecycle/Flow evidence
backfill increment = 4 weeks
maximum lookback = 52 weeks
```

The adapter starts far enough back to cover 12 completed ISO weeks before the current UTC+03:00 business week. If **source-wide** data-quality gaps mean fewer than eight usable completed calendar weeks are available at all, it may backfill in 4-week chunks up to 52 weeks.

Do not backfill indefinitely per new/slow SKU. If an individual `SKU × destination` still has fewer than eight eligible weeks, existing short-history demand fallback applies and its confidence remains lower.

Endpoint-specific page/date-window limits are handled inside adapters; they do not change the analytical history policy.

### 4.4 Capability matrix for partial API evidence

Do not collapse source completeness into one global boolean:

- orders/postings missing → demand/Flow dependent on that history is blocked;
- unresolved cluster identity → affected evidence blocked/diagnostic, never guessed from display names;
- current FBO missing → affected Need is unknown/incomplete, not zero;
- inbound missing matters only when `include_inbound=true`; if enabled it remains unknown/incomplete;
- seller stock missing → historical demand/Need may remain valid but operational allocation is incomplete for affected SKU;
- exact Ozon recommendation missing → only Ozon/Safe comparison is incomplete;
- placement zone missing → only method compatibility is incomplete;
- handoff search is not part of sync completeness;
- unit volume/multiplicity are operational prerequisites, not demand prerequisites.

A failed refresh preserves the previous valid snapshot and exposes causal endpoint diagnostics.

## 5. Reviewed Ozon endpoint registry

All external paths live in one backend registry. Frontend never knows Ozon endpoint strings.

### 5.1 Historical orders

```text
POST /v3/posting/fbo/list
POST /v4/posting/fbs/list
```

Normalize only the fields needed by existing `OrderRecord` semantics.

### 5.2 Current FBO stock

```text
POST /v1/analytics/stocks
```

Maps current warehouse/cluster stock to existing FBO availability evidence. `/v2/analytics/stock_on_warehouses` is not the new architecture owner.

### 5.3 Inbound FBO supply

Build inbound only from current supply-order evidence:

```text
POST /v3/supply-order/list
POST /v3/supply-order/get
POST /v1/supply-order/bundle
```

Only states not yet available as FBO stock contribute. Completed/cancelled/rejected/final states do not. Unknown states are diagnostic/incomplete. Tests must prove no double subtraction with current FBO stock.

### 5.4 Seller/FBS stock

Canonical current endpoint:

```text
POST /v2/product/info/stocks-by-warehouse/fbs
```

Do not implement the deprecated `/v1/product/info/stocks-by-warehouse/fbs` path.

### 5.5 Clusters

```text
POST /v2/cluster/list
POST /v1/cluster/list
```

Cluster IDs are canonical; display names never become identity by fuzzy matching.

### 5.6 Seller warehouses

```text
POST /v1/warehouse/fbo/seller/list
```

Normalize active seller warehouses into:

```text
SellerWarehouse
  seller_warehouse_id: int
  name/display label when returned
  address summary when returned
  is_active
  is_pickup when returned
```

Discard contacts and courier comments.

Seller warehouses are a small sync-owned catalog and belong in `OzonSourceSnapshot`.

### 5.7 Hand-off points

```text
POST /v1/warehouse/fbo/list
```

This is **remote search**, not bulk sync. Current contract requires supply-type filter and `search` with at least 4 trimmed characters.

Local flow:

```text
query >=4
→ POST /api/ozon/handoff/search
→ backend Ozon search
→ HandoffPoint[]
→ process-memory HandoffPointStore keyed by warehouse_id
```

Persisted preferred IDs are preferences only. After restart they must be resolved again. Unknown/stale frontend IDs fail before draft creation.

### 5.8 Placement zone

```text
POST /v1/product/placement-zone/info
```

Preserve Ozon evidence; do not infer replacement zones from dimensions.

### 5.9 Temporary supply validation

Use only current method-specific draft flow:

```text
POST /v1/draft/crossdock/create
POST /v1/draft/direct/create
POST /v1/draft/multi-cluster/create
POST /v2/draft/create/info
POST /v2/draft/timeslot/info
```

Forbidden:

```text
POST /v2/draft/supply/create
```

`draft_id` is integer/int64 identity.

## 6. Credential vault

Secrets live only in:

```text
data/ozon-credentials.json
```

Canonical v1 scheme:

```text
password UTF-8
→ hashlib.scrypt(n=32768, r=8, p=1, dklen=32, random 16-byte salt)
→ AES-256-GCM(random 12-byte nonce)
AAD = "sklad_ozon:ozon-vault:v1"
```

Vault JSON stores version/KDF/cipher metadata and ciphertext. Password is never stored. Forgotten password has no recovery path; reset vault and enter Ozon credentials again.

After unlock, decrypted credentials remain backend-memory-only until manual lock or process exit. No inactivity timeout.

Frontend receives only configured/locked state, masked Client-Id suffix and last connection check. Saved API key is never returned.

## 7. Ozon HTTP client

Backend-only fixed host:

```text
https://api-seller.ozon.ru
```

Use the standard-library synchronous HTTP stack in a dedicated client. Required behavior:

- finite request/socket timeout covering connection/read blocking;
- JSON encoding/decoding;
- secret headers injected only inside client;
- stable normalized errors and redacted correlation IDs;
- pagination helpers and cancellation between pages;
- bounded retry for retry-safe reads on 429/selected 5xx respecting `Retry-After`;
- **no blind retry** for draft creation after ambiguous transport failure (`DRAFT_CREATE_OUTCOME_UNKNOWN`).

Do not add another HTTP framework solely to manufacture independent connect/read timeout knobs.

## 8. Supplier pack multiplicity

Source:

```text
sheet: Прайс списком
КОД → seller article
Упак → positive integer to the right of '/'
```

Examples: `36/6→6`, `54/9→9`, `100+/1→1`.

Article normalization:

```text
"40750" → "40750"
40750 → "40750"
40750.0 → "40750"
40750.5 → invalid/diagnostic
blank → invalid
```

Alphanumeric string articles remain trimmed strings. Missing/conflicting multiplicity blocks operational exportability; never default to `1`. `Оглавление!КРАТНОСТЬ` is not product multiplicity.

## 9. Whole-pack ShippablePlan

Build once across **all clusters** before shipment selection:

```text
Calculated Plan
+ existing resolved seller stock
+ pack multiple
+ canonical unit volume
→ ShippablePlan
```

Every positive line satisfies:

```text
qty % pack_multiple == 0
sum(qty for SKU) <= resolved seller stock
```

Pack rounding is an operational adjustment, not additional demand.

Selected shipment clusters later are **filter-only**. They never trigger seller-stock reallocation.

Carry immutable `analysis_as_of` and source identity into ShippablePlan.

## 10. Shipment intent

```text
ShipmentScenario
  selected_cluster_ids
  date_from
  date_to
  allowed_methods
  preferred_clusters_per_shipment
  max_clusters_per_shipment
  seller_warehouse_id: int | None
  selected_handoff_point_ids
```

Methods:

```text
PVZ_CROSSDOCK
SC_CROSSDOCK
DIRECT
```

Hard limits:

```text
DIRECT = 1 cluster
multi-cluster cross-dock = max 20 clusters
```

User limits may only reduce hard limits.

### 10.1 Seller warehouse ownership

Cross-dock and multi-cluster draft payloads require `delivery_info.seller_warehouse_id`.

Rules:

- resolve only against active `SellerWarehouse` records from the current source snapshot;
- if exactly one active seller warehouse exists, backend may deterministically use it when scenario omits the ID;
- if more than one active warehouse exists, user must explicitly choose `Склад отправления` before cross-dock candidate validation;
- stale/inactive/unknown IDs fail closed before external draft creation;
- DIRECT does not require this cross-dock `delivery_info` field.

### 10.2 Hand-off point ownership

Cross-dock also requires a concrete current hand-off point resolved from `HandoffPointStore`. A method label alone is insufficient.

## 11. Candidate Shipment Builder

Pure/deterministic; **does not call Ozon**.

Input:

```text
ShippablePlan
ShipmentScenario
resolved active SellerWarehouse when required
resolved HandoffPoint records when required
method-rule registry
```

Output: bounded `CandidateShipment[]`.

Each `CandidateAssignment` keeps at least:

```text
sku
article
destination_cluster_id
quantity
pack_multiple
unit_volume_l
total_volume_l
placement_zone_kind
placement_zones
```

Each cross-dock candidate also carries resolved `seller_warehouse_id` and `handoff_point_id`.

Goals:

1. preserve exact existing shippable quantities;
2. filter selected clusters only;
3. group urgent/compatible clusters deterministically;
4. respect hard/user cluster limits;
5. apply local method/zone rules;
6. minimize needless fragmentation;
7. emit only a small set worth checking externally.

No subset brute force.

### 11.1 PVZ volume rule

PVZ 1000 L is a **candidate-total estimated item-volume** pre-check:

```text
CandidateShipment.total_volume_l > 1000
→ local block/split
```

It is not a per-line rule. `<=1000 L` means only `Предварительно подходит`; it does not prove packed cargo volume, box count, per-box weight or exact point acceptance.

Placement zones survive to candidate and manifest. Multiple zones may trigger manual packing guidance but do not auto-split supply requests solely by zone.

## 12. Bounded live validation

`Найти варианты в Ozon` is explicit user action.

Default external budget:

```text
max_new_drafts_per_user_run = 6
```

Backend also enforces current Ozon external limits. Repeated identical candidate checks may reuse short-lived process-memory evidence keyed by candidate fingerprint.

Flow:

```text
CandidateShipment
→ create method-specific temporary draft
→ /v2/draft/create/info
→ accepted/rejected + warehouse scoring/travel evidence
→ /v2/draft/timeslot/info
→ ValidatedShipmentOption
```

For cross-dock/multi-cluster create payloads, `delivery_info` contains both:

```text
seller_warehouse_id
and
resolved drop_off_warehouse { warehouse_id, warehouse_type }
```

Do not invent point type; use normalized Ozon search evidence.

Causal outcomes stay separate:

```text
Ozon rejected composition
no timeslot
rate limited
transport unavailable
unknown draft-create outcome
local incompatibility
```

Timeslot availability is observed evidence, not a booking.

## 13. Operational ranking

Ranking optimizes operational/service-level usefulness only:

1. accepted by Ozon;
2. has timeslot in requested range;
3. protects earliest known urgency;
4. latest still-on-time opportunity among equivalents;
5. lower fragmentation / more covered assignment volume;
6. user seller-warehouse/handoff preference where applicable;
7. stable candidate ID.

Do not claim cheapest/economically optimal inbound supply without a separate seller→FBO tariff contract.

## 14. Product identity and export

UI is article-first in presentation but **SKU is canonical selector/state identity**.

Never collapse two Ozon SKUs because they share one seller article.

Before aggregating export rows for one `article + destination_cluster`, all rows must agree on:

```text
sku
article
pack_multiple
```

Conflict → stable blocking diagnostic → no XLSX/ZIP for that option. Product name is display data, not canonical identity.

Ozon workbook is exact three columns:

```text
артикул
имя (необязательно)
количество
```

No helper/zone columns. One cluster → XLSX; multiple clusters → ZIP with one XLSX per cluster.

## 15. UI target

Top-level routes remain exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Inside `План`:

```text
Товары | Отгрузки
```

- `Товары`: bounded article-first/SKU-backed selector and selected-product workspace.
- `Отгрузки`: date/method/cluster intent, seller warehouse when needed, remote handoff search, explicit external validation and logistics manifests.
- `Данные`: Ozon connection/sync primary; FILES manual import secondary and explicit.

Distinguish:

```text
Кандидат
Проверено Ozon
реальная заявка на поставку  # not implemented
```

Never show `Поставка создана`, `Забронировано` or equivalent before future PR-F.

## 16. Active implementation sequence

```text
PR-API1  Ozon API core + encrypted vault
PR-API2  API sources + source snapshot + seller warehouses + remote handoff search + FILES fallback
PR-A     supply facts + supplier pack multiplicity
PR-B     all-cluster whole-pack ShippablePlan
PR-C     deterministic candidate builder
PR-API3  temporary draft validation + live timeslots
PR-D     ranking/orchestration + exact export
PR-E     API-first Data/Plan/Shipment UI + root design-contract migration
```

Each PR owns only its layer. Do not collapse the roadmap.

## 17. Acceptance invariants

A context-free implementation must be able to answer:

```text
Who owns API analysis date?             backend source snapshot, fixed UTC+03:00 business date
Can browser relabel current stock?      no
Default order-history coverage?         12 completed weeks, bounded backfill to max 52 when source-wide gaps require it
What if an SKU has only 4 weeks?        existing short-history demand fallback
Canonical FBS stock endpoint?           /v2/product/info/stocks-by-warehouse/fbs
Are handoff points bulk-synced?         no, remote search >=4 chars
Where do seller warehouses come from?   /v1/warehouse/fbo/seller/list in source sync
Crossdock seller warehouse required?    yes; auto only when exactly one active
Can selected clusters reallocate stock? no, filter-only
Is PVZ 1000 L per line?                 no, candidate total
Do placement zones survive?             yes, to manifest
What is selector identity?              SKU
Can conflicting same article merge?     no, fail closed
What type is draft_id?                  int/int64
Does temporary validation create supply? no
Does active roadmap call /v2/draft/supply/create? no
```