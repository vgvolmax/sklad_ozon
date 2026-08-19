# Ozon FBO Unit Economics & Supply Optimizer MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully local FBO planning application that imports Ozon reports, reconstructs demand and fulfillment routes, detects probable stockout substitution, reproduces the spreadsheet unit economics, and allocates limited stock to maximize expected absolute profit.

**Architecture:** Functional core / imperative shell. Ozon-specific file formats terminate at import adapters; all downstream modules consume canonical TypeScript domain contracts. Development uses TypeScript and Node-based build/test tooling, while the release is a static offline bundle that runs from `file://` without Node, Python, backend, API, or CDN.

**Tech Stack:** TypeScript, esbuild, Vitest, SheetJS (`xlsx`), Papa Parse, IndexedDB, vanilla DOM/CSS, optional Playwright only for final offline browser smoke tests.

**Spec:** `docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`

## Global Constraints

- FBO only in MVP.
- No Ozon API, backend, cloud storage, user accounts, or runtime server.
- Release must open from `file://` and must not require Node.js or Python.
- No runtime CDN dependencies.
- Demand is always attributed to the **delivery cluster**, never the dispatch cluster.
- `Вероятный stockout` is diagnostic evidence only and must not silently override an Ozon recommendation in MVP.
- Tariff matrix is user-loaded and locally persisted, not hard-coded into application source.
- Cluster master data are derived from imported sources; ambiguous mappings require explicit diagnostics/manual mapping.
- Business formulas must not read from DOM or IndexedDB directly.
- Missing tariff/economics inputs are blockers, never silently replaced with zero.
- Full seller-sensitive raw reports are not committed to the repository; tests use minimal sanitized fixtures.

---

## File map locked for MVP

```text
index.html                         release entry template
styles.css                         application styles
package.json                       development-only scripts/dependencies
tsconfig.json                      TypeScript configuration
vitest.config.ts                   test configuration
scripts/build.mjs                  bundles TypeScript to dist/app.js IIFE
scripts/copy-release-assets.mjs    writes static release files

src/app/bootstrap.ts               application composition root
src/app/state.ts                   AppState and reducer-like state transitions
src/app/selectors.ts               derived UI data only

src/domain/models.ts               canonical business models
src/domain/result.ts               Result/diagnostic primitives
src/domain/invariants.ts           runtime domain assertions

src/importers/workbook.ts          shared XLSX workbook access helpers
src/importers/csv.ts               robust CSV decoding
src/importers/availability.ts      Ozon availability adapter
src/importers/restrictions.ts      warehouse restriction adapter
src/importers/orders.ts            orders.csv adapter
src/importers/tariffs.ts           tariff workbook adapter
src/importers/products.ts          seller economics/stock input adapter
src/importers/import-diagnostics.ts diagnostic aggregation

src/normalization/clusters.ts      cluster canonicalization/manual mappings
src/normalization/sku.ts           SKU/article normalization
src/normalization/numbers.ts       locale-safe numeric parsing
src/normalization/dates.ts         report date parsing/week bucketing

src/analytics/demand-matrix.ts     destination demand aggregation
src/analytics/fulfillment-matrix.ts origin↔destination shares
src/analytics/weekly-series.ts     weekly route history
src/analytics/stockout-detector.ts probable-stockout heuristic
src/analytics/route-profile.ts     observed/clean route profiles + fallback

src/economics/tariff-index.ts      indexed tariff representation
src/economics/tariff-lookup.ts     exact tariff lookup
src/economics/expected-logistics.ts expected route-weighted logistics
src/economics/unit-economics.ts    spreadsheet-parity economics engine

src/supply/feasibility.ts          SKU×cluster warehouse feasibility
src/supply/cluster-score.ts        candidate composition/status codes
src/supply/optimizer.ts            deterministic constrained allocation

src/persistence/store.ts           LocalStore interface + keys/versioning
src/persistence/indexeddb-store.ts IndexedDB implementation
src/persistence/memory-store.ts    deterministic test implementation

src/ui/shell.ts                    navigation/layout
src/ui/upload-view.ts              report and economics import UI
src/ui/dashboard-view.ts           KPI + optimized plan
src/ui/sku-view.ts                 SKU detail + route/stockout evidence
src/ui/plan-view.ts                allocation table + explanations
src/ui/diagnostics-view.ts         import/calculation blockers
src/ui/components/*.ts             small reusable DOM components

tests/fixtures/*                   sanitized/minimal fixtures
tests/importers/*                  adapter contract tests
tests/analytics/*                  demand/route/stockout tests
tests/economics/*                  tariff + spreadsheet parity tests
tests/supply/*                     feasibility/optimizer tests
tests/integration/*                end-to-end domain pipeline tests
```

---

# PR sequence

