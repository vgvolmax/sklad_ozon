# sklad_ozon SCOZ-lite Portable Architecture Design

**Date:** 2026-08-20
**Status:** canonical and approved for subsequent implementation

## 1. Status / supersession

This specification supersedes the runtime and technical architecture in
`2026-08-19-ozon-fbo-unit-economics-optimizer-design.md` and the browser-only
foundation merged in GitHub PR #18. The old document remains authoritative for
business and analytical requirements unless this specification explicitly
changes one. This is a runtime migration, not a business redesign.

The former `repository ZIP → extract → file:// app/index.html` flow and its
SheetJS/browser-ingestion implementation are historical, not alternative entry
points. Replacement PR1 makes `start.bat` the sole canonical entry point.

## 2. Product goal

The product locally imports XLSX/CSV Ozon reports, separates demand geography
from fulfillment origin, evaluates placement economics and constraints, and
optimizes scarce seller stock. Spreadsheet-heavy ingestion and analytical work
belong in a runtime with mature XLSX tooling, deterministic tests, and a thin
local HTTP boundary.

The change is a product/architecture decision. Browser-only ingestion required a
manually vendored SheetJS bundle, JavaScript ZIP/XML edge-case handling, and heavy
work in the browser. An environment 403 merely exposed that unnecessary
complexity; this design is not a workaround for that response.

## 3. Architectural decision

sklad_ozon becomes a deliberately small SCOZ-like application:

```text
+portable project-local Python + FastAPI application
++ committed vanilla HTML/CSS/JavaScript frontend
+- SQLite or generic persistence infrastructure
+```

FastAPI is the transport/local application shell. Domain, ingestion, analytics,
economics, feasibility, and optimization remain independently testable Python.
Frontend code owns presentation and UI behavior only. There is no npm, package
manifest, TypeScript, framework, bundler, compilation, or frontend build.

The logical flow is:

```text
Source Adapter → Ingestion → Normalized Domain → Analytics → Economics
→ Feasibility → Optimizer → Application/API → Frontend
```

The functional-core/imperative-shell boundary remains mandatory. Route handlers
validate transport data and call application services; they do not contain
business formulas.

## 4. SCOZ reference boundary

