# Codex Cloud instructions

## Source of truth

Before implementation, read, in order:

1. `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`;
2. `docs/superpowers/plans/2026-08-20-scoz-lite-mvp-implementation.md`.

The design has precedence over the plan, and the plan over issue summaries. The
2026-08-19 browser-only design and plan are historical/superseded for technical
architecture. Their business and analytical requirements remain binding unless
the new design explicitly changes them.

## Canonical runtime contract

```text
repository ZIP
→ extract fully
→ start.bat
→ project-local portable Python
→ FastAPI bound to 127.0.0.1:17843
→ browser opens after /api/health succeeds
```

`start.bat` is the only canonical application entry point after replacement PR1.
Do not restore `file://`, direct `app/index.html`, SheetJS, browser-side XLSX
parsing, or a parallel browser-only runtime without an explicitly approved future
design change.

## Architectural reference and boundaries

[SCOZ](https://github.com/vgvolmax/SCOZ) is the primary reference for proven
portable-Windows patterns: `start.bat`, project-local Python, launcher, FastAPI,
loopback-only serving, committed vanilla frontend, Python ingestion, openpyxl,
pytest, and Windows portable smoke. Check SCOZ before designing an analogous
mechanism; diverge only for a concrete product or technical reason.

sklad_ozon is deliberately SCOZ-lite. Do not copy SQLite, migrations, repository
infrastructure, lineage/revision systems, accounts, auth, background jobs, or
other subsystems that the active MVP does not need. Project JSON remains the
planned persistence boundary.

## Development and verification

- Production frontend remains committed vanilla HTML/CSS/JavaScript: no npm,
  TypeScript, framework, compiler, bundler, or frontend build.
- Python owns ingestion, domain rules, analytics, economics, feasibility, and
  optimization. FastAPI routes are a thin application/transport shell.
- Use dependency-free functional cores and imperative shells; test Python with
  `python -m pytest -q`.
- Runtime dependencies are pinned. Do not add one without a demonstrated need.
- `runtime/` is disposable and separate from gitignored `data/`; repairing the
  runtime must never erase local data.
- Use TDD for behavior changes, work outside `main`, follow PR1–PR8, and create
  directories only when the current implementation needs them (YAGNI).
- Codex implementation constraints do not redefine the end-user architecture.
  Windows GitHub Actions is authoritative for portable Windows acceptance.

## Analytical safeguards

Runtime migration must not alter the domain model. Delivery/destination cluster
is customer-demand geography; origin/dispatch cluster is physical fulfillment
origin. Preserve metadata, lifecycle and PII boundaries, net-demand and
fulfilled-route populations, incomplete-week handling, stockout and distortion
logic, observed/clean routes, tariff coverage, spreadsheet parity, tax/VAT/
co-invest, feasibility, placement assessment, counterfactuals, recommendation
ceilings, and optimizer limits.

Do not start a later PR early. Implement only the current scope and acceptance
fixes.
