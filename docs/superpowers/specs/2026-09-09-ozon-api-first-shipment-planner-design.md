# Ozon API-First Shipment Planner — Canonical Design

**Date:** 2026-09-09  
**Status:** APPROVED / ACTIVE SOURCE OF TRUTH  
**Scope:** API-first data acquisition and operational FBO shipment planning downstream of the already-built Product Completion analytics.  
**Supersedes:** every 2026-09-08 selected-network/shipment-planner design and amendment for active implementation. Those files are archived and are historical only.

## 1. Product outcome

The application must answer, with minimal manual report work:

> what quantity to ship, to which Ozon clusters, through which hand-off point/method, and which currently available Ozon timeslot is the best operational choice.

The application **does not create the final Ozon supply request in this milestone**. It may create temporary Ozon drafts only to validate candidate supplies and discover timeslots. The user remains the final actor who creates/confirms the real supply in Ozon. XLSX/ZIP export remains available as hand-off/fallback.

Canonical flow:

```text
Ozon API sync
→ normalized PII-safe source snapshot
→ existing Product Completion analysis
→ Calculated Plan
→ resolved seller stock + pack multiplicity + unit volume
→ all-cluster whole-pack ShippablePlan
→ selected shipment scope + date range + methods + hand-off points
→ bounded CandidateShipment set
→ temporary Ozon draft validation
→ live Ozon draft info + travel/warehouse evidence
→ live Ozon timeslots
→ ranked ValidatedShipmentOptions
→ XLSX/ZIP for manual execution
→ user creates/confirms the real supply in Ozon
```

## 2. Non-goals — do not implement

The active roadmap MUST NOT:

- rewrite destination demand, DemandEstimate, stockout, clean-route history or historical Flow;
- change current FBO/inbound need semantics;
- change Safe/Calculated Plan meaning;
- create a second seller-stock resolver;
- merge API and Excel rows into one analysis source;
- use RouteCostIndex/DirectRouteQuote as seller→Ozon inbound cost evidence;
- brute-force combinations of Ozon drafts;
- call Ozon Seller API from frontend JavaScript;
- expose Client-Id/API-Key to frontend state, URLs, snapshots, logs or Project JSON;
- create a real Ozon supply request;
- create cargo places, pallets, labels, passes or other post-creation logistics artifacts;
- claim a temporary draft/timeslot is a booked/confirmed real supply;
- add a database, background worker service or cloud dependency.

Future `PR-F — Ozon Supply Execution` may add the final `/v2/draft/supply/create` step only after a separate approved design. It has no active implementation plan now.

## 3. What remains canonical upstream

### 3.1 Demand ownership

`destination_cluster` remains customer-demand geography. Historical origin never becomes demand ownership.

### 3.2 Need

Existing need semantics remain authoritative:

```text
raw_need = raw_demand_forecast
         - current_fbo_stock
         - inbound_qty  # only when include_inbound=true

calculated_need_qty = max(0, ceil(raw_need))
```

Missing evidence remains unknown; frontend/backend never coerce it to zero.

### 3.3 Analytical plan families

- Calculated Plan remains primary `Наш план`.
- Safe Plan remains a conservative analytical comparison when its external Ozon recommendation evidence exists.
- The active operational/export path is based on Calculated Plan.
- API-first mode must not substitute `/v1/analytics/turnover/stocks` or another metric for the existing Ozon recommendation merely because the exact 56-day recommendation is not exposed by a verified API contract.
- If exact Ozon recommendation evidence is unavailable in API mode, Safe/Ozon comparison is explicitly incomplete; Calculated Plan and shipment planning remain usable.

### 3.4 Seller stock

The existing runtime resolution is authoritative. FBS/operational seller-stock evidence wins when present; conflicts remain blocking; explicit zero remains known zero; `ProductEconomicsInput.available_qty` is only the existing permitted fallback.

Shipment code consumes the already-resolved value. It does not re-resolve seller stock.

### 3.5 Product volume and economics

`ProductEconomicsInput.volume_liters` remains the canonical unit-volume source. Unitka remains a local input because cost/economics are seller-owned facts, not an Ozon operational-data substitute.

## 4. Source architecture: API first, files explicit fallback

### 4.1 Source modes

Exactly one operational data source mode owns a full analysis run:

```text
API
or
FILES
```

No row-level or domain-level merge is allowed between API and file modes.

