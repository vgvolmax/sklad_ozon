# sklad_ozon SCOZ-lite MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the superseded browser-only foundation with a portable,
loopback-only Python/FastAPI application and deliver the unchanged Ozon FBO
analytical MVP through eight reviewable PRs.

**Architecture:** A project-local Windows Python runtime launches a thin FastAPI
shell on `127.0.0.1:17843`; committed vanilla frontend calls local APIs. Pure
Python modules own normalized domain contracts, ingestion, analytics, economics,
feasibility, and optimization. Project JSON is the only planned persistence.

**Tech Stack:** Official Windows embeddable Python 3.13.14; FastAPI 0.139.2;
Uvicorn 0.51.0; openpyxl 3.1.5; python-multipart 0.0.32; pytest 8.4.2; httpx
0.28.1; stdlib csv/zipfile/XML/JSON; committed HTML/CSS/plain JavaScript.

**Spec:** `docs/superpowers/specs/2026-08-20-scoz-lite-portable-architecture-design.md`.
It has technical precedence. The 2026-08-19 design remains binding for business
requirements that the canonical spec does not explicitly change.

## Global Constraints

- Execute PR1 through PR8 in order. Each PR must be independently reviewable and
  green; do not begin the next PR in the same change set.
- Use RED/GREEN TDD. Run the exact focused RED before production implementation,
  then focused GREEN and `python -m pytest -q` regression.
- Do not add dependencies beyond the pinned stack without a sanitized failing
  test and approved architecture change.
- Keep frontend vanilla and thin: no npm, package manifest, TypeScript, framework,
  bundler, build, business formulas, or workbook parsing.
- Bind only `127.0.0.1:17843`. Do not preserve direct `file:// app/index.html` as
  an alternate runtime after PR1.
- Preserve functional core/imperative shell, domain language, report metadata,
  lifecycle/PII rules, current-week exclusion, coverage, economics, feasibility,
  and optimizer invariants.
- Create directories when their first behavior is implemented, never as empty
  future scaffolding. Keep `runtime/` and `data/` gitignored and separate.
- Fixture workbooks and CSVs must be sanitized, minimal, deterministic, and free
  of seller/customer PII.
- Every task's final commit is made only after its GREEN and regression commands
  pass. If tasks are combined into one PR, retain the listed commit boundaries.

---

# PR1 — Replacement SCOZ-lite foundation and Python domain contracts

Merged GitHub PR #18 implemented the old browser-only foundation. Its technical
architecture is superseded. This replacement PR removes that implementation
rather than maintaining two runtime paths.

## Task 1: Pin Python runtime and bootstrap contract

**Files:** Create `requirements.txt`, `requirements-dev.txt`, `start.bat`,
`tests/test_runtime_bootstrap.py`; modify `.gitignore`.

**Interfaces:** `start.bat` accepts no required arguments, validates and reuses or
rebuilds `runtime/`, and invokes `runtime\python.exe launcher.py`. Validation
requires that the local interpreter exists, reports exactly Python 3.13.14, and
imports the exact pinned runtime dependency versions. It never falls back to
system Python, modifies PATH, or modifies/deletes `data/`.

- [ ] **Concrete failing test:** write `test_runtime_versions_are_exactly_pinned`
  to parse both requirements files and `test_start_script_uses_local_runtime`
  to assert the local path, exact Python version, no PATH mutation or system
  fallback, runtime/data isolation, working-runtime reuse, and broken-runtime
  rebuild. Assert incomplete downloads use `.part` and cannot pass validation.
- [ ] **RED command:** `python -m pytest tests/test_runtime_bootstrap.py -q`
- [ ] **Expected RED reason:** requirements and bootstrap files do not exist.
- [ ] **Minimal production implementation:** pin `fastapi==0.139.2`,
  `uvicorn==0.51.0`, `openpyxl==3.1.5`, `python-multipart==0.0.32`, then
  `-r requirements.txt`, `pytest==8.4.2`, `httpx==0.28.1`; follow the SCOZ
  bootstrap pattern to download official embeddable Python 3.13.14 through a
  `.part` path, reject absent/plainly corrupt artifacts, bootstrap pip, and
  validate the interpreter and exact installed versions before invoking the
  launcher. Rebuild only `runtime/` on failure and reuse it on success. Ignore
  `/runtime/` and `/data/` without creating either directory or a separate
  generic runtime-metadata subsystem.
