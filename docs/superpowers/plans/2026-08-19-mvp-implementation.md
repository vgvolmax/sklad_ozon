# Ozon FBO Unit Economics & Supply Optimizer MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully local FBO planning application that imports real Ozon reports, separates demand from fulfillment, detects probable stockout substitution and recommendation distortion, reproduces the spreadsheet unit economics, compares relevant placements, and allocates limited stock within Ozon recommendation ceilings to maximize expected absolute profit.

**Architecture:** Functional core / imperative shell. Ozon-specific file quirks terminate at import adapters; downstream modules consume canonical TypeScript contracts. Development uses TypeScript and Node-based build/test tooling, while the release is a static offline bundle that runs from `file://` without Node, Python, backend, API, CDN, accounts, or network access.

**Tech Stack:** TypeScript, esbuild, Vitest, SheetJS (`xlsx`) with a malformed-dimension recovery path, Papa Parse, IndexedDB, vanilla DOM/CSS, Playwright for the final offline smoke test if practical in CI.

**Spec:** `docs/superpowers/specs/2026-08-19-ozon-fbo-unit-economics-optimizer-design.md`

## Global Constraints

- FBO only in MVP.
- No Ozon API, backend, cloud storage, accounts, or runtime server.
- Release must open from `file://` and must not require Node.js or Python.
- No runtime CDN dependencies.
- Demand is always attributed to the **delivery cluster**, never the dispatch cluster.
- Fulfillment route analytics use only fulfilled orders; cancelled and in-progress orders cannot enter actual-route shares.
- The current/incomplete week cannot be used as an ordinary stockout baseline/comparison week.
- `Вероятный stockout` is diagnostic evidence only and must not silently override Ozon recommendation quantities.
- A recommendation-distortion signal belongs to a recommended donor origin and is distinct from the stockout signal of the affected destination.
- Counterfactual placement may be calculated for zero-Ozon-recommendation clusters, but automatic MVP allocation remains capped by Ozon recommendation.
- Tariff matrix is user-loaded and locally persisted, not hard-coded.
- Cluster master data are derived from imported sources; ambiguous mappings require explicit manual mapping.
- Business formulas do not read directly from DOM or IndexedDB.
- Missing tariff/economics inputs are blockers, never zero.
- Buyer PII and irrelevant raw CSV fields never enter canonical state or IndexedDB.
- Full seller-sensitive raw reports are not committed; tests use sanitized fixtures.

---

# File map locked for MVP

```text
index.html
styles.css
package.json
tsconfig.json
vitest.config.ts
scripts/build.mjs
scripts/copy-release-assets.mjs

src/app/bootstrap.ts
src/app/state.ts
src/app/selectors.ts

src/domain/models.ts
src/domain/result.ts
src/domain/invariants.ts
src/domain/report-meta.ts

src/importers/workbook.ts
src/importers/csv.ts
src/importers/availability.ts
src/importers/restrictions.ts
src/importers/orders.ts
src/importers/tariffs.ts
src/importers/products.ts
src/importers/import-diagnostics.ts

src/normalization/clusters.ts
src/normalization/sku.ts
src/normalization/numbers.ts
src/normalization/dates.ts
src/normalization/order-status.ts

src/analytics/order-populations.ts
src/analytics/demand-matrix.ts
src/analytics/fulfillment-matrix.ts
src/analytics/weekly-series.ts
src/analytics/stockout-detector.ts
src/analytics/recommendation-distortion.ts
src/analytics/route-profile.ts

src/economics/tariff-index.ts
src/economics/tariff-lookup.ts
src/economics/expected-logistics.ts
src/economics/unit-economics.ts

src/supply/feasibility.ts
src/supply/placement-assessment.ts
src/supply/cluster-candidate.ts
src/supply/optimizer.ts

src/persistence/store.ts
src/persistence/indexeddb-store.ts
src/persistence/memory-store.ts

src/ui/shell.ts
src/ui/upload-view.ts
src/ui/dashboard-view.ts
src/ui/sku-view.ts
src/ui/plan-view.ts
src/ui/diagnostics-view.ts
src/ui/components/*.ts

tests/fixtures/*
tests/domain/*
tests/normalization/*
tests/importers/*
tests/analytics/*
tests/economics/*
tests/supply/*
tests/persistence/*
tests/integration/*
tests/browser/*
```

---

# PR sequence

| PR | Deliverable | Merge gate |
|---|---|---|
| PR1 | Offline foundation + canonical contracts | static release shell; lifecycle/report contracts compile |
| PR2 | Robust Ozon operational imports + lifecycle classification | real-schema fixtures, malformed-dimension XLSX and PII boundary pass |
| PR3 | Tariff/product imports + persistence | existing multi-sheet unit workbook imports tariff sheet; settings survive reload |
| PR4 | Demand, fulfilled-route and weekly analytics | cancelled/in-progress exclusion + hand-calculated route shares pass |
| PR5 | Probable stockout + recommendation distortion + clean profiles | Moscow stockout correctly flags Kazan donor recommendation without rewriting Ozon qty |
| PR6 | Tariff engine + expected logistics + spreadsheet parity | golden Excel cases match including taxes/VAT/co-invest |
| PR7 | Feasibility + placement assessments + limited-stock optimizer | counterfactual comparison works; optimizer respects all ceilings |
| PR8 | Complete UI + explainability + offline release hardening | real reports → explainable optimized plan from `file://` |

Each PR is merged and reviewed before the next begins.

---

# PR1 — Offline foundation and canonical contracts

## Task 1: Static offline application skeleton

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

