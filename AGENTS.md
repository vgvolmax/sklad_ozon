# Codex Cloud instructions

## Source of truth

Before implementing selected supply-network / coverage-planning work, read, in order:

1. `docs/superpowers/specs/2026-09-08-route-cost-index-amendment.md` when the work touches route tariffs, RouteCostIndex, direct route economics, planned route evidence or replan tariff data;
2. `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`;
3. `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`;
4. the matching PR-specific 2026-09-03 design brief/spec (`pr1` … `pr5`) when the work touches those already-built layers;
5. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`;
6. `UX-CONTRACT.md`;
7. `DESIGN.md`;
8. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`;
9. the matching current implementation plan under `docs/superpowers/plans/`, when present.

For work confined to the already-completed real-data demand/stockout/Flow roadmap and unrelated to selected-network planning, read, in order:

1. `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`;
2. the matching PR-specific 2026-09-03 design brief/spec (`pr1` … `pr5`);
3. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`;
4. `UX-CONTRACT.md`;
5. `DESIGN.md`;
6. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`;
7. the matching current implementation plan under `docs/superpowers/plans/`, when present.

For PR1 specifically, the implementation plan is:

`docs/superpowers/plans/2026-09-03-pr1-true-demand-daily-fulfillment-implementation.md`.

Selected-network planning precedence is:

```text
2026-09-08 Route Cost Index amendment (within its explicit tariff-topology scope)
→ 2026-09-08 Selected Supply Network & Coverage Planner
→ 2026-09-03 real-data roadmap + matching PR specs
→ 2026-09-02 Product Completion design
→ UX-CONTRACT.md / DESIGN.md for frontend behavior and visual system
→ canonical SCOZ-lite runtime architecture
→ matching current implementation plan
→ older implementation plans / issue summaries
```

The Route Cost Index amendment supersedes the selected-network design only where it is explicitly more specific about the current customer-delivery tariff matrix, pair-level normalized RouteCostIndex, exact-fee tie behavior, PlanningBasis tariff scale and historical Flow percentage denominator. All other selected-network semantics remain in force.

The 2026-09-08 selected-network design supersedes earlier sources only where it is more specific about selected supply networks, destination-to-origin coverage assignment, tariff-based route ranking, physical-capacity ownership, planning snapshot/replan semantics and planned-flow UI.

The 2026-09-03 roadmap supersedes the earlier Product Completion design only where it is more specific about real-data demand/routing separation, daily stockout evidence, financial-impact presentation, diagnostics and real-scale Flow UI. Other Product Completion business rules remain in force.

The 2026-08-20 SCOZ-lite design remains canonical only for runtime and technical architecture: project-local Python, FastAPI on `127.0.0.1:17843`, `start.bat`, committed vanilla HTML/CSS/JavaScript, Project JSON, and no frontend build system. It does not override Product Completion business rules. The 2026-08-19 browser-only architecture is historical; its business requirements remain in force only where the later Product Completion designs do not supersede them.

## Canonical runtime contract

```text
repository ZIP
→ extract fully
→ start.bat
→ project-local portable Python
→ FastAPI bound to 127.0.0.1:17843
→ browser opens after /api/health succeeds
```

`start.bat` is the only canonical application entry point. Do not restore `file://`, direct `app/index.html`, SheetJS, browser-side XLSX parsing, or a parallel browser-only runtime without an explicitly approved future design change.

## Architectural reference and boundaries

