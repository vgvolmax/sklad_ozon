# Shipment Planner Clarifications Amendment

**Date:** 2026-09-08  
**Status:** approved correction  
**Applies to:** active shipment-planner roadmap PR-A…PR-E  
**Precedence:** this amendment supersedes `2026-09-08-ozon-shipment-planner-design.md`, `2026-09-08-article-first-plan-ui-amendment.md`, and active PR-A…PR-E implementation plans wherever it is more specific.  
**Purpose:** remove ambiguities that could make an implementation diverge from the existing runtime when read without conversation context.

## 1. Existing analytical calculation is the upstream owner

The active shipment feature is downstream of the existing Product Completion analysis.

Do not rewrite or independently resolve:

- destination demand;
- FBO/inbound need subtraction;
- current Calculated/Safe plan semantics;
- current seller-stock conflict/fallback rules;
- existing route economics;
- current per-SKU allocation eligibility/priority.

The operational layer consumes already-resolved analytical outputs and adds only whole-pack, shipment-batching and export behavior.

## 2. Seller available stock source — correction

The previous design wording that implied `ProductEconomicsInput.available_qty` is always the seller-stock source is incorrect.

Current runtime behavior in `backend/application.py` is authoritative:

1. when operational/FBS availability contains seller stock for a SKU, that evidence is resolved first;
2. conflicting positive FBS values block seller-stock resolution;
3. explicit all-zero FBS is a known zero;
4. `ProductEconomicsInput.available_qty` is only the existing fallback when FBS evidence is absent and the current authority rules allow that fallback.

PR-B MUST NOT create a second seller-stock resolver.

For whole-pack operationalization, use the seller quantity already resolved for the existing Calculated allocation result for that SKU, or expose that exact resolved value through an explicit immutable field. Do not re-read `ProductEconomicsInput.available_qty` and thereby bypass FBS/conflict semantics.

Product unit volume remains the existing canonical `ProductEconomicsInput.volume_liters` source.

Acceptance invariant:

```text
shipment seller stock == existing analytical seller stock resolution
```

A shipment feature must never make a SKU shippable merely because `ProductEconomicsInput.available_qty` exists when current analysis blocked seller stock as conflicting/missing.

## 3. Ozon 56-day recommendation — two sources, one analytical owner

The existing analytical Ozon recommendation already comes from the availability/report path used by `calculate_need()` and Safe Plan.

The same restrictions workbook may also contain `Рекомендуемая поставка на 56 дней`. In this milestone that restrictions value is a **secondary control/reference signal only**.

Therefore:

- do not replace the existing analytical Ozon recommendation with the restrictions value;
- do not pass the restrictions recommendation into `calculate_need()`;
- do not change Safe Plan quantities because the restrictions workbook contains another recommendation;
- preserve `0` vs missing (`-`/blank) in the restrictions reference;
- deduplicate repeated warehouse rows at `SKU × cluster`;
- when both analytical and restrictions recommendations are explicit and differ, surface an explainable mismatch diagnostic/reference;
- missing restrictions recommendation is not an analytical error.

Prefer a name that makes the secondary role obvious, for example:

```text
RestrictionOzonReference
restriction_ozon_recommended_qty_56d
```

rather than a generic replacement `OzonSupplyRecommendation` that could be confused with the canonical analytical signal.

## 4. Selected shipment clusters are filter-only

The active milestone has no selected-network reallocation.

Cluster selection means only:

> include this destination cluster's already-calculated `ShippableLine` quantities in the current shipment run.

Changing selected clusters MUST NOT:

- recompute seller-stock scarcity across only the selected subset;
- move quantity from an unselected cluster to a selected cluster;
- renormalize or increase another cluster's `shippable_qty`;
- rerun the analytical allocator.

Canonical flow:

```text
full analytical plan
→ full all-cluster ShippablePlan
→ selected-cluster filter
→ shipment batching/scheduling only
```

The sentence in the base design allowing seller-stock whole-pack reallocation over the selected subset is superseded and must not be implemented.

## 5. Restrictions capacity is a dated snapshot, not a future-date guarantee

The Ozon restrictions workbook is a snapshot of physical receiving evidence at its report date.

`allowed`, capacity and placement-zone facts are valuable for conservative planning, but they do not prove that the same capacity/warehouse state will be available on a future shipping date.

Required semantics:

```text
restriction capacity = conservative snapshot pre-check
≠ confirmed future capacity
≠ booked Ozon slot
```