**Produces:** `npm run build` → `dist/index.html`, `dist/app.js`, `dist/styles.css`.

- [ ] **Step 1: Write failing offline-shell test**

```ts
import { expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';

it('builds a classic-script offline shell', () => {
  expect(existsSync('dist/index.html')).toBe(true);
  expect(existsSync('dist/app.js')).toBe(true);
  const html = readFileSync('dist/index.html', 'utf8');
  expect(html).toContain('<script src="./app.js"></script>');
  expect(html).not.toContain('type="module"');
  expect(html).not.toMatch(/https?:\/\//);
});
```

- [ ] **Step 2: Verify red state**

Run: `npm test -- tests/integration/offline-shell.test.ts`

Expected: FAIL because build artifacts do not exist.

- [ ] **Step 3: Implement build as browser IIFE**

`package.json` scripts:

```json
{
  "scripts": {
    "build": "node scripts/build.mjs",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

`build.mjs` bundles `src/app/bootstrap.ts` as an IIFE and copies local assets only.

- [ ] **Step 4: Add minimal bootstrap**

```ts
const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('APP_ROOT_MISSING');
root.textContent = 'Ozon FBO Supply Optimizer';
```

- [ ] **Step 5: Verify**

Run:

```bash
npm run typecheck
npm run build
npm test
```

Expected: all exit 0.

- [ ] **Step 6: Commit**

```bash
git add package.json tsconfig.json vitest.config.ts index.html styles.css scripts src/app/bootstrap.ts tests/integration/offline-shell.test.ts
git commit -m "build: add offline static application foundation"
```

## Task 2: Canonical models, report metadata and invariants

**Files:**
- Create: `src/domain/models.ts`
- Create: `src/domain/report-meta.ts`
- Create: `src/domain/result.ts`
- Create: `src/domain/invariants.ts`
- Test: `tests/domain/models.test.ts`

**Produces:** exact canonical contracts used by every later PR.

- [ ] **Step 1: Write failing invariant tests**

```ts
import { expect, it } from 'vitest';
import { assertNonNegative, assertRate } from '../../src/domain/invariants';

it('rejects negative quantity', () => {
  expect(() => assertNonNegative(-1, 'quantity')).toThrow('quantity');
});

it('accepts decimal rates', () => {
  expect(assertRate(0.25, 'commissionRate')).toBe(0.25);
});
```

- [ ] **Step 2: Define canonical lifecycle/report contracts**

```ts
export type OrderLifecycle = 'fulfilled' | 'in_progress' | 'cancelled' | 'unknown';

export interface ReportMeta {
  sourceName: string;
  importedAt: string;
  reportGeneratedAt: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  recommendationHorizonDays: number | null;
}