- [ ] **GREEN command:** `python -m pytest tests/test_runtime_bootstrap.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add .gitignore start.bat requirements.txt requirements-dev.txt tests/test_runtime_bootstrap.py && git commit -m "feat: add portable Python bootstrap contract"`

## Task 2: Add launcher lifecycle and developer server command

**Files:** Create `launcher.py`, `RUN_SERVER.cmd`, `tests/test_launcher.py`.

**Interfaces:** `launcher.expected_health(payload)`, `fetch_health(...)`,
`port_is_open()`, `start_server_wrapper()`, `wait_until_ready(...)`,
`open_browser()`, and `launch()` implement the SCOZ lifecycle. `launch()` reuses
an existing valid health response; otherwise it requires a free port, starts
`RUN_SERVER.cmd` detached/in the background, waits to a bounded deadline, and
opens one browser tab only after readiness. It writes startup state under
`data/`, returns success, and leaves a successfully started server running.

- [ ] **Concrete failing test:** with existing valid health, prove server start is
  not called, browser opens once, and launch succeeds. With a free port and no
  initial health, prove the detached wrapper starts once, readiness eventually
  succeeds, browser opens once, launch succeeds, and no stop/cleanup call occurs.
  With permanent readiness failure, prove no browser opens and failure status is
  written. With an occupied port and invalid health, prove no second server is
  started, an actionable failure is returned, and no browser opens.
- [ ] **RED command:** `python -m pytest tests/test_launcher.py -q`
- [ ] **Expected RED reason:** `launcher` cannot be imported.
- [ ] **Minimal production implementation:** use stdlib subprocess, urllib,
  webbrowser, JSON, and pathlib with injected helpers for deterministic tests;
  create `data/` lazily; start `RUN_SERVER.cmd` with Windows detached/background
  flags and the project-local interpreter at the same bind/port. The production
  launcher never stops a successfully started server; smoke/tests own explicit
  cleanup of servers they create.
- [ ] **GREEN command:** `python -m pytest tests/test_launcher.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add launcher.py RUN_SERVER.cmd tests/test_launcher.py && git commit -m "feat: launch loopback service after health readiness"`

## Task 3: Introduce FastAPI health and committed frontend serving

**Files:** Create `backend/__init__.py`, `backend/config.py`, `backend/main.py`,
`tests/api/test_health.py`; move `app/index.html` to `frontend/index.html`,
`app/assets/css/app.css` to `frontend/assets/css/app.css`, and the UI shell script
to `frontend/assets/js/app.js`; update asset references.

**Interfaces:** `GET /api/health` returns
`{"status":"ok","service":"sklad_ozon","api_version":1}`; `GET /` returns the
committed frontend; `/assets/*` serves local committed assets.

- [ ] **Concrete failing test:** TestClient asserts exact health JSON/content type,
  index HTML response, CSS/JS reachability, and config host/port constants equal
  `127.0.0.1` and `17843`.
- [ ] **RED command:** `python -m pytest tests/api/test_health.py -q`
- [ ] **Expected RED reason:** `backend.main` and target frontend paths are absent.
- [ ] **Minimal production implementation:** create app/config, define health
  before mounting static assets, serve index explicitly, move the visual shell
  without redesign, and use local server paths only.
- [ ] **GREEN command:** `python -m pytest tests/api/test_health.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend frontend tests/api app && git commit -m "feat: serve vanilla frontend from local FastAPI"`

## Task 4: Port canonical domain language from JavaScript to Python

**Files:** Create `backend/domain/__init__.py`, `backend/domain/contracts.py`,
`backend/domain/invariants.py`, `tests/domain/test_contracts.py`,
`tests/domain/test_invariants.py`; delete `app/assets/js/domain/contracts.js`,
`app/assets/js/domain/invariants.js`, `tests/helpers/load-classic-script.mjs`, and
superseded node:test domain test files identified by `git grep load-classic-script`.

**Interfaces:** Python exposes `OrderLifecycle`, `ReportMeta`, `ImportResult`,
`OrderRecord`, cluster-direction guards, lifecycle population predicates, the PII
boundary, and serializable validation errors. Future behavioral contracts are
introduced by their owning PR rather than as empty dataclasses in PR1.

