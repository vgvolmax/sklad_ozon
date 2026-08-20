# sklad_ozon MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL:
> Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task.

**Goal**

Deliver a fully local application that turns seller reports into an explainable, feasible, unit-economic allocation of limited stock within Ozon recommendation ceilings.

**Architecture**

The product is a static browser app opened directly at `app/index.html`. A functional core keeps imports, analytics, economics, feasibility, and optimization pure, while an imperative shell owns Browser File API and UI effects. Data flows source adapters → normalized domain → analytics → economics → feasibility → optimizer → UI.

**Tech Stack**

- vanilla HTML;
- vanilla CSS;
- plain JavaScript (`*.js` production files);
- Browser File API and `FileReader`/`ArrayBuffer`;
- locally vendored browser XLSX parser, introduced in PR2 at `app/vendor/xlsx/xlsx.full.min.js` with `app/vendor/xlsx/LICENSE`;
- a locally vendored CSV library only if native parsing proves insufficient;
- dependency-free `node:test` tests in `*.test.mjs`;
- `node:assert`.

**Spec**

`docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`

**Global Constraints**

- Canonical runtime: repository ZIP → extract → open `app/index.html` through `file://`; all assets are checked in, relative, local, and work without a network or a process to start.
- Production is vanilla HTML/CSS/plain JavaScript. End users install nothing. Development verification is `node --test`.
- Use classic ordered scripts and `globalThis.SkladOzon` where multiple browser files cooperate. Do not fetch application assets or configuration.
- Preserve the functional-core/imperative-shell boundary: adapters contain source quirks; canonical contracts contain no report headings; UI contains no formulas.
- Delivery cluster is demand geography and origin/dispatch cluster is fulfillment origin. `Казань → Москва` is Moscow demand served by Kazan.
- Preserve explicit `ReportMeta`, lifecycle populations, diagnostics, freshness, incomplete-week exclusion, probabilistic stockout semantics, distortion links, observed/clean routes, tariff coverage, spreadsheet parity, taxes/VAT/co-invest, feasibility, placement assessment, counterfactual display, and optimizer ceilings.
- Raw reports and buyer/customer PII never enter canonical or exported project state and never leave the computer.
- Missing tariff coverage is incomplete data, never zero cost. Partial coverage is never renormalized.
- Ozon quantities are immutable inputs: neither a distortion signal nor a counterfactual may raise an automatic allocation above the recommendation.
- Create files only in the PR that needs them; do not pre-create future directories.

