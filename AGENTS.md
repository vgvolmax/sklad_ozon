# Codex Cloud instructions

## Active source of truth

For current development, read in this order:

1. `docs/superpowers/specs/2026-09-09-api-first-roadmap-corrections.md` — active precedence patch; apply it to every matching 2026-09-09 spec/plan before implementation;
2. `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`;
3. for frontend/UI work, `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md`;
4. when touching already-built demand/stockout/Flow layers, `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`;
5. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md` for Product Completion semantics not superseded above;
6. `DESIGN.md` for the currently shipped visual identity/tokens. Root `UX-CONTRACT.md` is current-runtime evidence only until PR-E; selected-network/PlanningSnapshot sections in it are superseded for active development by the 2026-09-09 API-first UI spec + correction patch;
7. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` for runtime/technical architecture;
8. exactly one matching active implementation plan from `docs/superpowers/plans/`.

If an active implementation-plan sentence conflicts with the correction patch, the correction patch wins. Do not create a separate implementation PR for the correction patch; apply its requirement inside the already-owned PR scope.

Do not reconstruct active behavior from Git history or archived documents when an active source above exists. Detailed completed PR1…PR5 design documents are archived implementation history and are not part of the active reading path.

## Archive exclusion

`docs/superpowers/archive/**` contains completed, abandoned or superseded documents **for historical audit only**.

**Do not read, search, quote, or implement from `docs/superpowers/archive/**` during normal feature development.** Open archive files only when the user explicitly asks for history, rationale, comparison with an old design, or an audit of superseded work.

Archive content has no precedence over active specs/plans even if an archived file says `approved`, `canonical`, `source of truth` or contains executable-looking steps.

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

Do not collapse this sequence into one implementation PR.

`PR-F — Ozon Supply Execution` is future/non-active. There is intentionally no current implementation plan for it.

## Canonical analytical safeguards

- `destination_cluster` is customer-demand geography; historical fulfillment origin never becomes demand ownership.
- Historical Flow is evidence, not future allocation weight.
- Existing DemandEstimate, stockout, clean-route, Flow and route-economics math stays unchanged unless a later explicitly approved design changes it.
- Current FBO and inbound remain upstream Need inputs:

```text
raw_need = raw_demand_forecast - current_fbo_stock - inbound_qty  # when inbound enabled
calculated_need_qty = max(0, ceil(raw_need))
```

- Missing FBO/inbound evidence is unknown, never zero by convenience.
- Calculated Plan remains primary `Наш план`; Safe Plan remains a conservative comparison only when its Ozon reference evidence is complete.
- Do not substitute turnover/another Ozon API metric for the exact analytical Ozon recommendation merely to make Safe Plan complete.
- Existing seller-stock resolution is authoritative: FBS/operational evidence first, conflicts blocking, explicit zero known, ProductEconomics `available_qty` only the current allowed fallback. Shipment code consumes the resolved result; it does not implement a second resolver.
- `ProductEconomicsInput.volume_liters` remains canonical unit volume.
- Supplier pack multiplicity comes from `Прайс списком`: seller `КОД` + positive right-hand integer of `Упак`; never use `Оглавление!КРАТНОСТЬ`.
- Supplier article normalization must preserve stable identity: integer-like Excel numeric `40750.0` becomes `"40750"`; non-integer numeric identifiers are invalid rather than silently coerced.
- Positive operational quantities are whole packs.
- Whole-pack ShippablePlan is built across all clusters before shipment selection. Selected clusters are filter-only and do not reallocate seller stock.

## API-first source safeguards

Exactly one source mode owns an analysis run:

```text
API
or
FILES
```

Never silently mix API and file sources by domain, SKU, cluster or missing-row fallback. API failure does not switch to FILES automatically.

API adapters normalize into existing PII-safe domain contracts. Do not fork analytics by source mode.

Current operational endpoint paths live only in the backend Ozon endpoint registry. If Ozon changes a version, change the adapter/registry and parity tests rather than spreading endpoint strings through application/frontend code.