Valid:

```text
API orders + API FBO stock + API inbound + API seller stock
```

or:

```text
file orders + file availability + file restrictions
```

Invalid:

```text
API orders + file FBO stock
API Moscow + file Perm
API missing SKU silently filled from Excel
```

A fallback transition is explicit and visible to the user. It never happens silently after an API failure.

### 4.2 API source snapshot

`POST /api/ozon/sync` creates an immutable in-memory `OzonSourceSnapshot` with a generated ID. The snapshot contains only normalized domain evidence needed by analysis and diagnostics; raw buyer/address/phone/email payloads are discarded before snapshot assembly.

Minimum contract:

```text
OzonSourceSnapshot
  source_snapshot_id
  synced_at_utc
  as_of
  history_from
  history_to
  orders: tuple[OrderRecord, ...]
  availability: tuple[AvailabilityRecord, ...]
  operational_seller_stock evidence
  cluster_catalog
  handoff_point_catalog
  placement_zone evidence
  endpoint_evidence
  diagnostics
```

The active process may keep the latest few snapshots in memory for stale-response safety, but persistence is not required. Restarting the application discards API source snapshots and requires unlock + sync again.

A later analytical recalculation with a different horizon/inbound flag references the same source snapshot and does not refetch Ozon unless the user chooses `Обновить данные`.

### 4.3 File fallback

Existing importers remain supported. File mode is intentionally secondary and is labelled `Ручной импорт`.

File mode keeps current behavior and can use the current restrictions workbook as conservative dated evidence. It has no live draft/timeslot capability unless the vault is unlocked and the user explicitly performs a live validation step; the source data itself still remains file-owned.

## 5. Ozon Seller API endpoint registry

All paths live in one backend registry/module. Frontend never knows endpoint paths.

Current reviewed API contracts for this milestone:

### Historical demand/fulfillment

```text
POST /v3/posting/fbo/list
POST /v4/posting/fbs/list
```

Both adapters normalize into the existing `OrderRecord` whitelist. The adapters retain only fields needed for lifecycle, SKU/article/name, quantity, origin/destination cluster and seller price/economic evidence. Raw PII is discarded immediately.

### FBO stock by warehouse/cluster

Preferred current source:

```text
POST /v1/analytics/stocks
```

It is the current stock-analytics endpoint and is treated as real-time current evidence. The adapter maps warehouse/cluster identity to `AvailabilityRecord.fbo_quantity` without changing need formulas.

`/v2/analytics/stock_on_warehouses` is legacy compatibility evidence, not the new canonical dependency. Do not build new architecture around it.

### Inbound FBO supply

Do not guess inbound from an unrelated stock metric. Build inbound from current supply-order evidence:

```text
POST /v3/supply-order/list
POST /v3/supply-order/get
POST /v1/supply-order/bundle
```

Only states that have not yet become available FBO stock contribute to `inbound_quantity`. Completed/cancelled/rejected orders do not. Warehouse/cluster mapping comes from the cluster catalog. The adapter must have parity tests proving no double counting against current FBO stock.

### Seller/FBS stock

Current endpoint registry uses the current Ozon stock-by-warehouse method available for the account, with the reviewed path:

```text
POST /v1/product/info/stocks-by-warehouse/fbs
```

If Ozon exposes a newer equivalent version, only the centralized registry/adapter changes; seller-stock business resolution does not.

### Cluster/warehouse catalogs

```text
POST /v2/cluster/list        # macro-local catalog
POST /v1/cluster/list        # cluster + fulfillment warehouses
POST /v1/warehouse/fbo/list  # concrete cross-dock/direct hand-off points
```

### Placement zone

```text
POST /v1/product/placement-zone/info
```

The app preserves Ozon's zone evidence; it does not infer a replacement zone from dimensions.

### Temporary supply validation

New draft creation uses only current non-deprecated creation methods:

```text
POST /v1/draft/crossdock/create
POST /v1/draft/direct/create
POST /v1/draft/multi-cluster/create
POST /v2/draft/create/info
POST /v2/draft/timeslot/info
```

Explicitly forbidden in this milestone:

```text
POST /v2/draft/supply/create
```

Ozon draft lifecycle constraints are operational limits, not UI decorations: drafts are temporary; draft creation is rate-limited; multi-cluster draft size is bounded; timeslot search has a bounded date window. The backend must enforce the current registry limits and expose user-readable throttling states.