- [ ] **Concrete failing test:** instantiate each listed contract; reject an order whose
  destination and origin fields are missing; prove net-demand eligibility is
  fulfilled/in-progress, route eligibility is fulfilled only, and a
  `Kazan → Moscow` record retains Moscow destination and Kazan origin.
- [ ] **RED command:** `python -m pytest tests/domain/test_contracts.py tests/domain/test_invariants.py -q`
- [ ] **Expected RED reason:** Python domain package does not exist.
- [ ] **Minimal production implementation:** port semantics into frozen
  dataclasses/enums and pure guards, preserving unknown lifecycle and explicit
  metadata/diagnostics; remove the obsolete JavaScript implementation and its
  Node harness after parity tests pass.
- [ ] **GREEN command:** `python -m pytest tests/domain/test_contracts.py tests/domain/test_invariants.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add -A backend/domain tests/domain app/assets/js/domain tests/helpers && git commit -m "feat: port canonical domain contracts to Python"`

## Task 5: Make start.bat the sole runtime and add Windows acceptance

**Files:** Delete remaining obsolete `app/` runtime files and old node:test tests;
create `.github/workflows/ci.yml`, `tests/windows/portable-smoke.ps1`; modify
`README.md` only where implementation status must become release fact.

**Interfaces:** Windows smoke runs `start.bat` in a path containing spaces with an
isolated runtime/data sandbox, observes `/api/health`, verifies reuse on second
launch, and proves the listener is loopback-only. CI runs Python 3.13 tests before
portable smoke.

- [ ] **Concrete failing test:** PowerShell smoke asserts the first launch prepares
  the runtime and reaches health; the second launch succeeds with that same
  validated runtime without another Python download or pip/dependency
  install/rebuild; the sentinel in `data/` remains intact; no listener exists on
  non-loopback addresses; and the test server shuts down cleanly. Do not introduce
  a test-only metadata artifact solely to prove reuse.
- [ ] **RED command:** `powershell -File tests/windows/portable-smoke.ps1`
- [ ] **Expected RED reason:** smoke/workflow and complete portable behavior are
  absent; on non-Windows development hosts this RED is recorded and executed by
  the first Windows Actions run before merge.
- [ ] **Minimal production implementation:** remove the direct browser entry point
  and obsolete harness, add Python test job plus Windows portable job patterned
  on SCOZ but scoped to sklad_ozon, cache only downloads when safe, and retain
  artifacts/logs on failure.
- [ ] **GREEN command:** `powershell -File tests/windows/portable-smoke.ps1`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add -A app tests .github/workflows/ci.yml README.md && git commit -m "test: enforce portable Windows foundation"`

**PR1 acceptance:** `start.bat` is the only application entry point; no production
browser XLSX path or obsolete JS domain contracts remain; Python suite and Windows
portable smoke pass.

---

# PR2 — Operational imports in Python

## Task A: Normalize source values and classify lifecycle

**Files:** Create `backend/ingestion/__init__.py`,
`backend/ingestion/normalization.py`, `backend/ingestion/lifecycle.py`,
`tests/ingestion/test_normalization.py`, `tests/ingestion/test_lifecycle.py`.

**Interfaces:** `normalize_header(value)`, `normalize_text(value)`,
`normalize_cluster_label(raw)`,
`resolve_cluster_id(raw_label, alias_map, manual_mappings)`, and
`classify_order_lifecycle(raw_status)` return normalized/classified values plus
diagnostics where applicable. `normalize_cluster_label` is harmless text cleanup
only: Unicode and NBSP/whitespace normalization, trim, and whitespace collapse;
case normalization is allowed only when it cannot change semantic identity. It
must not translate, shorten, geographically guess, or otherwise change cluster
identity. Semantic resolution occurs only in `resolve_cluster_id` from explicit
caller-supplied maps: manual mappings take precedence over imported/confirmed
aliases, and a missing mapping returns `None`/unresolved with a diagnostic.

- [ ] **Concrete failing test:** cover BOM headers, nonbreaking spaces, composed
  Unicode, blank values, and Ozon statuses mapping to all four lifecycle values
  without silently treating unknown as cancelled. Assert
  `normalize_cluster_label("  МОСКВА  ") == "МОСКВА"`. Assert `Москва Север`
  resolves to `None`/unresolved with a diagnostic when both maps are empty. With
  caller-supplied `alias_map={"МОСКВА": "cluster-moscow"}`, assert `МОСКВА`
  resolves to `cluster-moscow`. With that key in both maps, assert the explicit
  `manual_mappings={"МОСКВА": "cluster-moscow-manual"}` value wins over
  `alias_map={"МОСКВА": "cluster-moscow-imported"}` and the result is
  `cluster-moscow-manual`.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_normalization.py tests/ingestion/test_lifecycle.py -q`