Ozon source snapshots are memory-only in the active milestone. Raw buyer/address/phone/email payloads are discarded before snapshot assembly and never serialized to frontend.

### API `source_as_of`

- API sync owns the date basis: `source_as_of` is backend-assigned from the actual sync/current-evidence basis.
- Browser/API callers do not choose an arbitrary historical `as_of` for current API stock.
- In API mode, `analysis_as_of = source_snapshot.source_as_of`; a redundant request field must equal it or be rejected.
- Changing horizon or inbound flag can reuse the same snapshot, but cannot relabel its date.
- Arbitrary historical `as_of` belongs only to a historically consistent source workflow, currently FILES.

### Source capability matrix

Do not invent a single global completeness rule:

- orders/postings missing → demand/Flow capability blocked for the missing history;
- unresolved cluster identity → affected evidence blocked/diagnostic, never guessed;
- current FBO missing → affected Need is unknown/incomplete, never zero; whole FBO failure can leave history inspectable but not a valid Calculated Need/Plan;
- inbound missing matters only when `include_inbound=true`; when enabled, missing inbound stays unknown/incomplete;
- seller stock missing does not invalidate historical demand/Need, but blocks/marks incomplete operational allocation for affected SKU;
- exact Ozon recommendation missing only disables/incompletes Ozon comparison/Safe Plan;
- placement zone missing affects shipment-method compatibility only, not demand/Need;
- hand-off search is not part of source-sync completeness;
- unit volume/multiplicity are seller-local operational prerequisites for affected SKU exportability, not demand prerequisites.

### Hand-off point search

Do not bulk-sync `/v1/warehouse/fbo/list` into `OzonSourceSnapshot`.

Canonical workflow:

```text
frontend query >= 4 trimmed chars
→ POST /api/ozon/handoff/search
→ backend Ozon search
→ normalized HandoffPoint[]
→ process-memory HandoffPointStore keyed by warehouse_id
→ selected_handoff_point_ids resolve against that backend store
```

- Search requires unlocked vault.
- Persisted preferred point IDs are preferences only; after restart they must be resolved again before candidate use.
- Unknown/stale IDs fail before draft creation.
- Frontend remote search is debounced (~300 ms), IME-safe and stale-response protected.

## Credential/security safeguards

Credential vault path:

```text
data/ozon-credentials.json
```

`data/` is local/gitignored. Vault contains ciphertext/metadata only.

Canonical vault:

```text
hashlib.scrypt(n=32768, r=8, p=1, dklen=32, random 16-byte salt)
→ AES-256-GCM (random 12-byte nonce)
AAD = "sklad_ozon:ozon-vault:v1"
```

- Password is never stored.
- Decrypted Client-Id/API-Key live backend-memory-only until manual lock or process exit.
- No inactivity auto-lock in current scope.
- Stored API key is never returned to frontend after setup.
- No secrets in Project JSON, URL, logs, snapshots, errors, analytics or test artifacts.
- Do not claim reliable secure memory zeroization in Python.
- Ozon API calls originate only from localhost backend; frontend never calls `api-seller.ozon.ru` directly.
- Fixed external host only; no user-provided arbitrary outbound URL.
- With stdlib `urllib.request`, PR-API1 requires a finite request/socket timeout covering connection/read blocking. Do not add a second HTTP framework solely to manufacture independent connect/read timeout knobs.

## Shipment-planner safeguards

Active flow:

```text
Calculated Plan
→ resolved stock + pack multiple + volume
→ full ShippablePlan
→ shipment intent + concrete Ozon hand-off points
→ bounded local candidates
→ temporary Ozon draft validation
→ current timeslots
→ ranked validated options
→ XLSX/ZIP
→ user performs final real supply action in Ozon
```

