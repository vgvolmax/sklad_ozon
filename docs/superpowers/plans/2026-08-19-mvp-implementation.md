# sklad_ozon MVP implementation plan

> The design specification is the architectural source of truth. This plan
> sequences implementation without weakening its analytical contracts.

## Runtime and engineering baseline

Canonical user flow:

```text
repository ZIP
→ extract
→ open app/index.html in browser
→ application works locally
```

The MVP is a static application made from vanilla HTML, CSS and JavaScript.
There is no process to start: no launcher, backend, service, port, runtime
bootstrap, installation, or local HTTP server. The end user needs neither
Python nor Node. Every production asset is committed and addressed relatively so
`file:///.../app/index.html` works without a network.

Development uses plain JavaScript and the Node built-in test runner. The only
canonical automated test command is:

```bash
node --test
```

Do not add a package manager, TypeScript toolchain, compiler, bundler, frontend
build output, or mandatory browser automation. Classic ordered scripts share the
small `globalThis.SkladOzon` application namespace when multiple browser files
are needed. Do not use `fetch()` for application assets/configuration or ES
modules where browser `file://` restrictions would break loading.

**TypeScript-style contract snippets are specification notation only. They do
not require TypeScript, compilation, npm or a build system.**

## Target structure

Create entries only when their PR actually needs them; never pre-create empty
folders.

```text
app/
  index.html
  assets/
    css/app.css
    js/
      app.js
      domain/
      importers/
      normalization/
      analytics/
      economics/
      supply/
      ui/
  vendor/                 # browser libraries only when actually needed
tests/
  fixtures/
  *.test.mjs
docs/
```

## Invariants for every PR

- Functional core / imperative shell: import quirks stop at adapters; UI owns no
  formulas; pure business functions remain browser-independent.
- Delivery cluster is demand geography. Origin/dispatch cluster is fulfillment
  origin. `Казань → Москва` remains Moscow demand physically served by Kazan.
- Preserve `ReportMeta`, `OrderLifecycle`, PII minimization, report freshness,
  incomplete/current week exclusion, probable-stockout semantics,
  recommendation distortion, clean routes, tariff and spreadsheet parity,
  taxes/VAT/co-invest, feasibility, `PlacementAssessment`, optimizer ceilings,
  and counterfactual placement logic.
- Raw reports and buyer/customer PII are neither transmitted nor persisted.
- Apply YAGNI and do not start a later PR's scope early.
- Each behavior change starts with a failing `node:test` test and ends with fresh
  verification.

---

# PR1 — Static browser foundation + canonical contracts

## Scope

Create only:

```text
app/index.html
app/assets/css/app.css
app/assets/js/app.js
minimal plain-JS domain/invariant files, only if tests require them
tests/*.test.mjs
```

The HTML uses relative production paths such as `./assets/css/app.css` and
`./assets/js/app.js`, classic scripts, and no runtime HTTP/HTTPS resource. The
shell opens directly by double-click through `file://`.

Define the minimum canonical report metadata, lifecycle values, result shape,
and destination/origin invariant needed to anchor later work. Contract objects
must not contain report-specific headings or PII.

Explicitly absent: `start.bat`, launcher, server, package manifests, TypeScript,
Vite, esbuild, Vitest, compilation, bundling, and generated release directory.

## Tests and merge gate

Using `node:test` and `node:assert`, check:

- `app/index.html` exists;
- CSS and JavaScript use relative paths, never root `/assets/...` paths;
- normal operation has no remote resources, localhost, API, service worker,
  runtime bootstrap, or server requirement;
- the namespace initializes using classic browser scripts;
- canonical data distinguishes destination demand from fulfillment origin;
- PII fields are absent from canonical contracts.

```bash
node --test
git diff --check
```

Also inspect `app/index.html` through `file://` with the network unavailable.

**PR1 acceptance:** the direct static shell works from disk and canonical
contracts protect the core geography/lifecycle/PII invariants.

---

# PR2 — Robust Ozon XLSX/CSV imports + normalization

Add browser file import through File API, `FileReader`/`ArrayBuffer`, normalized
availability, restrictions, and orders adapters, status mapping, diagnostics,
and sanitized fixtures. Add a vendored XLSX browser parser here for the first
time. Add a CSV library only if native parsing is insufficient and the choice is
justified. Vendor assets are committed directly under `app/vendor/` with
provenance/license; there is no CDN or runtime download.

Importer acceptance includes Cyrillic headers, locale numbers, BOM/delimiters,
row-level diagnostics, required-column errors, report metadata, lifecycle
populations, and immediate PII discard. The workbook adapter must recover real
populated rows when worksheet metadata says `dimension=A1`, emit
`WORKSHEET_DIMENSION_REPAIRED`, and prove it with a sanitized regression fixture.

**PR2 merge gate:** `node --test`, malformed-dimension regression, lifecycle/PII
checks, static network inspection, and manual import of current real reports.

---

# PR3 — Tariffs/product inputs + project JSON persistence

Import tariff sheets and seller product economics/available stock. Normalize
clusters without a hard-coded master list; harmless aliases may normalize, while
ambiguous mappings remain visible and manual. Validate tariff ranges and retain
source metadata. Preserve the spreadsheet's explicit economics settings.

Persistence is explicit project JSON:

```text
Export project → browser downloads JSON
Import project → user selects saved JSON
```

Project state may contain tariff data/metadata, product economics, available
stock, manual mappings, economics settings, optimizer thresholds, and (only when
needed) normalized operational snapshots with explicit report dates. It must not
contain raw reports or customer PII. Restored snapshots are visibly stale/current.
Browser storage may be considered later only as optional convenience; the MVP
must not depend on it. Never create a server for persistence.

