# Codex Cloud instructions

## Active source of truth

For current development, read in this order:

1. `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md` — canonical API-first shipment/data/business architecture;
2. for frontend/UI work, `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md`;
3. when touching already-built demand/stockout/Flow layers, `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`;
4. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md` for Product Completion semantics not superseded above;
5. `DESIGN.md` and `UX-CONTRACT.md` for shipped visual/behavior baseline; target Plan/Data behavior is owned by the active 2026-09-09 specs until PR-E ships and migrates root contracts;
6. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` for runtime/technical architecture;
7. exactly one matching active implementation plan from `docs/superpowers/plans/`.

There is **no active correction/amendment overlay**. Active specs/plans are consolidated and self-contained. If an archived file contradicts an active file, the active file wins and archive must not be consulted during normal implementation.

Detailed completed PR1…PR5 links inside older maintained analytical specs are historical implementation references; do not resolve them from archive unless the user explicitly asks for history/audit.

## Archive exclusion

`docs/superpowers/archive/**` contains completed, abandoned or superseded documents for historical audit only.

**Do not read, search, quote or implement from `docs/superpowers/archive/**` during normal feature development.** Open archive only when the user explicitly asks for history, rationale, comparison with old design or audit of superseded work.

Archive content has no active precedence even if an archived file says `approved`, `canonical`, `source of truth` or contains executable-looking steps.

## Active implementation sequence

Implement one PR scope at a time, in this order:

```text
PR-API1  docs/superpowers/plans/2026-09-09-pr-api1-ozon-api-core-vault-implementation.md
PR-API2  docs/superpowers/plans/2026-09-09-pr-api2-api-data-sources-fallback-implementation.md
PR-A     docs/superpowers/plans/2026-09-09-pr-a-supply-facts-pack-multiplicity-implementation.md
PR-B     docs/superpowers/plans/2026-09-09-pr-b-whole-pack-shippable-plan-implementation.md
PR-C     docs/superpowers/plans/2026-09-09-pr-c-candidate-shipment-builder-implementation.md
PR-API3  docs/superpowers/plans/2026-09-09-pr-api3-live-draft-timeslots-implementation.md
PR-D     docs/superpowers/plans/2026-09-09-pr-d-shipment-orchestration-export-implementation.md
PR-E     docs/superpowers/plans/2026-09-09-pr-e-api-first-plan-ui-implementation.md
```

Do not collapse the sequence into one implementation PR.

`PR-F — Ozon Supply Execution` is future/non-active. There is intentionally no implementation plan for it.

## Canonical analytical safeguards

- `destination_cluster` is customer-demand geography; fulfillment origin never becomes demand ownership.
- Historical Flow is evidence, not future allocation weight.
- Existing DemandEstimate, stockout, clean-route, Flow and route-economics math stays unchanged unless a later approved design explicitly changes it.
- Current FBO/inbound remain upstream Need inputs:

```text
raw_need = raw_demand_forecast - current_fbo_stock - inbound_qty  # when inbound enabled
calculated_need_qty = max(0, ceil(raw_need))
```

- Missing FBO/inbound evidence is unknown, never zero by convenience.
- Calculated Plan remains primary `Наш план`; Safe Plan is comparison only when exact comparable Ozon evidence is complete.
- Never substitute turnover/another API metric for the exact Ozon recommendation merely to make Safe complete.
- Existing seller-stock resolver is authoritative; shipment code consumes the resolved result and does not create another resolver.
- `ProductEconomicsInput.volume_liters` remains canonical unit volume.
- Supplier multiplicity comes from `Прайс списком`: normalized seller `КОД` + positive right-hand integer of `Упак`; never use `Оглавление!КРАТНОСТЬ`.
- Integer-like Excel article `40750.0` normalizes to `"40750"`; non-integer numeric article is invalid.
- Positive operational quantities are whole packs.
- Whole-pack ShippablePlan is built across all clusters before shipment selection; selected clusters are filter-only.