- DIRECT hard max = 1 cluster.
- Multi-cluster cross-dock hard max = 20 clusters.
- Cross-dock requires a concrete Ozon hand-off point ID resolved from backend search evidence.
- Candidate builder is deterministic/bounded; no cluster-subset brute force.
- Default live-validation budget is at most 6 new temporary drafts per user run plus current Ozon external limits.
- Draft create calls are not blindly retried after ambiguous network failure.
- `draft_id` is backend integer/int64 identity, not a string convenience type.
- Product rejection, no timeslot, rate limit, transport unavailable and unknown create outcome remain causally distinct.
- PVZ 1000 L local rule is a **candidate-total item-volume** pre-check, not a per-line check. `<=1000 L` is preliminary only and does not prove actual packed cargo/box count/weight/point acceptance.
- Preserve exact normalized `placement_zones` through ShippableLine → CandidateAssignment → validated option/manifest. Multiple zones may produce manual packing guidance but do not automatically create separate supply requests.
- Shipment ranking is operational/service-level. Never use customer-delivery `RouteCostIndex` / `DirectRouteQuote` as seller→FBO supply cost evidence.
- No endpoint or frontend action in the active roadmap may call `POST /v2/draft/supply/create` or claim a real supply was created/booked.

## Product identity and export safeguards

- UI is article-first in presentation but SKU is the canonical selector/state identity (`selectedSku`).
- Never silently collapse two Ozon SKUs because they share one seller article; render separate SKU-backed items and expose an identity diagnostic.
- Before aggregating XLSX rows for one `article + destination_cluster`, all rows must agree on `sku`, `article` and `pack_multiple`.
- Conflicting same-article identity is a blocking export diagnostic; never merge/repair it silently.
- Product name is display data, not the canonical export identity when SKU/article agree.

## UI safeguards

Keep top-level routes exactly:

```text
План
Потоки спроса
Экономика
Данные
```

Inside `План` target runtime:

```text
Товары | Отгрузки
```

- `Товары`: article-first bounded selector left, selected product context right; canonical item identity is SKU, with seller article as primary display label; no giant primary `SKU × cluster` table.
- `Отгрузки`: shipment intent, remote hand-off selector, explicit `Найти варианты в Ozon`, validated logistics manifests and XLSX/ZIP export.
- `Данные`: API connection/sync is primary; manual reports are an explicit reserve mode, never a peer auto-toggle.
- Temporary-draft disclosure must state that real supply requests are not created.
- Distinguish `Кандидат` from `Проверено Ozon`. Do not show `Поставка создана`, `Забронировано` or equivalent real-supply success before future PR-F.
- Frontend owns presentation/state only; Python owns business formulas, candidate grouping, Ozon validation/ranking and export.
- Keep separate source/analysis/shipment freshness and dirty ownership.
- Preserve historical Flow and existing visual identity.
- Root `UX-CONTRACT.md` selected-network/PlanningSnapshot workflow is not an active future requirement. PR-E must remove/replace those semantics when it migrates root `DESIGN.md` / `UX-CONTRACT.md` with the shipped API-first UI.
- Empty current root DESIGN component maps are not permission to invent variants; reuse canonical visual tokens/owners and reconcile them in PR-E.
- Target WCAG 2.2 AA, native semantic controls, stable busy geometry, persistent correction-oriented failures and 200% zoom operability.

## Runtime and development

Canonical runtime remains SCOZ-lite:

```text
repository ZIP
→ start.bat
→ project-local Python 3.13.14
→ FastAPI 127.0.0.1:17843
→ committed vanilla HTML/CSS/JavaScript
```

- No npm, TypeScript, frontend framework, compiler or bundler.
- No SQLite/database/background-service architecture without a later approved need.
- `cryptography` is the only newly approved runtime dependency for the current API-first roadmap; pin it and verify Windows wheel/bootstrap behavior in PR-API1.
- Use TDD and work outside `main`.
- FastAPI routes remain thin; pure domain/adapters remain independently testable.
- Run `python -m pytest -q` before completion.
- `/api/analysis/stream` regression tests live in `tests/api/test_analysis.py`.
- Windows portable smoke remains authoritative for runtime/bootstrap behavior.
- Existing real-scale Flow acceptance remains mandatory when shared layout/frontend code changes.