| PR | Deliverable | Merge gate |
|---|---|---|
| PR1 | Static offline foundation + canonical domain contracts | `dist/index.html` opens from `file://`; tests green |
| PR2 | Ozon operational imports + normalization + diagnostics | real-schema fixtures import without preprocessing |
| PR3 | Tariff/product imports + local persistence | tariff lookup dataset and product economics survive reload |
| PR4 | Demand, fulfillment, weekly route analytics | destination/origin shares match hand-calculated fixtures |
| PR5 | Probable stockout detector + clean route profiles | synthetic Moscow/Kazan substitution cases classified correctly |
| PR6 | Tariff engine + expected logistics + spreadsheet-parity unit economics | golden Excel fixture matches within tolerance |
| PR7 | Warehouse feasibility + candidate scoring + optimizer | all constraints hold; limited stock maximizes expected profit |
| PR8 | Complete user workflow, explainability, release hardening | real reports → optimized plan from offline release |

Each PR is intended to be merged before the next one begins. Do not stack multiple unreviewed architectural PRs unless explicitly requested.

---

## PR1 — Static offline foundation and domain contracts

### Task 1: Create development and release skeleton

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `vitest.config.ts`
- Create: `index.html`
- Create: `styles.css`
- Create: `scripts/build.mjs`
- Create: `scripts/copy-release-assets.mjs`
- Create: `src/app/bootstrap.ts`
- Test: `tests/integration/offline-shell.test.ts`

**Interfaces:**
- Produces: `npm run build` → `dist/index.html`, `dist/app.js`, `dist/styles.css`.
- Runtime contract: opening `dist/index.html` must execute `dist/app.js` as a classic script, not require a dev server.

- [ ] **Step 1: Write the failing build/shell test**

```ts
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

it('builds a file:// compatible static release shell', async () => {
  expect(existsSync('dist/index.html')).toBe(true);
  expect(existsSync('dist/app.js')).toBe(true);
  const html = readFileSync('dist/index.html', 'utf8');
  expect(html).toContain('<script src="./app.js"></script>');
  expect(html).not.toContain('type="module"');
  expect(html).not.toContain('http://');
  expect(html).not.toContain('https://');
});
```

- [ ] **Step 2: Run the test before implementation**

Run: `npm test -- tests/integration/offline-shell.test.ts`

Expected: FAIL because build files/scripts do not exist.

- [ ] **Step 3: Add minimal package/build configuration**

`package.json` scripts:

```json
{
  "scripts": {
    "build": "node scripts/build.mjs",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

`build.mjs` must bundle `src/app/bootstrap.ts` as browser IIFE, target modern Chromium/Edge, emit `dist/app.js`, and copy `index.html`/`styles.css` into `dist/`.

- [ ] **Step 4: Add minimal bootstrap behavior**

```ts
const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('APP_ROOT_MISSING');
root.textContent = 'Ozon FBO Supply Optimizer';
```

- [ ] **Step 5: Build and test**

Run:

```bash
npm run build
npm test
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add package.json tsconfig.json vitest.config.ts index.html styles.css scripts src/app/bootstrap.ts tests/integration/offline-shell.test.ts
git commit -m "build: add offline static application foundation"
```

### Task 2: Define canonical domain and diagnostic contracts

**Files:**
- Create: `src/domain/models.ts`
- Create: `src/domain/result.ts`
- Create: `src/domain/invariants.ts`
- Test: `tests/domain/models.test.ts`

**Interfaces:**
- Produces the exact canonical contracts defined by the design spec: `ProductRef`, `AvailabilityRecommendation`, `WarehouseRestriction`, `OrderRecord`, `ProductEconomicsInput`, `TariffRow`, `ImportDiagnostic`, `ImportResult<T>`.
- All downstream PRs import domain types from `src/domain/models.ts`; they do not redefine report-shaped interfaces.

- [ ] **Step 1: Write compile/runtime invariant tests**

```ts
import { expect, it } from 'vitest';
import { assertNonNegative, assertRate } from '../../src/domain/invariants';

it('rejects negative quantities', () => {
  expect(() => assertNonNegative(-1, 'quantity')).toThrow('quantity');
});