Every task below is a separate RED → GREEN unit. Run commands from repository root. Task 2 creates the single dependency-free classic-script test harness used by every later test. A test must import `loadClassicScripts`, pass production scripts in browser execution order, and bind its return value to `api`; it must not invent an ES-module production entry point. Task-local inputs such as `fixture`, and assertion helpers such as `find`, `route`, `sum`, `sumShares`, `sumProducts`, and `pick`, must be declared in that test file (or loaded there from a fixture named in the task's **Files** list) before use. Node built-ins such as `readFileSync` and `existsSync` must likewise be imported explicitly. Thus the snippets describe assertions, while the committed test files are self-contained executables: they contain their imports, `loadClassicScripts(...)` call, fixtures, and small assertion helpers; no identifier is supplied by a test runner global.

---

# PR1 — Static foundation + contracts

Implement only these tasks in PR1; do not pull later scope forward.

### Task 1: Static `file://` shell

**Files**
- Create: `app/index.html`
- Create: `app/assets/css/app.css`
- Create: `app/assets/js/app.js`
- Test: `tests/offline-shell.test.mjs`

**Interfaces**
- Consumes: repository files.
- Produces: `app/index.html` loading `./assets/css/app.css` and classic `./assets/js/app.js`; `SkladOzon.boot()`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

test('Static `file://` shell', async () => {
  const html = readFileSync('app/index.html','utf8');
  assert.match(html, /href="\.\/assets\/css\/app\.css"/);
  assert.match(html, /src="\.\/assets\/js\/app\.js"/);
  assert.doesNotMatch(html, /type="module"|(?:https?:\/\/)|localhost|["']\/assets\//);
  assert.doesNotMatch(html, /server|api\/|bootstrap/i);
  assert.equal(existsSync('start.bat'),false);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/offline-shell.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
globalThis.SkladOzon = globalThis.SkladOzon || {};
SkladOzon.boot = function () { document.documentElement.dataset.ready = 'true'; };
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/offline-shell.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR1 PASS.

- [ ] Step 6: Commit

```bash
git add app/index.html app/assets/css/app.css app/assets/js/app.js tests/offline-shell.test.mjs
git commit -m "test: static file:// shell"
```

### Task 2: Canonical contracts and runtime invariants

**Files**
- Create: `tests/helpers/load-classic-script.mjs`
- Create: `app/assets/js/domain/contracts.js`
- Create: `app/assets/js/domain/invariants.js`
- Test: `tests/domain-contracts.test.mjs`
- Test: `tests/invariants.test.mjs`

**Interfaces**
- Consumes: raw normalized field values.
- Produces: `OrderLifecycle`, `createReportMeta(fields)`, `createOrderRecord(fields)`, `createImportResult(records, diagnostics, meta)`, `assertNonNegative`, `assertRate`, `assertNonEmpty`.

- [ ] Step 1: Write failing test

Create the reusable test infrastructure first (this is test plumbing, not the GREEN production implementation):

```js
// tests/helpers/load-classic-script.mjs
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

export function loadClassicScripts(paths, globals = {}) {
  if (!Array.isArray(paths) || paths.length === 0) {
    throw new TypeError('paths must be a non-empty array');
  }

  const context = { console, ...globals };
  context.globalThis = context;
  vm.createContext(context);

  for (const path of paths) {
    const source = readFileSync(path, 'utf8');
    vm.runInContext(source, context, { filename: path });
  }

  if (!context.SkladOzon) {
    throw new Error('SkladOzon namespace was not created');
  }
  return context.SkladOzon;
}
```

The helper loads production classic scripts verbatim and deliberately does not read the DOM, discover files, inject fixtures, or provide analytical helpers. Browser APIs needed by a particular shell test are passed explicitly through `globals`. Production files initialize the shared namespace with `globalThis.SkladOzon = globalThis.SkladOzon || {}` and attach their public functions to it.

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadClassicScripts } from './helpers/load-classic-script.mjs';

const api = loadClassicScripts([
  'app/assets/js/domain/contracts.js',
  'app/assets/js/domain/invariants.js',
]);

test('Canonical contracts and runtime invariants', async () => {
  assert.deepEqual(api.OrderLifecycle, ['fulfilled','in_progress','cancelled','unknown']);
  const order=api.createOrderRecord({sku:'1',originClusterId:'Kazan',destinationClusterId:'Moscow'});
  assert.equal(order.originClusterId,'Kazan'); assert.equal(order.destinationClusterId,'Moscow');
  assert.deepEqual(Object.keys(api.createReportMeta({})), ['sourceName','importedAt','reportGeneratedAt','periodStart','periodEnd','recommendationHorizonDays']);
  assert.deepEqual(Object.keys(api.createImportResult([],[],{})), ['records','diagnostics','meta']);
  assert.throws(()=>api.assertNonNegative(-1)); assert.throws(()=>api.assertRate(1.1)); assert.throws(()=>api.assertNonEmpty(''));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/domain-contracts.test.mjs tests/invariants.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
const OrderLifecycle=Object.freeze(['fulfilled','in_progress','cancelled','unknown']);
function createImportResult(records,diagnostics,meta){ return {records,diagnostics,meta}; }
function assertRate(v){ if(v<0||v>1) throw Error('RATE_OUT_OF_RANGE'); return v; }
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/domain-contracts.test.mjs tests/invariants.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR1 PASS.

- [ ] Step 6: Commit

```bash
git add tests/helpers/load-classic-script.mjs app/assets/js/domain/contracts.js app/assets/js/domain/invariants.js tests/domain-contracts.test.mjs tests/invariants.test.mjs
git commit -m "feat: canonical contracts and runtime invariants"
```

## PR1 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

Manually open `app/index.html` through `file://` with network disabled and confirm the shell renders.

---

# PR2 — Operational imports

Implement only these tasks in PR2; do not pull later scope forward.

### Task 3: Normalization primitives

**Files**
- Create: `app/assets/js/normalization/values.js`
- Test: `tests/normalization.test.mjs`

**Interfaces**
- Consumes: source strings and locale-formatted cells.
- Produces: `normalizeHeader`, `normalizeClusterId`, `parseLocaleNumber`, `parseIsoDate`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Normalization primitives', async () => {
  assert.equal(api.normalizeHeader('  Артикул! '),'артикул');
  assert.equal(api.normalizeClusterId('  МОСКВА '),'Moscow');
  assert.equal(api.parseLocaleNumber('1 234,50'),1234.5);
  assert.equal(api.normalizeClusterId('Москва Север'), 'Москва Север');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/normalization.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function normalizeHeader(v){return String(v).trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu,'');}
function parseLocaleNumber(v){return Number(String(v).replace(/\s/g,'').replace(',','.'));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/normalization.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/normalization/values.js tests/normalization.test.mjs
git commit -m "feat: normalization primitives"
```

### Task 4: Order lifecycle classification

**Files**
- Create: `app/assets/js/importers/order-status.js`
- Test: `tests/order-status.test.mjs`

**Interfaces**
- Consumes: raw Ozon status text.
- Produces: `classifyOrderLifecycle(status)` returning `fulfilled|in_progress|cancelled|unknown`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Order lifecycle classification', async () => {
  for(const [raw,want] of [['Доставлен','fulfilled'],['Отменён','cancelled'],['Доставляется','in_progress'],['Ожидает отгрузки','in_progress'],['Ожидает сборки','in_progress'],['новый статус','unknown']]) assert.equal(api.classifyOrderLifecycle(raw),want);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/order-status.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
const STATUS=new Map([['Доставлен','fulfilled'],['Отменён','cancelled'],['Доставляется','in_progress'],['Ожидает отгрузки','in_progress'],['Ожидает сборки','in_progress']]);
function classifyOrderLifecycle(v){return STATUS.get(String(v).trim())||'unknown';}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/order-status.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/order-status.js tests/order-status.test.mjs
git commit -m "feat: order lifecycle classification"
```

### Task 5: Browser workbook adapter

**Files**
- Create: `app/vendor/xlsx/xlsx.full.min.js`
- Create: `app/vendor/xlsx/LICENSE`
- Create: `app/assets/js/importers/workbook.js`
- Test: `tests/workbook-adapter.test.mjs`
- Test: `tests/fixtures/malformed-dimension-a1.xlsx`

**Interfaces**
- Consumes: a local `File`/`ArrayBuffer` and vendored XLSX parser.
- Produces: `readWorkbook(arrayBuffer)` producing `{sheets, diagnostics}` with populated rows beyond declared range.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Browser workbook adapter', async () => {
  const out=await api.readWorkbook(readFileSync('tests/fixtures/malformed-dimension-a1.xlsx'));
  assert.equal(out.sheets[0].rows.length,4);
  assert.ok(out.diagnostics.some(d=>d.code==='WORKSHEET_DIMENSION_REPAIRED'));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/workbook-adapter.test.mjs tests/fixtures/malformed-dimension-a1.xlsx
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
async function readWorkbook(bytes){
 const workbook=XLSX.read(bytes,{type:'array',dense:true});
 return extractPhysicalCellsAndRepairDimensions(workbook);
}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/workbook-adapter.test.mjs tests/fixtures/malformed-dimension-a1.xlsx
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/vendor/xlsx/xlsx.full.min.js app/vendor/xlsx/LICENSE app/assets/js/importers/workbook.js tests/workbook-adapter.test.mjs tests/fixtures/malformed-dimension-a1.xlsx
git commit -m "feat: browser workbook adapter"
```

### Task 6: CSV reader

**Files**
- Create: `app/assets/js/importers/csv.js`
- Test: `tests/csv-reader.test.mjs`
- Test: `tests/fixtures/orders-bom-semicolon.csv`

**Interfaces**
- Consumes: UTF-8 text or browser `File`.
- Produces: `detectDelimiter(text)`, `parseCsv(text)` returning `{headers, rows, diagnostics}`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('CSV reader', async () => {
  const out=api.parseCsv('\uFEFFSKU;Цена\r\n1;1 234,50');
  assert.deepEqual(out.headers,['SKU','Цена']); assert.equal(out.rows[0][1],'1 234,50');
  assert.equal(api.detectDelimiter('a,b\n1,2'),',');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/csv-reader.test.mjs tests/fixtures/orders-bom-semicolon.csv
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function detectDelimiter(text){return scoreDelimiters(text,[',',';','\t']);}
function parseCsv(text){return parseQuotedRows(text.replace(/^\uFEFF/,''),detectDelimiter(text));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/csv-reader.test.mjs tests/fixtures/orders-bom-semicolon.csv
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/csv.js tests/csv-reader.test.mjs tests/fixtures/orders-bom-semicolon.csv
git commit -m "feat: csv reader"
```

### Task 7: Availability importer

**Files**
- Create: `app/assets/js/importers/availability.js`
- Test: `tests/availability-importer.test.mjs`
- Test: `tests/fixtures/availability.json`

**Interfaces**
- Consumes: workbook rows and import context.
- Produces: `importAvailability(rows, context)` returning `ImportResult<AvailabilityRecommendation>`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Availability importer', async () => {
  const out=api.importAvailability(fixture.rows,fixture.context);
  assert.equal(out.records[0].clusterId,'Moscow');
  assert.equal(out.records[0].recommendedQty,25); assert.equal(out.records[0].daysWithoutStock,3);
  assert.equal(out.meta.recommendationHorizonDays,28);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/availability-importer.test.mjs tests/fixtures/availability.json
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importAvailability(rows,context){return importRows(rows,context,mapAvailabilityRow,AVAILABILITY_REQUIRED_COLUMNS);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/availability-importer.test.mjs tests/fixtures/availability.json
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/availability.js tests/availability-importer.test.mjs tests/fixtures/availability.json
git commit -m "feat: availability importer"
```

### Task 8: Restrictions importer

**Files**
- Create: `app/assets/js/importers/restrictions.js`
- Test: `tests/restrictions-importer.test.mjs`
- Test: `tests/fixtures/restrictions.json`

**Interfaces**
- Consumes: workbook rows and import context.
- Produces: `importRestrictions(rows, context)` returning `ImportResult<WarehouseRestriction>`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Restrictions importer', async () => {
  const out=api.importRestrictions(fixture.rows,fixture.context);
  assert.deepEqual(out.records[0],{sku:'1',clusterId:'Kazan',warehouseId:'w1',warehouseName:'Казань РФЦ',allowed:false,maxSupplyQty:0,placementZone:null,reasonCodes:['SKU_BLOCKED']});
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/restrictions-importer.test.mjs tests/fixtures/restrictions.json
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importRestrictions(rows,context){return importRows(rows,context,mapRestrictionRow,RESTRICTION_REQUIRED_COLUMNS);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/restrictions-importer.test.mjs tests/fixtures/restrictions.json
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/restrictions.js tests/restrictions-importer.test.mjs tests/fixtures/restrictions.json
git commit -m "feat: restrictions importer"
```

### Task 9: Orders importer

**Files**
- Create: `app/assets/js/importers/orders.js`
- Test: `tests/orders-importer.test.mjs`
- Test: `tests/fixtures/orders-kazan-moscow.csv`

**Interfaces**
- Consumes: parsed CSV rows and import context.
- Produces: `importOrders(rows, context)` returning `ImportResult<OrderRecord>`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Orders importer', async () => {
  const out=api.importOrders(fixture.rows,fixture.context); const r=out.records[0];
  assert.equal(r.originClusterId,'Kazan'); assert.equal(r.destinationClusterId,'Moscow');
  assert.equal(r.lifecycle,'fulfilled'); assert.equal(r.quantity,2);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/orders-importer.test.mjs tests/fixtures/orders-kazan-moscow.csv
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importOrders(rows,context){return importRows(rows,context,row=>({sku:cell(row,'SKU'),originClusterId:cluster(cell(row,'Кластер отгрузки')),destinationClusterId:cluster(cell(row,'Кластер доставки')),lifecycle:classifyOrderLifecycle(cell(row,'Статус')),quantity:number(cell(row,'Количество'))}),ORDER_REQUIRED_COLUMNS);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/orders-importer.test.mjs tests/fixtures/orders-kazan-moscow.csv
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/orders.js tests/orders-importer.test.mjs tests/fixtures/orders-kazan-moscow.csv
git commit -m "feat: orders importer"
```

### Task 10: Diagnostics, metadata, and PII boundary

**Files**
- Create: `app/assets/js/importers/import-result.js`
- Test: `tests/import-boundary.test.mjs`
- Test: `tests/fixtures/orders-with-pii.csv`

**Interfaces**
- Consumes: decoded source rows, required columns, row mapper, report context.
- Produces: `importRows(rows, context, mapper, requiredColumns)` with row diagnostics and complete `ReportMeta`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Diagnostics, metadata, and PII boundary', async () => {
  const out=api.importRows(fixture.rows,fixture.context,fixture.mapper,['SKU']);
  assert.equal(out.records.length,1); assert.ok(out.diagnostics.some(d=>d.row===3));
  assert.deepEqual(Object.keys(out.meta),['sourceName','importedAt','reportGeneratedAt','periodStart','periodEnd','recommendationHorizonDays']);
  const json=JSON.stringify(out); for(const secret of ['Иван Иванов','ул. Ленина','7701/7702','buyerName','buyerAddress','inn','kpp']) assert.equal(json.includes(secret),false);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/import-boundary.test.mjs tests/fixtures/orders-with-pii.csv
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importRows(rows,context,mapper,required){ validateColumns(rows[0],required); const records=[],diagnostics=[]; rows.slice(1).forEach((r,i)=>mapSafely(r,i+2,mapper,records,diagnostics)); return {records,diagnostics,meta:createReportMeta(context)}; }
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/import-boundary.test.mjs tests/fixtures/orders-with-pii.csv
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR2 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/import-result.js tests/import-boundary.test.mjs tests/fixtures/orders-with-pii.csv
git commit -m "feat: diagnostics, metadata, and pii boundary"
```

## PR2 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR2

Import current availability, restrictions, and orders reports; record accepted/rejected rows, dates, mappings, lifecycle counts, repaired worksheet diagnostics, and confirm serialized canonical data contains no PII. Use current real seller reports outside git; never commit sensitive raw reports.

---

# PR3 — Tariffs + project JSON

Implement only these tasks in PR3; do not pull later scope forward.

### Task 11: Tariff workbook detection

**Files**
- Create: `app/assets/js/importers/tariff-workbook.js`
- Test: `tests/tariff-workbook.test.mjs`
- Test: `tests/fixtures/unit-economics-multisheet.json`

**Interfaces**
- Consumes: workbook sheet names and header rows.
- Produces: `detectTariffSheet(workbook)` returning the signature-matching sheet.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Tariff workbook detection', async () => {
  const sheet=api.detectTariffSheet(fixture); assert.equal(sheet.name,'Логистика с 28 августа 2026г.');
  assert.throws(()=>api.detectTariffSheet({sheets:[{name:'Логистика',rows:[['x']]}]}),/TARIFF_SHEET_NOT_FOUND/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/tariff-workbook.test.mjs tests/fixtures/unit-economics-multisheet.json
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function detectTariffSheet(workbook){return workbook.sheets.find(s=>hasColumns(s.rows[0],TARIFF_SIGNATURE))||raise('TARIFF_SHEET_NOT_FOUND');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/tariff-workbook.test.mjs tests/fixtures/unit-economics-multisheet.json
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/tariff-workbook.js tests/tariff-workbook.test.mjs tests/fixtures/unit-economics-multisheet.json
git commit -m "feat: tariff workbook detection"
```

### Task 12: Tariff normalization and index input

**Files**
- Create: `app/assets/js/importers/tariffs.js`
- Test: `tests/tariff-importer.test.mjs`

**Interfaces**
- Consumes: detected tariff rows and report context.
- Produces: `importTariffs(rows, context)` returning `ImportResult<TariffRow>`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Tariff normalization and index input', async () => {
  const out=api.importTariffs(fixture.rows,fixture.context); assert.deepEqual(out.records[0],{originClusterId:'Kazan',destinationClusterId:'Moscow',minVolumeLiters:0,maxVolumeLiters:1,minPrice:null,maxPrice:null,logisticsFee:100});
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/tariff-importer.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importTariffs(rows,context){return importRows(rows,context,mapTariffRow,TARIFF_REQUIRED_COLUMNS);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/tariff-importer.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/tariffs.js tests/tariff-importer.test.mjs
git commit -m "feat: tariff normalization and index input"
```

### Task 13: Product economics import

**Files**
- Create: `app/assets/js/importers/product-economics.js`
- Test: `tests/product-economics-importer.test.mjs`

**Interfaces**
- Consumes: XLSX/CSV rows recognized in seller workbook.
- Produces: `importProductEconomics(rows, context)` returning `ImportResult<ProductEconomicsInput>`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Product economics import', async () => {
  const r=api.importProductEconomics(fixture.rows,fixture.context).records[0];
  assert.deepEqual(r,{sku:'1',article:'A',cost:400,availableQty:12,price:1000,commissionRate:.15,volumeLiters:2.5});
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/product-economics-importer.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function importProductEconomics(rows,context){return importRows(rows,context,mapProductEconomicsRow,PRODUCT_REQUIRED_COLUMNS);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/product-economics-importer.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/importers/product-economics.js tests/product-economics-importer.test.mjs
git commit -m "feat: product economics import"
```

### Task 14: Project JSON schema and version

**Files**
- Create: `app/assets/js/domain/project.js`
- Test: `tests/project-schema.test.mjs`

**Interfaces**
- Consumes: normalized project business state.
- Produces: `PROJECT_VERSION`, `createProject(state)`, `validateProject(project)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Project JSON schema and version', async () => {
  const p=api.createProject(fixture.state); assert.equal(p.schemaVersion,1);
  assert.doesNotThrow(()=>api.validateProject(p)); assert.throws(()=>api.validateProject({...p,schemaVersion:99}),/UNSUPPORTED_PROJECT_VERSION/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/project-schema.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
const PROJECT_VERSION=1; function createProject(state){return {schemaVersion:PROJECT_VERSION,savedAt:new Date().toISOString(),state:pickPersistableState(state)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/project-schema.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/domain/project.js tests/project-schema.test.mjs
git commit -m "feat: project json schema and version"
```

### Task 15: Export project

**Files**
- Create: `app/assets/js/domain/project-export.js`
- Test: `tests/project-export.test.mjs`

**Interfaces**
- Consumes: normalized state with tariff meta, economics, stock, mappings, settings, thresholds, and optional dated snapshots.
- Produces: `serializeProject(state)` returning portable JSON text.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Export project', async () => {
  const json=api.serializeProject(fixture.stateWithRawAndPii); const p=JSON.parse(json);
  assert.deepEqual(Object.keys(p.state).sort(),fixture.allowedKeys.sort());
  for(const key of ['rawReports','buyerName','buyerAddress','inn','kpp']) assert.equal(json.includes(key),false);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/project-export.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function serializeProject(state){return JSON.stringify(createProject(pickPersistableState(state)),null,2);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/project-export.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/domain/project-export.js tests/project-export.test.mjs
git commit -m "feat: export project"
```

### Task 16: Import project

**Files**
- Create: `app/assets/js/domain/project-import.js`
- Test: `tests/project-roundtrip.test.mjs`

**Interfaces**
- Consumes: project JSON text selected by the user.
- Produces: `deserializeProject(text)` returning normalized business state.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Import project', async () => {
  const restored=api.deserializeProject(api.serializeProject(fixture.state));
  assert.deepEqual(restored,fixture.normalizedState);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/project-roundtrip.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function deserializeProject(text){const p=JSON.parse(text); validateProject(p); return normalizePersistedState(p.state);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/project-roundtrip.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/domain/project-import.js tests/project-roundtrip.test.mjs
git commit -m "feat: import project"
```

### Task 17: Validation and stale report metadata

**Files**
- Create: `app/assets/js/domain/project-validation.js`
- Test: `tests/project-validation.test.mjs`

**Interfaces**
- Consumes: restored project plus current time and freshness policy.
- Produces: `validateProjectState(state)`, `assessReportFreshness(meta, now, maxAgeDays)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Validation and stale report metadata', async () => {
  assert.deepEqual(api.assessReportFreshness({reportGeneratedAt:'2026-08-01T00:00:00Z'},'2026-08-20T00:00:00Z',7),{status:'stale',ageDays:19});
  assert.ok(api.validateProjectState(fixture.invalid).some(d=>d.code==='PROJECT_FIELD_INVALID'));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/project-validation.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function assessReportFreshness(meta,now,maxAgeDays){const ageDays=(Date.parse(now)-Date.parse(meta.reportGeneratedAt))/864e5; return {status:ageDays>maxAgeDays?'stale':'current',ageDays};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/project-validation.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR3 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/domain/project-validation.js tests/project-validation.test.mjs
git commit -m "feat: validation and stale report metadata"
```

## PR3 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

---

# PR4 — Demand + fulfillment

Implement only these tasks in PR4; do not pull later scope forward.

### Task 18: Order populations

**Files**
- Create: `app/assets/js/analytics/populations.js`
- Test: `tests/order-populations.test.mjs`

**Interfaces**
- Consumes: canonical `OrderRecord[]`.
- Produces: `selectNetDemandOrders`, `selectFulfilledRouteOrders`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Order populations', async () => {
  assert.deepEqual(api.selectNetDemandOrders(fixture.orders).map(x=>x.lifecycle),['fulfilled','in_progress']);
  assert.deepEqual(api.selectFulfilledRouteOrders(fixture.orders).map(x=>x.lifecycle),['fulfilled']);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/order-populations.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
const selectNetDemandOrders=xs=>xs.filter(x=>x.lifecycle==='fulfilled'||x.lifecycle==='in_progress'); const selectFulfilledRouteOrders=xs=>xs.filter(x=>x.lifecycle==='fulfilled');
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/order-populations.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR4 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/populations.js tests/order-populations.test.mjs
git commit -m "feat: order populations"
```

### Task 19: Destination demand matrix

**Files**
- Create: `app/assets/js/analytics/demand.js`
- Test: `tests/demand-matrix.test.mjs`

**Interfaces**
- Consumes: net-demand `OrderRecord[]`.
- Produces: `buildDemandMatrix(orders)` returning `DemandCell[]` grouped by SKU and destination.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Destination demand matrix', async () => {
  const cells=api.buildDemandMatrix(fixture.orders); assert.equal(find(cells,'Moscow').quantity,1000); assert.equal(find(cells,'Kazan').quantity,100); assert.equal(find(cells,'Moscow').orderCount,2);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/demand-matrix.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildDemandMatrix(orders){return groupSum(selectNetDemandOrders(orders),['sku','destinationClusterId'],'quantity');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/demand-matrix.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR4 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/demand.js tests/demand-matrix.test.mjs
git commit -m "feat: destination demand matrix"
```

### Task 20: Fulfillment matrix

**Files**
- Create: `app/assets/js/analytics/fulfillment.js`
- Test: `tests/fulfillment-matrix.test.mjs`

**Interfaces**
- Consumes: fulfilled-only `OrderRecord[]`.
- Produces: `buildFulfillmentMatrix(orders)` returning `FulfillmentShare[]`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Fulfillment matrix', async () => {
  const rows=api.buildFulfillmentMatrix(fixture.orders); assert.equal(route(rows,'Moscow','Moscow').share,.8); assert.equal(sumShares(rows,'Moscow'),1);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/fulfillment-matrix.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildFulfillmentMatrix(orders){return sharesBy(selectFulfilledRouteOrders(orders),['sku','destinationClusterId'],'originClusterId');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/fulfillment-matrix.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR4 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/fulfillment.js tests/fulfillment-matrix.test.mjs
git commit -m "feat: fulfillment matrix"
```

### Task 21: Reverse donor matrix

**Files**
- Create: `app/assets/js/analytics/donors.js`
- Test: `tests/donor-matrix.test.mjs`

**Interfaces**
- Consumes: fulfilled-only `OrderRecord[]`.
- Produces: `buildDonorMatrix(orders)` returning origin-to-destination quantities/shares.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Reverse donor matrix', async () => {
  const rows=api.buildDonorMatrix(fixture.orders); assert.equal(route(rows,'Kazan','Kazan').share,100/300); assert.equal(route(rows,'Kazan','Moscow').quantity,200);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/donor-matrix.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildDonorMatrix(orders){return sharesBy(selectFulfilledRouteOrders(orders),['sku','originClusterId'],'destinationClusterId');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/donor-matrix.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR4 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/donors.js tests/donor-matrix.test.mjs
git commit -m "feat: reverse donor matrix"
```

### Task 22: Completed weekly series

**Files**
- Create: `app/assets/js/analytics/weekly-series.js`
- Test: `tests/weekly-series.test.mjs`

**Interfaces**
- Consumes: orders and `asOf` instant.
- Produces: `isoWeek(date)`, `buildCompletedWeeklySeries(orders, asOf)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Completed weekly series', async () => {
  const out=api.buildCompletedWeeklySeries(fixture.orders,'2026-08-20T00:00:00Z'); assert.equal(out.some(w=>w.week==='2026-W34'),false);
  assert.deepEqual(out[0].origins.Kazan,{quantity:5,share:.05});
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/weekly-series.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildCompletedWeeklySeries(orders,asOf){const current=isoWeek(asOf); return aggregateWeeks(selectFulfilledRouteOrders(orders).filter(x=>isoWeek(x.deliveredAt)!==current));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/weekly-series.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR4 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/weekly-series.js tests/weekly-series.test.mjs
git commit -m "feat: completed weekly series"
```

## PR4 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR4

Reconcile destination demand, fulfillment origins, donor shares, lifecycle filtering, and completed-week exclusion for three SKUs. Use current real seller reports outside git; never commit sensitive raw reports.

---

# PR5 — Stockout + distortion + clean routes

Implement only these tasks in PR5; do not pull later scope forward.

### Task 23: Probable stockout detector

**Files**
- Create: `app/assets/js/analytics/stockout.js`
- Test: `tests/stockout.test.mjs`

**Interfaces**
- Consumes: completed weekly series, availability, and thresholds.
- Produces: `detectProbableStockouts(series, availability, thresholds)` returning `StockoutSignal[]`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Probable stockout detector', async () => {
  const [s]=api.detectProbableStockouts(fixture.positive,fixture.availability,fixture.thresholds); assert.equal(s.destinationClusterId,'Moscow'); assert.equal(s.replacementOrigins[0].originClusterId,'Kazan'); assert.equal(s.availabilityCorroboration,'supports');
  for(const x of fixture.negativeControls) assert.deepEqual(api.detectProbableStockouts(x,[],fixture.thresholds),[]);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/stockout.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function detectProbableStockouts(series,availability,t){return completedPairs(series).filter(p=>passesDemandSampleAndShareRules(p,t)).map(p=>toStockoutSignal(p,availability));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/stockout.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR5 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/stockout.js tests/stockout.test.mjs
git commit -m "feat: probable stockout detector"
```

### Task 24: Recommendation distortion signal

**Files**
- Create: `app/assets/js/analytics/distortion.js`
- Test: `tests/distortion.test.mjs`

**Interfaces**
- Consumes: stockout signals and unchanged availability recommendations.
- Produces: `buildDistortionSignals(stockouts, recommendations)` returning `RecommendationDistortionSignal[]`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Recommendation distortion signal', async () => {
  const rec={sku:'1',clusterId:'Kazan',recommendedQty:150}; const [s]=api.buildDistortionSignals(fixture.stockouts,[rec]); assert.equal(s.recommendedClusterId,'Kazan'); assert.equal(s.affectedDestinations[0].destinationClusterId,'Moscow'); assert.equal(rec.recommendedQty,150); assert.ok(s.explanationCodes.includes('PROBABLE_RECOMMENDATION_DISTORTION'));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/distortion.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildDistortionSignals(stockouts,recs){return recs.flatMap(r=>signalForDonor(r,stockouts));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/distortion.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR5 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/distortion.js tests/distortion.test.mjs
git commit -m "feat: recommendation distortion signal"
```

### Task 25: Observed route profile

**Files**
- Create: `app/assets/js/analytics/route-profiles.js`
- Test: `tests/observed-route-profile.test.mjs`

**Interfaces**
- Consumes: eligible fulfilled routes.
- Produces: `buildObservedRouteProfile(orders, sku, originClusterId)` returning probabilities, sample size, source, confidence.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Observed route profile', async () => {
  const p=api.buildObservedRouteProfile(fixture.orders,'1','Kazan'); assert.equal(p.source,'sku_origin_observed'); assert.equal(p.sampleSize,300); assert.equal(sum(p.destinations,'probability'),1);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/observed-route-profile.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildObservedRouteProfile(orders,sku,origin){return profile(selectFulfilledRouteOrders(orders).filter(x=>x.sku===sku&&x.originClusterId===origin),'sku_origin_observed');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/observed-route-profile.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR5 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/route-profiles.js tests/observed-route-profile.test.mjs
git commit -m "feat: observed route profile"
```

### Task 26: Stockout-clean route profile

**Files**
- Create: `app/assets/js/analytics/clean-routes.js`
- Test: `tests/clean-route-profile.test.mjs`

**Interfaces**
- Consumes: fulfilled routes and high-confidence stockout weeks.
- Produces: `buildCleanRouteProfile(orders, stockouts, sku, originClusterId)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Stockout-clean route profile', async () => {
  const p=api.buildCleanRouteProfile(fixture.orders,fixture.stockouts,'1','Kazan'); assert.equal(p.source,'sku_origin_clean'); assert.equal(p.excludedWeeks.length,1); assert.equal(sum(p.destinations,'probability'),1);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/clean-route-profile.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildCleanRouteProfile(orders,signals,sku,origin){const excluded=highConfidenceKeys(signals); return profile(eligible(orders,sku,origin).filter(x=>!excluded.has(routeWeekKey(x))),'sku_origin_clean');}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/clean-route-profile.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR5 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/clean-routes.js tests/clean-route-profile.test.mjs
git commit -m "feat: stockout-clean route profile"
```

### Task 27: Route fallback and confidence

**Files**
- Create: `app/assets/js/analytics/route-fallback.js`
- Test: `tests/route-fallback.test.mjs`

**Interfaces**
- Consumes: clean/observed SKU-origin, origin-all-SKU, and global profiles.
- Produces: `selectRouteProfile(candidates, minimumSample)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Route fallback and confidence', async () => {
  assert.equal(api.selectRouteProfile(fixture.withClean,10).source,'sku_origin_clean'); assert.equal(api.selectRouteProfile(fixture.observedOnly,10).source,'sku_origin_observed'); assert.equal(api.selectRouteProfile(fixture.originOnly,10).source,'origin_all_skus'); assert.equal(api.selectRouteProfile(fixture.globalOnly,10).confidence,'low');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/route-fallback.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function selectRouteProfile(c,n){return [c.clean,c.observed,c.originAllSkus,c.global].find(p=>p&&p.sampleSize>=n)||c.global;}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/route-fallback.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR5 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/analytics/route-fallback.js tests/route-fallback.test.mjs
git commit -m "feat: route fallback and confidence"
```

## PR5 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR5

Review 5–10 probable signals against historical evidence; record results outside the automatic decision path and preserve probabilistic wording. Use current real seller reports outside git; never commit sensitive raw reports.

---

# PR6 — Logistics + unit economics

Implement only these tasks in PR6; do not pull later scope forward.

### Task 28: Tariff index

**Files**
- Create: `app/assets/js/economics/tariff-index.js`
- Test: `tests/tariff-index.test.mjs`

**Interfaces**
- Consumes: normalized `TariffRow[]`.
- Produces: `buildTariffIndex(rows)` keyed by origin and destination with sorted ranges.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Tariff index', async () => {
  const i=api.buildTariffIndex(fixture.rows); assert.deepEqual(i.get('Kazan|Moscow').map(x=>x.minVolumeLiters),[0,1,5]);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/tariff-index.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildTariffIndex(rows){return indexAndSort(rows,r=>`${r.originClusterId}|${r.destinationClusterId}`,r=>r.minVolumeLiters);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/tariff-index.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR6 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/economics/tariff-index.js tests/tariff-index.test.mjs
git commit -m "feat: tariff index"
```

### Task 29: Tariff lookup

**Files**
- Create: `app/assets/js/economics/tariff-lookup.js`
- Test: `tests/tariff-lookup.test.mjs`

**Interfaces**
- Consumes: tariff index, route, volume, and price.
- Produces: `lookupTariff(index, query)` returning `{fee, complete, blocker}`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Tariff lookup', async () => {
  assert.deepEqual(api.lookupTariff(fixture.index,{origin:'Kazan',destination:'Moscow',volume:2,price:1000}),{fee:100,complete:true,blocker:null}); assert.equal(api.lookupTariff(fixture.index,{origin:'Kazan',destination:'Perm',volume:2,price:1000}).blocker,'MISSING_TARIFF');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/tariff-lookup.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function lookupTariff(index,q){const row=findMatchingRange(index.get(`${q.origin}|${q.destination}`)||[],q); return row?{fee:row.logisticsFee,complete:true,blocker:null}:{fee:null,complete:false,blocker:'MISSING_TARIFF'};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/tariff-lookup.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR6 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/economics/tariff-lookup.js tests/tariff-lookup.test.mjs
git commit -m "feat: tariff lookup"
```

### Task 30: Expected logistics

**Files**
- Create: `app/assets/js/economics/expected-logistics.js`
- Test: `tests/expected-logistics.test.mjs`

**Interfaces**
- Consumes: route profile, tariff index, volume, and price.
- Produces: `calculateExpectedLogistics(input)` with fee, coverage, source, confidence, missing destinations.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Expected logistics', async () => {
  const full=api.calculateExpectedLogistics(fixture.eightyTwenty); assert.equal(full.expectedFee,60); assert.equal(full.tariffCoverage,1);
  const partial=api.calculateExpectedLogistics(fixture.partial); assert.equal(partial.tariffCoverage,.8); assert.equal(partial.expectedFee,40); assert.deepEqual(partial.missingDestinations,['Kazan']);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/expected-logistics.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function calculateExpectedLogistics(i){const legs=i.profile.destinations.map(d=>priceLeg(d,i)); return {expectedFee:sumKnownWeighted(legs),tariffCoverage:sumKnownProbability(legs),missingDestinations:missing(legs),routeProfileSource:i.profile.source,routeConfidence:i.profile.confidence};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/expected-logistics.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR6 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/economics/expected-logistics.js tests/expected-logistics.test.mjs
git commit -m "feat: expected logistics"
```

### Task 31: Spreadsheet-parity unit economics

**Files**
- Create: `app/assets/js/economics/unit-economics.js`
- Test: `tests/unit-economics.test.mjs`

**Interfaces**
- Consumes: `UnitEconomicsInput` with explicit `EconomicsSettings`.
- Produces: `calculateUnitEconomics(input)` returning every canonical result field and blockers.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Spreadsheet-parity unit economics', async () => {
  const r=api.calculateUnitEconomics(fixture.input); assert.equal(r.commission,150); assert.equal(r.acquiring,20); assert.equal(r.cost,400); assert.equal(r.complete,true); assert.equal(r.profitPerUnit,fixture.expected.profitPerUnit); assert.equal(r.marginRate,fixture.expected.marginRate); assert.equal(r.roi,fixture.expected.roi);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/unit-economics.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function calculateUnitEconomics(i){const commission=i.price*i.commissionRate; const acquiring=i.price*i.settings.acquiringRate; const parts=applySpreadsheetOrder({...i,commission,acquiring}); return finalizeEconomics(parts);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/unit-economics.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR6 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/economics/unit-economics.js tests/unit-economics.test.mjs
git commit -m "feat: spreadsheet-parity unit economics"
```

### Task 32: Golden regression fixtures

**Files**
- Create: `tests/fixtures/economics-golden.json`
- Test: `tests/economics-golden.test.mjs`

**Interfaces**
- Consumes: sanitized spreadsheet input/output rows and rounding tolerance.
- Produces: a regression assertion over local/intercluster, commission, acquiring, services, buyout, taxes, VAT, co-invest, cost, profit, margin, and ROI.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Golden regression fixtures', async () => {
  for(const c of fixture.cases){const actual=api.calculateUnitEconomics(c.input); for(const field of ['commission','acquiring','expectedLogistics','advertisingAndServices','coInvest','vat','incomeTax','tax','cost','profitPerUnit','marginRate','roi']) assert.ok(Math.abs(actual[field]-c.expected[field])<=c.tolerance,`${c.name}: ${field}`);}
  assert.ok(fixture.cases.some(x=>x.route==='local')&&fixture.cases.some(x=>x.route==='intercluster'));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/economics-golden.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
// Encode 5–10 sanitized oracle rows with explicit inputs, expected outputs, and tolerance; production behavior remains `calculateUnitEconomics`.
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/economics-golden.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR6 PASS.

- [ ] Step 6: Commit

```bash
git add tests/fixtures/economics-golden.json tests/economics-golden.test.mjs
git commit -m "feat: golden regression fixtures"
```

## PR6 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR6

Compare 5–10 sanitized/current cases with the seller spreadsheet, including local/intercluster routes and tax/VAT/co-invest branches; parity within declared tolerance is a hard gate. Use current real seller reports outside git; never commit sensitive raw reports.

---

# PR7 — Feasibility + optimizer

Implement only these tasks in PR7; do not pull later scope forward.

### Task 33: Warehouse feasibility

**Files**
- Create: `app/assets/js/supply/feasibility.js`
- Test: `tests/feasibility.test.mjs`

**Interfaces**
- Consumes: SKU, cluster, and normalized warehouse restrictions.
- Produces: `evaluateSupplyFeasibility(input)` returning `SupplyFeasibility`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Warehouse feasibility', async () => {
  const blocked=api.evaluateSupplyFeasibility(fixture.allBlocked); assert.equal(blocked.allowed,false); assert.deepEqual(blocked.eligibleWarehouses,[]);
  const ambiguous=api.evaluateSupplyFeasibility(fixture.multipleMaxima); assert.ok(ambiguous.reasons.includes('AMBIGUOUS_MAXIMUM_CONSERVATIVE')); assert.equal(ambiguous.maxSupplyQty,20);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/feasibility.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function evaluateSupplyFeasibility(i){const eligible=i.restrictions.filter(r=>r.allowed); return {sku:i.sku,clusterId:i.clusterId,allowed:eligible.length>0,maxSupplyQty:conservativeMaximum(eligible),eligibleWarehouses:eligible.map(r=>r.warehouseId),reasons:feasibilityReasons(i,eligible)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/feasibility.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR7 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/supply/feasibility.js tests/feasibility.test.mjs
git commit -m "feat: warehouse feasibility"
```

### Task 34: Placement assessment

**Files**
- Create: `app/assets/js/supply/placement.js`
- Test: `tests/placement-assessment.test.mjs`

**Interfaces**
- Consumes: recommendations, demand destinations, stockouts, donor origins, feasibility, economics, and route confidence.
- Produces: `buildPlacementAssessments(input)` returning relevant `PlacementAssessment[]`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Placement assessment', async () => {
  const out=api.buildPlacementAssessments(fixture.counterfactual); const m=find(out,'Moscow'); assert.equal(m.ozonRecommendedQty,0); assert.ok(m.statusCodes.includes('COUNTERFACTUAL_ONLY')); assert.ok(find(out,'Kazan').distortionSignal);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/placement-assessment.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildPlacementAssessments(i){return relevantClusters(i).map(clusterId=>assessCluster(i,clusterId));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/placement-assessment.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR7 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/supply/placement.js tests/placement-assessment.test.mjs
git commit -m "feat: placement assessment"
```

### Task 35: Optimization candidates

**Files**
- Create: `app/assets/js/supply/candidates.js`
- Test: `tests/optimization-candidates.test.mjs`

**Interfaces**
- Consumes: placement assessments and `OptimizerThresholds`.
- Produces: `buildOptimizationCandidates(assessments, thresholds)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Optimization candidates', async () => {
  const out=api.buildOptimizationCandidates(fixture.assessments,fixture.thresholds); assert.equal(find(out,'Moscow').eligible,false); assert.equal(find(out,'Moscow').ceiling,0); assert.equal(find(out,'Kazan').eligible,true);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/optimization-candidates.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildOptimizationCandidates(xs,t){return xs.map(a=>({clusterId:a.clusterId,eligible:a.ozonRecommendedQty>0&&a.feasibility.allowed&&a.economics.complete&&aboveThresholds(a.economics,t),ceiling:Math.min(a.ozonRecommendedQty,a.feasibility.maxSupplyQty??Infinity),expectedProfitPerUnit:a.economics.profitPerUnit,assessment:a}));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/optimization-candidates.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR7 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/supply/candidates.js tests/optimization-candidates.test.mjs
git commit -m "feat: optimization candidates"
```

### Task 36: Threshold and status composition

**Files**
- Create: `app/assets/js/supply/statuses.js`
- Test: `tests/recommendation-statuses.test.mjs`

**Interfaces**
- Consumes: assessment, completeness, thresholds, and signals.
- Produces: `composeRecommendationStatuses(input)` returning ordered machine-readable codes.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Threshold and status composition', async () => {
  assert.deepEqual(api.composeRecommendationStatuses(fixture.negative),['NEGATIVE_ECONOMICS']); assert.deepEqual(api.composeRecommendationStatuses(fixture.blockedDistorted),['SUPPLY_BLOCKED','PROBABLE_RECOMMENDATION_DISTORTION']); assert.ok(api.composeRecommendationStatuses(fixture.missingTariff).includes('INCOMPLETE_TARIFF_COVERAGE'));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/recommendation-statuses.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function composeRecommendationStatuses(i){return STATUS_RULES.filter(r=>r.when(i)).map(r=>r.code);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/recommendation-statuses.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR7 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/supply/statuses.js tests/recommendation-statuses.test.mjs
git commit -m "feat: threshold and status composition"
```

### Task 37: Deterministic limited-stock optimizer

**Files**
- Create: `app/assets/js/supply/optimizer.js`
- Test: `tests/optimizer.test.mjs`

**Interfaces**
- Consumes: eligible candidates and seller available quantity.
- Produces: `optimizeSkuAllocation(candidates, availableQty)` returning allocations and expected plan profit.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Deterministic limited-stock optimizer', async () => {
  const plan=api.optimizeSkuAllocation(fixture.candidates,12); assert.ok(plan.allocations.every(a=>a.quantity>=0&&a.quantity<=a.ozonRecommendedQty&&a.quantity<=a.feasibleQty)); assert.ok(sum(plan.allocations,'quantity')<=12); assert.equal(find(plan.allocations,'Moscow').quantity,0); assert.equal(plan.expectedProfit,sumProducts(plan.allocations)); assert.deepEqual(api.optimizeSkuAllocation(fixture.ties,5),api.optimizeSkuAllocation(fixture.ties,5));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/optimizer.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function optimizeSkuAllocation(cs,stock){let left=stock; const ordered=[...cs].sort(compareByProfitConfidenceRiskRecommendationCluster); const allocations=ordered.map(c=>{const quantity=c.eligible?Math.max(0,Math.min(left,c.ceiling)):0; left-=quantity; return allocation(c,quantity);}); return {allocations,expectedProfit:allocations.reduce((s,a)=>s+a.quantity*a.expectedProfitPerUnit,0)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/optimizer.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR7 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/supply/optimizer.js tests/optimizer.test.mjs
git commit -m "feat: deterministic limited-stock optimizer"
```

## PR7 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR7

Compare donor recommendation, affected-destination counterfactual, feasibility, deterministic ordering, and allocations under unchanged Ozon ceilings. Use current real seller reports outside git; never commit sensitive raw reports.

---

# PR8 — UI + end-to-end

Implement only these tasks in PR8; do not pull later scope forward.

### Task 38: Application state and composition

**Files**
- Modify: `app/assets/js/app.js`
- Create: `app/assets/js/ui/state.js`
- Test: `tests/application-state.test.mjs`

**Interfaces**
- Consumes: import results, settings, and user actions.
- Produces: `createAppState()`, `reduceAppState(state, action)`, `calculatePlan(state)` composing the pipeline.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Application state and composition', async () => {
  let s=api.createAppState(); s=api.reduceAppState(s,{type:'IMPORT_ACCEPTED',kind:'orders',result:fixture.orders}); assert.equal(s.imports.orders.records.length,4); assert.deepEqual(api.calculatePlan(fixture.completeState),fixture.planSummary);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/application-state.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function calculatePlan(state){const analytics=runAnalytics(state); const assessments=runEconomicsAndFeasibility(state,analytics); return optimizeAndExplain(state,assessments);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/application-state.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/app.js app/assets/js/ui/state.js tests/application-state.test.mjs
git commit -m "feat: application state and composition"
```

### Task 39: File import and settings UI

**Files**
- Create: `app/assets/js/ui/import-screen.js`
- Modify: `app/index.html`
- Modify: `app/assets/css/app.css`
- Test: `tests/import-screen.test.mjs`

**Interfaces**
- Consumes: application state and local file/settings events.
- Produces: `renderImportScreen(state)`, `readSelectedFile(file)`, `parseSettings(formData)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('File import and settings UI', async () => {
  const html=api.renderImportScreen(fixture.state); for(const label of ['Availability','Warehouse restrictions','Orders history','Tariffs','Product economics']) assert.match(html,new RegExp(label)); assert.doesNotMatch(html,/onchange=|onclick=/); assert.deepEqual(api.parseSettings(fixture.form),fixture.settings);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/import-screen.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function renderImportScreen(state){return IMPORT_CARDS.map(c=>renderFileCard(c,state.imports[c.kind])).join('')+renderSettings(state.settings);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/import-screen.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/import-screen.js app/index.html app/assets/css/app.css tests/import-screen.test.mjs
git commit -m "feat: file import and settings ui"
```

### Task 40: Report freshness and diagnostics UI

**Files**
- Create: `app/assets/js/ui/diagnostics.js`
- Test: `tests/diagnostics-ui.test.mjs`

**Interfaces**
- Consumes: `ImportResult` metadata/diagnostics and current instant.
- Produces: `buildImportCardModel(result, now)` and `detectReportDateMismatch(results, toleranceDays)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Report freshness and diagnostics UI', async () => {
  const m=api.buildImportCardModel(fixture.result,'2026-08-20T00:00:00Z'); assert.deepEqual(pick(m,['sourceName','period','importedAt','accepted','rejected','skuCount','validationStatus']),fixture.expected); assert.equal(api.detectReportDateMismatch(fixture.misaligned,2).code,'REPORT_DATES_MISMATCH');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/diagnostics-ui.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildImportCardModel(r,now){return {sourceName:r.meta.sourceName,period:formatPeriod(r.meta),importedAt:r.meta.importedAt,accepted:r.records.length,rejected:errorRows(r.diagnostics),skuCount:uniqueSkus(r.records),validationStatus:status(r,now)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/diagnostics-ui.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/diagnostics.js tests/diagnostics-ui.test.mjs
git commit -m "feat: report freshness and diagnostics ui"
```

### Task 41: Dashboard

**Files**
- Create: `app/assets/js/ui/dashboard.js`
- Test: `tests/dashboard.test.mjs`

**Interfaces**
- Consumes: explainable optimized plan.
- Produces: `buildDashboardModel(plan)`, `renderDashboard(model)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Dashboard', async () => {
  const m=api.buildDashboardModel(fixture.plan); assert.deepEqual(m,{analyzedSkus:2,ozonRecommendedUnits:200,sellerAvailableUnits:120,allocatedUnits:120,expectedProfit:36000,negativeEconomics:1,probableStockouts:1,distortedRecommendations:1,blockedRoutes:1,incompleteSkus:1}); assert.match(api.renderDashboard(m),/120/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/dashboard.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildDashboardModel(plan){return aggregateDashboardMetrics(plan);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/dashboard.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/dashboard.js tests/dashboard.test.mjs
git commit -m "feat: dashboard"
```

### Task 42: SKU detail

**Files**
- Create: `app/assets/js/ui/sku-detail.js`
- Test: `tests/sku-detail.test.mjs`

**Interfaces**
- Consumes: SKU analytics, signals, and assessments.
- Produces: `buildSkuDetailModel(input)`, `renderSkuDetail(model)` with four distinct views.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('SKU detail', async () => {
  const m=api.buildSkuDetailModel(fixture.input); assert.deepEqual(Object.keys(m.views),['demand','destinationFulfillment','originDonor','placementComparison']); const html=api.renderSkuDetail(m); for(const title of fixture.fourTitles) assert.match(html,new RegExp(title)); assert.match(html,/Kazan.*Moscow|Казань.*Москв/s);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/sku-detail.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildSkuDetailModel(i){return {views:{demand:demandView(i),destinationFulfillment:destinationView(i),originDonor:donorView(i),placementComparison:placementView(i)},stockouts:i.stockouts};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/sku-detail.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/sku-detail.js tests/sku-detail.test.mjs
git commit -m "feat: sku detail"
```

### Task 43: Placement comparison UI

**Files**
- Create: `app/assets/js/ui/placement-comparison.js`
- Test: `tests/placement-comparison.test.mjs`

**Interfaces**
- Consumes: recommended and counterfactual `PlacementAssessment[]`.
- Produces: `renderPlacementComparison(assessments)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Placement comparison UI', async () => {
  const html=api.renderPlacementComparison(fixture.assessments); assert.match(html,/COUNTERFACTUAL_ONLY/); assert.match(html,/PROBABLE_RECOMMENDATION_DISTORTION/); assert.match(html,/Moscow/); assert.match(html,/Kazan/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/placement-comparison.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function renderPlacementComparison(xs){return table(xs.map(a=>({cluster:a.clusterId,quantity:a.ozonRecommendedQty,profit:a.economics.profitPerUnit,statuses:a.statusCodes,evidence:distortionText(a)})));}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/placement-comparison.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/placement-comparison.js tests/placement-comparison.test.mjs
git commit -m "feat: placement comparison ui"
```

### Task 44: Supply plan UI

**Files**
- Create: `app/assets/js/ui/supply-plan.js`
- Test: `tests/supply-plan-ui.test.mjs`

**Interfaces**
- Consumes: optimizer output and assessment explanations.
- Produces: `buildSupplyPlanModel(plan)`, `renderSupplyPlan(model)`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Supply plan UI', async () => {
  const m=api.buildSupplyPlanModel(fixture.plan); assert.equal(sum(m.rows,'allocatedQty'),fixture.plan.allocatedQty); const html=api.renderSupplyPlan(m); assert.match(html,/expected profit/i); assert.match(html,/INCOMPLETE_TARIFF_COVERAGE/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/supply-plan-ui.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function buildSupplyPlanModel(plan){return {rows:plan.allocations.map(joinAssessmentEvidence),totals:sumPlan(plan)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/supply-plan-ui.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/supply-plan.js tests/supply-plan-ui.test.mjs
git commit -m "feat: supply plan ui"
```

### Task 45: Project JSON controls

**Files**
- Create: `app/assets/js/ui/project-controls.js`
- Modify: `app/index.html`
- Test: `tests/project-controls.test.mjs`

**Interfaces**
- Consumes: current state, selected JSON file, and browser download callback.
- Produces: `exportProject(state, download)`, `importProject(fileText)`, `renderProjectControls()`.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Project JSON controls', async () => {
  let saved; api.exportProject(fixture.state,(name,text)=>saved={name,text}); assert.match(saved.name,/\.json$/); assert.deepEqual(api.importProject(saved.text),fixture.normalizedState); assert.match(api.renderProjectControls(),/Export project/);
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/project-controls.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function exportProject(state,download){download(projectFileName(state),serializeProject(state));} function importProject(text){return deserializeProject(text);}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/project-controls.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/assets/js/ui/project-controls.js app/index.html tests/project-controls.test.mjs
git commit -m "feat: project json controls"
```

### Task 46: End-to-end pipeline fixture

**Files**
- Create: `tests/fixtures/e2e/availability.json`
- Create: `tests/fixtures/e2e/restrictions.json`
- Create: `tests/fixtures/e2e/orders.csv`
- Create: `tests/fixtures/e2e/tariffs.json`
- Create: `tests/fixtures/e2e/products.json`
- Test: `tests/e2e-pipeline.test.mjs`

**Interfaces**
- Consumes: real-schema sanitized local fixtures.
- Produces: canonical pipeline output: diagnostics, Moscow stockout, Kazan distortion, assessments, bounded allocation, and explanations.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('End-to-end pipeline fixture', async () => {
  const out=runPipeline(loadE2eFixtures()); assert.equal(out.stockouts[0].destinationClusterId,'Moscow'); assert.equal(out.distortions[0].recommendedClusterId,'Kazan'); assert.ok(out.assessments.some(x=>x.clusterId==='Moscow')); assert.ok(out.plan.allocations.every(x=>x.quantity<=x.ozonRecommendedQty)); assert.ok(out.plan.allocations.every(x=>x.statusCodes.length));
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/e2e-pipeline.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
function runPipeline(files){const normalized=importAll(files); const analytics=analyze(normalized); const economics=assess(normalized,analytics); return {...analytics,assessments:economics,plan:optimize(economics,normalized.products)};}
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/e2e-pipeline.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add tests/fixtures/e2e/availability.json tests/fixtures/e2e/restrictions.json tests/fixtures/e2e/orders.csv tests/fixtures/e2e/tariffs.json tests/fixtures/e2e/products.json tests/e2e-pipeline.test.mjs
git commit -m "feat: end-to-end pipeline fixture"
```

### Task 47: Final `file://` hardening

**Files**
- Modify: `app/index.html`
- Modify: `app/assets/js/app.js`
- Modify: `app/assets/css/app.css`
- Test: `tests/offline-acceptance.test.mjs`

**Interfaces**
- Consumes: checked-in HTML and every referenced production asset.
- Produces: an offline asset graph rooted at `app/index.html` with no unresolved or non-local dependency.

- [ ] Step 1: Write failing test

```js
import test from 'node:test';
import assert from 'node:assert/strict';

test('Final `file://` hardening', async () => {
  const graph=api.inspectOfflineAssetGraph('app/index.html'); assert.deepEqual(graph.missing,[]); assert.deepEqual(graph.remote,[]); assert.deepEqual(graph.rootRelative,[]); assert.deepEqual(graph.dynamicAssetLoads,[]); assert.equal(graph.entry,'app/index.html');
});
```

- [ ] Step 2: Run test and verify RED

```bash
node --test tests/offline-acceptance.test.mjs
```

Expected: FAIL because the named production function/file or the asserted behavior does not exist yet.

- [ ] Step 3: Implement minimal behavior

```js
// Keep all script/style/vendor references explicit and relative in app/index.html; start via SkladOzon.boot() after ordered classic scripts load.
```

Expose the named functions on the relevant `globalThis.SkladOzon` namespace; keep source decoding/DOM effects outside pure calculations.

- [ ] Step 4: Run test and verify GREEN

```bash
node --test tests/offline-acceptance.test.mjs
```

Expected: PASS for this task's assertions.

- [ ] Step 5: Run relevant regression suite

```bash
node --test
```

Expected: all tests through PR8 PASS.

- [ ] Step 6: Commit

```bash
git add app/index.html app/assets/js/app.js app/assets/css/app.css tests/offline-acceptance.test.mjs
git commit -m "feat: final file:// hardening"
```

## PR8 merge gate

```bash
node --test
git diff --check
```

Expected: the full suite passes and the diff has no whitespace errors.

## Manual validation checkpoint after PR8

From a fresh ZIP, double-click the entry page offline, import current reports, calculate, inspect every explanation, export JSON, re-import it, and reconcile totals. Use current real seller reports outside git; never commit sensitive raw reports.

---

# Final acceptance and plan self-review

Task count: **47** (PR1: 2, PR2: 8, PR3: 7, PR4: 5, PR5: 5, PR6: 5, PR7: 5, PR8: 10).

The accepted user journey is:

```text
repository ZIP
→ extract
→ double-click app/index.html
→ select local reports
→ calculate
→ inspect an explainable plan
→ export/import project JSON
```

It must complete with no network, no server process, and no installation.

Before completing PR8, check every box:

- [ ] Every major design requirement maps to a task above; PR1–PR8 are present and ordered.
- [ ] Every task contains exact files, interfaces, a concrete failing test, a RED command/reason, a minimal implementation signature, a GREEN command, a regression command, and commit commands.
- [ ] Production files use `.js`; Node tests use `.test.mjs`; names and data shapes are consistent.
- [ ] There is no placeholder wording and no superseded toolchain or runtime architecture.
- [ ] `app/index.html` remains the canonical runtime entry point with relative local assets.
- [ ] The malformed `dimension=A1` regression imports all populated rows and emits `WORKSHEET_DIMENSION_REPAIRED`.
- [ ] The Kazan-origin/Moscow-destination invariant, 800/200/100 matrix, stockout positive fixture, and all negative controls remain covered.
- [ ] Spreadsheet parity remains a hard merge gate before optimizer acceptance.
- [ ] Counterfactual assessments remain separate from candidates, and all automatic allocations remain within Ozon recommendation, feasibility, and seller-stock ceilings.
- [ ] Manual checkpoints use current seller reports outside git and no sensitive report is committed.