## 6. Credential vault

### 6.1 Storage

Secrets live only in:

```text
data/ozon-credentials.json
```

`data/` is already gitignored. The vault file contains version/KDF/cipher metadata and ciphertext only.

Plaintext payload:

```text
client_id
api_key
```

### 6.2 Cryptography

Use standard audited primitives; no custom cipher.

Canonical scheme:

```text
password UTF-8
→ hashlib.scrypt
   n = 32768
   r = 8
   p = 1
   dklen = 32
   random 16-byte salt
→ 32-byte key
→ AES-256-GCM
   random 12-byte nonce
   AAD = "sklad_ozon:ozon-vault:v1"
```

AES-GCM comes from the pinned `cryptography` runtime dependency. Vault JSON stores base64 salt/nonce/ciphertext and exact KDF parameters. Writes are atomic (`temp → fsync where available → os.replace`).

Password is never stored. Forgotten password has no recovery path: the user deletes/resets the vault and enters Ozon credentials again.

### 6.3 Session lifetime

After successful unlock, decrypted credentials remain backend-memory-only until:

- user presses `Заблокировать`; or
- application process exits.

There is no inactivity timeout in the active milestone.

Do not claim secure zeroization of immutable Python strings/bytes. Minimize copies, remove references on lock, and never serialize plaintext.

### 6.4 Backend-only secret boundary

Frontend can receive only:

```text
configured: bool
locked: bool
masked_client_id_suffix
last_connection_check
```

It never receives stored API key or full saved credentials.

## 7. Ozon HTTP client behavior

The client is backend-only and has a fixed base URL:

```text
https://api-seller.ozon.ru
```

No frontend/user-provided arbitrary host or URL is accepted.

Use the Python standard library HTTP stack in a dedicated synchronous client, invoked from worker threads where necessary. Do not add a second HTTP framework solely for this feature.

Required behavior:

- connect/read timeouts;
- JSON encoding/decoding;
- `Client-Id` and `Api-Key` headers injected only inside the client;
- rate-limit accounting;
- stable normalized errors;
- request correlation IDs with secret redaction;
- pagination helpers;
- cancellation between page calls;
- read-only calls may retry boundedly on 429/selected 5xx with server `Retry-After` respected;
- draft-creation calls are **not blindly retried after ambiguous network failure** because duplicate temporary drafts may have been created. Surface `DRAFT_CREATE_OUTCOME_UNKNOWN` instead.

Never log request headers containing secrets or full external payloads containing buyer data.

## 8. API sync adapters and parity

API adapters must target existing domain contracts rather than duplicate analysis types.

Before API mode can replace a file source, tests must prove semantic parity for the fields used by analysis:

```text
OrderRecord destination/origin/lifecycle/quantity
AvailabilityRecord FBO quantity by cluster
AvailabilityRecord inbound quantity by cluster
seller stock evidence
cluster identity
article/SKU identity
```

A same-day API-vs-file fixture comparison is the acceptance gate for each migrated source. Differences are diagnostics, not silent normalization.

Exact Ozon 56-day recommendation parity is not required because no verified equivalent API contract is assumed. Missing recommendation makes that comparison incomplete, not the whole analysis invalid.

## 9. Pack multiplicity

Supplier pack multiplicity remains local supplier evidence.

Current source contract:

```text
sheet: Прайс списком
КОД → seller article
Упак → right-hand positive integer after '/'
```

Examples:

```text
36/6 → 6
54/9 → 9
100+/1 → 1
```

`Оглавление!КРАТНОСТЬ` is not product multiplicity.

Missing/conflicting multiplicity blocks exportable operational quantity for that SKU; never default silently to `1`.

## 10. Whole-pack ShippablePlan

The operational whole-pack layer is built once for the full current analysis, before user shipment-scope selection.

```text
analytical Calculated Plan
+ resolved seller stock
+ pack multiplicity
+ canonical unit volume
→ ShippablePlan
```

Every positive line satisfies:

```text
shippable_qty % pack_multiple == 0
sum(shippable_qty for SKU) <= resolved_seller_stock
```

Pack rounding is visible as operational adjustment, never additional demand.

Cluster selection later is **filter-only**. It never reallocates seller stock among the selected subset.

Live Ozon draft validation is the final current authority for whether the proposed quantity/cluster combination can actually be accepted. Static file `max_supply_qty` is fallback evidence only.

