# Codex Cloud instructions

## Source of truth

Before implementing any work from the real-data demand/stockout/Flow roadmap, read, in order:

1. `docs/superpowers/specs/2026-09-03-real-data-demand-stockout-flow-design.md`;
2. the matching PR-specific 2026-09-03 design brief/spec (`pr1` … `pr5`);
3. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`;
4. `DESIGN.md`;
5. `UX-CONTRACT.md`;
6. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`;
7. the matching current implementation plan under `docs/superpowers/plans/`, when present.

For PR1 specifically, the implementation plan is:

`docs/superpowers/plans/2026-09-03-pr1-true-demand-daily-fulfillment-implementation.md`.

Precedence is:

```text
2026-09-03 real-data roadmap design
→ matching PR-specific 2026-09-03 spec/design brief
→ 2026-09-02 Product Completion design
→ DESIGN.md / UX-CONTRACT.md for UI
→ canonical SCOZ-lite runtime architecture
→ matching current implementation plan
→ older implementation plans / issue summaries
```

The 2026-09-03 roadmap supersedes the earlier Product Completion design only where it is more specific about real-data demand/routing separation, daily stockout evidence, financial-impact presentation, diagnostics and real-scale Flow UI. Other Product Completion business rules remain in force.

The 2026-08-20 SCOZ-lite design remains canonical only for runtime and technical architecture: project-local Python, FastAPI on `127.0.0.1:17843`, `start.bat`, committed vanilla HTML/CSS/JavaScript, Project JSON, and no frontend build system. It does not override Product Completion business rules. The 2026-08-19 browser-only architecture is historical; its business requirements remain in force only where the Product Completion designs do not supersede them.

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
- Before any UI change, read `DESIGN.md`, `UX-CONTRACT.md`, the 2026-09-03 roadmap design, and the matching PR-specific UI design brief.
- Production frontend remains committed vanilla HTML/CSS/JavaScript: no npm, TypeScript, framework, compiler, bundler, or frontend build.
- Python owns ingestion, domain rules, analytics, demand, stockout, economics, feasibility, optimization, diagnostic causal grouping and business presentation aggregates. FastAPI routes are a thin application/transport shell.
- Use dependency-free functional cores and imperative shells; test Python with `python -m pytest -q`.
- Runtime dependencies are pinned. Do not add one without a demonstrated need.
- `runtime/` is disposable and separate from gitignored `data/`; repairing the runtime must never erase local data.
- Do not rewrite working subsystems without a concrete product or technical reason. Create directories only when the current implementation needs them (YAGNI).
- Codex implementation constraints do not redefine the end-user architecture.
- Windows GitHub Actions portable smoke is an acceptance gate and authoritative for portable Windows runtime behavior.
- For PR5, tiny synthetic fixtures are insufficient by themselves: real-scale/stress browser acceptance is mandatory because the previous Flow implementation failed only at realistic cardinality.

## Analytical safeguards

- `destination_cluster` is customer-demand geography; `origin_cluster` is physical fulfillment origin. `Казань → Москва` remains Moscow demand fulfilled from Kazan, never Kazan demand.
- **Routing-independent observed destination demand** is the planning quantity source. Physical dispatch volume from an origin to other destinations never increases the origin cluster's own demand or calculated need.
- Example: if Moscow fulfills `Москва→Москва 500`, `Москва→Казань 300`, `Москва→Тверь 200`, Moscow physical dispatch is 1000 but Moscow demand is 500.
- External fulfillment does not erase destination demand. If Kazan demand is entirely fulfilled from Moscow, that volume remains Kazan demand.
- Do not fabricate latent/lost orders when inventory was unavailable everywhere. Such evidence may reduce confidence but does not create quantity without a separately approved model/source.
- Route cleaning and demand-history eligibility are separate mechanisms. A route-substitution period can be excluded from clean route history without erasing valid destination demand.
- Daily stockout/substitution detection is performed at `SKU × destination` before any cluster-level presentation aggregation.
- Current availability corroborates historical stockout evidence but does not define historical stock state.
- Economics changes placement priority and quantifies routing loss; it never creates or multiplies demand.
- Extra logistics, margin effect and profit effect are distinct metrics and must remain separately named.
- Historical route-impact ₽ uses current modeled tariffs/settings applied to historical observed quantities unless an explicit source provides historical charges.
- Missing tariffs, seller stock or product economics remain incomplete/unknown; never coerce them to zero to make a calculation appear complete.
- Ozon recommendation remains an external comparison/control signal, not a universal ceiling.
- **Safe Plan** is capped by Ozon recommendation, own calculated need, and physical feasibility.
- **Calculated Plan** is capped by own calculated need and physical feasibility, but not by Ozon recommendation. It is the primary `Наш план` recommendation.
- The single supported product allocation objective is `MAX_MARGIN`; it is not user-selectable.
- Frontend code must not calculate demand, stockout, route cleaning, route economics, unit economics, weighted margin/profit aggregates, or optimizer formulas.
- Do not serialize raw order/buyer PII or an unbounded daily route matrix to the frontend. PR3+ presentation contracts must be bounded backend aggregates.
- Preserve metadata, lifecycle semantics, the PII boundary, fail-closed ingestion, incomplete-period handling, tariff coverage without renormalization, spreadsheet parity, and correct tax/VAT/co-invest, feasibility, and counterfactual economics contracts unless the approved Product Completion designs explicitly change them.

## Real-scale presentation safeguards

- Do not render every destination/origin/SKU as a large card simultaneously.
- Do not let Flow SVG/canvas height grow proportionally with route count.
- Do not use a global Sankey/chord for the full network.
- PR5 overview uses selected context, bounded selectors, bounded route overview, and explicit drill-down.
- The locality timeline is the primary visual explanation of demand retention + local-share collapse + donor substitution.
- `Прочие` is a presentation grouping only; it must never become a fake business route or enter economics formulas.
- Raw repeated diagnostics are technical detail, not the primary user interface. Group root causes with counts and affected entities.