- [ ] **Expected RED reason:** ingestion normalization modules are absent.
- [ ] **Minimal production implementation:** pure stdlib text normalization plus
  lookup only in the mappings supplied to `resolve_cluster_id`; preserve raw
  source values and emit diagnostics for semantic decisions. Add no hard-coded
  Ozon cluster master, embedded Russian-to-English cluster dictionary, fuzzy
  semantic matching, or automatic geography guessing.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_normalization.py tests/ingestion/test_lifecycle.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion tests/ingestion && git commit -m "feat: normalize import values and lifecycle"`

## Task B: Add XLSX adapter and malformed-dimension regression

**Files:** Create `backend/ingestion/xlsx.py`,
`tests/ingestion/test_xlsx_adapter.py`,
`tests/fixtures/xlsx/ozon_dimension_a1.xlsx`,
`tests/fixtures/xlsx/ozon_regular.xlsx`, and
`tests/fixtures/xlsx/README.md`.

**Interfaces:** `iter_worksheet_rows(stream, sheet_selector)` returns every
populated row with its source row number and diagnostics; repaired workbooks emit
`WORKSHEET_DIMENSION_REPAIRED` exactly once.

- [ ] **Concrete failing test:** a sanitized workbook declares
  `<dimension ref="A1"/>` but contains a header and at least three populated data
  rows; regular and read-only modes return all values in order, and only malformed
  input emits the repair diagnostic.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_xlsx_adapter.py -q`
- [ ] **Expected RED reason:** the adapter is absent and the malformed declared
  range can truncate openpyxl iteration.
- [ ] **Minimal production implementation:** use openpyxl 3.1.5 and
  `reset_dimensions()` first; add narrowly scoped zipfile/ElementTree range
  inspection only if the fixture proves it necessary, never independent XLSX cell
  parsing.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_xlsx_adapter.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion/xlsx.py tests/ingestion/test_xlsx_adapter.py tests/fixtures/xlsx && git commit -m "feat: recover malformed Ozon worksheet dimensions"`

## Task C: Add the CSV row adapter

**Files:** Create `backend/ingestion/csv_adapter.py`,
`tests/ingestion/test_csv_adapter.py`, and sanitized files under
`tests/fixtures/csv/`.

**Interfaces:** `iter_csv_rows(data, encoding="utf-8-sig")` accepts bytes and
returns normalized header-keyed rows with source row numbers and structured
adapter diagnostics.

- [ ] **Concrete failing test:** cover UTF-8 BOM, comma and semicolon inputs,
  quoted delimiters, CRLF/LF, missing headers, duplicate normalized headers, and
  stable source row numbers.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_csv_adapter.py -q`
- [ ] **Expected RED reason:** `backend.ingestion.csv_adapter` does not exist.
- [ ] **Minimal production implementation:** use stdlib `csv` with candidate
  delimiters limited to comma and semicolon; reuse normalization helpers and
  return explicit diagnostics instead of guessing through invalid headers.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_csv_adapter.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion/csv_adapter.py tests/ingestion/test_csv_adapter.py tests/fixtures/csv && git commit -m "feat: add deterministic CSV row adapter"`

## Task D: Import availability reports

**Files:** Create `backend/ingestion/availability.py`,
`tests/ingestion/test_availability.py`, and sanitized availability fixtures under
`tests/fixtures/operational/`.

**Interfaces:** `import_availability(data, report_context)` consumes rows from the
XLSX/CSV adapter and returns `ImportResult` with immutable normalized availability
records, `ReportMeta`, source row numbers, and structured diagnostics.

- [ ] **Concrete failing test:** cover required/duplicate headers, report date,
  SKU and warehouse/cluster normalization, numeric quantities, invalid negative
  or malformed values, source row numbers, and metadata/diagnostic retention.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_availability.py -q`