**PR3 merge gate:** `node --test`, tariff workbook parity/validation tests,
project round-trip/schema-version tests, PII/raw-row absence, and stale metadata
visibility.

---

# PR4 — Demand + fulfillment analytics

Build explicit populations: fulfilled plus in-progress for net demand; fulfilled
only for actual route behavior. Exclude cancelled/unknown records as specified
and exclude current/incomplete weeks from historical comparisons.

Implement destination demand matrix, origin→destination fulfillment matrix,
reverse donor view, local shares, completed weekly series, and coverage metadata.
The canonical test remains:

```text
800 Moscow → Moscow
200 Kazan → Moscow
100 Kazan → Kazan
```

Expected Moscow demand is 1000, Kazan demand is 100, Moscow destination-local
share is 80%, and Kazan origin-local share is 100/300.

**PR4 merge gate:** `node --test`, lifecycle/current-week cases, route conservation
properties, and manual reconciliation for three SKUs.

---

# PR5 — Stockout + recommendation distortion + clean routes

Implement the probable destination-stockout heuristic with the approved sample,
prior-share, share-drop, replacement-rise, and demand-retention thresholds.
Availability evidence may corroborate but cannot fabricate historical stock.
Keep probabilistic wording and evidence codes.

Link donor-cluster recommendations to affected stockout destinations without
reassigning demand. Build observed and stockout-cleaned route profiles; excluded
periods and confidence/coverage remain explainable.

**PR5 merge gate:** `node --test`, positive and negative controls, incomplete-week
protection, Kazan-donor/Moscow-stockout linkage, cleaned-share conservation, and
manual review of 5–10 signals.

---

# PR6 — Expected logistics + unit economics

Implement indexed tariff lookup, explicit missing-route diagnostics,
stockout-cleaned expected logistics, and unit economics using the approved
spreadsheet formulas. Preserve commission, acquiring, services/advertising,
buyout treatment, tax system, VAT, co-invest, cost, profit, margin, ROI, rounding,
and incomplete-data behavior. Never silently treat a missing route as zero.

**PR6 merge gate:** `node --test` plus 5–10 sanitized golden spreadsheet cases
covering local/intercluster routes and material tax/VAT/co-invest branches.
Optimizer work cannot merge until spreadsheet parity is accepted.

---

# PR7 — Feasibility + placement comparison + optimizer

Evaluate warehouse restrictions, maximum quantities, route/tariff completeness,
and relevant clusters before optimization. Keep placement assessment separate
from allocation eligibility. Include Ozon-recommended and counterfactual affected
clusters, even when the latter has zero recommended quantity.

The deterministic optimizer maximizes expected absolute profit subject to:

```text
allocated ≤ seller available stock
allocated per cluster ≤ Ozon recommendation
allocated per cluster ≤ feasible capacity
blocked/incomplete/below-threshold allocation = 0
counterfactual-only allocation with Ozon quantity 0 = 0
```

Keep all status/evidence codes, including supply blocked, incomplete data or
tariff coverage, low route confidence/economics, probable distortion, and
counterfactual-only.

**PR7 merge gate:** `node --test`, deterministic ties, conservation/property
checks, Moscow-vs-Kazan comparisons, and spreadsheet parity still passing.

---

# PR8 — Complete UI + offline hardening

Compose the full pipeline without moving business formulas into the DOM:

```text
source files → adapters → normalized canonical data → analytics → economics
→ feasibility → optimizer → UI
```

Complete import diagnostics/report freshness, settings, dashboard, four SKU views
(demand, destination fulfillment, origin donor, placement comparison), supply
plan, evidence/status explanations, and project JSON controls. The Kazan row must
visibly explain a linked probable Moscow stockout when applicable.

Harden the direct checked-in `app/index.html` release. Static tests must reject
root asset paths, remote resources, service workers, server/localhost assumptions,
and missing relative assets. Browser automation is optional rather than a
mandatory dependency; final manual acceptance is authoritative:

```text
repository ZIP → extract → double-click app/index.html
→ import sanitized/real local files without network → produce explainable plan
```

**PR8 merge gate:** `node --test`, full fixture pipeline, project round trip,
network/static inspection, fresh spreadsheet/optimizer suites, and offline
`file://` manual validation.

---

# Manual checkpoints

- **After PR2:** record accepted/rejected rows, SKU/report dates, mappings,
  malformed-dimension recovery, lifecycle counts, and verify PII absence.
- **After PR4:** reconcile destination demand, fulfillment origins, reverse donor
  shares, lifecycle filtering, and incomplete-week exclusion for three SKUs.
- **After PR5:** inspect 5–10 probable stockouts without tuning to one anecdote.
- **After PR6:** accept spreadsheet parity for representative golden cases.
- **After PR7:** compare donor recommendation, affected destination
  counterfactual, and allocation under the Ozon ceiling.
- **After PR8:** reconcile recommendation totals, lifecycle counts, warnings,
  exclusions, allocation, expected profit, and counterfactual comparisons using
  current real data.

# MVP completion

All eight PRs remain required. MVP is done only when a user can extract the
repository ZIP, open `app/index.html` directly, select real local reports, obtain
an explainable feasible/economic limited-stock plan, export/import project JSON,
and repeat the workflow offline without installing or starting anything.

PR #13 implements a superseded TypeScript/build architecture. Do not use it as an
implementation base; after this architecture correction is accepted, close PR
#13 without merge. Useful domain ideas may be reimplemented in plain JavaScript.
Synchronize stale technical details in Issues #2–#9 separately after this docs PR.