it('accepts normalized decimal rates', () => {
  expect(assertRate(0.25, 'commissionRate')).toBe(0.25);
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test -- tests/domain/models.test.ts`

Expected: FAIL because invariant helpers are missing.

- [ ] **Step 3: Implement types and invariants**

Required signatures:

```ts
export function assertNonNegative(value: number, field: string): number;
export function assertRate(value: number, field: string): number;
export function assertNonEmpty(value: string, field: string): string;
```

Rates are normalized decimals in domain code (`0.25`, not `25`).

- [ ] **Step 4: Run full test suite**

Run: `npm test`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/domain tests/domain
git commit -m "feat: define canonical optimizer domain contracts"
```

**PR1 acceptance:** release shell works offline; domain contracts compile; no Ozon column names appear outside importers because importers do not exist yet.

---

## PR2 — Operational Ozon imports, normalization, diagnostics

### Task 3: Implement normalization primitives

**Files:**
- Create: `src/normalization/numbers.ts`
- Create: `src/normalization/dates.ts`
- Create: `src/normalization/sku.ts`
- Create: `src/normalization/clusters.ts`
- Test: `tests/normalization/*.test.ts`

**Interfaces:**

```ts
export function parseRuNumber(value: unknown): number | null;
export function parseIsoDate(value: unknown): string | null;
export function toIsoWeek(date: string): string;
export function normalizeSku(value: unknown): string | null;
export function normalizeArticle(value: unknown): string | null;

export interface ClusterMapping {
  rawName: string;
  clusterId: string;
}

export function normalizeClusterName(rawName: string): string;
export function resolveClusterId(rawName: string, manual: ReadonlyMap<string, string>): string;
```

- [ ] **Step 1: Add table-driven failing tests**

Include Russian decimal commas, non-breaking spaces, `1 234,50`, empty values, mixed case cluster names, repeated whitespace, and punctuation-only differences.

- [ ] **Step 2: Run tests and verify failures**

Run: `npm test -- tests/normalization`

- [ ] **Step 3: Implement minimal deterministic normalizers**

Do not fuzzy-merge semantically different cluster strings. Only normalize harmless formatting differences automatically.

- [ ] **Step 4: Run tests**

Run: `npm test`

- [ ] **Step 5: Commit**

```bash
git add src/normalization tests/normalization
git commit -m "feat: add deterministic report normalization"
```

### Task 4: Implement shared XLSX/CSV decoding and diagnostics

**Files:**
- Create: `src/importers/workbook.ts`
- Create: `src/importers/csv.ts`
- Create: `src/importers/import-diagnostics.ts`
- Test: `tests/importers/workbook.test.ts`
- Test: `tests/importers/csv.test.ts`

**Interfaces:**

```ts
export interface TabularSheet {
  name: string;
  rows: Record<string, unknown>[];
}

export async function readWorkbook(file: File): Promise<TabularSheet[]>;
export async function readCsv(file: File): Promise<Record<string, unknown>[]>;
export function requireColumns(rows: Record<string, unknown>[], required: string[]): ImportDiagnostic[];
```

- [ ] **Step 1: Add minimal sanitized XLSX/CSV fixtures**

Fixtures contain only synthetic rows matching known report headers; no full production seller reports.

- [ ] **Step 2: Write tests for Cyrillic headers and quoted CSV**

Test semicolon/comma delimiter detection and UTF-8 BOM handling.

- [ ] **Step 3: Run tests and verify failure**

Run: `npm test -- tests/importers/workbook.test.ts tests/importers/csv.test.ts`

- [ ] **Step 4: Implement SheetJS/Papa Parse adapters**

Keep dependency calls isolated in these files.

- [ ] **Step 5: Run tests and commit**

```bash
npm test
git add src/importers tests/importers package.json package-lock.json
git commit -m "feat: add local xlsx and csv decoding"
```

### Task 5: Implement Availability, Restrictions and Orders adapters

**Files:**
- Create: `src/importers/availability.ts`
- Create: `src/importers/restrictions.ts`
- Create: `src/importers/orders.ts`
- Create: `tests/fixtures/availability-minimal.xlsx`
- Create: `tests/fixtures/restrictions-minimal.xlsx`
- Create: `tests/fixtures/orders-minimal.csv`
- Test: `tests/importers/availability.test.ts`
- Test: `tests/importers/restrictions.test.ts`
- Test: `tests/importers/orders.test.ts`

**Interfaces:**

```ts
export async function importAvailability(file: File, mappings: ReadonlyMap<string, string>): Promise<ImportResult<AvailabilityRecommendation>>;
export async function importRestrictions(file: File, mappings: ReadonlyMap<string, string>): Promise<ImportResult<WarehouseRestriction>>;
export async function importOrders(file: File, mappings: ReadonlyMap<string, string>): Promise<ImportResult<OrderRecord>>;
```

- [ ] **Step 1: Encode exact fixture expectations**

Orders test must explicitly assert:

```ts
expect(record.destinationClusterId).toBe('moscow');
expect(record.originClusterId).toBe('kazan');
```

for a synthetic `Казань → Москва` row. This guards the central demand-attribution invariant.

- [ ] **Step 2: Verify tests fail**

Run: `npm test -- tests/importers`

- [ ] **Step 3: Implement column alias maps inside each adapter**

Each adapter owns its source header aliases. Domain modules must never reference Russian report headings.

- [ ] **Step 4: Add partial-row error behavior**

Malformed rows produce diagnostics and are skipped; missing mandatory file columns produce file-level errors and zero accepted records.

- [ ] **Step 5: Run full suite and commit**

```bash
npm test
git add src/importers tests/importers tests/fixtures
git commit -m "feat: import Ozon operational reports"
```

**PR2 acceptance:** minimal fixtures for all three operational reports import into canonical records; diagnostics are explicit; Kazan→Moscow is represented as Moscow demand fulfilled from Kazan.

---

## PR3 — Tariffs, seller economics input, local persistence

### Task 6: Import tariffs and seller product inputs

**Files:**
- Create: `src/importers/tariffs.ts`
- Create: `src/importers/products.ts`
- Create: `tests/fixtures/tariffs-minimal.xlsx`
- Create: `tests/fixtures/products-minimal.xlsx`
- Test: `tests/importers/tariffs.test.ts`
- Test: `tests/importers/products.test.ts`

**Interfaces:**

```ts
export async function importTariffs(file: File, mappings: ReadonlyMap<string, string>): Promise<ImportResult<TariffRow>>;
export async function importProductInputs(file: File): Promise<ImportResult<ProductEconomicsInput>>;
```

Product input aliases must support at least:

```text
Артикул / article
SKU
Себестоимость / cost
Доступно / availableQty
Цена / price
Комиссия / commission
Объём / volumeLiters
```

- [ ] **Step 1: Write failing fixture tests including interval boundaries**
- [ ] **Step 2: Run tests and confirm failure**
- [ ] **Step 3: Implement adapters with diagnostics**
- [ ] **Step 4: Run full tests**
- [ ] **Step 5: Commit**

```bash
git add src/importers tests/importers tests/fixtures
git commit -m "feat: import tariffs and seller economics inputs"
```

### Task 7: Add versioned local persistence

**Files:**
- Create: `src/persistence/store.ts`
- Create: `src/persistence/indexeddb-store.ts`
- Create: `src/persistence/memory-store.ts`
- Test: `tests/persistence/store.test.ts`

**Interfaces:**

```ts
export interface LocalStore {
  get<T>(key: string): Promise<T | null>;
  set<T>(key: string, value: T): Promise<void>;
  remove(key: string): Promise<void>;
}

export const STORE_KEYS = {
  tariffs: 'v1:tariffs',
  tariffMeta: 'v1:tariff-meta',
  products: 'v1:products',
  clusterMappings: 'v1:cluster-mappings',
  economicsSettings: 'v1:economics-settings',
  optimizerSettings: 'v1:optimizer-settings'
} as const;
```

- [ ] **Step 1: Write contract tests against `MemoryStore`**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Implement `MemoryStore` and IndexedDB adapter with the same contract**
- [ ] **Step 4: Add test ensuring old key versions are not silently interpreted as current**
- [ ] **Step 5: Commit**

```bash
git add src/persistence tests/persistence
git commit -m "feat: persist slowly changing optimizer inputs locally"
```

**PR3 acceptance:** tariffs/product parameters can be imported and stored locally without embedding tariff data in source.

---

## PR4 — Demand, fulfillment and route analytics

### Task 8: Build destination-demand and fulfillment matrices

**Files:**
- Create: `src/analytics/demand-matrix.ts`
- Create: `src/analytics/fulfillment-matrix.ts`
- Test: `tests/analytics/demand-matrix.test.ts`
- Test: `tests/analytics/fulfillment-matrix.test.ts`

**Interfaces:**

```ts
export interface DemandCell {
  sku: Sku;
  destinationClusterId: ClusterId;
  quantity: number;
  orderCount: number;
}

export interface FulfillmentShare {
  sku: Sku;
  destinationClusterId: ClusterId;
  originClusterId: ClusterId;
  quantity: number;
  share: number;
}

export function buildDemandMatrix(orders: readonly OrderRecord[]): DemandCell[];
export function buildFulfillmentMatrix(orders: readonly OrderRecord[]): FulfillmentShare[];
export function buildOriginDonorMatrix(orders: readonly OrderRecord[]): FulfillmentShare[];
```

- [ ] **Step 1: Write hand-calculated Moscow/Kazan fixture test**

Synthetic orders:

```text
800 Moscow→Moscow
200 Kazan→Moscow
100 Kazan→Kazan
```

Expected:

```text
Moscow demand = 1000
Kazan demand = 100
Moscow local fulfillment share = 80%
Kazan origin local share = 100 / 300 = 33.33%
```

- [ ] **Step 2: Run tests and verify failure**
- [ ] **Step 3: Implement pure aggregators**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

```bash
git add src/analytics tests/analytics
git commit -m "feat: reconstruct demand and fulfillment matrices"
```

### Task 9: Add ISO-week route series

**Files:**
- Create: `src/analytics/weekly-series.ts`
- Test: `tests/analytics/weekly-series.test.ts`

**Interfaces:**

```ts
export interface WeeklyRoutePoint {
  week: string;
  sku: Sku;
  destinationClusterId: ClusterId;
  demandQty: number;
  localQty: number;
  localShare: number;
  originShares: Readonly<Record<ClusterId, number>>;
}

export function buildWeeklyRouteSeries(orders: readonly OrderRecord[]): WeeklyRoutePoint[];
```

- [ ] **Step 1: Write week-boundary and share tests**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Implement deterministic weekly aggregation**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

```bash
git add src/analytics/weekly-series.ts tests/analytics/weekly-series.test.ts
git commit -m "feat: add weekly fulfillment route history"
```

**PR4 acceptance:** the application can answer both “where was demand?” and “from where was that demand fulfilled?” without economics or stockout heuristics.

---

## PR5 — Probable stockout detector and clean route profiles

### Task 10: Implement deterministic stockout evidence detection

**Files:**
- Create: `src/analytics/stockout-detector.ts`
- Test: `tests/analytics/stockout-detector.test.ts`

**Interfaces:**

```ts
export interface StockoutConfig {
  minPriorLocalShare: number;
  minLocalShareDrop: number;
  minReplacementRise: number;
  minWeeklyDemand: number;
  demandRetentionFloor: number;
}

export const DEFAULT_STOCKOUT_CONFIG: StockoutConfig = {
  minPriorLocalShare: 0.60,
  minLocalShareDrop: 0.30,
  minReplacementRise: 0.20,
  minWeeklyDemand: 10,
  demandRetentionFloor: 0.60
};

export function detectProbableStockouts(
  series: readonly WeeklyRoutePoint[],
  config?: StockoutConfig
): StockoutSignal[];
```

- [ ] **Step 1: Write positive Moscow stockout fixture**

```text
week 1: Moscow demand 100, Moscow→Moscow 90%, Kazan→Moscow 5%
week 2: Moscow demand 95, Moscow→Moscow 20%, Kazan→Moscow 65%
```

Expected: a Moscow signal with at least `medium` confidence and Kazan listed as replacement origin.

- [ ] **Step 2: Write negative controls**

No signal when:

- demand collapses together with local fulfillment;
- sample is below `minWeeklyDemand`;
- local share was already low in baseline;
- external share does not materially rise.

- [ ] **Step 3: Run tests and verify failure**
- [ ] **Step 4: Implement evidence and confidence rules**

Confidence must be based on explicit evidence counts/magnitudes; no random or ML component.

- [ ] **Step 5: Run full suite**
- [ ] **Step 6: Commit**

```bash
git add src/analytics/stockout-detector.ts tests/analytics/stockout-detector.test.ts
git commit -m "feat: detect probable cluster stockouts from route substitution"
```

### Task 11: Build observed and clean route profiles with fallback

**Files:**
- Create: `src/analytics/route-profile.ts`
- Test: `tests/analytics/route-profile.test.ts`

**Interfaces:**

```ts
export type RouteProfileSource =
  | 'sku-origin-clean'
  | 'sku-origin-observed'
  | 'origin-all-skus'
  | 'global';

export interface RouteProfile {
  sku: Sku;
  originClusterId: ClusterId;
  destinationShares: Readonly<Record<ClusterId, number>>;
  source: RouteProfileSource;
  confidence: 'low' | 'medium' | 'high';
  sampleQty: number;
}

export function buildRouteProfile(input: {
  sku: Sku;
  originClusterId: ClusterId;
  orders: readonly OrderRecord[];
  stockoutSignals: readonly StockoutSignal[];
  minSkuOriginSample?: number;
}): RouteProfile;
```

- [ ] **Step 1: Test exclusion of high-confidence substitution weeks from clean SKU-origin profile**
- [ ] **Step 2: Test fallback order exactly as specified**
- [ ] **Step 3: Verify failure**
- [ ] **Step 4: Implement route profile selection**
- [ ] **Step 5: Run tests and commit**

```bash
git add src/analytics/route-profile.ts tests/analytics/route-profile.test.ts
git commit -m "feat: build stockout-aware route profiles"
```

**PR5 acceptance:** the Moscow/Kazan failure mode is surfaced as `Вероятный stockout`, with evidence; the warning does not mutate Ozon recommendation quantities.

---

## PR6 — Tariff engine, expected logistics, spreadsheet-parity unit economics

### Task 12: Build indexed tariff lookup

**Files:**
- Create: `src/economics/tariff-index.ts`
- Create: `src/economics/tariff-lookup.ts`
- Test: `tests/economics/tariff-lookup.test.ts`

**Interfaces:**

```ts
export interface TariffIndex {
  byRoute: ReadonlyMap<string, readonly TariffRow[]>;
}

export function buildTariffIndex(rows: readonly TariffRow[]): TariffIndex;
export function lookupTariff(index: TariffIndex, input: TariffLookupInput): TariffLookupResult;
```

- [ ] **Step 1: Write boundary tests for volume and optional price intervals**
- [ ] **Step 2: Test missing route returns `fee: null` with diagnostic code**
- [ ] **Step 3: Verify failure**
- [ ] **Step 4: Implement sorted route interval index and deterministic matching**
- [ ] **Step 5: Run tests and commit**

```bash
git add src/economics tests/economics
git commit -m "feat: add indexed Ozon tariff lookup"
```

### Task 13: Calculate expected route-weighted logistics

**Files:**
- Create: `src/economics/expected-logistics.ts`
- Test: `tests/economics/expected-logistics.test.ts`

**Interfaces:**

```ts
export interface ExpectedLogisticsResult {
  expectedFee: number | null;
  tariffCoverage: number;
  routeProfileSource: RouteProfileSource;
  confidence: 'low' | 'medium' | 'high';
  missingDestinations: ClusterId[];
}

export function calculateExpectedLogistics(input: {
  profile: RouteProfile;
  tariffIndex: TariffIndex;
  volumeLiters: number;
  price: number;
}): ExpectedLogisticsResult;
```

- [ ] **Step 1: Write weighted-average test**

Example: 80% local tariff 50 ₽ + 20% Moscow tariff 100 ₽ => 60 ₽ expected logistics.

- [ ] **Step 2: Test partial tariff coverage**
- [ ] **Step 3: Verify failure**
- [ ] **Step 4: Implement weighted calculation without renormalizing missing tariff share**

If any destination share lacks a tariff, coverage is below 1 and result is incomplete; do not pretend the known routes represent 100%.

- [ ] **Step 5: Run tests and commit**

```bash
git add src/economics/expected-logistics.ts tests/economics/expected-logistics.test.ts
git commit -m "feat: calculate expected intercluster logistics"
```

### Task 14: Reproduce spreadsheet unit economics

**Files:**
- Create: `src/economics/unit-economics.ts`
- Create: `tests/fixtures/unit-economics-golden.json`
- Test: `tests/economics/unit-economics.test.ts`

**Interfaces:**

```ts
export interface EconomicsSettings {
  acquiringRate: number;
  advertisingRate: number;
  taxRate: number;
  buyoutRate: number;
  fixedFboFee: number;
  minProfitPerUnit: number;
  minMarginRate: number;
  minRoi: number;
}

export interface UnitEconomicsInput {
  sku: Sku;
  placementClusterId: ClusterId;
  price: number;
  cost: number;
  commissionRate: number;
  expectedLogistics: number;
  settings: EconomicsSettings;
}

export function calculateUnitEconomics(input: UnitEconomicsInput): UnitEconomicsResult;
```

- [ ] **Step 1: Extract 5–10 sanitized golden rows from the working spreadsheet**

Store only calculation inputs/expected outputs necessary for regression; do not commit the original workbook unless explicitly approved.

- [ ] **Step 2: Write parity test with explicit tolerance**

```ts
expect(actual.profitPerUnit).toBeCloseTo(expected.profitPerUnit, 2);
expect(actual.marginRate).toBeCloseTo(expected.marginRate, 4);
expect(actual.roi).toBeCloseTo(expected.roi, 4);
```

- [ ] **Step 3: Run and verify failure**
- [ ] **Step 4: Implement formulas exactly as the spreadsheet, documenting order of operations and buyout treatment**
- [ ] **Step 5: Run golden tests plus full suite**
- [ ] **Step 6: Commit**

```bash
git add src/economics/unit-economics.ts tests/economics/unit-economics.test.ts tests/fixtures/unit-economics-golden.json
git commit -m "feat: reproduce spreadsheet unit economics"
```

**PR6 acceptance:** exact tariff matching is test-covered and golden spreadsheet rows match within stated tolerance.

---

## PR7 — Feasibility, candidate scoring and limited-stock optimizer

### Task 15: Derive cluster feasibility from warehouse restrictions

**Files:**
- Create: `src/supply/feasibility.ts`
- Test: `tests/supply/feasibility.test.ts`

**Interfaces:**

```ts
export function deriveSupplyFeasibility(
  sku: Sku,
  clusterId: ClusterId,
  restrictions: readonly WarehouseRestriction[]
): SupplyFeasibility;
```

- [ ] **Step 1: Test all warehouses blocked => cluster blocked**
- [ ] **Step 2: Test at least one eligible warehouse => cluster allowed**
- [ ] **Step 3: Test cap handling conservatively**

Until report semantics are proven, never sum ambiguous per-warehouse maxima as if independently additive. Expose a reason code when a conservative cap is used.

- [ ] **Step 4: Implement and run tests**
- [ ] **Step 5: Commit**

```bash
git add src/supply/feasibility.ts tests/supply/feasibility.test.ts
git commit -m "feat: derive FBO cluster supply feasibility"
```

### Task 16: Compose explainable cluster candidates

**Files:**
- Create: `src/supply/cluster-score.ts`
- Test: `tests/supply/cluster-score.test.ts`

**Interfaces:**

```ts
export interface OptimizerThresholds {
  minProfitPerUnit: number;
  minMarginRate: number;
  minRoi: number;
}

export function buildClusterCandidate(input: {
  recommendation: AvailabilityRecommendation;
  feasibility: SupplyFeasibility;
  economics: UnitEconomicsResult;
  stockoutSignal: StockoutSignal | null;
  routeConfidence: 'low' | 'medium' | 'high';
  thresholds: OptimizerThresholds;
}): ClusterCandidate;
```

- [ ] **Step 1: Test status-code composition**

Cover `SUPPLY_BLOCKED`, `NEGATIVE_ECONOMICS`, `LOW_ECONOMICS`, `PROBABLE_STOCKOUT_DISTORTION`, `INCOMPLETE_DATA`, and `OK`.

- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Implement status derivation without UI strings**
- [ ] **Step 4: Run tests and commit**

```bash
git add src/supply/cluster-score.ts tests/supply/cluster-score.test.ts
git commit -m "feat: compose explainable cluster candidates"
```

### Task 17: Implement deterministic limited-stock allocation

**Files:**
- Create: `src/supply/optimizer.ts`
- Test: `tests/supply/optimizer.test.ts`

**Interfaces:**

```ts
export interface AllocationLine {
  sku: Sku;
  clusterId: ClusterId;
  ozonRecommendedQty: number;
  allocatedQty: number;
  expectedProfitPerUnit: number;
  expectedProfit: number;
  reasonCodes: string[];
}

export interface AllocationPlan {
  sku: Sku;
  availableQty: number;
  allocatedQty: number;
  unallocatedQty: number;
  expectedProfit: number;
  lines: AllocationLine[];
}

export function optimizeSkuAllocation(input: {
  sku: Sku;
  availableQty: number;
  candidates: readonly ClusterCandidate[];
}): AllocationPlan;
```

- [ ] **Step 1: Write main limited-stock test**

Example:

```text
available = 200
Moscow: Ozon 120, profit 181
Kazan: Ozon 80, profit 149
Krasnodar: Ozon 100, profit 117
```

Expected allocation:

```text
Moscow 120
Kazan 80
Krasnodar 0
Total 200
```

- [ ] **Step 2: Add physical-cap and blocked-cluster tests**
- [ ] **Step 3: Add deterministic tie-break test**
- [ ] **Step 4: Add invariant/property tests**

For every generated test case assert:

```ts
allocatedQty <= availableQty
line.allocatedQty <= line.ozonRecommendedQty
line.allocatedQty <= feasibleQty
blocked candidates receive 0
expectedProfit === Σ(line qty × line profit/unit)
```

- [ ] **Step 5: Verify failure, implement greedy optimizer, rerun tests**
- [ ] **Step 6: Commit**

```bash
git add src/supply/optimizer.ts tests/supply/optimizer.test.ts
git commit -m "feat: optimize limited FBO stock allocation"
```

**PR7 acceptance:** optimizer never violates Ozon ceiling, warehouse feasibility/caps, available stock, or configured economic thresholds; output is deterministic and explainable.

---

## PR8 — Full workflow, UI, diagnostics and release hardening

### Task 18: Implement application state and composition pipeline

**Files:**
- Create: `src/app/state.ts`
- Create: `src/app/selectors.ts`
- Modify: `src/app/bootstrap.ts`
- Test: `tests/integration/pipeline.test.ts`

**Interfaces:**

```ts
export interface AppState {
  availability: AvailabilityRecommendation[];
  restrictions: WarehouseRestriction[];
  orders: OrderRecord[];
  tariffs: TariffRow[];
  productInputs: ProductEconomicsInput[];
  diagnostics: ImportDiagnostic[];
  clusterMappings: ReadonlyMap<string, string>;
  economicsSettings: EconomicsSettings;
  optimizerThresholds: OptimizerThresholds;
}

export function calculatePlans(state: AppState): AllocationPlan[];
```

- [ ] **Step 1: Write integration test from canonical fixtures through `calculatePlans`**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Compose analytics → stockout → route profile → tariffs → economics → feasibility → optimizer**
- [ ] **Step 4: Run integration and full suites**
- [ ] **Step 5: Commit**

```bash
git add src/app tests/integration
git commit -m "feat: compose end-to-end optimizer pipeline"
```

### Task 19: Build import/settings UI

**Files:**
- Create: `src/ui/shell.ts`
- Create: `src/ui/upload-view.ts`
- Create: `src/ui/diagnostics-view.ts`
- Create: `src/ui/components/file-card.ts`
- Create: `src/ui/components/editable-number.ts`
- Modify: `styles.css`
- Test: `tests/ui/upload-view.test.ts`

**Required behavior:**

- separate Operational Ozon Data and Economics groups;
- file name/date/row count/SKU count/status after import;
- manual product economics editing;
- manual cluster mapping for unresolved names;
- explicit stale operational-report metadata;
- errors remain visible without crashing the app.

- [ ] **Step 1: Write DOM test for required cards/statuses**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Implement small DOM components and upload view**
- [ ] **Step 4: Test and commit**

```bash
git add src/ui styles.css tests/ui
git commit -m "feat: add local report import and diagnostics UI"
```

### Task 20: Build dashboard, SKU diagnostics and optimized plan UI

**Files:**
- Create: `src/ui/dashboard-view.ts`
- Create: `src/ui/sku-view.ts`
- Create: `src/ui/plan-view.ts`
- Create: `src/ui/components/table.ts`
- Create: `src/ui/components/metric-card.ts`
- Create: `src/ui/components/status-badge.ts`
- Test: `tests/ui/dashboard-view.test.ts`
- Test: `tests/ui/sku-view.test.ts`

**Required visible information:**

Dashboard metrics:

```text
analyzed SKU
Ozon recommended units
seller available units
allocated units
expected profit
negative-economics recommendations
probable-stockout warnings
blocked routes
incomplete SKU
```

SKU detail must expose both projections:

```text
Destination view: who fulfilled Moscow demand?
Origin view: where did Kazan stock actually go?
```

Stockout warning must show evidence, e.g. local share before/after, replacement origins and demand retention.

- [ ] **Step 1: Write DOM tests for plan row explanation and stockout evidence**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Implement views using selectors only; no formulas in UI**
- [ ] **Step 4: Run tests and commit**

```bash
git add src/ui tests/ui
git commit -m "feat: add explainable supply plan and SKU diagnostics UI"
```

### Task 21: Wire persistence without hiding stale data

**Files:**
- Modify: `src/app/bootstrap.ts`
- Modify: `src/app/state.ts`
- Modify: `src/ui/upload-view.ts`
- Test: `tests/integration/persistence.test.ts`

**Required behavior:**

Persist tariffs, seller economics, settings and manual cluster mappings. Operational availability/restrictions/orders may be restored only if UI clearly labels their source and report/import date; the user must never mistake stale data for a fresh report.

- [ ] **Step 1: Write reload test**
- [ ] **Step 2: Verify failure**
- [ ] **Step 3: Wire `LocalStore` through bootstrap**
- [ ] **Step 4: Test and commit**

```bash
git add src/app src/ui tests/integration/persistence.test.ts
git commit -m "feat: restore local optimizer configuration safely"
```

### Task 22: Release hardening and offline smoke test

**Files:**
- Create: `tests/browser/offline-release.spec.ts`
- Create: `.github/workflows/ci.yml`
- Modify: `scripts/build.mjs`
- Modify: `README.md`

**Required behavior:**

- CI runs typecheck, unit/integration tests and production build.
- Browser smoke test opens built `dist/index.html` via a `file://` URL.
- No network request is required for normal operation.
- README documents exactly which reports to download and how to launch.

- [ ] **Step 1: Add failing offline browser smoke test**

The test opens `file://${absolutePath}/dist/index.html`, verifies the title and imports sanitized fixtures through the browser file inputs.

- [ ] **Step 2: Run and verify failure before final wiring**
- [ ] **Step 3: Fix bundle/resource paths until test passes without server**
- [ ] **Step 4: Add CI workflow**

CI commands:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

Run the browser smoke test on supported CI runners if Playwright is included; otherwise document it as a release gate executed locally and keep CI build/test mandatory.

- [ ] **Step 5: Final verification**

Run:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

Then manually disconnect network and open `dist/index.html` from disk. Import the fixture reports and verify a plan is produced.

- [ ] **Step 6: Commit**

```bash
git add .github README.md scripts tests/browser package.json package-lock.json
git commit -m "chore: harden offline MVP release"
```

**PR8 acceptance:** offline release completes the full user flow and every recommendation/exclusion can be explained from visible inputs and reason codes.

---

# Manual validation checkpoints using real seller data

These checks happen after automated tests; full raw reports remain outside git.

## Checkpoint A — after PR2

Load the three provided operational reports and record:

- accepted row counts;
- SKU counts;
- unknown cluster mappings;
- malformed row count.

No manual file editing is allowed before import.

## Checkpoint B — after PR4

Pick 3 SKUs and manually verify:

- demand quantity by delivery cluster;
- top fulfillment origins for Moscow/Kazan/one other cluster;
- reverse donor share for Kazan.

## Checkpoint C — after PR5

Manually inspect 5–10 `Вероятный stockout` signals against Ozon historical evidence where available. Record confirmed/not-confirmed outcomes outside the code path. Do not change the detector based on one anecdotal case; adjust thresholds only after a small validation set shows a consistent bias.

## Checkpoint D — after PR6

Compare 5–10 exact spreadsheet examples including local and intercluster routes. No optimizer work should merge until economics parity is accepted.

## Checkpoint E — after PR8

Use current real reports and compare:

1. Ozon recommendation totals;
2. app feasibility exclusions;
3. app economic exclusions;
4. limited-stock allocation;
5. expected profit;
6. stockout warnings and their evidence.

---

# Self-review against specification

- Offline/local-only runtime: PR1 + PR8.
- All required imports: PR2 + PR3.
- No hard-coded tariff matrix/master cluster list: PR3 + normalization.
- Destination-demand invariant: PR2 fixture guard + PR4 analytics.
- Bidirectional route analysis: PR4.
- Probable stockout, evidence and non-override rule: PR5.
- Stockout-aware route profile: PR5.
- Expected intercluster logistics: PR6.
- Spreadsheet regression oracle: PR6.
- Warehouse restrictions: PR7.
- Limited-stock max-profit optimization: PR7.
- Explainability/status codes: PR7 + PR8.
- Local persistence with stale-data visibility: PR3 + PR8.
- End-to-end user workflow: PR8.

No MVP requirement is intentionally deferred beyond PR8. Historical stock balances, API integration and automatic correction of Ozon recommendations remain explicitly post-MVP.