export interface OrderRecord {
  acceptedAt: string;
  plannedShipAt: string | null;
  handedToDeliveryAt: string | null;
  deliveredAt: string | null;
  lifecycle: OrderLifecycle;
  rawStatus: string;
  sku: string;
  article: string;
  name: string;
  quantity: number;
  sellerPrice: number;
  originClusterId: string;
  destinationClusterId: string;
  originWarehouse: string | null;
  volumetricWeightKg: number | null;
}
```

Also define `ProductRef`, `AvailabilityRecommendation`, `WarehouseRestriction`, `ProductEconomicsInput`, `TariffRow`, `ImportDiagnostic`, `ImportResult<T>` exactly as the spec.

- [ ] **Step 3: Implement invariants**

```ts
export function assertNonNegative(value: number, field: string): number;
export function assertRate(value: number, field: string): number;
export function assertNonEmpty(value: string, field: string): string;
```

- [ ] **Step 4: Verify**

Run: `npm run typecheck && npm test`

- [ ] **Step 5: Commit**

```bash
git add src/domain tests/domain
git commit -m "feat: define canonical optimizer contracts"
```

**PR1 acceptance:** offline shell builds; canonical contracts include report metadata and order lifecycle; no report-shaped fields leak into domain interfaces.

---

# PR2 — Robust Ozon operational imports and lifecycle classification

## Task 3: Normalization primitives and order status mapping

**Files:**
- Create: `src/normalization/numbers.ts`
- Create: `src/normalization/dates.ts`
- Create: `src/normalization/sku.ts`
- Create: `src/normalization/clusters.ts`
- Create: `src/normalization/order-status.ts`
- Test: `tests/normalization/*.test.ts`

**Interfaces:**

```ts
export function parseRuNumber(value: unknown): number | null;
export function parseIsoDateTime(value: unknown): string | null;
export function toIsoWeek(dateTime: string): string;
export function normalizeSku(value: unknown): string | null;
export function normalizeArticle(value: unknown): string | null;
export function normalizeClusterName(rawName: string): string;
export function resolveClusterId(rawName: string, manual: ReadonlyMap<string, string>): string;
export function classifyOrderStatus(rawStatus: string): OrderLifecycle;
```

- [ ] **Step 1: Write table-driven tests**

Required order status cases:

```ts
expect(classifyOrderStatus('Доставлен')).toBe('fulfilled');
expect(classifyOrderStatus('Отменён')).toBe('cancelled');
expect(classifyOrderStatus('Доставляется')).toBe('in_progress');
expect(classifyOrderStatus('Ожидает отгрузки')).toBe('in_progress');
expect(classifyOrderStatus('Ожидает сборки')).toBe('in_progress');
```

Also cover Russian decimal commas, NBSP, BOM-adjacent text, empty values and harmless cluster formatting variants.

- [ ] **Step 2: Verify red state**

Run: `npm test -- tests/normalization`

- [ ] **Step 3: Implement deterministic normalizers**

Unknown statuses map to `unknown` and emit an importer warning later; never guess them into fulfilled.

- [ ] **Step 4: Verify and commit**

```bash
npm test
git add src/normalization tests/normalization
git commit -m "feat: normalize Ozon values and order lifecycle"
```

## Task 4: XLSX/CSV readers with malformed-dimension recovery

**Files:**
- Create: `src/importers/workbook.ts`
- Create: `src/importers/csv.ts`
- Create: `src/importers/import-diagnostics.ts`
- Create: `tests/fixtures/malformed-dimension.xlsx`
- Test: `tests/importers/workbook.test.ts`
- Test: `tests/importers/csv.test.ts`

**Interfaces:**

```ts
export interface TabularSheet {
  name: string;
  rows: Record<string, unknown>[];
  diagnostics: ImportDiagnostic[];
}

export async function readWorkbook(file: File): Promise<TabularSheet[]>;
export async function readCsv(file: File): Promise<Record<string, unknown>[]>;
```

- [ ] **Step 1: Create regression fixture**

The XLSX fixture must contain multiple populated rows while worksheet XML declares `dimension=A1`.

- [ ] **Step 2: Write failing test proving all rows are read**

```ts
it('recovers populated rows when worksheet dimension incorrectly says A1', async () => {
  const sheets = await readWorkbook(fixtureFile('malformed-dimension.xlsx'));
  expect(sheets[0].rows).toHaveLength(3);
  expect(sheets[0].diagnostics.some(d => d.code === 'WORKSHEET_DIMENSION_REPAIRED')).toBe(true);
});
```

- [ ] **Step 3: Add CSV tests**

Cover UTF-8 BOM, quoted commas/semicolons and Cyrillic headers.

- [ ] **Step 4: Implement readers**

Do not trust the worksheet declared range when it conflicts with populated cells. Recompute the effective range from actual populated cell addresses before row conversion.

- [ ] **Step 5: Verify and commit**

```bash
npm test -- tests/importers/workbook.test.ts tests/importers/csv.test.ts
git add src/importers tests/importers tests/fixtures/malformed-dimension.xlsx package.json package-lock.json
git commit -m "feat: read real Ozon xlsx and csv exports robustly"
```

## Task 5: Availability, restrictions and orders adapters with PII boundary

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

- [ ] **Step 1: Guard central demand invariant**

For synthetic `Казань → Москва`:

```ts
expect(record.originClusterId).toBe('kazan');
expect(record.destinationClusterId).toBe('moscow');
```

- [ ] **Step 2: Guard lifecycle fields**

```ts
expect(delivered.lifecycle).toBe('fulfilled');
expect(cancelled.lifecycle).toBe('cancelled');
expect(inProgress.lifecycle).toBe('in_progress');
```

- [ ] **Step 3: Guard PII exclusion**

Input fixture contains `Имя покупателя`, `Адрес покупателя`, `ИНН`.

```ts
const serialized = JSON.stringify(result.records);
expect(serialized).not.toContain('Имя покупателя');
expect(serialized).not.toContain('Адрес покупателя');
expect(serialized).not.toContain('ИНН');
expect(serialized).not.toContain('Иван Иванов');
```

- [ ] **Step 4: Implement source-specific aliases and metadata extraction**

Availability importer extracts `daysWithoutStock`; orders importer extracts accepted/planned/handover/delivery dates and status; all adapters populate `ReportMeta`.

- [ ] **Step 5: Verify with sanitized fixtures and current real files outside git**

Run: `npm test -- tests/importers`

Manual gate: load the three provided files without preprocessing and record accepted rows/SKUs/diagnostics.

- [ ] **Step 6: Commit**

```bash
git add src/importers tests/importers tests/fixtures
git commit -m "feat: import Ozon operational reports safely"
```

**PR2 acceptance:** real-format Ozon files import without preprocessing; malformed worksheet ranges are recovered; statuses are classified; PII is discarded; report dates are explicit.

---

# PR3 — Tariffs, product economics and local persistence

## Task 6: Multi-sheet tariff/workbook importer

**Files:**
- Create: `src/importers/tariffs.ts`
- Create: `src/importers/products.ts`
- Create: `tests/fixtures/unit-workbook-minimal.xlsx`
- Test: `tests/importers/tariffs.test.ts`
- Test: `tests/importers/products.test.ts`

**Interfaces:**

```ts
export async function importTariffs(file: File, mappings: ReadonlyMap<string, string>): Promise<ImportResult<TariffRow>>;
export async function importProductInputs(file: File): Promise<ImportResult<ProductEconomicsInput>>;
```

- [ ] **Step 1: Write failing tariff-sheet detection test**

Fixture has three sheets and the tariff sheet is not first. Detect by required header signature rather than exact sheet index.

- [ ] **Step 2: Test product aliases**

Support:

```text
Артикул / article
SKU
Себестоимость / cost
Доступно / availableQty
Цена / price
Комиссия / commission
Объём / volumeLiters
```

- [ ] **Step 3: Test interval boundaries and cluster normalization**

- [ ] **Step 4: Implement importer**

The existing unit-economics workbook must be accepted as a tariff source. Recognizable product parameters from its calculation sheet may be imported as editable initial values.

- [ ] **Step 5: Verify and commit**

```bash
npm test -- tests/importers/tariffs.test.ts tests/importers/products.test.ts
git add src/importers tests/importers tests/fixtures/unit-workbook-minimal.xlsx
git commit -m "feat: import tariffs and product economics from workbooks"
```

## Task 7: Versioned local persistence

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
  optimizerThresholds: 'v1:optimizer-thresholds'
} as const;
```

- [ ] **Step 1: Write MemoryStore contract tests**
- [ ] **Step 2: Add version-isolation test**
- [ ] **Step 3: Add test that raw order rows/PII are never persisted**
- [ ] **Step 4: Implement IndexedDB adapter**
- [ ] **Step 5: Verify and commit**

```bash
npm test -- tests/persistence
git add src/persistence tests/persistence
git commit -m "feat: persist slowly changing optimizer inputs"
```

**PR3 acceptance:** tariffs/product inputs/settings survive reload; no tariff matrix is hard-coded; raw customer rows are not persisted.

---

# PR4 — Demand, fulfillment and completed-week route analytics

## Task 8: Build explicit order populations

**Files:**
- Create: `src/analytics/order-populations.ts`
- Test: `tests/analytics/order-populations.test.ts`

**Interfaces:**

```ts
export interface OrderPopulations {
  netDemand: OrderRecord[];
  fulfilledRoutes: OrderRecord[];
}

export function buildOrderPopulations(orders: readonly OrderRecord[]): OrderPopulations;
```

- [ ] **Step 1: Write lifecycle population test**

Fixture contains fulfilled, cancelled and in-progress orders.

Expected:

```ts
expect(pop.netDemand.map(x => x.lifecycle)).toEqual(['fulfilled', 'in_progress']);
expect(pop.fulfilledRoutes.every(x => x.lifecycle === 'fulfilled')).toBe(true);
```

- [ ] **Step 2: Verify red state**
- [ ] **Step 3: Implement explicit filters**
- [ ] **Step 4: Verify and commit**

```bash
npm test -- tests/analytics/order-populations.test.ts
git add src/analytics/order-populations.ts tests/analytics/order-populations.test.ts
git commit -m "feat: separate demand from fulfilled route observations"
```

## Task 9: Demand and fulfillment matrices

**Files:**
- Create: `src/analytics/demand-matrix.ts`
- Create: `src/analytics/fulfillment-matrix.ts`
- Test: `tests/analytics/demand-matrix.test.ts`
- Test: `tests/analytics/fulfillment-matrix.test.ts`

**Interfaces:**

```ts
export function buildDemandMatrix(netDemand: readonly OrderRecord[]): DemandCell[];
export function buildFulfillmentMatrix(fulfilledRoutes: readonly OrderRecord[]): FulfillmentShare[];
export function buildOriginDonorMatrix(fulfilledRoutes: readonly OrderRecord[]): FulfillmentShare[];
```

- [ ] **Step 1: Write Moscow/Kazan fixture**

```text
800 fulfilled Moscow→Moscow
200 fulfilled Kazan→Moscow
100 fulfilled Kazan→Kazan
100 cancelled Kazan→Moscow
```

Expected fulfilled-route analytics:

```text
Moscow fulfilled demand = 1000, not 1100
Kazan fulfilled demand = 100
Moscow local share = 80%
Kazan origin local share = 33.33%
```

- [ ] **Step 2: Verify red state**
- [ ] **Step 3: Implement pure aggregators**
- [ ] **Step 4: Verify and commit**

```bash
npm test -- tests/analytics/demand-matrix.test.ts tests/analytics/fulfillment-matrix.test.ts
git add src/analytics tests/analytics
git commit -m "feat: reconstruct destination demand and fulfillment routes"
```

## Task 10: Completed-week route series

**Files:**
- Create: `src/analytics/weekly-series.ts`
- Test: `tests/analytics/weekly-series.test.ts`

**Interfaces:**

```ts
export interface WeeklyRoutePoint {
  week: string;
  sku: string;
  destinationClusterId: string;
  fulfilledQty: number;
  localQty: number;
  localShare: number;
  originShares: Readonly<Record<string, number>>;
  completed: boolean;
}

export function buildWeeklyRouteSeries(input: {
  fulfilledRoutes: readonly OrderRecord[];
  now: string;
}): WeeklyRoutePoint[];
```

- [ ] **Step 1: Write ISO-week boundary test**
- [ ] **Step 2: Write current-week exclusion marker test**

Current ISO week must return `completed: false` and stockout code later must ignore it.

- [ ] **Step 3: Implement**
- [ ] **Step 4: Verify and commit**

```bash
npm test -- tests/analytics/weekly-series.test.ts
git add src/analytics/weekly-series.ts tests/analytics/weekly-series.test.ts
git commit -m "feat: build completed weekly fulfillment history"
```

**PR4 acceptance:** the app answers where demand arose and where fulfilled stock came from; cancelled/in-progress orders cannot contaminate actual-route shares; current week is visibly incomplete.

---

# PR5 — Probable stockout, recommendation distortion and clean route profiles

## Task 11: Probable stockout evidence detector

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

export function detectProbableStockouts(input: {
  series: readonly WeeklyRoutePoint[];
  availability: readonly AvailabilityRecommendation[];
  config?: StockoutConfig;
}): StockoutSignal[];
```

- [ ] **Step 1: Positive Moscow/Kazan fixture**

```text
week 1 completed: Moscow demand 100, local 90%, Kazan 5%
week 2 completed: Moscow demand 95, local 20%, Kazan 65%
availability: Moscow daysWithoutStock > 0
```

Expected: Moscow stockout signal, Kazan replacement origin, corroboration=`supports`.

- [ ] **Step 2: Negative controls**

No signal when:

- demand collapses;
- sample is insufficient;
- local baseline was already low;
- no donor rises;
- only the current incomplete week changes.

- [ ] **Step 3: Verify red state**
- [ ] **Step 4: Implement deterministic evidence/confidence rules**

Current availability may corroborate confidence but must not fabricate a historical zero-stock date.

- [ ] **Step 5: Verify and commit**

```bash
npm test -- tests/analytics/stockout-detector.test.ts
git add src/analytics/stockout-detector.ts tests/analytics/stockout-detector.test.ts
git commit -m "feat: detect probable destination stockouts"
```

## Task 12: Recommendation distortion from donor behavior

**Files:**
- Create: `src/analytics/recommendation-distortion.ts`
- Test: `tests/analytics/recommendation-distortion.test.ts`

**Interfaces:**

```ts
export interface RecommendationDistortionSignal {
  sku: string;
  recommendedClusterId: string;
  confidence: 'low' | 'medium' | 'high';
  affectedDestinations: Array<{
    destinationClusterId: string;
    stockoutConfidence: 'low' | 'medium' | 'high';
    donorShareAfter: number;
    donorShareIncrease: number;
  }>;
  explanationCodes: string[];
}

export function detectRecommendationDistortion(input: {
  recommendations: readonly AvailabilityRecommendation[];
  stockouts: readonly StockoutSignal[];
}): RecommendationDistortionSignal[];
```

- [ ] **Step 1: Write core cross-cluster test**

Given Moscow stockout with Kazan replacement share rising 5%→65% and Ozon recommending Kazan +150, expect a distortion signal whose `recommendedClusterId === 'kazan'` and affected destination includes Moscow.

- [ ] **Step 2: Add negative control**

No Kazan distortion when Kazan was not a material replacement origin.

- [ ] **Step 3: Implement and verify**

Run: `npm test -- tests/analytics/recommendation-distortion.test.ts`

- [ ] **Step 4: Commit**

```bash
git add src/analytics/recommendation-distortion.ts tests/analytics/recommendation-distortion.test.ts
git commit -m "feat: flag donor-driven recommendation distortion"
```

## Task 13: Observed and clean route profiles

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
  sku: string;
  originClusterId: string;
  destinationShares: Readonly<Record<string, number>>;
  source: RouteProfileSource;
  confidence: 'low' | 'medium' | 'high';
  sampleQty: number;
}

export function buildRouteProfile(input: {
  sku: string;
  originClusterId: string;
  fulfilledRoutes: readonly OrderRecord[];
  stockoutSignals: readonly StockoutSignal[];
  minSkuOriginSample?: number;
}): RouteProfile;
```

- [ ] **Step 1: Test high-confidence substitution weeks are excluded from clean profile**
- [ ] **Step 2: Test exact fallback order**
- [ ] **Step 3: Test cancelled/in-progress orders cannot enter any profile**
- [ ] **Step 4: Implement, verify and commit**

```bash
npm test -- tests/analytics/route-profile.test.ts
git add src/analytics/route-profile.ts tests/analytics/route-profile.test.ts
git commit -m "feat: build stockout-aware route profiles"
```

**PR5 acceptance:** Moscow stockout is a destination signal; Kazan donor recommendation gets a separate distortion signal; no Ozon quantity is mutated; clean logistics profiles remove high-confidence substitution noise.

---

# PR6 — Tariff engine, expected logistics and spreadsheet-parity economics

## Task 14: Indexed tariff lookup

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

- [ ] **Step 1: Test volume and price interval boundaries**
- [ ] **Step 2: Test missing route returns `fee:null` with diagnostic**
- [ ] **Step 3: Implement deterministic sorted lookup**
- [ ] **Step 4: Verify and commit**

```bash
npm test -- tests/economics/tariff-lookup.test.ts
git add src/economics/tariff-index.ts src/economics/tariff-lookup.ts tests/economics/tariff-lookup.test.ts
git commit -m "feat: add indexed Ozon tariff lookup"
```

## Task 15: Expected route-weighted logistics

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
  missingDestinations: string[];
}

export function calculateExpectedLogistics(input: {
  profile: RouteProfile;
  tariffIndex: TariffIndex;
  volumeLiters: number;
  price: number;
}): ExpectedLogisticsResult;
```

- [ ] **Step 1: Weighted average test**

80% × 50 ₽ + 20% × 100 ₽ = 60 ₽.

- [ ] **Step 2: Partial coverage test**

Missing 20% route must produce coverage 0.8 and incomplete result; known routes are not renormalized to 100%.

- [ ] **Step 3: Implement, verify and commit**

```bash
npm test -- tests/economics/expected-logistics.test.ts
git add src/economics/expected-logistics.ts tests/economics/expected-logistics.test.ts
git commit -m "feat: calculate expected intercluster logistics"
```

## Task 16: Spreadsheet-parity unit economics

**Files:**
- Create: `src/economics/unit-economics.ts`
- Create: `tests/fixtures/unit-economics-golden.json`
- Test: `tests/economics/unit-economics.test.ts`

**Interfaces:**

```ts
export type TaxSystem = 'usn_income' | 'usn_income_minus_expenses' | 'osno' | 'manual';

export interface EconomicsSettings {
  acquiringRate: number;
  advertisingRate: number;
  buyoutRate: number;
  fixedFboFee: number;
  taxSystem: TaxSystem;
  incomeTaxRate: number;
  vatRate: number;
  coInvestRate: number;
}

export interface UnitEconomicsInput {
  sku: string;
  placementClusterId: string;
  price: number;
  cost: number;
  commissionRate: number;
  expectedLogistics: number;
  settings: EconomicsSettings;
}

export function calculateUnitEconomics(input: UnitEconomicsInput): UnitEconomicsResult;
```

- [ ] **Step 1: Extract 5–10 sanitized golden cases from the working spreadsheet**

Cases must collectively cover local/intercluster logistics, commission, acquiring, advertising/services, buyout, tax system, VAT if active, co-invest if active, cost, profit, margin and ROI.

- [ ] **Step 2: Encode failing parity assertions**

```ts
expect(actual.profitPerUnit).toBeCloseTo(expected.profitPerUnit, 2);
expect(actual.marginRate).toBeCloseTo(expected.marginRate, 4);
expect(actual.roi).toBeCloseTo(expected.roi, 4);
```

Also assert component amounts (`commission`, `tax`, `vat`, `coInvest`) when present in the golden row.

- [ ] **Step 3: Verify red state**
- [ ] **Step 4: Implement spreadsheet order of operations exactly**

Golden values are authoritative. Do not simplify the tax base or buyout/co-invest treatment merely because another formula seems more conventional.

- [ ] **Step 5: Verify full suite and commit**

```bash
npm test -- tests/economics
npm test
git add src/economics/unit-economics.ts tests/economics/unit-economics.test.ts tests/fixtures/unit-economics-golden.json
git commit -m "feat: reproduce spreadsheet unit economics"
```

**PR6 acceptance:** tariff matching and expected logistics are explicit; spreadsheet economics match golden cases within tolerance; optimizer thresholds are not embedded in economics settings.

---

# PR7 — Feasibility, placement assessment and limited-stock optimization

## Task 17: Cluster feasibility from warehouse restrictions

**Files:**
- Create: `src/supply/feasibility.ts`
- Test: `tests/supply/feasibility.test.ts`

**Interfaces:**

```ts
export function deriveSupplyFeasibility(
  sku: string,
  clusterId: string,
  restrictions: readonly WarehouseRestriction[]
): SupplyFeasibility;
```

- [ ] **Step 1: Test all warehouses blocked → cluster blocked**
- [ ] **Step 2: Test one eligible warehouse → allowed**
- [ ] **Step 3: Test ambiguous per-warehouse caps use conservative interpretation and reason code**
- [ ] **Step 4: Implement, verify and commit**

```bash
npm test -- tests/supply/feasibility.test.ts
git add src/supply/feasibility.ts tests/supply/feasibility.test.ts
git commit -m "feat: derive FBO cluster feasibility"
```

## Task 18: Placement assessments including counterfactual clusters

**Files:**
- Create: `src/supply/placement-assessment.ts`
- Test: `tests/supply/placement-assessment.test.ts`

**Interfaces:**

```ts
export interface PlacementAssessment {
  sku: string;
  clusterId: string;
  ozonRecommendedQty: number;
  feasibility: SupplyFeasibility;
  economics: UnitEconomicsResult;
  distortionSignal: RecommendationDistortionSignal | null;
  routeConfidence: 'low' | 'medium' | 'high';
  statusCodes: string[];
}

export function buildPlacementAssessments(input: {
  sku: string;
  recommendations: readonly AvailabilityRecommendation[];
  demandClusters: readonly string[];
  stockoutSignals: readonly StockoutSignal[];
  distortionSignals: readonly RecommendationDistortionSignal[];
  evaluateCluster: (clusterId: string) => Omit<PlacementAssessment, 'sku' | 'clusterId' | 'ozonRecommendedQty' | 'distortionSignal'>;
}): PlacementAssessment[];
```

- [ ] **Step 1: Write core counterfactual test**

Ozon recommends Kazan +150 and Moscow 0. Moscow has probable stockout and Kazan is donor. Expected assessments include both Kazan and Moscow; Moscow row has `ozonRecommendedQty:0` and `COUNTERFACTUAL_ONLY`.

- [ ] **Step 2: Verify assessment does not allocate anything**

This module only evaluates; it does not change Ozon ceilings.

- [ ] **Step 3: Implement, verify and commit**

```bash
npm test -- tests/supply/placement-assessment.test.ts
git add src/supply/placement-assessment.ts tests/supply/placement-assessment.test.ts
git commit -m "feat: compare recommended and counterfactual placements"
```

## Task 19: Optimization candidates and thresholds

**Files:**
- Create: `src/supply/cluster-candidate.ts`
- Test: `tests/supply/cluster-candidate.test.ts`

**Interfaces:**

```ts
export interface OptimizerThresholds {
  minProfitPerUnit: number;
  minMarginRate: number;
  minRoi: number;
}

export interface ClusterCandidate extends PlacementAssessment {
  feasibleQty: number;
  optimizationEligible: boolean;
}

export function buildClusterCandidate(
  assessment: PlacementAssessment,
  thresholds: OptimizerThresholds
): ClusterCandidate;
```

- [ ] **Step 1: Test status composition**

Cover `SUPPLY_BLOCKED`, `NEGATIVE_ECONOMICS`, `LOW_ECONOMICS`, `PROBABLE_RECOMMENDATION_DISTORTION`, `INCOMPLETE_DATA`, `INCOMPLETE_TARIFF_COVERAGE`, `LOW_ROUTE_CONFIDENCE`, `COUNTERFACTUAL_ONLY`, `OK`.

- [ ] **Step 2: Assert zero Ozon recommendation is never optimization-eligible**
- [ ] **Step 3: Implement and verify**
- [ ] **Step 4: Commit**

```bash
git add src/supply/cluster-candidate.ts tests/supply/cluster-candidate.test.ts
git commit -m "feat: compose explainable optimization candidates"
```

## Task 20: Deterministic limited-stock allocator

**Files:**
- Create: `src/supply/optimizer.ts`
- Test: `tests/supply/optimizer.test.ts`

**Interfaces:**

```ts
export interface AllocationLine {
  sku: string;
  clusterId: string;
  ozonRecommendedQty: number;
  allocatedQty: number;
  expectedProfitPerUnit: number;
  expectedProfit: number;
  reasonCodes: string[];
}

export interface AllocationPlan {
  sku: string;
  availableQty: number;
  allocatedQty: number;
  unallocatedQty: number;
  expectedProfit: number;
  lines: AllocationLine[];
}

export function optimizeSkuAllocation(input: {
  sku: string;
  availableQty: number;
  candidates: readonly ClusterCandidate[];
}): AllocationPlan;
```

- [ ] **Step 1: Main max-profit case**

```text
available 200
Moscow Ozon 120 profit 181
Kazan Ozon 80 profit 149
Krasnodar Ozon 100 profit 117
```

Expected: Moscow 120, Kazan 80, Krasnodar 0.

- [ ] **Step 2: Counterfactual ceiling test**

Moscow counterfactual with Ozon 0 and profit 300 must still allocate 0 in MVP.

- [ ] **Step 3: Physical cap / blocked / incomplete tests**
- [ ] **Step 4: Deterministic tie-break test**
- [ ] **Step 5: Property invariants**

```ts
allocatedQty <= availableQty
line.allocatedQty <= line.ozonRecommendedQty
line.allocatedQty <= line.feasibleQty
counterfactual-only receives 0
expectedProfit === sum(line.allocatedQty * line.expectedProfitPerUnit)
```

- [ ] **Step 6: Implement greedy allocator, verify and commit**

```bash
npm test -- tests/supply/optimizer.test.ts
git add src/supply/optimizer.ts tests/supply/optimizer.test.ts
git commit -m "feat: optimize limited FBO stock allocation"
```

**PR7 acceptance:** all relevant clusters can be assessed, including Moscow-vs-Kazan counterfactuals; automatic allocation remains strictly bounded by Ozon recommendations, feasibility and available stock.

---

# PR8 — End-to-end workflow, UI and offline release

## Task 21: Compose application state and calculation pipeline

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
  reportMeta: Record<string, ReportMeta>;
  diagnostics: ImportDiagnostic[];
  clusterMappings: ReadonlyMap<string, string>;
  economicsSettings: EconomicsSettings;
  optimizerThresholds: OptimizerThresholds;
}

export interface SkuAnalysis {
  sku: string;
  stockouts: StockoutSignal[];
  distortionSignals: RecommendationDistortionSignal[];
  placements: PlacementAssessment[];
  plan: AllocationPlan;
}

export function calculateAnalyses(state: AppState): SkuAnalysis[];
```

- [ ] **Step 1: Write end-to-end canonical fixture test**

Expected pipeline:

```text
orders
→ lifecycle populations
→ demand + fulfilled routes
→ completed weeks
→ probable stockout
→ recommendation distortion
→ clean route profiles
→ expected logistics
→ unit economics
→ feasibility
→ placement assessments
→ optimization candidates
→ allocation plan
```

- [ ] **Step 2: Assert Moscow/Kazan linkage survives entire pipeline**

Kazan recommendation exposes Moscow as affected destination; Moscow counterfactual assessment exists; optimizer still respects Moscow Ozon ceiling 0.

- [ ] **Step 3: Implement composition without business formulas in selectors/UI**
- [ ] **Step 4: Verify full suite and commit**

```bash
npm test -- tests/integration/pipeline.test.ts
npm test
git add src/app tests/integration/pipeline.test.ts
git commit -m "feat: compose end-to-end optimizer analysis"
```

## Task 22: Import/settings UI and report freshness

**Files:**
- Create: `src/ui/shell.ts`
- Create: `src/ui/upload-view.ts`
- Create: `src/ui/diagnostics-view.ts`
- Create: `src/ui/components/file-card.ts`
- Create: `src/ui/components/editable-number.ts`
- Modify: `styles.css`
- Test: `tests/ui/upload-view.test.ts`

- [ ] **Step 1: Write DOM test for input groups and metadata**

UI must show file name, report period/date, import timestamp, rows accepted/rejected, SKU count and validation state.

- [ ] **Step 2: Test mismatched operational dates warning**
- [ ] **Step 3: Test manual cluster mapping and product input editing**
- [ ] **Step 4: Implement, verify and commit**

```bash
npm test -- tests/ui/upload-view.test.ts
git add src/ui styles.css tests/ui/upload-view.test.ts
git commit -m "feat: add report import and diagnostics UI"
```

## Task 23: Dashboard, SKU diagnostics and placement comparison

**Files:**
- Create: `src/ui/dashboard-view.ts`
- Create: `src/ui/sku-view.ts`
- Create: `src/ui/plan-view.ts`
- Create: `src/ui/components/table.ts`
- Create: `src/ui/components/metric-card.ts`
- Create: `src/ui/components/status-badge.ts`
- Test: `tests/ui/dashboard-view.test.ts`
- Test: `tests/ui/sku-view.test.ts`

- [ ] **Step 1: Dashboard metrics test**

Required metrics:

```text
analyzed SKU
Ozon recommended units
seller available units
allocated units
expected profit
negative-economics recommendations
probable stockout destinations
probable recommendation distortions
blocked routes
incomplete SKU
```

- [ ] **Step 2: SKU four-view test**

Require:

```text
Demand view
Destination fulfillment view
Origin donor view
Placement comparison
```

- [ ] **Step 3: Moscow/Kazan evidence test**

Kazan recommendation row must visibly state that Kazan acted as donor for probable Moscow stockout and offer comparison to Moscow placement economics.

- [ ] **Step 4: Implement views using selectors only**
- [ ] **Step 5: Verify and commit**

```bash
npm test -- tests/ui/dashboard-view.test.ts tests/ui/sku-view.test.ts
git add src/ui tests/ui
git commit -m "feat: add explainable plan and stockout diagnostics UI"
```

## Task 24: Persistence wiring without hidden stale data

**Files:**
- Modify: `src/app/bootstrap.ts`
- Modify: `src/app/state.ts`
- Modify: `src/ui/upload-view.ts`
- Test: `tests/integration/persistence.test.ts`

- [ ] **Step 1: Write reload test for tariffs/settings/product inputs/mappings**
- [ ] **Step 2: Assert no PII/raw order row persistence**
- [ ] **Step 3: Assert restored operational reports retain visible stale metadata if restoration is supported**
- [ ] **Step 4: Implement, verify and commit**

```bash
npm test -- tests/integration/persistence.test.ts
git add src/app src/ui tests/integration/persistence.test.ts
git commit -m "feat: restore local optimizer configuration safely"
```

## Task 25: CI and offline release smoke test

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tests/browser/offline-release.spec.ts`
- Modify: `scripts/build.mjs`
- Modify: `README.md`
- Modify: `package.json`

- [ ] **Step 1: Add failing `file://` smoke test**

Open built `dist/index.html`, import sanitized fixture files and verify a plan is rendered without a server.

- [ ] **Step 2: Add network-request assertion**

Normal flow must produce no required external requests.

- [ ] **Step 3: Add CI**

```yaml
- run: npm ci
- run: npm run typecheck
- run: npm test
- run: npm run build
```

Include browser smoke test when environment support is reliable; otherwise keep it as mandatory local release gate and document the exact command.

- [ ] **Step 4: README launch/report instructions**

Document the three operational Ozon reports, tariff/unit workbook, product cost/available stock input and `index.html` launch.

- [ ] **Step 5: Final verification**

Run:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

Then disconnect network, open `dist/index.html` from disk, import fixtures and verify an explainable plan.

- [ ] **Step 6: Commit**

```bash
git add .github README.md scripts tests/browser package.json package-lock.json
git commit -m "chore: harden offline MVP release"
```

**PR8 acceptance:** supported reports flow through the full offline pipeline; every allocation/exclusion/distortion warning is explainable; no runtime service or data transmission is required.

---

# Manual validation checkpoints using real seller data

## Checkpoint A — after PR2

Load the current real files without preprocessing and record:

- accepted/rejected rows;
- SKU counts;
- report dates/periods;
- unknown cluster mappings;
- malformed worksheet recovery diagnostics;
- order lifecycle counts.

Confirm that customer name/address/INN are absent from canonical serialized records.

## Checkpoint B — after PR4

Pick three SKUs and manually verify:

- demand by delivery cluster;
- fulfillment origins for Moscow, Kazan and one other destination;
- reverse donor share for Kazan;
- cancelled/in-progress orders do not influence fulfilled-route shares;
- current week is excluded from stockout comparison.

## Checkpoint C — after PR5

Inspect 5–10 `Вероятный stockout` cases manually in Ozon where possible.

For each case record:

```text
signal destination
replacement donor origins
manual confirmation yes/no/unclear
availability daysWithoutStock evidence
whether Ozon recommends a donor cluster
```

Do not tune thresholds from one anecdote; adjust only after a small validation set shows consistent bias.

## Checkpoint D — after PR6

Compare 5–10 exact workbook examples, covering local/intercluster routes and material tax/VAT/co-invest branches.

Optimizer PR7 must not merge until parity is accepted.

## Checkpoint E — after PR7

For at least one known donor scenario compare:

```text
Ozon recommendation for donor cluster
counterfactual economics of affected destination
optimizer allocation under Ozon ceiling
```

Confirm the app highlights the counterfactual without silently reallocating beyond Ozon recommendation.

## Checkpoint F — after PR8

Use current real reports and compare:

1. Ozon recommendation totals;
2. lifecycle counts;
3. stockout warnings;
4. donor recommendation-distortion warnings;
5. feasibility exclusions;
6. economic exclusions;
7. limited-stock allocation;
8. expected profit;
9. counterfactual placement comparisons.

---

# Self-review against specification

- Offline/local-only runtime: PR1 + PR8.
- Report metadata/freshness: PR1 + PR2 + PR8.
- Malformed `dimension=A1` Ozon XLSX: PR2.
- Order lifecycle and incomplete-week protection: PR2 + PR4.
- PII boundary: PR2 + PR3 + PR8.
- No hard-coded tariff matrix/master cluster list: PR3.
- Existing multi-sheet unit workbook as tariff source: PR3.
- Destination-demand invariant: PR2 + PR4.
- Bidirectional route analysis: PR4.
- Probable destination stockout: PR5.
- Availability corroboration via `daysWithoutStock`: PR5.
- Donor-linked recommendation distortion: PR5.
- Stockout-cleaned route profile: PR5.
- Expected intercluster logistics: PR6.
- Spreadsheet parity including tax/VAT/co-invest: PR6.
- Warehouse restrictions: PR7.
- Counterfactual placement assessment: PR7.
- Ozon-ceiling limited-stock optimization: PR7.
- Explainability/status codes: PR7 + PR8.
- Local persistence with stale-data visibility: PR3 + PR8.
- End-to-end user workflow: PR8.

Historical daily stock, API integration and automatic quantity correction above Ozon recommendations remain explicitly post-MVP.