[SCOZ](https://github.com/vgvolmax/SCOZ) is the primary reference for proven portable-Windows patterns: `start.bat`, project-local Python, launcher, FastAPI, loopback-only serving, committed vanilla frontend, Python ingestion, openpyxl, pytest, and Windows portable smoke. Check SCOZ before designing an analogous mechanism; diverge only for a concrete product or technical reason.

sklad_ozon is deliberately SCOZ-lite. Do not copy SQLite, migrations, repository infrastructure, lineage/revision systems, accounts, auth, background jobs, or other subsystems that the approved product does not need. Project JSON remains the persistence boundary.

## Development and verification

- Work outside `main`; use TDD for behavior changes and implement only the current approved PR scope and acceptance fixes.
- Do not collapse the five-PR real-data roadmap into one large implementation PR.
- Do not collapse the selected-network implementation sequence (PR-A … PR-E) into one large implementation PR.
- Before any UI change, read `DESIGN.md`, `UX-CONTRACT.md`, the applicable canonical product design/amendment, and the matching PR-specific UI design brief/plan.
- Production frontend remains committed vanilla HTML/CSS/JavaScript: no npm, TypeScript, framework, compiler, bundler, or frontend build.
- Python owns ingestion, domain rules, analytics, demand, stockout, economics, feasibility, coverage planning, optimization, diagnostic causal grouping and business presentation aggregates. FastAPI routes are a thin application/transport shell.
- Use dependency-free functional cores and imperative shells; test Python with `python -m pytest -q`.
- Runtime dependencies are pinned. Do not add one without a demonstrated need.
- `runtime/` is disposable and separate from gitignored `data/`; repairing the runtime must never erase local data.
- Do not rewrite working subsystems without a concrete product or technical reason. Create directories only when the current implementation needs them (YAGNI).
- Codex implementation constraints do not redefine the end-user architecture.
- Windows GitHub Actions portable smoke is an acceptance gate and authoritative for portable Windows runtime behavior.
- For real-scale Flow work, tiny synthetic fixtures are insufficient by themselves: real-scale/stress browser acceptance is mandatory because the previous Flow implementation failed only at realistic cardinality.

## Analytical safeguards

- `destination_cluster` is customer-demand geography; `origin_cluster` is physical fulfillment/placement origin. `Казань → Москва` remains Moscow demand fulfilled/served from Kazan, never Kazan demand.
- **Routing-independent observed destination demand** is the planning quantity source. Physical dispatch volume from an origin to other destinations never increases the origin cluster's own demand or calculated need.
- Example: if Moscow fulfills `Москва→Москва 500`, `Москва→Казань 300`, `Москва→Тверь 200`, Moscow physical dispatch is 1000 but Moscow demand is 500.
- External fulfillment does not erase destination demand. If Kazan demand is entirely fulfilled from Moscow, that volume remains Kazan demand.
- Do not fabricate latent/lost orders when inventory was unavailable everywhere. Such evidence may reduce confidence but does not create quantity without a separately approved model/source.
- Route cleaning and demand-history eligibility are separate mechanisms. A route-substitution period can be excluded from clean route history without erasing valid destination demand.
- Daily stockout/substitution detection is performed at `SKU × destination` before any cluster-level presentation aggregation.
- Current availability corroborates historical stockout evidence but does not define historical stock state.
- Historical observed/clean route shares are evidence only. They MUST NOT become future coverage weights or be renormalized across the selected network.
- For selected-network planning, LOCAL is preferred first. A non-local candidate must have complete current direct customer-delivery tariff evidence for the concrete SKU conditions after restrictions/physical feasibility filtering.
- Non-local route ordering is exact direct fee ascending. A pair-level SKU-independent `RouteCostIndex` may break an exact direct-fee tie; it never substitutes for an incomplete direct quote.
- `RouteCostIndex` is normalized only within identical price+volume tariff classes, excludes LOCAL rows, is stored once per route pair, and is not an allocation/margin score.
- The normalized customer-delivery tariff matrix is carried once. Do not persist or precompute a Cartesian `SKU × origin × destination` route-affinity/economics matrix.
- Cross-docking / seller supply-delivery tariffs are outside RouteCostIndex and DirectRouteQuote.
- When historical Flow % is shown for a concrete SKU route, use the destination-oriented denominator represented by `FulfillmentFlowCell.destination_share`; do not substitute the origin-profile `RouteDistributionCell.share`.
- The user selects the global operational supply network; per-SKU feasible origins are filtered/selected automatically by restrictions and route tariffs.
- Do not save daily historical inventory snapshots for the selected-network feature.
- Restrictions are the physical eligibility/capacity source. Explicit finite, explicit unlimited and unknown capacity evidence must remain distinct; unknown is never treated as unlimited.
- Multiple allowed warehouse maxima inside one cluster are not summed by the cluster-level planner unless a later warehouse-level design explicitly proves additive capacity.
- Economics changes placement/allocation priority and quantifies routing loss; it never creates or multiplies demand.
- Extra logistics, margin effect and profit effect are distinct metrics and must remain separately named.
- Historical route-impact ₽ uses current modeled tariffs/settings applied to historical observed quantities unless an explicit source provides historical charges.
- Missing tariffs, seller stock or product economics remain incomplete/unknown; never coerce them to zero to make a calculation appear complete.
- Ozon recommendation remains an external comparison/control signal, not a universal ceiling.
- **Safe destination target** is `min(Ozon recommendation, calculated need)` when both are complete. Physical feasibility applies downstream to selected origins in Coverage Planner.
- **Calculated destination target** is own calculated need and is not capped by Ozon recommendation. Physical feasibility applies downstream to selected origins in Coverage Planner. Calculated remains the primary `Наш план` family.
- The single supported product allocation objective is `MAX_MARGIN`; it is not user-selectable.
- Coverage Planner decides desired placement inside the selected network; MAX_MARGIN remains the allocation eligibility/scarcity policy.
- Numeric RouteCostIndex MUST NOT be a MAX_MARGIN scarcity sort key; scarcity uses exact direct/local route economics on desired legs.
- Keep `network_uncovered`, allocation-policy/data-blocked quantity, and seller-stock-uncovered quantity causally distinct.
- A network-only replan must create a new immutable PlanningSnapshot referencing the unchanged AnalysisSnapshot; it must not mutate/relabel the base analysis.
- Network-only replan may perform exact direct tariff lookup/economics from its immutable normalized PlanningBasis, but it must not rerun ingestion, demand, stockout, clean-route history or RouteCostIndex derivation.
- Checkbox edits are draft only. The selected network becomes applied only after explicit `Пересчитать план` succeeds.
- Frontend code must not calculate demand, stockout, route cleaning, route economics, unit economics, coverage quantities, RouteCostIndex, weighted margin/profit aggregates, or optimizer formulas.
- Do not serialize raw order/buyer PII or an unbounded daily route matrix to the frontend. Presentation contracts must remain bounded backend aggregates.
- Preserve metadata, lifecycle semantics, the PII boundary, fail-closed ingestion, incomplete-period handling, tariff coverage without renormalization, spreadsheet parity, and correct tax/VAT/co-invest, feasibility, and counterfactual economics contracts unless an approved later design explicitly changes them.

## Real-scale presentation safeguards

- Do not render every destination/origin/SKU as a large card simultaneously.
- Do not let Flow SVG/canvas height grow proportionally with route count.
- Do not use a global Sankey/chord for the full network.
- Flow overview uses selected context, bounded selectors, bounded route overview, and explicit drill-down.
- The locality timeline remains the primary visual explanation of historical demand retention + local-share collapse + donor substitution.
- Planned placement is a separate `План размещения` view, not a third historical evidence source.
- `Прочие` is a presentation grouping only; it must never become a fake business route or enter economics formulas.
- Raw repeated diagnostics are technical detail, not the primary user interface. Group root causes with counts and affected entities.
