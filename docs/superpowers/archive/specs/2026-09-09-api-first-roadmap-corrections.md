# API-First Roadmap Corrections — Active Precedence Patch

**Date:** 2026-09-09  
**Status:** APPROVED / ACTIVE PRECEDENCE PATCH  
**Scope:** narrow corrections to the 2026-09-09 API-first shipment-planner specs and implementation plans after merge review.  
**Purpose:** remove implementation ambiguity without changing the product outcome or PR sequence.

## 0. Precedence and reading rule

This document is not a new product design and does not add another implementation PR.

For the active API-first roadmap, this file has precedence over conflicting wording in:

- `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`;
- `docs/superpowers/specs/2026-09-09-api-first-plan-ui-design.md`;
- every active `2026-09-09-pr-*.md` plan;
- root `UX-CONTRACT.md` where that file still describes the superseded selected-network / PlanningSnapshot workflow.

Interpret the existing PR sequence unchanged:

```text
PR-API1 → PR-API2 → PR-A → PR-B → PR-C → PR-API3 → PR-D → PR-E
```

Do not create a separate implementation PR for this correction document. Apply the relevant correction while executing the already-planned PR that owns the affected code.

Archive files remain historical only.

---

## 1. Root UI-contract transition is explicit

Until PR-E changes the shipped UI, root `DESIGN.md` and `UX-CONTRACT.md` remain evidence of the current runtime look/behavior only.

However, any root `UX-CONTRACT.md` section that describes the superseded selected-network design is **not an active product requirement** for new development. In particular, do not implement or preserve as future target merely because it appears in the current root file:

```text
SupplyNetworkSelector
PlanningSnapshot selected-network semantics
network-only replan
origin coverage as the primary future Plan workflow
selected-network "План размещения" behavior
```

For target `План` / `Данные` behavior, the active 2026-09-09 API-first UI spec plus this correction file wins.

PR-E must update root `DESIGN.md` and `UX-CONTRACT.md` in the same changeset so post-PR-E root contracts no longer contain selected-network owners or obsolete PlanningSnapshot workflow language.

Empty/placeholder component maps in the current root `DESIGN.md` are not permission to invent new visual variants. Reuse the existing visual identity/tokens and fill durable component ownership only when PR-E ships the corresponding runtime behavior.

---

## 2. Hand-off points are remote search results, not a bulk sync catalog

### 2.1 Correct Ozon contract

`POST /v1/warehouse/fbo/list` is a search operation, not a reliable "download every hand-off point" catalog.

Current reviewed request semantics require:

```text
filter_by_supply_type
search  # trimmed query, minimum 4 characters
```

Therefore `POST /api/ozon/sync` must **not** attempt to prefetch all PVZ/SC/direct hand-off points and must not require a complete `handoff_point_catalog` inside `OzonSourceSnapshot`.

### 2.2 Backend owner

Add one localhost backend search operation in PR-API2:

```text
POST /api/ozon/handoff/search
```

Request contract:

```text
query: string             # trim; minimum 4 characters
supply_types: tuple       # current supported Ozon create-type filters
```

Response contains normalized `HandoffPoint` records:

```text
warehouse_id
name
address
point_type
coordinates when returned
```

The endpoint:

- requires an unlocked vault;
- calls the centralized Ozon endpoint registry/client;
- never exposes credentials;
- never becomes part of the analytical source snapshot completeness gate.

### 2.3 Backend identity/store

Search results populate a small process-memory `HandoffPointStore` keyed by `warehouse_id`.

Shipment candidate code resolves `selected_handoff_point_ids` against this backend-owned store. Do not trust arbitrary frontend IDs as known Ozon points.

A persisted preferred point ID/order is non-secret and may remain in Project JSON, but after process restart it is only a preference. The point must be resolved again through current search evidence before candidate creation. Unknown/stale IDs fail with a stable hand-off resolution diagnostic.

### 2.4 Frontend behavior

PR-E implements the selector as remote search:

```text
< 4 trimmed characters → no Ozon search
>= 4 characters → debounced backend search
```