- [ ] **Expected RED reason:** the availability importer does not exist.
- [ ] **Minimal production implementation:** add the report-specific header map
  and pure row conversion over the common adapter interface; create the smallest
  shared ImportResult/diagnostics helper here if repeated construction requires
  it, without a generic importer framework.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_availability.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion/availability.py tests/ingestion/test_availability.py tests/fixtures/operational && git commit -m "feat: import Ozon availability reports"`

## Task E: Import restriction reports

**Files:** Create `backend/ingestion/restrictions.py`,
`tests/ingestion/test_restrictions.py`, and sanitized restriction fixtures under
`tests/fixtures/operational/`.

**Interfaces:** `import_restrictions(data, report_context)` returns `ImportResult`
with normalized SKU/warehouse restriction records, `ReportMeta`, source row
numbers, reason codes, and structured diagnostics.

- [ ] **Concrete failing test:** cover required/duplicate headers, explicit
  allowed/prohibited source values, unknown restriction values, report date,
  source row numbers, SKU/warehouse normalization, and rejected malformed rows.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_restrictions.py -q`
- [ ] **Expected RED reason:** the restrictions importer does not exist.
- [ ] **Minimal production implementation:** define an explicit source-value map
  and immutable restriction rows over the shared adapter/diagnostic contracts;
  preserve unknown values diagnostically rather than coercing them to allowed.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_restrictions.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion/restrictions.py tests/ingestion/test_restrictions.py tests/fixtures/operational && git commit -m "feat: import Ozon restriction reports"`

## Task F: Import orders with direction and PII safeguards

**Files:** Create `backend/ingestion/orders.py`,
`tests/ingestion/test_orders.py`, and sanitized order fixtures under
`tests/fixtures/operational/`.

**Interfaces:** `import_orders(data, report_context)` returns an `ImportResult` of
`OrderRecord` values with `ReportMeta`, source row numbers, lifecycle and
structured diagnostics. Normalized records expose no buyer/customer name,
address, phone, email, or raw-row payload.

- [ ] **Concrete failing test:** cover required/duplicate headers, numeric parsing,
  report date, every lifecycle, and source row numbers. A sanitized
  `Казань → Москва` input must produce `origin_cluster == "Казань"` and
  `destination_cluster == "Москва"`; input buyer/customer name, address, phone,
  and email must be wholly absent from the normalized `ImportResult` and its
  serialized form.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_orders.py -q`
