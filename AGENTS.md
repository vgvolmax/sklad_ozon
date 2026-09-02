# Codex Cloud instructions

## Source of truth

Before implementing Product Completion, read, in order:

1. `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`;
2. `DESIGN.md`;
3. `UX-CONTRACT.md`;
4. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`;
5. the Product Completion implementation plan, when it appears.

Precedence is:

```text
Product Completion design
→ DESIGN.md / UX-CONTRACT.md for UI
→ canonical SCOZ-lite runtime architecture
→ Product Completion implementation plan
→ older implementation plans / issue summaries
```

The 2026-08-20 SCOZ-lite design remains canonical only for runtime and technical
architecture: project-local Python, FastAPI on `127.0.0.1:17843`, `start.bat`,
committed vanilla HTML/CSS/JavaScript, Project JSON, and no frontend build
system. It does not override Product Completion business rules. The 2026-08-19
browser-only architecture is historical; its business requirements remain in
force only where the Product Completion design does not supersede them.

## Canonical runtime contract

```text
repository ZIP
→ extract fully
→ start.bat
→ project-local portable Python
→ FastAPI bound to 127.0.0.1:17843
→ browser opens after /api/health succeeds
```

`start.bat` is the only canonical application entry point. Do not restore
`file://`, direct `app/index.html`, SheetJS, browser-side XLSX parsing, or a
parallel browser-only runtime without an explicitly approved future design
change.

## Architectural reference and boundaries

[SCOZ](https://github.com/vgvolmax/SCOZ) is the primary reference for proven
portable-Windows patterns: `start.bat`, project-local Python, launcher, FastAPI,
loopback-only serving, committed vanilla frontend, Python ingestion, openpyxl,
pytest, and Windows portable smoke. Check SCOZ before designing an analogous
mechanism; diverge only for a concrete product or technical reason.

sklad_ozon is deliberately SCOZ-lite. Do not copy SQLite, migrations, repository
infrastructure, lineage/revision systems, accounts, auth, background jobs, or
other subsystems that the approved product does not need. Project JSON remains
the persistence boundary.

## Development and verification

- Work outside `main`; use TDD for behavior changes and implement only the
  current approved scope and acceptance fixes.
- Before any UI change, read `DESIGN.md` and `UX-CONTRACT.md`.
- Production frontend remains committed vanilla HTML/CSS/JavaScript: no npm,
  TypeScript, framework, compiler, bundler, or frontend build.
- Python owns ingestion, domain rules, analytics, demand, stockout, economics,
  feasibility, and optimization. FastAPI routes are a thin
  application/transport shell.
- Use dependency-free functional cores and imperative shells; test Python with
  `python -m pytest -q`.
- Runtime dependencies are pinned. Do not add one without a demonstrated need.
- `runtime/` is disposable and separate from gitignored `data/`; repairing the
  runtime must never erase local data.
- Do not rewrite working subsystems without a concrete product or technical
  reason. Create directories only when the current implementation needs them
  (YAGNI).
- Codex implementation constraints do not redefine the end-user architecture.
  Windows GitHub Actions portable smoke is an acceptance gate and authoritative
  for portable Windows runtime behavior.

## Analytical safeguards

- `destination_cluster` is customer-demand geography; `origin_cluster` is the
  physical fulfillment origin. `Казань → Москва` remains Moscow demand fulfilled
  from Kazan, never Kazan demand.
- Route cleaning and demand-history eligibility are separate mechanisms. A
  route-substitution period can be excluded from clean route history without
  erasing valid destination demand.
- Economics changes placement priority; it never creates or multiplies demand.
- Ozon recommendation remains an external comparison/control signal, not a
  universal ceiling.
- **Safe Plan** is capped by Ozon recommendation, own calculated need, and
  physical feasibility.
- **Calculated Plan** is capped by own calculated need and physical feasibility,
  but not by Ozon recommendation. It is the primary `Наш план` recommendation.
- The supported allocation objectives are `Макс. прибыль` and `Макс. маржа`.
- Frontend code must not calculate demand, stockout, route economics, unit
  economics, or optimizer formulas.
- Preserve metadata, lifecycle semantics, the PII boundary, fail-closed
  ingestion, incomplete-period handling, tariff coverage without
  renormalization, spreadsheet parity, and correct tax/VAT/co-invest,
  feasibility, and counterfactual economics contracts unless the Product
  Completion design explicitly changes them.
- Current availability corroborates historical stockout evidence but does not
  define historical stock state. Follow the Product Completion design's
  confidence and route-cleaning rules rather than preserving an older stockout
  interpretation by default.