Canonical interaction rules:

- about 300 ms debounce after eligible text input;
- IME/composition-safe input handling;
- stale-response/run-sequence protection;
- previous selected points stay visible while a new search is busy/fails;
- show name, address and point type from the returned record;
- no free-form warehouse-ID input;
- do not claim server-side address search if Ozon only documents the search string as warehouse/name search.

### 2.5 Plan overrides

This section overrides:

- canonical spec `OzonSourceSnapshot.handoff_point_catalog` wording;
- PR-API2 Task 5/6 wording that implies bulk `fetch_handoff_points()` during sync;
- PR-C wording that resolves selected hand-off IDs from the source snapshot catalog;
- PR-E wording that treats the selector as a preloaded source catalog.

---

## 3. API `source_as_of` is server-owned and immutable

Current FBO/seller/inbound evidence fetched during API sync is current evidence. The browser must not label that evidence as an arbitrary historical date.

### 3.1 Source snapshot contract

Use:

```text
OzonSourceSnapshot
  source_snapshot_id
  synced_at_utc
  source_as_of: date
  history_from
  history_to
  ...
```

`source_as_of` is assigned by the backend from the actual sync date/basis. It is not supplied as an arbitrary UI analysis parameter.

### 3.2 API analysis contract

For `source_mode=api`:

```text
analysis_as_of = source_snapshot.source_as_of
```

The client/browser cannot override it.

If an API analysis request still serializes an `as_of` field for compatibility, backend must require exact equality to `source_snapshot.source_as_of` and reject mismatch. Prefer removing the redundant mutable field from the target API contract.

Changing horizon or `include_inbound` may recalculate against the same immutable API snapshot without refetching. It does not change `source_as_of`.

Historical `as_of` analysis is allowed only when the selected source provides historically consistent evidence for that date. In the active roadmap this means the explicit FILES workflow, not current API stock relabelled as historical.

### 3.3 Downstream propagation

`analysis_as_of` copied into `ShippablePlan` and `ShipmentPlan` comes from this immutable analytical basis. Shipment requests never invent or override it.

### 3.4 Plan overrides

This replaces PR-API2 examples where `/api/ozon/sync` or API analysis appears to accept a free arbitrary `as_of` date independent of current stock evidence.

---

## 4. API-domain completeness is capability-based, not left to implementer choice

Do not make a developer invent one global `complete=True/False` rule. Preserve causal capabilities.

### 4.1 Required capability matrix

| Source domain | Failure / missing evidence consequence |
|---|---|
| Orders/postings | Blocks demand/Flow analysis that depends on the missing history. Do not substitute files silently. |
| Cluster/warehouse identity needed to map evidence | Blocks the affected evidence from entering demand/Need. Unresolved identity stays diagnostic; do not guess by display-name similarity. |
| Current FBO stock | Missing SKU×cluster remains unknown under existing Need semantics. If the whole FBO source fails, demand history may still be inspectable, but Calculated Need/Plan that requires current FBO evidence is unavailable/incomplete rather than using zero. |
| Inbound supply evidence | Required only when `include_inbound=true`. If `include_inbound=false`, inbound-source failure does not block Need. If enabled and evidence is missing, affected Need is incomplete; do not use zero. |
| Seller/FBS stock | Does not invalidate historical demand/Need by itself. It blocks/marks incomplete operational allocation for affected SKU under the existing seller-stock resolver. |
| Exact Ozon recommendation | Only disables/incompletes Ozon comparison and Safe Plan. Never substitute another analytics metric. Calculated Plan may remain usable. |
| Placement zone | Does not invalidate demand/Need. It limits/marks incomplete the shipment methods whose local compatibility needs zone evidence. |
| Hand-off point search | Not part of source sync completeness at all. It is requested later when the user configures cross-dock intent. |
| Unit volume / supplier multiplicity | Seller-local operational evidence. Missing values block exportable operational quantity for the affected SKU, not demand history. |

### 4.2 Snapshot/status presentation