- [ ] **Expected RED reason:** the orders importer does not exist.
- [ ] **Minimal production implementation:** map explicit order headers through
  the common adapters, lifecycle classifier, and direction guards; construct
  only whitelisted immutable `OrderRecord` fields so PII never crosses the
  normalized boundary.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_orders.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/ingestion/orders.py tests/ingestion/test_orders.py tests/fixtures/operational && git commit -m "feat: import directional orders without PII"`

---

# PR3 — Tariffs, product economics, and Project JSON

## Task 9: Import slowly changing inputs and persist safe project state

**Files:** Create `backend/ingestion/tariffs.py`,
`backend/ingestion/product_economics.py`, `backend/project.py`,
`tests/ingestion/test_tariffs.py`, `tests/ingestion/test_product_economics.py`,
`tests/test_project.py`, and sanitized `tests/fixtures/project/` inputs.

**Interfaces:** importers return typed rows with metadata; `load_project(path)`
and `save_project_atomic(path, project)` enforce schema version and permit only
tariffs+metadata, product economics, available stock, mappings, settings,
thresholds, and explicitly dated operational snapshots.

- [ ] **Concrete failing test:** import decimal/percent cells and tariff validity;
  round-trip an allowed project; reject unknown version, undated snapshot, raw
  report bytes, and customer PII; simulate replacement failure and prove the old
  JSON remains intact.
- [ ] **RED command:** `python -m pytest tests/ingestion/test_tariffs.py tests/ingestion/test_product_economics.py tests/test_project.py -q`
- [ ] **Expected RED reason:** slow-input importers and Project JSON boundary are
  absent.
- [ ] **Minimal production implementation:** explicit field schemas, Decimal-safe
  conversion policy, validation before mutation, UTF-8 JSON temporary write plus
  atomic replace; add no database or repository abstraction.
- [ ] **GREEN command:** `python -m pytest tests/ingestion/test_tariffs.py tests/ingestion/test_product_economics.py tests/test_project.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend tests && git commit -m "feat: persist validated Project JSON inputs"`

---

# PR4 — Demand and fulfillment analytics

## Task 10: Aggregate completed-week demand and directional routes

**Files:** Create `backend/analytics/__init__.py`,
`backend/analytics/demand.py`, `backend/analytics/routes.py`,
`tests/analytics/test_demand_routes.py`.

**Interfaces:** `aggregate_demand(orders, as_of, week_policy)` uses destination;
`build_route_profile(orders, as_of, week_policy)` uses origin→destination and
returns counts/shares plus completed-week metadata.

- [ ] **Concrete failing test:** fixture contains 800 Moscow→Moscow fulfilled,
  200 Kazan→Moscow fulfilled, 100 Kazan→Kazan fulfilled, and 100 cancelled
  Kazan→Moscow. Assert Moscow fulfilled demand 1000, Kazan fulfilled demand 100,
  Moscow destination local share 80%, and Kazan origin local share `100 / 300`.
  Add in-progress to net demand but not fulfilled routes; exclude the explicit
  current/incomplete week.
- [ ] **RED command:** `python -m pytest tests/analytics/test_demand_routes.py -q`
- [ ] **Expected RED reason:** analytics modules are absent.
- [ ] **Minimal production implementation:** pure grouping keyed by destination
  for demand and origin/destination for routes, lifecycle predicates from domain,
  explicit denominator/population metadata, and injected as-of date.
- [ ] **GREEN command:** `python -m pytest tests/analytics/test_demand_routes.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/analytics tests/analytics && git commit -m "feat: compute directional demand and route profiles"`

---

# PR5 — Stockout, recommendation distortion, and clean routes

## Task 11: Detect probable stockouts and donor distortion

**Files:** Create `backend/domain/signals.py`, `backend/analytics/stockout.py`,
`backend/analytics/distortion.py`, `tests/analytics/test_stockout_distortion.py`.

**Interfaces:** `detect_stockouts(weekly_profiles, availability, thresholds)`
returns the PR5-owned `StockoutSignal`;
`detect_recommendation_distortion(signals, routes)` returns the PR5-owned
`RecommendationDistortionSignal` with destination-linked donor evidence and
never rewrites observed history.

- [ ] **Concrete failing test:** week1 Moscow demand 100/local 90%/Kazan donor 5%;
  week2 Moscow demand 95/local 20%/Kazan donor 65%. Assert probable Moscow
  stockout and Kazan donor/distortion referencing Moscow. Show availability can
  corroborate confidence but cannot create or erase the route-pattern signal.
- [ ] **RED command:** `python -m pytest tests/analytics/test_stockout_distortion.py -q`
- [ ] **Expected RED reason:** detectors do not exist.
- [ ] **Minimal production implementation:** introduce both immutable signal
  types with their first detectors; use explicit threshold comparisons over
  completed weeks, no origin-as-demand shortcut, and a separate corroboration
  field.
- [ ] **GREEN command:** `python -m pytest tests/analytics/test_stockout_distortion.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/domain/signals.py backend/analytics tests/analytics && git commit -m "feat: identify stockout-driven route distortion"`

## Task 12: Produce observed and clean route profiles

**Files:** Create `backend/analytics/clean_routes.py`,
`tests/analytics/test_clean_routes.py`.

**Interfaces:** `build_clean_route_profile(observed, distortions, policy)` returns
both observed and clean profiles, excluded evidence, share sums, and fallback
status; it never mutates the observed profile.

- [ ] **Concrete failing test:** remove the flagged Moscow distortion interval,
  preserve unflagged Kazan demand, prove observed values remain byte-for-byte
  equal, and exercise no-clean-history fallback with an explicit insufficient
  data diagnostic rather than fabricated shares.
- [ ] **RED command:** `python -m pytest tests/analytics/test_clean_routes.py -q`
- [ ] **Expected RED reason:** clean-route module is absent.
- [ ] **Minimal production implementation:** filter source observations by signal
  identity, recompute denominators without hiding exclusions, and return both
  profiles with coverage/evidence.
- [ ] **GREEN command:** `python -m pytest tests/analytics/test_clean_routes.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/analytics/clean_routes.py tests/analytics/test_clean_routes.py && git commit -m "feat: derive auditable clean route profiles"`

---

# PR6 — Tariff engine and unit economics

## Task 13: Calculate covered route logistics without renormalization

**Files:** Create `backend/economics/__init__.py`,
`backend/economics/tariffs.py`, `tests/economics/test_tariffs.py`.

**Interfaces:** `expected_logistics(profile, tariff_table, context)` returns total
expected cost, covered/uncovered share, per-route contributions, lookup metadata,
and diagnostics.

- [ ] **Concrete failing test:** 80% route at 50 plus 20% route at 100 equals
  expected logistics 60. With only the 80% tariff, contribution is 40 and
  coverage is 80%; assert the engine does **not** renormalize 80% to 100% and does
  not claim a complete expected cost.
- [ ] **RED command:** `python -m pytest tests/economics/test_tariffs.py -q`
- [ ] **Expected RED reason:** economics tariff engine is absent.
- [ ] **Minimal production implementation:** Decimal contributions against the
  original profile weights, explicit uncovered route keys, effective-date lookup,
  and caller-visible completeness status.
- [ ] **GREEN command:** `python -m pytest tests/economics/test_tariffs.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/economics tests/economics && git commit -m "feat: calculate coverage-aware route logistics"`

## Task 14: Match unit-economics spreadsheet semantics

**Files:** Create `backend/economics/unit.py`,
`tests/economics/test_unit.py`, `tests/fixtures/economics/spreadsheet_cases.json`.

**Interfaces:** `calculate_unit_economics(product, placement, logistics, settings)`
returns line items, tax/VAT/co-invest bases, contribution/profit, margin,
coverage, and rounding metadata.

- [ ] **Concrete failing test:** encode numeric cases from the approved spreadsheet
  for commission, acquisition/cost, logistics, tax, VAT mode, co-invest, returns,
  and rounding; include zero revenue, negative profit, and partial tariff coverage
  that remains incomplete.
- [ ] **RED command:** `python -m pytest tests/economics/test_unit.py -q`
- [ ] **Expected RED reason:** unit-economics calculator is absent.
- [ ] **Minimal production implementation:** pure Decimal formulas in named line
  item order, explicit bases and quantization boundaries, no float coercion, and
  no presentation rounding inside intermediate calculations.
- [ ] **GREEN command:** `python -m pytest tests/economics/test_unit.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/economics/unit.py tests/economics && git commit -m "feat: implement spreadsheet-parity unit economics"`

---

# PR7 — Feasibility, placement comparison, and optimizer

## Task 15: Assess feasibility and counterfactual placements

**Files:** Create `backend/supply/__init__.py`, `backend/supply/contracts.py`,
`backend/supply/feasibility.py`, `backend/supply/placement.py`,
`tests/supply/test_placement.py`.

**Interfaces:** this PR introduces `PlacementAssessment` with its first behavior;
`assess_feasibility` returns reason-coded eligibility, and `compare_placements`
returns assessments for observed, recommended, and counterfactual candidates
while keeping assessment distinct from allocation.

- [ ] **Concrete failing test:** evaluate Moscow when Ozon recommendation is zero:
  counterfactual economics remain visible, but automatic eligibility/ceiling is
  zero. Cover restriction, warehouse acceptance, incomplete tariffs, and a
  feasible positive-ceiling case with comparable line items.
- [ ] **RED command:** `python -m pytest tests/supply/test_placement.py -q`
- [ ] **Expected RED reason:** supply feasibility/placement modules are absent.
- [ ] **Minimal production implementation:** compose domain restrictions,
  warehouse capabilities, coverage and economics into reason-coded assessments;
  never convert a profitable counterfactual into feasibility.
- [ ] **GREEN command:** `python -m pytest tests/supply/test_placement.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/supply tests/supply && git commit -m "feat: assess feasible and counterfactual placements"`

## Task 16: Optimize limited seller stock under hard ceilings

**Files:** Modify `backend/supply/contracts.py`; create `backend/supply/optimizer.py`,
`tests/supply/test_optimizer.py`.

**Interfaces:** introduce `ClusterCandidate` only if the optimizer's tested input
requires that named type; `optimize_allocations(candidates, available_stock, thresholds)`
maximizes `Σ allocation × expected_profit_per_unit` with integer nonnegative
allocations, total-stock limit, feasibility, recommendation ceilings, and minimum
quality/coverage thresholds; result includes objective and binding reasons.

- [ ] **Concrete failing test:** allocate scarce units to highest incremental
  profit within ceilings, handle ties deterministically, never exceed stock, and
  prove a profitable counterfactual Moscow candidate with recommendation ceiling
  zero receives automatic allocation zero. Reject infeasible and insufficient-
  coverage candidates.
- [ ] **RED command:** `python -m pytest tests/supply/test_optimizer.py -q`
- [ ] **Expected RED reason:** optimizer module is absent.
- [ ] **Minimal production implementation:** deterministic exact allocation for
  the approved separable linear objective (profit-ranked bounded integer fill),
  with Decimal objective and auditable exclusion/binding reasons; do not add a
  solver dependency.
- [ ] **GREEN command:** `python -m pytest tests/supply/test_optimizer.py -q`
- [ ] **Regression command:** `python -m pytest -q`
- [ ] **Commit:** `git add backend/supply/contracts.py backend/supply/optimizer.py tests/supply/test_optimizer.py && git commit -m "feat: optimize stock under recommendation ceilings"`

---

# PR8 — UI and release hardening

## Task 17: Expose application APIs and connect the thin UI

**Files:** Create `backend/application.py`, `backend/api.py`,
`tests/api/test_analysis.py`; modify `backend/main.py`, `frontend/index.html`,
`frontend/assets/css/app.css`, `frontend/assets/js/app.js`.

**Interfaces:** multipart import endpoints return versioned ImportResult JSON;
analysis endpoint returns demand, observed/clean routes, signals, economics,
placement assessments, allocations, metadata, coverage, and diagnostics. UI
renders these contracts and keeps formulas server-side.

- [ ] **Concrete failing test:** TestClient uploads sanitized operational inputs,
  receives exact response keys/status/error shape, proves no PII echo, and checks
  `frontend/assets/js/app.js` calls only relative `/api/` URLs and contains no
  XLSX parsing or unit-economics formula implementation.
- [ ] **RED command:** `python -m pytest tests/api/test_analysis.py -q`
- [ ] **Expected RED reason:** application orchestration and analysis endpoints are
  absent.
- [ ] **Minimal production implementation:** thin dependency-injected orchestration
  over existing pure modules, bounded multipart validation, stable serialization,
  and vanilla DOM/fetch presentation with accessible status/error states.
- [ ] **GREEN command:** `python -m pytest tests/api/test_analysis.py -q`
- [ ] **Regression command:** `python -m pytest -q && node --check frontend/assets/js/app.js`
- [ ] **Commit:** `git add backend frontend tests/api && git commit -m "feat: connect local analysis API and UI"`

## Task 18: Harden offline portable release behavior

**Files:** Modify `start.bat`, `launcher.py`, `backend/main.py`, `README.md`,
`.github/workflows/ci.yml`, `tests/windows/portable-smoke.ps1`; create
`tests/test_offline_assets.py`.

**Interfaces:** release works from an extracted path with spaces, reuses valid
runtime without network, rejects corrupt runtime with actionable repair state,
serves no external asset URL, preserves `data/`, and shuts down cleanly.

- [ ] **Concrete failing test:** static test rejects external runtime asset links;
  Windows smoke disables network after prepared launch, launches again, checks
  health/UI, validates seller-data locality and data sentinel, corrupts a required
  runtime component, and observes bounded actionable failure/recovery rather than
  silent use or reliance on a generic runtime-metadata subsystem.
- [ ] **RED command:** `python -m pytest tests/test_offline_assets.py -q && powershell -File tests/windows/portable-smoke.ps1`
- [ ] **Expected RED reason:** final offline/corruption/path acceptance assertions
  are not yet satisfied; Windows half runs authoritatively in Actions.
- [ ] **Minimal production implementation:** close only demonstrated bootstrap,
  launcher, static-serving, logging, and cleanup gaps; document exact user flow
  and recovery; add no updater, telemetry, background-job framework, database,
  auth, LAN bind, or frontend toolchain.
- [ ] **GREEN command:** `python -m pytest tests/test_offline_assets.py -q && powershell -File tests/windows/portable-smoke.ps1`
- [ ] **Regression command:** `python -m pytest -q && node --check frontend/assets/js/app.js`
- [ ] **Commit:** `git add start.bat launcher.py backend/main.py README.md .github/workflows/ci.yml tests && git commit -m "test: harden offline portable release"`

**Final acceptance:** canonical entry is `start.bat`; Windows portable smoke is
green; full pytest is green; frontend has no runtime network dependency; all
business fixtures from PR4–PR7 remain green; no SQLite or unnecessary SCOZ
subsystem has entered the MVP.