PR-A must preserve `ReportMeta.report_generated_at` / equivalent trusted report-date evidence for restrictions when it can be extracted reliably. Do not derive it from the user-selected shipment date.

If report date cannot be proven, keep it unknown.

The UI/data-quality surface must show the restrictions evidence date when known and must not label a future shipment as capacity-confirmed. Manual Ozon creation remains the final authority for current capacity and slot availability.

The active V1 may continue to use the snapshot capacity as a conservative ceiling for generated quantities; it must communicate that this can understate or differ from future Ozon capacity and should be refreshed when planning materially later dates.

Do not invent an arbitrary stale-after-N-days threshold unless later approved.

## 6. Shipment method hard caps

The user-provided `max_clusters` is never allowed to exceed the method's hard rule.

V1 hard method rules:

```text
DIRECT
  hard_max_clusters = 1

PVZ_CROSSDOCK
  hard_max_clusters = 20

SC_CROSSDOCK
  hard_max_clusters = 20
```

Effective max clusters:

```text
effective_max_clusters = min(user_max_clusters, hard_max_clusters)
```

The UI may prevent entry above the hard max, and the backend must still validate it.

Do not interpret `DIRECT` as a generic multi-cluster opportunity.

These hard caps belong in the backend method-rule registry, not scattered UI conditionals.

## 7. PVZ is only a preliminary compatibility check

The planner currently has canonical product volume per unit, but it does not have a cargo-packing model.

For PVZ V1:

- planner item-volume estimate above 1000 L is a hard pre-check failure;
- item-volume estimate at or below 1000 L is only **preliminarily compatible**;
- actual point capacity may be lower;
- the planner does not know final packed-box outer volume;
- the planner does not validate the public small-supply limits of box count or per-box weight;
- live slot/point acceptance is confirmed manually in Ozon.

The UI must not say simply `ПВЗ подходит` as if all operational checks passed.

Use wording such as:

```text
Предварительно подходит для ПВЗ
Требуется проверка в Ozon
```

and include a manual checklist for the currently known unmodelled constraints, including box count, per-box weight, actual point limit and slot availability.

The 1000 L value is a planning ceiling, not a guarantee that a concrete PVZ accepts exactly 1000 L.

## 8. Placement zones and cargo preparation

`Зона размещения` remains Ozon evidence; the application does not reclassify the SKU from dimensions.

For V1:

- KGT and UNKNOWN/MULTIPLE zone evidence are not auto-assigned to PVZ;
- sortable/non-sortable can pass the preliminary PVZ method check when other known constraints pass;
- a shipment may contain SKU lines from different placement zones;
- do not automatically split them into separate supply requests solely because zones differ;
- the shipment manifest must make the zone composition visible;
- add an explicit manual preparation warning that cargo places/boxes must be separated according to Ozon placement-zone requirements where applicable.

The Ozon XLSX stays the exact three-column template and must not gain a zone helper column.

Cargo-box/pallet modelling remains deferred.

## 9. Scheduling objective is operational, not economic

The active scheduler optimizes only deterministic operational goals:

1. preserve already-calculated quantities;
2. respect whole packs and known method/volume/cluster constraints;
3. protect urgent demand;
4. prefer the latest still-on-time opportunity;
5. surface late/unscheduled residuals causally.

It is **not** a cost-minimizing supply-route optimizer.

The current customer-delivery `RouteCostIndex` / `DirectRouteQuote` must not be reused as a seller-to-FBO shipment-cost signal.

Current customer-delivery economics remain analytical evidence only.

If future work adds cross-dock/direct inbound supply tariffs, they need a separately named source/contract such as `SupplyRouteQuote`; that is outside this milestone.

UI copy should say `Рекомендуемое расписание/отгрузки`, not `Самый дешёвый`, `Экономически оптимальный` or equivalent unsupported claims.

## 10. Immutable analysis date for urgency

Shipment urgency must belong to the same immutable analysis that produced `ShippablePlan`.

Add/retain:

```text
ShippablePlan.analysis_as_of
```

or an equivalent immutable field owned by the analysis snapshot.

`/api/shipment-plan` MUST NOT accept an independent arbitrary `as_of` supplied by the browser that can differ from the parent analysis.

Use:

```text
shipment analysis_as_of == parent AnalysisSnapshot.as_of
```

for depletion/urgency calculations.

The browser sends snapshot/shippable-plan identity plus shipment scenario only; date ownership comes from the immutable operational basis.