## 11. Shipment intent and hand-off points

The user controls intent, not fake availability.

Scenario contract:

```text
ShipmentScenario
  selected_cluster_ids
  date_from
  date_to
  allowed_methods
  preferred_clusters_per_shipment
  max_clusters_per_shipment
  selected_handoff_point_ids
```

Supported methods:

```text
PVZ_CROSSDOCK
SC_CROSSDOCK
DIRECT
```

For cross-dock validation, the scenario must contain one or more concrete hand-off point IDs returned by `/v1/warehouse/fbo/list`. A method label alone is insufficient to create a real draft.

The UI lets the user search/select Ozon hand-off points and may persist non-secret preferred point IDs/order in Project JSON.

DIRECT does not use a cross-dock hand-off point.

Hard cluster limits belong to backend method rules:

```text
DIRECT = 1 cluster
multi-cluster cross-dock = max 20 clusters
```

User limits may only reduce a hard method limit.

## 12. Candidate Shipment Builder

The builder is pure/deterministic and **does not call Ozon**.

Input:

```text
ShippablePlan
ShipmentScenario
method rule registry
```

Output:

```text
CandidateShipment[]
```

Candidate goals:

1. preserve exact existing shippable quantities;
2. group urgent/compatible clusters;
3. respect hard/user cluster count limits;
4. respect preliminary item-volume ceilings;
5. respect placement-zone compatibility known locally;
6. minimize needless fragmentation;
7. produce only a small deterministic set worth validating externally.

The candidate builder never says `окно доступно` or `Ozon принял`.

## 13. Bounded live validation

`Найти варианты в Ozon` is an explicit user action. It may create temporary Ozon drafts; UI copy states that temporary drafts are created for checking and no real supply request is created.

Validation flow:

```text
CandidateShipment
→ create appropriate temporary draft
→ poll /v2/draft/create/info until terminal/timeout
→ capture accepted/rejected item/cluster/warehouse evidence
→ query /v2/draft/timeslot/info for requested date range
→ ValidatedShipmentOption
```

### 13.1 Bounded search

Do not enumerate cluster subsets.

Default run budget:

```text
max_new_drafts_per_user_run = 6
```

The backend also obeys Ozon's current per-minute/hour/day limits. It may return fewer validated options when the remaining external budget is insufficient.

Candidate order is deterministic so stopping at the budget boundary remains explainable.

Repeated identical candidate validation within the temporary-draft lifetime may reuse cached validation evidence keyed by candidate fingerprint; cache never survives process restart.

### 13.2 Date range

The user chooses a date range. Backend clamps/rejects a range outside the current Ozon timeslot API maximum window rather than inventing availability.

### 13.3 Failure semantics

Keep separate:

```text
OZON_REJECTED_CANDIDATE   # business validation response
NO_TIMESLOT               # draft valid, requested period has no slot
OZON_RATE_LIMITED         # temporary external throttle
OZON_UNAVAILABLE          # transport/service failure
DRAFT_CREATE_OUTCOME_UNKNOWN
LOCAL_CANDIDATE_BLOCKED   # never sent because local hard rule failed
```

An Ozon transport error never becomes `товар запрещён`.

## 14. PVZ and placement-zone semantics

Local volume uses item volume only and is a preliminary gate. It is not a packed-cargo model.

For PVZ:

- configured/current planning item-volume ceiling may reject an obviously too-large candidate;
- passing the item-volume check means `Предварительно подходит`, not confirmed acceptance;
- draft/timeslot evidence is stronger than the local check;
- actual box count, per-box weight, packed outer volume, point-specific rules and final booking remain outside the local model;
- KGT and unknown/multiple zone evidence are not auto-assigned to PVZ unless Ozon draft validation proves a usable path under a later explicit rule;
- shipment detail shows zone composition and manual cargo-separation guidance where relevant;
- XLSX never gains helper zone columns.

## 15. Ranking validated options

Ranking is operational, not cost optimization.

Order of preference:

1. candidate accepted by Ozon;
2. has a timeslot in the user's requested period;
3. protects earliest explainable stockout/urgency;
4. chooses the latest still-on-time slot when several are equivalent;
5. reduces shipment fragmentation;
6. prefers user's hand-off point priority;
7. stable ID tie-break.

Do not call the result `самый дешёвый` or `экономически оптимальный` without a separate seller→Ozon supply-tariff model.

