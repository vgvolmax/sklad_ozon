# Codex Cloud instructions

## Source of truth

For the active operational shipment-planner roadmap, read in this order:

1. `docs/superpowers/specs/2026-09-08-ozon-shipment-planner-design.md`;
2. for `План` UI work, `docs/superpowers/specs/2026-09-08-article-first-plan-ui-amendment.md`;
3. `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md` and the matching already-built PR1…PR5 specs when touching those layers;
4. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`;
5. `UX-CONTRACT.md` and `DESIGN.md`, except where the 2026-09-08 article-first UI amendment is explicitly more specific for `План`;
6. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md` for runtime/technical architecture;
7. the matching **active** implementation plan below.

Active implementation sequence:

```text
PR-A  docs/superpowers/plans/2026-09-08-pr-a-supply-facts-pack-multiplicity-implementation.md
PR-B  docs/superpowers/plans/2026-09-08-pr-b-multiplicity-aware-shippable-plan-implementation.md
PR-C  docs/superpowers/plans/2026-09-08-pr-c-shipment-batching-schedule-implementation.md
PR-D  docs/superpowers/plans/2026-09-08-pr-d-local-shipment-api-ozon-export-implementation.md
PR-E  docs/superpowers/plans/2026-09-08-pr-e-article-first-plan-shipment-ui-implementation.md
```

Do not collapse PR-A…PR-E into one implementation PR.

## Deferred selected-network roadmap

The following 2026-09-08 designs are **historical/deferred for implementation**:

- `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`;
- `docs/superpowers/specs/2026-09-08-route-cost-index-amendment.md` when it is being used to propose future placement topology;
- the former selected-network PR-A…PR-E plans, whose files now contain DEFERRED redirects.

Do **not** implement from those documents in the active milestone:

- alternate-origin future coverage (`SKU × origin × destination` Coverage Planner);
- hard LOCAL-first selected-network assignment;
- RouteCostIndex/direct customer-delivery tariff as a future-placement selector;
- desired coverage legs;
- selected-network `PlanningBasis` / `PlanningSnapshot`;
- selected-network `/api/replan`;
- applied/draft selected supply-network persistence;
- planned alternate-origin Flow surface.

Git history preserves the old plans. They may return only after a new approved product design.

The old documents remain useful only as historical rationale and do not override the active shipment-planner design.

## What remains canonical and must not be broken

### Demand / analysis

- `destination_cluster` is customer-demand geography. Historical fulfillment origin never becomes demand ownership.
- Routing-independent observed destination demand remains the quantity source for DemandEstimate.
- External fulfillment does not erase destination demand.
- Route cleaning and demand-history eligibility remain separate mechanisms.
- Daily stockout/substitution detection remains `SKU × destination` before presentation aggregation.
- Do not fabricate latent/lost demand when no approved evidence/model exists.
- Current FBO and inbound remain upstream need inputs:

```text
raw_need = raw_demand_forecast - current_fbo_stock - inbound_qty  # when inbound enabled
calculated_need_qty = max(0, ceil(raw_need))
```

- Unknown FBO/inbound evidence is never coerced to zero.
- Safe Plan remains the conservative analytical reference; Calculated Plan remains primary `Наш план`.
- Ozon recommendation remains an external comparison/control signal, not physical capacity.
- Existing historical Flow, stockout impact, route economics and local counterfactual analysis stay in the product.
- Historical Flow shares remain evidence only and are never future shipment weights.

### Seller stock / whole-pack operationalization

- Seller available stock is a separate physical ceiling; it never reduces demand itself.
- Product volume and seller available stock come from the existing canonical ProductEconomics input unless a later approved design changes that source.
- Supplier product pack multiplicity comes from the approved supplier workbook contract: sheet `Прайс списком`, `КОД` + `Упак`, using the positive right-hand integer after `/`.
- Example: `40750: 36/6 → pack_multiple = 6`.
- Never use the supplier workbook's `Оглавление!КРАТНОСТЬ` currency-conversion divisor as product multiplicity.
- Missing/conflicting multiplicity remains incomplete; do not default silently to `1`.
- Every positive operational shipment quantity is a complete pack multiple.
- Pack rounding is downstream operationalization and never creates/relabels demand.
- Finite physical capacity and seller stock are converted to complete packs with floor; desired analytical quantity may require ceil-to-pack when capacity/stock permit.
- Reuse the existing deterministic per-SKU allocation eligibility/priority; do not add a new portfolio/global objective in this milestone.