## 11. Initial cluster selection and empty-scenario behavior

Canonical first-use behavior:

- when no prior shipment selection exists for the current analysis/project state, select all destination clusters with positive complete `shippable_qty`;
- after the user has made an explicit selection, preserve that selection where cluster IDs still exist;
- newly appearing clusters after a later full recalculation default **unselected** once a prior explicit selection exists;
- remove clusters that no longer exist/are no longer selectable;
- cluster checkbox edits remain local draft state and issue no backend request.

`Рассчитать отгрузки` requires:

```text
at least 1 selected cluster with positive shippable quantity
AND at least 1 enabled ShipmentOpportunity
```

The UI validates this before request.

The backend must also reject an empty executable shipment scenario with stable validation errors rather than returning a misleading successful empty schedule.

Suggested error identities:

```text
EMPTY_SHIPMENT_SCOPE
NO_ENABLED_SHIPMENT_OPPORTUNITY
```

Ordinary scheduling infeasibility after a valid scenario still returns a valid `ShipmentPlan` with `UNSCHEDULED` reasons.

## 12. PR-specific overrides

### PR-A

- Preserve restrictions report date when known.
- Treat restrictions 56-day recommendation as secondary `RestrictionOzonReference`, never the analytical Safe/Need source.
- Do not introduce a second user upload for that reference.

### PR-B

- Obtain `seller_available_qty` from the existing resolved analytical seller-stock result/contract, not directly from `ProductEconomicsInput.available_qty`.
- Keep all-cluster whole-pack allocation immutable after the full analysis.
- Selected shipment scope later filters these lines only.

### PR-C

- Enforce method hard max clusters: DIRECT=1, cross-dock multi-cluster=20.
- PVZ compatibility is preliminary; preserve manual checks.
- Include placement-zone composition/manual preparation warning in shipment result evidence.
- Do not introduce cost optimization or RouteCostIndex.
- Use immutable `analysis_as_of` for urgency.

### PR-D

Request contract correction:

```text
POST /api/shipment-plan
  analysis_snapshot_id
  shippable_plan / immutable operational basis
  scenario
```

Do not accept a free-standing browser-controlled `as_of` that can differ from the analysis.

Selected-cluster behavior is filter-only; never rerun pack scarcity for the subset.

The existing stream regression lives in:

```text
tests/api/test_analysis.py
```

There is no canonical `tests/api/test_analysis_stream.py` file. PR-D verification should run `tests/api/test_analysis.py`, whose existing tests cover `/api/analysis/stream`.

### PR-E

- Initialize shipment cluster scope according to section 11.
- Disable/show inline validation for calculate when cluster scope/opportunities are empty.
- Show restrictions report date/data-quality warning when known.
- Show `Предварительно подходит` + manual checks for PVZ, never confirmed capacity/slot language.
- Show placement-zone composition and cargo-separation warning in shipment detail without modifying XLSX columns.
- Do not present scheduling as cost optimization.

## 13. Deferred documents remain deferred

The following remain historical and must not be implemented for this milestone even if their own older text says `approved`:

- `2026-09-08-selected-supply-network-coverage-planner-design.md`;
- `2026-09-08-route-cost-index-amendment.md` for future placement;
- former selected-network PR-A…PR-E plans.

`AGENTS.md` is required to point Codex to this amendment before the base shipment design and to state that these older designs are DEFERRED.

If an agent opens an older document and finds text conflicting with this amendment, this amendment wins and the agent must not reconstruct the deferred Coverage Planner/replan architecture.

## 14. Correction acceptance checklist

A context-free implementation is correct only if all are true:

```text
seller stock resolution is exactly the existing analytical resolution
restrictions Ozon 56d reference does not replace analytical Ozon/Safe Plan
selected shipment clusters filter only; no quantity reallocation
restriction capacities are labelled dated snapshot evidence
DIRECT cannot contain >1 cluster
cross-dock opportunities cannot contain >20 clusters
PVZ <=1000 L is preliminary, not confirmed point compatibility
PVZ manual box/weight/point/slot checks remain explicit
zone composition is visible and cargo separation warning remains manual
scheduler does not use RouteCostIndex or claim cost optimum
urgency uses parent analysis_as_of only
empty shipment scope/opportunity set cannot return misleading success
stream regression uses tests/api/test_analysis.py
```

These are corrections to documentation ambiguity, not a new product scope.