`EndpointEvidence.complete` may still describe whether one endpoint fetch completed, but application behavior is derived from the capability matrix above.

Do not collapse all failures into one generic "sync failed" if a prior valid snapshot can remain active. Do not advertise a capability as ready when one of its required domains is incomplete.

### 4.3 PR-API2 Task 6 override

Replace the open-ended instruction:

> define which missing domains block full analysis and which only disable a comparison

with the matrix in this section. Tests must encode these exact capability consequences.

---

## 5. PVZ 1000 L is a shipment-level preliminary item-volume ceiling

Do not model the PVZ planning ceiling on one `ShippableLine`.

### 5.1 Correct local pre-check

Use a method rule concept such as:

```text
preliminary_max_shipment_item_volume_l
```

For PVZ cross-dock in the current reviewed rule set:

```text
CandidateShipment.total_volume_l > 1000 L
→ local pre-check block
```

The value is the sum of current product/unit-volume evidence for the whole candidate shipment.

Do **not** implement:

```text
line.total_volume_l <= 1000 L for every line
→ therefore candidate fits PVZ
```

because many individually small lines can exceed the shipment ceiling together.

### 5.2 Passing is preliminary only

`CandidateShipment.total_volume_l <= 1000 L` means only:

```text
preliminary item-volume check passed
```

It does not prove actual packed cargo volume, box count, per-box weight, or the exact selected point's current limit.

The active milestone does not infer cargo box count from supplier `pack_multiple` and does not fabricate per-box weight.

UI wording before Ozon validation remains `Предварительно подходит`.

### 5.3 PR-C override

Move the volume check from line-level compatibility to candidate-level compatibility/grouping. Tests must include a case where every line is below 1000 L but the aggregate candidate is above 1000 L and is therefore blocked/split.

---

## 6. Placement-zone evidence must survive to candidate and manifest

`placement_zone_kind` alone is insufficient for operational explanation.

### 6.1 Propagation contract

Carry the normalized zone evidence through the operational chain:

```text
ShippableLine
→ CandidateAssignment
→ ValidatedShipmentOption
→ ShipmentManifest presentation
```

Candidate assignment minimum:

```text
placement_zone_kind
placement_zones: tuple[str, ...]
```

or an equivalent backend-owned immutable `zone_composition` that preserves the exact normalized zones represented by the assignments.

### 6.2 Mixed-zone behavior

Different placement zones do not automatically require separate supply requests in this milestone.

When a candidate/validated option contains multiple zones:

- keep one shipment candidate if the Ozon method permits it;
- expose the zone composition;
- show manual packing guidance such as `При упаковке разделите грузоместа по зонам размещения`;
- do not auto-create cargo boxes/pallets;
- do not claim cargo-zone packing is validated.

KGT/unknown/multiple zone evidence continues to follow the conservative local compatibility rules for methods such as PVZ.

### 6.3 PR-C / PR-E override

PR-C must preserve zone values, not only a summary kind. PR-E renders backend-owned zone composition/warnings rather than recomputing zone logic in JavaScript.

---

## 7. Product identity and export aggregation are fail-closed

### 7.1 Canonical selector identity

The UI is article-first in presentation, but the canonical selector/state identity is **SKU**.

```text
selectedSku = stable selected item identity
article = primary seller-facing display/business label
```

Do not silently collapse two different Ozon SKUs into one item merely because their seller article strings are equal.

If one article is associated with multiple current SKUs, render separate SKU-backed selector items and surface an identity diagnostic. Search may still match the shared article.

### 7.2 Export aggregation guard

Before aggregating duplicate rows for one `article + destination_cluster` in XLSX export, prove that all rows agree on:

```text
sku
article
pack_multiple
```

Product name is display data and need not be a blocking identity field when the canonical SKU/article agree.

If the same `article + cluster` appears with conflicting SKU or pack multiplicity:

```text
fail closed
→ stable blocking diagnostic
→ no XLSX/ZIP for that option
```

Never merge/repair the conflict silently.