### Ozon restrictions

- The already-uploaded Ozon restrictions report is the physical eligibility/capacity source.
- Preserve `FINITE / UNLIMITED / UNKNOWN`; unknown never means unlimited.
- `allowed = Да + FINITE(0)` is unusable for positive shipment quantity.
- Multiple allowed warehouse maxima inside one cluster are **not summed**. Explicit UNLIMITED wins; otherwise use the maximum independently proven positive FINITE value.
- Preserve placement-zone evidence at warehouse level and aggregate without guessing conflicts.
- `Зона размещения`, card errors, equipment and liquidity fields explain/classify; they never override explicit `Возможно ли поставить товар`.
- Numeric Ozon 56-day recommendation `0` is explicit zero; dash/blank is missing.

## Operational shipment-planner contract

The active downstream flow is:

```text
AnalysisSnapshot / Calculated Plan
→ restrictions + seller stock + pack multiplicity
→ whole-pack ShippablePlan
→ selected shipment clusters
→ operator-defined shipment opportunities
→ recommended shipment calendar
→ exact Ozon XLSX / ZIP
→ operator manually uploads/books the slot in Ozon
```

### Cluster selection

Selected shipment clusters mean only:

> include these destination clusters in the current operational shipment run.

They do not let one cluster serve another cluster's future demand and do not rewrite unselected cluster quantities.

### Dates and methods

V1 opportunity methods are:

```text
PVZ_CROSSDOCK
SC_CROSSDOCK
DIRECT
```

An opportunity owns explicit date, max clusters, optional/required lead days and effective volume cap.

Without Ozon Seller API the app recommends a date; it never claims a slot is available, confirmed or booked.

Current inbound evidence has quantity but no ETA. It must not postpone depletion/urgency by itself.

### PVZ

Current reviewed V1 planning ceiling is 1000 liters total for a PVZ cross-dock shipment. A concrete Ozon point may have a lower real limit, so user override may lower the planner cap and manual Ozon confirmation remains required.

V1 has no cargo-box/pallet packing model. Do not claim validation of box count, per-box weight, pallet count or live point capacity.

KGT and unknown/multiple placement-zone evidence are not automatically assigned to PVZ.

### Scheduling

- Use a bounded deterministic heuristic, not brute-force cluster subset search or a general LP/min-cost-flow solver.
- Prefer the latest feasible opportunity that is still on/before the explainable latest recommended ship date.
- If only later opportunities fit, choose the earliest feasible late option and keep days-late explicit.
- Unknown urgency/date quality remains explicit.
- Every split remains whole-pack.
- Max-cluster and volume constraints are hard per opportunity.
- Unscheduled residual quantity and causal constraint reasons must remain visible.

## Local API / export boundary

"No Ozon API" means no external Seller API/network integration in the active roadmap. Local FastAPI endpoints are canonical:

```text
POST /api/shipment-plan
POST /api/shipment-export
```

- `/api/shipment-plan` recalculates only downstream shipment scheduling from immutable analytical/operational inputs.
- `/api/shipment-export` renders an already-calculated planned shipment; it does not recalculate demand.
- No endpoint may call `api-seller.ozon.ru` in this milestone.
- One Ozon workbook corresponds to one cluster inside one planned shipment.
- Workbook columns are exactly:

```text
артикул
имя (необязательно)
количество
```

- Multi-cluster planned shipment → one ZIP containing one XLSX per cluster.
- Do not add helper columns to Ozon templates.

## Plan UI safeguards

The article-first UI amendment is authoritative for `План` until PR-E folds it into root `DESIGN.md` / `UX-CONTRACT.md`.