[SCOZ](https://github.com/vgvolmax/SCOZ) is the primary architectural reference.
The approved baseline is informed specifically by its `AGENTS.md`, `README.md`,
`start.bat`, `launcher.py`, `RUN_SERVER.cmd`, pinned requirements,
`backend/main.py`, `backend/ingestion/ozon_products_xlsx.py`, and Windows CI.
Those sources establish proven patterns for portable bootstrap, runtime
validation, launcher/health sequencing, loopback FastAPI, committed frontend,
Python/openpyxl ingestion, pytest, and portable Windows smoke.

We adopt patterns, not the whole repository design. Before implementing an
analogous facility, inspect SCOZ's current solution. Divergence requires a
recorded concrete technical or product reason. sklad_ozon stays simpler because
it presently needs neither a database nor SCOZ's persistence/history machinery.

## 5. Canonical user flow

First launch:

1. The user downloads the repository ZIP and extracts it fully.
2. The user double-clicks `start.bat`.
3. `start.bat` checks the project-local `runtime/`.
4. If absent or invalid, bootstrap downloads official Windows embeddable Python
   3.13.14, enables/bootstraps pip, and installs pinned requirements.
5. Bootstrap validates imports and runtime version before marking it valid.
6. `launcher.py` starts local FastAPI.
7. The launcher polls `http://127.0.0.1:17843/api/health` with a bounded timeout.
8. Only a successful health response opens the browser.

Subsequent launch is `start.bat → validate/reuse runtime → FastAPI → health →
browser`. It requires no administrator rights, system Python, system Node/npm,
or PATH modification. First preparation may need Internet; normal later use with
a valid runtime must not.

Failures remain visible and actionable through console/status/log files. A failed
health check must never open a misleading browser tab.

## 6. Portable runtime

`runtime/` is project-local, runtime-created, gitignored, and disposable. The
bootstrap pins the official 64-bit Windows embeddable Python 3.13.14 artifact and
verifies the download using an approved checksum recorded in implementation.
Partial preparation uses a staging location and is never treated as valid.

Runtime validity covers Python version, installed dependency imports, and a
version/requirements marker. A dependency change causes revalidation or repair.
Repair/rebuild may replace `runtime/` but may not touch `data/`.

`RUN_SERVER.cmd` is a developer/diagnostic convenience using the project-local
interpreter; it is not a second user entry point. `launcher.py` owns child server
lifecycle, bounded readiness polling, browser opening, and useful failure state.
Uvicorn binds exactly `127.0.0.1:17843`; port 17842 is reserved by SCOZ and is
not used.

## 7. Runtime/data separation

`runtime/` contains only replaceable interpreter and installed packages.
`data/` contains strictly necessary local application artifacts such as
`launcher.log`, `startup_status.json`, `server_console.log`, and `server.pid`,
plus future approved local state. Both are runtime-created and gitignored.

No empty runtime or future domain directories are committed. The implementation
creates a directory only when the current task uses it. Runtime repair is scoped
to `runtime/` and never deletes, resets, or migrates `data/` implicitly.

The presence of `data/` does not justify a database. Project JSON remains the
simple planned user-state format.

## 8. Backend/frontend boundary

FastAPI serves the committed `frontend/index.html` and relative assets and
provides `/api/*`. Static responses work without external CDNs or network access.
`GET /api/health` returns a stable versioned JSON contract suitable for launcher
readiness and tests.

Frontend:

- committed HTML, CSS, and plain JavaScript;
- thin rendering, interaction, file selection/upload, and API error display;
- no formulas, report parsing, domain classification, or optimizer decisions;
- no npm, `package.json`, TypeScript, React/Vue, browser framework, build, or
  bundler.

Backend:

- adapters decode files and application services orchestrate use cases;
- pure domain modules normalize and calculate;
- API handlers translate requests/responses and errors;
- uploaded content is processed locally and is not silently retained.

## 9. Python domain architecture

Merged PR #18's JavaScript `contracts.js` and `invariants.js` are superseded as
implementation, not semantics. Replacement PR1 ports them to
`backend/domain/contracts.py` and `backend/domain/invariants.py`, with typed
Python contracts and pytest parity tests. It then removes obsolete JS contracts,
the classic-script loader, and node:test domain tests.

Canonical types include `OrderLifecycle` (`fulfilled`, `in_progress`,
`cancelled`, `unknown`), `ReportMeta`, `ImportResult`, `OrderRecord`,
`StockoutSignal`, `RecommendationDistortionSignal`, and `PlacementAssessment`.
Contracts distinguish `delivery_cluster`/`destination_cluster` from
`origin_cluster`/`dispatch_cluster`; adapters may retain source-field provenance
without collapsing these concepts.

Python packages are introduced only when used: `backend/domain`, then
`backend/ingestion`, `backend/analytics`, `backend/economics`, and
`backend/supply`. Pure calculations accept explicit values and return data plus
diagnostics, without reading files, clocks, environment, HTTP, or mutable global
state.

## 10. XLSX/CSV ingestion

Active XLSX ingestion uses `openpyxl==3.1.5`. SheetJS, `app/vendor/xlsx`,
`xlsx.full.min.js`, browser workbook parsing, and manual browser bundle vendoring
are excluded. Python stdlib `zipfile` and `xml.etree.ElementTree` are used only
for proven low-level inspection/recovery that openpyxl cannot perform; the
project will not implement an XLSX parser.

The workbook adapter yields normalized sheet rows and diagnostics independently
of report-specific importers. Importers retain report metadata, source row
numbers, warnings/errors, and lifecycle classification. Raw reports and buyer or
customer PII do not enter persisted project state.

CSV defaults to Python stdlib `csv`, with tests for UTF-8 BOM, comma/semicolon
detection, quoted fields, and CRLF/LF. No CSV dependency is added unless a
sanitized failing fixture proves unsupported behavior.

## 11. `dimension=A1` robustness

Real Ozon workbooks may declare `<dimension ref="A1"/>` while containing hundreds
or thousands of populated rows. This is a mandatory sanitized regression fixture,
not a theoretical fallback.

The adapter must:

1. reproduce truncated-range behavior against openpyxl 3.1.5;
2. never treat worksheet dimension as authoritative without checking actual data;
3. first use the smallest supported openpyxl recovery, including
   `reset_dimensions()` when it resolves the fixture;
4. use minimal `zipfile`/XML inspection only if that recovery is insufficient;
5. return every populated row in order; and
6. emit the stable diagnostic `WORKSHEET_DIMENSION_REPAIRED`.

The low-level path may detect/recover range metadata; it must not become a custom
cell-style, formula, shared-string, or workbook parser.

## 12. Persistence boundary

The approved persistence model remains Project JSON, implemented in PR3. It may
contain normalized slowly changing state:

- tariffs and their report metadata;
- product economics and available seller stock;
- manual mappings;
- economics settings and optimizer thresholds;
- operational snapshots only with explicit report dates.

It must not contain raw reports or buyer/customer PII. Atomic write/validation
and schema versioning are allowed because they directly protect the file. This
MVP does not include SQLite, migrations, repository abstractions, import-history
or lineage databases, observation revisions, or a generic persistence framework.

## 13. Analytical invariants preserved

Runtime migration preserves all existing business meaning:

- delivery/destination cluster is customer demand geography;
- origin/dispatch cluster is physical fulfillment origin;
- `Kazan → Moscow` is Moscow demand served from Kazan;
- net demand uses `fulfilled + in_progress`; fulfilled route profiles use
  `fulfilled` only; cancelled and unknown rows remain diagnosable but excluded;
- current/incomplete weeks are excluded from completed-week comparisons;
- availability corroborates stockout inference but does not determine it;
- stockout and recommendation-distortion signals keep causal destination and
  donor-origin references;
- observed and clean route profiles remain distinct;
- tariff coverage is reported and uncovered share is never renormalized away;
- unit economics retains spreadsheet parity, tax, VAT, co-invest, and explicit
  rounding policies;
- feasibility precedes automatic placement; `PlacementAssessment` may evaluate a
  counterfactual that automatic allocation cannot use;
- Ozon recommendation ceilings cap automatic allocation, including a zero
  recommendation; and
- optimizer objective remains
  `MAX Σ allocation × expected_profit_per_unit` under stock, feasibility,
  ceiling, integer/nonnegative, and configured threshold constraints.

ReportMeta, ImportResult, OrderRecord, lifecycle classification, PII boundaries,
clean routes, economics, feasibility, and counterfactual outputs remain explicit
contracts. Any future change to them needs its own business design approval.

## 14. Security/local-only profile

The service binds only `127.0.0.1`, never `0.0.0.0`, LAN interfaces, or public
hosts. It is single-user and local-only. No cloud upload, telemetry, analytics
beacon, CDN, or remote API is required for normal use.

File endpoints enforce explicit size/type expectations and treat workbook/CSV
content as untrusted input. Paths are application-controlled; uploaded filenames
do not choose filesystem destinations. Errors returned to UI are useful but do
not expose unnecessary local paths or PII. The design has no accounts or auth
because it has no remote/multi-user exposure; that does not authorize LAN bind.

## 15. Dependencies

The proven baseline is exact unless implementation demonstrates a real
incompatibility:

```text
# official Windows embeddable runtime
Python 3.13.14

# requirements.txt
fastapi==0.139.2
uvicorn==0.51.0
openpyxl==3.1.5
python-multipart==0.0.32

# requirements-dev.txt
-r requirements.txt
pytest==8.4.2
httpx==0.28.1
```

Python stdlib supplies `csv`, `zipfile`, JSON, subprocess/lifecycle, hashing, and
XML inspection as needed. Each added dependency requires a concrete tested need
and design review; convenience alone is insufficient.

## 16. Testing/CI

Canonical automated command is:

```bash
python -m pytest -q
```

pytest covers domain, ingestion, analytics, economics, supply/optimizer,
application services, and API contracts. Tests use sanitized synthetic fixtures
and deterministic dates/settings. Optional
`node --check frontend/assets/js/app.js` is syntax coverage only; Node is neither
an end-user dependency nor a frontend toolchain.

Future CI in replacement PR1 performs checkout, setup Python 3.13, installation
from `requirements-dev.txt`, `python -m pytest -q`, optional JavaScript syntax,
and Windows portable smoke. A GitHub Actions Windows runner is authoritative for
`.bat` bootstrap, runtime reuse, loopback bind, health-before-browser behavior,
and paths with spaces. This docs PR does not add the workflow.

Codex runs every check available in its environment. Inability to prove Windows
bootstrap or a network download inside Codex is recorded and delegated to that
Windows acceptance; it never triggers an alternative architecture.

## 17. Migration from merged browser PR1

GitHub PR #18 implemented the old browser-only foundation. Its architecture is
superseded. A single replacement PR1 will:

- add `start.bat`, project-local runtime bootstrap, `launcher.py`, and
  `RUN_SERVER.cmd`;
- add pinned requirements, FastAPI health/static serving, and pytest;
- port JS domain contracts/invariants to Python with semantic parity;
- move the existing visual shell from `app/` to `frontend/` and connect it to the
  local API while retaining its simple vanilla appearance/behavior;
- remove obsolete JS domain contracts, browser XLSX path/vendor expectation,
  classic-script node:test harness/tests, and the old `app/` entry point;
- gitignore `runtime/` and `data/`; and
- add Python CI and authoritative Windows portable smoke.

Migration is atomic at PR scope: after it, only `start.bat` is canonical. The
project does not maintain both `start.bat` and direct `file:// app/index.html` as
peer runtime paths. This docs-only PR intentionally changes none of those
production/test/workflow files.

## 18. Explicit out-of-scope

Unless separately approved, the active MVP does **not** include:

- SQLite, migrations, repository pattern, lineage DB, import-history DB,
  observation revisions, or generic persistence;
- user accounts, auth, CSRF framework, multi-user or LAN service;
- Docker, PostgreSQL, generic background jobs, event bus, telemetry, or an auto
  updater;
- React, Vue, npm frontend build, TypeScript, bundler, or browser framework;
- a custom XLSX parser, SheetJS, or a parallel direct-file browser runtime.

The target tree below is a destination map, not permission to create empty future
directories.

## 19. Final target repository shape

```text
sklad_ozon/
├─ start.bat
├─ launcher.py
├─ RUN_SERVER.cmd
├─ requirements.txt
├─ requirements-dev.txt
├─ backend/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ main.py
│  ├─ domain/
│  │  ├─ __init__.py
│  │  ├─ contracts.py
│  │  └─ invariants.py
│  ├─ ingestion/        # introduced by PR2 when used
│  ├─ analytics/        # introduced by PR4 when used
│  ├─ economics/        # introduced by PR6 when used
│  └─ supply/           # introduced by PR7 when used
├─ frontend/
│  ├─ index.html
│  └─ assets/
│     ├─ css/app.css
│     └─ js/app.js
├─ data/                # runtime-created, gitignored
├─ runtime/             # runtime-created, gitignored
├─ tests/
└─ docs/
```

Implementation applies YAGNI: PR1 creates only foundation/domain/frontend paths;
later packages appear with their first production behavior and tests. Production
assets are committed and use server-relative/local paths without runtime network
requests.