Positive exported quantity still must be an integer and preserve the serialized pack multiple.

### 7.3 Plan overrides

This tightens PR-D Task 5 duplicate aggregation and PR-E wording `one article/SKU`. Tests must explicitly cover conflicting same-article identity.

---

## 8. Supplier article normalization is explicit

Supplier packaging import joins by seller article. Excel numeric cells must not create accidental `.0` identity drift.

Canonical normalization:

```text
string cell "40750" → "40750"
integer numeric 40750 → "40750"
integer-like float 40750.0 → "40750"
non-integer numeric identifier 40750.5 → invalid/diagnostic
blank → invalid
```

Preserve trimmed string identifiers as strings; do not coerce arbitrary alphanumeric article values through numeric parsing.

Never default missing/conflicting multiplicity to `1`.

PR-A must add regression tests for integer-like numeric article cells before supplier multiplicity is considered complete.

---

## 9. Ozon `draft_id` remains integer identity

Current reviewed draft APIs use `draft_id` as `int64` identity.

Backend contracts therefore use:

```text
draft_id: int | None
```

Do not convert it to a string merely for storage/wire convenience. String formatting is allowed only for display/log-safe formatting.

PR-API3 contract tests must reject bool-as-int and invalid/non-positive IDs where applicable.

---

## 10. Stdlib HTTP timeout wording

The active client remains stdlib-based unless a later approved design changes the stack.

Because `urllib.request` does not provide a clean independent connect-timeout/read-timeout API like some third-party clients, the canonical requirement for PR-API1 is:

```text
finite request/socket timeout covering connection/read blocking
```

Separate connect/read timeout values are required only if the chosen standard-library transport implementation can enforce them independently without adding a second HTTP framework.

Do not add a new HTTP dependency solely to satisfy wording that the selected stdlib stack cannot represent separately.

All other retry/redaction/fixed-host safeguards remain unchanged.

---

## 11. Codex implementation mapping

Apply these corrections inside the existing PR owners:

```text
PR-API1
  - stdlib finite request/socket timeout wording

PR-API2
  - server-owned source_as_of
  - capability completeness matrix
  - remote /api/ozon/handoff/search + process-memory HandoffPointStore
  - no bulk handoff catalog in source sync

PR-A
  - supplier integer-like article normalization tests

PR-B
  - preserve immutable analysis_as_of/source identity downstream
  - no change to filter-only shipment selection rule

PR-C
  - resolve handoff IDs from backend HandoffPointStore, not source snapshot
  - shipment-level PVZ aggregate item-volume precheck
  - preserve placement_zones
  - SKU remains canonical assignment identity

PR-API3
  - draft_id is int64/int
  - no change to temporary-draft/no-real-create boundary

PR-D
  - fail-closed same-article export identity guard
  - ranking remains operational, not inbound-cost optimization

PR-E
  - remote handoff search interaction
  - SKU-backed article-first selector
  - zone composition/manual packing copy
  - root DESIGN.md / UX-CONTRACT.md migration removes selected-network target semantics
```

No active PR may reinterpret these as optional polish.

---

## 12. Acceptance checklist for this correction

Before implementing any active PR, a Codex/agent should be able to answer all of these from active docs alone:

```text
Who owns API as_of?                         backend sync/source snapshot
Can browser choose historical as_of?       not in API mode
Are handoff points bulk-synced?             no
How are handoff points found?               backend remote search, query >=4 chars
Does handoff search gate source sync?       no
Can selected clusters reallocate stock?     no, filter-only
Is PVZ 1000 L line-level?                   no, candidate total
Does <=1000 L prove packed cargo?           no
Do placement zones survive to manifest?     yes
What is selector identity?                  SKU
Can same article+cluster conflicting SKU merge in export? no
Can missing FBO/inbound become zero?        no
Can missing Ozon recommendation be replaced by another metric? no
What type is draft_id?                      int64/int
Does the app create the real Ozon supply?   no
```

If an implementation plan sentence appears to answer one of these differently, this correction document wins.