### Analysis provenance

Every successful `AnalysisSnapshot` must carry immutable source provenance needed by downstream shipment layers:

```text
analysis_as_of
source_mode = api | files
source_snapshot_id = API source snapshot ID | None
```

In API mode `analysis_as_of == OzonSourceSnapshot.source_as_of` and `source_snapshot_id` is required. In FILES mode `source_snapshot_id=None` and the existing historically consistent file workflow owns `analysis_as_of`. Downstream code must consume these fields from the parent analysis snapshot; it must not reconstruct provenance from a browser request.

## API-first source safeguards

Exactly one source mode owns an analysis run:

```text
API
or
FILES
```

Never silently mix sources by domain/SKU/cluster/missing-row fallback. API error never switches to FILES automatically.

API adapters normalize into existing PII-safe domain contracts; do not fork analytics by source mode.

FILES is a reserve **analytical** workflow. In the active milestone, live handoff search, temporary Ozon draft validation and timeslot discovery require an unlocked Ozon API session and API-backed source context. Do not combine a FILES analysis with live API operational catalogs/validation as a hybrid third mode.

### API source date

Use dependency-free Moscow business time:

```text
synced_at_utc = backend UTC timestamp
business offset = UTC+03:00
source_timezone = "UTC+03:00"
source_as_of = calendar date of synced_at_utc converted with datetime.timezone(timedelta(hours=3))
analysis_as_of = source_as_of in API mode
```

Do not add `zoneinfo`/`tzdata` merely for this fixed-offset business date. Browser cannot choose another historical API `as_of`.

### API order-history policy

```text
initial lookback = 12 completed ISO weeks
source-wide-gap backfill step = 4 weeks
maximum lookback = 52 weeks
```

Do not backfill indefinitely per new SKU; existing 4–7/1–3 week demand fallback owns short individual history.

### Current endpoint safeguards

- seller/FBS stock: `POST /v2/product/info/stocks-by-warehouse/fbs`; do **not** implement deprecated v1;
- seller warehouses: `POST /v1/warehouse/fbo/seller/list` as small source-sync catalog;
- handoff points: `POST /v1/warehouse/fbo/list` as remote search only, not bulk source sync;
- handoff local search requires trimmed query ≥4 chars and backend `HandoffPointStore`;
- current endpoint strings live only in backend registry/adapters.

### Capability consequences

- postings missing blocks affected demand/Flow history;
- unresolved cluster identity blocks affected evidence;
- missing FBO makes affected Need incomplete;
- inbound missing matters only when `include_inbound=true`;
- seller stock missing blocks operational allocation only;
- exact Ozon recommendation missing disables/incompletes comparison only;
- placement zone missing affects shipment compatibility only;
- handoff search is not source-sync completeness;
- unit volume/multiplicity are operational prerequisites, not demand prerequisites.

Ozon source snapshots are process-memory-only. Raw buyer/address/phone/email and seller-warehouse contacts/courier comments are discarded before normalized snapshot assembly.

## Credential/security safeguards

Vault:

```text
data/ozon-credentials.json
hashlib.scrypt(n=32768, r=8, p=1, dklen=32, random 16-byte salt)
→ AES-256-GCM(random 12-byte nonce)
AAD = "sklad_ozon:ozon-vault:v1"
```

- Password never stored.
- Decrypted Client-Id/API-Key live backend-memory-only until manual lock/process exit.
- No inactivity auto-lock.
- Saved API key never returned to frontend.
- No secrets in Project JSON, URL, logs, snapshots, errors, analytics or tests.
- Ozon API calls originate only from localhost backend to fixed `https://api-seller.ozon.ru`.
- With stdlib transport use finite request/socket timeout; do not add another HTTP framework solely for separate timeout knobs.

## Shipment-planner safeguards

Active flow:

```text
Calculated Plan
→ resolved stock + pack multiple + volume
→ full all-cluster ShippablePlan
→ shipment intent
→ resolved seller warehouse + remote-search handoff when cross-dock
→ bounded local candidates
→ temporary Ozon draft validation
→ current timeslots
→ ranked validated options
→ XLSX/ZIP
→ user performs final real supply action manually
```

- DIRECT hard max = 1 cluster.
- Multi-cluster cross-dock hard max = 20.
- Cross-dock requires concrete resolved handoff point and active seller warehouse.
- If exactly one active seller warehouse exists, backend may auto-resolve it; with >1, explicit user choice is required.
- Candidate builder is deterministic/bounded; no subset brute force.
- Default live-validation budget ≤6 new temporary drafts per user run plus external Ozon limits.
- Draft create is not blindly retried after ambiguous transport failure.
- `draft_id` is integer/int64.
- PVZ 1000 L is candidate-total estimated item-volume pre-check, not per-line and not packed-cargo proof.
- Preserve exact `placement_zones` through candidate/validated manifest.
- Ranking is operational/service-level; do not use customer-delivery route costs as inbound supply tariff.
- **Do not invent `urgency_date`, stockout date or days-late math in the shipment layer.** Urgency may influence grouping/ranking only if a later approved upstream analytical contract already exposes an immutable canonical urgency field. Otherwise omit urgency keys entirely and rank by Ozon acceptance/timeslot, lower fragmentation/covered volume, user warehouse/handoff preference and stable identity.
- No active endpoint/action may call `POST /v2/draft/supply/create` or claim a real supply was created/booked.

## Product identity/export safeguards

- UI is article-first in presentation but SKU is canonical selector/state identity.
- Never collapse different SKUs sharing one article.
- Before export aggregation for `article + destination_cluster`, all rows must agree on `sku`, `article`, `pack_multiple`.
- Conflict is blocking; never silently merge/repair.

## UI safeguards

Top-level routes exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Inside target Plan:

```text
Товары | Отгрузки
```

- `Товары`: bounded SKU-backed article-first selector + selected product workspace.
- `Отгрузки`: date/method/cluster intent, SellerWarehouseSelector where needed, remote HandoffPointSelector, explicit `Найти варианты в Ozon`, validated manifests and export.
- `Данные`: API connection/sync primary; FILES explicit reserve mode.
- FILES mode does not expose live Ozon shipment validation; direct the user back to API mode for handoff search/draft/timeslot checks.
- Use native `input[type="date"]` for shipment dates when platform-owned calendar behavior is acceptable.
- Use native `<select>` for seller warehouse when more than one active warehouse requires a choice; do not build a custom select solely for styling.
- Handoff point remains an authored accessible remote combobox/listbox because it owns asynchronous search/result behavior.
- Temporary-draft disclosure must say real supply requests are not created.
- Distinguish `Кандидат` from `Проверено Ozon`; never show real-supply success copy before PR-F.
- Frontend owns presentation/state only; Python owns calculations, candidates, validation, ranking and export.
- Preserve historical Flow and established visual identity.
- PR-E updates runtime + root `DESIGN.md`/`UX-CONTRACT.md` together to final shipped truth.
- Target WCAG 2.2 AA, semantic controls, stable busy geometry, persistent correction-oriented failures and 200% zoom.

## Runtime/development

Canonical runtime remains:

```text
repository ZIP
→ start.bat
→ project-local Python 3.13.14
→ FastAPI 127.0.0.1:17843
→ committed vanilla HTML/CSS/JavaScript
```

- No npm/TypeScript/framework/compiler/bundler.
- No database/background-service architecture without approved need.
- `cryptography` is the only newly approved runtime dependency in active roadmap.
- Use TDD and work outside `main`.
- FastAPI routes thin; pure domain/adapters independently testable.
- Run `python -m pytest -q` before completion.
- `/api/analysis/stream` regression tests live in `tests/api/test_analysis.py`.
- Windows portable smoke remains authoritative for bootstrap/runtime.
- Existing real-scale Flow acceptance remains mandatory when shared frontend/layout changes.