`RouteCostIndex` and current customer-delivery route economics never enter this ranking.

## 16. Local API boundary

Active local endpoints by the end of the roadmap:

```text
GET  /api/ozon/credentials/status
POST /api/ozon/credentials/setup
POST /api/ozon/credentials/unlock
POST /api/ozon/credentials/lock
POST /api/ozon/connection/test
POST /api/ozon/sync
GET  /api/ozon/source/{source_snapshot_id}/status
POST /api/analysis              # supports FILES or API source mode
POST /api/analysis/stream       # same ownership with progress
POST /api/shipment/candidates
POST /api/shipment/validate
POST /api/shipment/export
```

Endpoint names may be implemented under the existing router file structure, but ownership must remain clear: credentials/client, source sync, analysis, candidate builder, external validation, export.

No endpoint in this milestone creates the final supply order.

## 17. Export

Manual execution remains first-class.

One workbook corresponds to one cluster within one planned shipment and has exactly:

```text
артикул
имя (необязательно)
количество
```

Multi-cluster shipment → ZIP with one XLSX per cluster.

Export consumes a validated/ranked option's assignments but does not recalculate demand or alter quantities. If a line was rejected by Ozon, it is excluded from an exportable accepted option and remains visible as rejected/unscheduled evidence in UI.

## 18. UI architecture

The active UI target is defined in `2026-09-09-api-first-plan-ui-design.md`.

Top-level sections remain:

```text
План | Потоки спроса | Экономика | Данные
```

Inside `План`:

```text
Товары | Отгрузки
```

`Товары` is article-first master/detail. `Отгрузки` is shipment intent → candidate/live validation → manifest results.

The existing historical Flow remains unchanged.

## 19. Data freshness and stale ownership

Keep separate clocks:

```text
sourceSyncedAt
analysisCalculatedAt
shipmentValidatedAt
```

Changing analytical scenario settings marks analysis stale but does not automatically resync source data.

Refreshing Ozon source data invalidates the current analysis and validated shipment options.

Changing only shipment scenario makes shipment results stale; analysis remains current.

Previous successful results remain visible during refresh/recalculation with explicit stale labels.

## 20. Security and privacy

- Secrets never leave backend memory except encrypted vault bytes.
- Vault password is never stored.
- Raw Ozon PII is discarded during API adaptation and not serialized to frontend.
- No arbitrary outbound host.
- No secrets in exception messages/logging.
- No full raw Ozon responses in normal logs.
- Project JSON stores only non-secret preferences, e.g. preferred hand-off point IDs.
- API source snapshots remain memory-only in this milestone.

## 21. Runtime constraints

SCOZ-lite architecture remains canonical:

```text
start.bat
→ project-local portable Python
→ FastAPI 127.0.0.1:17843
→ committed vanilla HTML/CSS/JS
```

No npm/framework/build system/database/background service.

One new runtime dependency is permitted for authenticated encryption: `cryptography`. It must be pinned to a wheel-compatible release for the repository's portable Python and verified by Windows portable smoke before merge of PR-API1.

## 22. Active implementation sequence

```text
PR-API1  Ozon API Core + Encrypted Credentials Vault
PR-API2  Ozon API Data Sources + Explicit Excel Fallback
PR-A     Supply Facts + Pack Multiplicity
PR-B     Whole-Pack Shippable Plan
PR-C     Candidate Shipment Builder
PR-API3  Live Ozon Draft Validation + Timeslots
PR-D     Shipment Orchestration + Ozon XLSX/ZIP Export
PR-E     API-First Article Plan + Shipment UI
```

Do not collapse these into one implementation PR.

## 23. Acceptance summary

The milestone is complete only when:

```text
user can unlock encrypted Ozon credentials without exposing the key
API sync can replace routine order/FBO/FBS/cluster data files
file mode still works explicitly as fallback
API and file records are never silently merged
existing demand/need/Flow/economics results stay regression-compatible
whole-pack quantities preserve seller-stock conservation
shipment scope is filter-only over full ShippablePlan
cross-dock uses concrete Ozon hand-off points
candidate generation is bounded and local
live validation creates only temporary drafts
Ozon rejection/timeslot/rate-limit/transport states remain distinct
validated options show real current timeslot evidence
XLSX/ZIP remains available
no real Ozon supply request is created by the application
```