Keep top-level routes exactly:

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

### `Товары`

- Primary navigation unit is one SKU/article, not `SKU × cluster` row.
- Reuse the master/detail interaction grammar of `Потоки спроса → По артикулу`: bounded selector left, selected context right.
- Show product identity once in the right header.
- Primary product planning evidence is persistently visible; do not require repeated `Открыть детали` buttons.
- Focused cluster table defaults to:

```text
Кластер | FBO | В пути | Ozon | Потребность | Аналитический план |
Кратность | К поставке | Объём | Зона | Статус
```

- Preserve the decision-line visual signature.
- Do not move route economics/history into the default cluster table; `Потоки спроса` / `Экономика` keep those responsibilities.

### `Отгрузки`

- Owns selected shipment scope, opportunity editor, downstream recalc, shipment manifests and Ozon export.
- Shipment result surfaces use restrained logistics-manifest structure, not KPI-card mosaics.
- Do not label recommended dates as confirmed slots.

### Dirty state

Keep two independent concepts:

```text
analysisDirty
shipmentDirty
```

- horizon/inbound/source change → analysis dirty/full `Пересчитать план`;
- shipment clusters/dates/methods/lead/max-clusters/volume change → shipment dirty only;
- shipment edits never silently issue a full analysis request;
- failure keeps the previous successful result and current draft for retry.

## Real-scale / frontend production safeguards

- Production frontend remains committed vanilla HTML/CSS/JavaScript: no npm, TypeScript, framework, compiler or bundler.
- Python owns business formulas, shipment constraints, scheduling and XLSX generation; frontend owns state transitions/presentation only.
- Reuse shared primitives/tokens instead of screen-local equivalents.
- Before any PR-E UI implementation, read `DESIGN.md`, `UX-CONTRACT.md`, the article-first UI amendment and Frontend Design Premium requirements.
- PR-E must update root `DESIGN.md` and `UX-CONTRACT.md` in the same changeset as runtime Plan UI.
- Target WCAG 2.2 AA; use native semantic controls, visible focus, stable busy geometry and persistent correction-oriented errors.
- Search has an explicit clear button and keyboard focus restoration.
- Do not render every SKU/cluster as a giant card matrix.
- Flow keeps bounded selected-context views; no global Sankey/chord and no route-count-dependent unbounded canvas.
- Test Plan at realistic article/cluster cardinality and 200% zoom; selector should stack above detail rather than squeeze into an unusable split.
- Verify `Потоки спроса`, `Экономика` and `Данные` after any shared CSS/layout change.

## Canonical runtime contract

```text
repository ZIP
→ extract fully
→ start.bat
→ project-local portable Python
→ FastAPI bound to 127.0.0.1:17843
→ browser opens after /api/health succeeds
```

`start.bat` remains the only canonical entry point. Do not restore `file://`, direct HTML launch, SheetJS/browser-side XLSX parsing or a parallel browser-only runtime.

[SCOZ](https://github.com/vgvolmax/SCOZ) remains the reference for proven portable Windows patterns. `sklad_ozon` stays SCOZ-lite: do not introduce SQLite/migrations/accounts/auth/background-job infrastructure without a demonstrated approved need. Project JSON remains the persistence boundary where persistence is needed.

## Development and verification

- Work outside `main`.
- Use TDD for behavior changes.
- Implement only one active PR scope at a time.
- Do not rewrite working upstream analytics merely to fit the shipment feature.
- Use dependency-free functional cores and imperative shells; FastAPI routes remain thin.
- Runtime dependencies are pinned; add none without a demonstrated need.
- Test Python with `python -m pytest -q`.
- Windows portable smoke remains authoritative for runtime behavior.
- Existing real-scale Flow acceptance remains mandatory when Flow/shared layout code is touched.
- Preserve metadata, lifecycle semantics, PII boundary, fail-closed ingestion, incomplete-period behavior, tariff coverage semantics, tax/VAT/co-invest economics and existing counterfactual contracts unless a later approved design explicitly changes them.
