# Ozon FBO Unit Economics & Supply Optimizer — Design

## Status

Approved product design for MVP, based on the working unit-economics spreadsheet and the provided Ozon reports.

## Product goal

Build a fully local browser application that evaluates Ozon FBO supply recommendations economically and allocates limited available stock across clusters to maximize expected absolute profit.

The product does **not** replace Ozon's demand forecast. It separates three questions:

1. **Where did customer demand arise?** — delivery cluster.
2. **From where did Ozon physically fulfill that demand?** — origin/dispatch cluster.
3. **Where should the next available unit be placed economically?** — result of our analysis and optimizer.

This separation is a hard domain invariant. A sale shipped from Kazan to a buyer in Moscow is Moscow demand, not Kazan demand.

## MVP scope

### In scope

- FBO only.
- Local browser execution; no backend, accounts, cloud storage, or Ozon API.
- Import of:
  - `Доступность товаров` XLSX;
  - `Ограничение складов по товарам` XLSX;
  - `orders.csv`;
  - Ozon logistics tariff XLSX;
  - seller product parameters/cost/available stock from XLSX/CSV and manual editing.
- Historical demand-by-destination analysis.
- Origin-to-destination fulfillment matrix and reverse donor matrix.
- Probable stockout detection from route substitution patterns.
- Forecast unit economics for `SKU × placement cluster`.
- Warehouse feasibility filter.
- Limited-stock allocation optimizer.
- Explainable recommendation statuses and reasons.
- Local persistence for slowly changing inputs.

### Explicitly out of scope

- FBS.
- Ozon API.
- Automatic report download.
- Automatic creation of supply orders.
- Own demand forecasting/ML.
- Historical daily stock balance import in MVP.
- Automatic override of Ozon recommendations solely because of `Вероятный stockout`.
- Cloud/backend/multi-user features.

## Runtime and development constraints

The distributed application must run without Node.js, Python, a local web server, or installation.

User flow:

```text
unpack/download release
→ open index.html
→ load local XLSX/CSV files
→ calculate locally in the browser
```

Development tooling may use Node.js. The release build must be a static offline bundle using classic browser scripts/assets so it remains usable from `file://`.

No runtime CDN dependencies are allowed. XLSX parsing code must be vendored or bundled into the release.

## Architectural style

Use a functional-core / imperative-shell structure:

- **Import adapters** know Ozon file formats.
- **Domain modules** know normalized business concepts only.
- **Analytics/economics/optimizer modules** are pure functions where practical.
- **UI/persistence** orchestrate domain modules but do not contain business formulas.

The primary design rule is that report column names, sheet names and CSV quirks must not leak beyond import adapters.

## Proposed source tree

```text
src/
  app/
    bootstrap.ts
    state.ts
    selectors.ts
  domain/
    models.ts
    result.ts
    invariants.ts
  importers/
    workbook.ts
    availability.ts
    restrictions.ts
    orders.ts
    tariffs.ts
    products.ts
    import-diagnostics.ts
  normalization/
    clusters.ts
    sku.ts
    numbers.ts
    dates.ts
  analytics/
    demand-matrix.ts
    fulfillment-matrix.ts
    weekly-series.ts
    stockout-detector.ts
    route-profile.ts
  economics/
    tariff-index.ts
    tariff-lookup.ts
    unit-economics.ts
    expected-logistics.ts
  supply/
    feasibility.ts
    cluster-score.ts
    optimizer.ts
  persistence/
    store.ts
    indexeddb-store.ts
  ui/
    shell.ts
    upload-view.ts
    dashboard-view.ts
    sku-view.ts
    plan-view.ts
    diagnostics-view.ts
    components/
      table.ts
      metric-card.ts
      status-badge.ts
      file-card.ts
      editable-number.ts

tests/
  fixtures/
  importers/
  analytics/
  economics/
  supply/
  integration/

public/
  vendor/

scripts/
  build.mjs
  copy-release-assets.mjs

dist/
  index.html
  app.js
  styles.css
  vendor/
```

`dist/` is the distributable artifact. Source modules may use ES modules/TypeScript, but the final browser runtime must not require module loading across `file://` boundaries.

## Canonical domain contracts

All importers produce canonical models. Exact Ozon headings remain private to the importers.

```ts
export type Sku = string;
export type SellerArticle = string;
export type ClusterId = string;
export type WarehouseId = string;
export type IsoDate = string;

export interface ProductRef {
  sku: Sku;
  article: SellerArticle;
  name: string;
}

export interface AvailabilityRecommendation {
  product: ProductRef;
  clusterId: ClusterId;
  recommendedQty: number;
  fboStock: number | null;
  fbsStock: number | null;
  inTransit: number | null;
  avgDailyUnits: number | null;
  daysWithoutStock: number | null;
  daysOfCover: number | null;
  ozonLocalShare: number | null;
  ozonStatus: string | null;
  reportDate: IsoDate | null;
}

export interface WarehouseRestriction {
  sku: Sku;
  clusterId: ClusterId;
  warehouseId: WarehouseId;
  warehouseName: string;
  allowed: boolean;
  maxSupplyQty: number | null;
  placementZone: string | null;
  reasonCodes: string[];
}

export interface OrderRecord {
  orderedAt: IsoDate;
  sku: Sku;
  article: SellerArticle;
  name: string;
  quantity: number;
  sellerPrice: number;
  originClusterId: ClusterId;
  destinationClusterId: ClusterId;
  originWarehouse: string | null;
  volumetricWeightKg: number | null;
}

export interface ProductEconomicsInput {
  sku: Sku;
  article: SellerArticle;
  cost: number | null;
  availableQty: number | null;
  price: number | null;
  commissionRate: number | null;
  volumeLiters: number | null;
}

export interface TariffRow {
  originClusterId: ClusterId;
  destinationClusterId: ClusterId;
  minVolumeLiters: number;
  maxVolumeLiters: number | null;
  minPrice: number | null;
  maxPrice: number | null;
  logisticsFee: number;
}
```

## Import pipeline

Each file passes through:

```text
raw file
→ parser
→ format detector
→ column mapper
→ row decoder
→ normalization
→ validation
→ canonical records + diagnostics
```

No malformed row may crash the whole import. Import results must contain both accepted records and diagnostics.

```ts
export interface ImportDiagnostic {
  severity: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  row?: number;
  field?: string;
}

export interface ImportResult<T> {
  records: T[];
  diagnostics: ImportDiagnostic[];
  sourceName: string;
  importedAt: string;
}
```

Missing mandatory columns are file-level errors. Invalid individual rows are row-level errors and are skipped unless doing so would make the dataset unusable.

## Cluster normalization

There is no hard-coded master list of clusters.

Cluster IDs are generated from normalized names found in the input datasets. Normalization handles whitespace, case, punctuation and known harmless textual variants.

Ambiguous or materially different names must not be silently merged. They appear in diagnostics and may be manually mapped by the user. Manual mappings are persisted locally.

## Demand model

Historical demand is attributed exclusively by `destinationClusterId`.

Canonical aggregation:

```ts
interface DemandCell {
  sku: Sku;
  destinationClusterId: ClusterId;
  quantity: number;
  orderCount: number;
}
```

This answers: **where did buyers request the product?**

## Fulfillment matrix

For each `SKU × destination cluster`, aggregate where fulfillment originated:

```ts
interface FulfillmentShare {
  sku: Sku;
  destinationClusterId: ClusterId;
  originClusterId: ClusterId;
  quantity: number;
  share: number;
}
```

Also build the reverse donor view for `SKU × origin cluster → destination clusters`.

Two distinct metrics must remain separate:

- **Destination local fulfillment share**: demand of cluster D fulfilled from D / all demand of D.
- **Origin local share**: units shipped from O to O / all units shipped from O.

## Weekly series

Route behavior is analyzed in fixed ISO-week buckets.

For each `SKU × destination cluster × week` calculate:

- total demand quantity;
- locally fulfilled quantity/share;
- quantities/shares by external origin;
- total order count.

Weekly aggregation is the input to probable-stockout detection.

## Probable stockout detector

Historical daily stock is not available in MVP. The detector therefore produces a diagnostic hypothesis, never a confirmed fact.

Allowed status wording:

```text
Вероятный stockout <cluster>
```

A strong signal is:

1. destination demand remains broadly stable;
2. local fulfillment share drops materially;
3. one or more external origin shares rise materially;
4. sample size is sufficient.

Initial configurable thresholds:

- local share drop: 30 percentage points;
- external replacement rise: 20 percentage points;
- minimum weekly demand: 10 units;
- minimum prior local share: 60%;
- demand-retention floor: current week demand >= 60% of baseline demand.

The implementation must return evidence, not only a boolean:

```ts
export interface StockoutSignal {
  sku: Sku;
  destinationClusterId: ClusterId;
  confidence: 'low' | 'medium' | 'high';
  baselineLocalShare: number;
  observedLocalShare: number;
  demandRetention: number;
  replacementOrigins: Array<{
    originClusterId: ClusterId;
    shareBefore: number;
    shareAfter: number;
  }>;
  explanationCodes: string[];
}
```

Initial confidence rules are deterministic and testable. The thresholds are configuration, not magic constants hidden in UI code.

The signal does **not** automatically rewrite an Ozon recommendation in MVP. It reduces trust and triggers a sanity-check warning.

## Route profile for expected logistics

For a candidate placement cluster, estimate which destination clusters it historically served.

Store two route profiles where data permits:

- `observed`: all historical routes;
- `clean`: excludes weeks classified as high-confidence stockout substitution for the affected destination.

Fallback hierarchy when SKU-level data are sparse:

1. `SKU × origin cluster` clean profile;
2. `SKU × origin cluster` observed profile;
3. origin-cluster profile across all SKUs;
4. global route profile.

Every profile carries a confidence/source label so the UI can explain the estimate.

## Tariff engine

The tariff workbook is user-supplied and locally persisted. It is not compiled into application source.

On import, tariff rows are normalized and indexed by:

```text
origin cluster
× destination cluster
× volume interval
× optional price interval
```

Lookup API:

```ts
export interface TariffLookupInput {
  originClusterId: ClusterId;
  destinationClusterId: ClusterId;
  volumeLiters: number;
  price: number;
}

export interface TariffLookupResult {
  fee: number | null;
  matchedRow: TariffRow | null;
  diagnosticCode: string | null;
}
```

Missing route/volume matches are explicit calculation blockers for that candidate cluster, never silently treated as zero.

## Expected logistics

For a candidate placement origin `O`:

```text
E(logistics | SKU, O)
= Σ P(destination_i | SKU, O) × tariff(SKU volume, O, destination_i, price)
```

The result includes the route profile source and coverage percentage.

If tariff coverage is incomplete, the result is marked incomplete and cannot receive a green recommendation.

## Unit-economics engine

The first implementation must reproduce the working spreadsheet's formulas for equivalent inputs. The spreadsheet is the regression oracle.

Canonical result:

```ts
export interface UnitEconomicsResult {
  sku: Sku;
  placementClusterId: ClusterId;
  price: number;
  commission: number;
  acquiring: number;
  expectedLogistics: number;
  advertisingAndServices: number;
  tax: number;
  cost: number;
  profitPerUnit: number;
  marginRate: number;
  roi: number;
  complete: boolean;
  blockers: string[];
}
```

All rates/settings are explicit calculation inputs. Formula code must not read values directly from DOM or persistence.

## Supply feasibility

For each `SKU × cluster`, derive:

```ts
export interface SupplyFeasibility {
  sku: Sku;
  clusterId: ClusterId;
  allowed: boolean;
  maxSupplyQty: number | null;
  eligibleWarehouses: WarehouseId[];
  reasons: string[];
}
```

If every warehouse in a cluster rejects the SKU, the cluster is infeasible.

When warehouse caps are present, cluster capacity is the safe aggregate capacity defined by the report semantics. If the report's cap semantics are ambiguous, the implementation must use the conservative interpretation and surface a diagnostic rather than summing blindly.

## Candidate cluster score

A candidate combines:

- Ozon recommended quantity;
- feasibility;
- unit economics;
- stockout-risk diagnostic;
- route-profile confidence.

```ts
export interface ClusterCandidate {
  sku: Sku;
  clusterId: ClusterId;
  ozonRecommendedQty: number;
  feasibleQty: number;
  economics: UnitEconomicsResult;
  stockoutSignal: StockoutSignal | null;
  routeConfidence: 'low' | 'medium' | 'high';
  statusCodes: string[];
}
```

Stockout warning remains explanatory in MVP; it does not change the optimizer's recommendation ceiling automatically.

## Optimizer

For each SKU, the user provides available stock.

Constraints:

```text
0 <= allocation(cluster)
allocation(cluster) <= Ozon recommended quantity
allocation(cluster) <= feasible cluster quantity
Σ allocation(cluster) <= available stock
```

Optional user thresholds:

- minimum profit per unit;
- minimum margin;
- minimum ROI.

Candidates below thresholds are excluded.

MVP objective:

```text
maximize Σ allocation(cluster) × expected profit per unit(cluster)
```

Because the objective is linear and units are homogeneous within a candidate, the MVP can use a deterministic greedy allocation sorted by expected profit per unit after all constraints/thresholds are applied. No LP solver dependency is needed unless future constraints make the problem non-linear or cross-SKU.

Tie-breaking order must be deterministic:

1. higher profit/unit;
2. higher route confidence;
3. lower stockout risk;
4. higher Ozon recommended quantity;
5. stable cluster ID order.

## Recommendation statuses

Statuses are derived from codes, not hard-coded presentation strings.

Minimum set:

- `OK` — economically acceptable and feasible;
- `LOW_ECONOMICS` — below configured threshold;
- `PROBABLE_STOCKOUT_DISTORTION` — historical substitution risk;
- `NEGATIVE_ECONOMICS` — expected profit < 0;
- `SUPPLY_BLOCKED` — physical placement unavailable;
- `INCOMPLETE_DATA` — required calculation input missing.

UI renders Russian labels and explanations from these codes.

## Local persistence

Persist slowly changing data:

- tariff dataset + import metadata;
- product economics inputs;
- manual cluster mappings;
- global economics settings;
- optimizer thresholds.

Do not silently treat old operational reports as current. Availability, restrictions and orders must display file name, report period/date and import timestamp.

Persistence interface:

```ts
export interface LocalStore {
  get<T>(key: string): Promise<T | null>;
  set<T>(key: string, value: T): Promise<void>;
  remove(key: string): Promise<void>;
}
```

Use IndexedDB in production with an in-memory implementation for tests.

## UI information architecture

### 1. Data / import screen

Two groups:

**Operational Ozon data**
- Availability;
- Warehouse restrictions;
- Orders history.

**Economics**
- Tariffs;
- product parameters/cost/available stock;
- global settings.

Each file card shows source name, period/date, row count, SKU count and validation status.

### 2. Dashboard / supply plan

Top metrics:

- analyzed SKUs;
- total Ozon recommended units;
- seller available units;
- units allocated;
- expected profit;
- negative-economics recommendations;
- probable-stockout warnings;
- blocked routes;
- incomplete SKUs.

Main table shows the optimized supply plan.

### 3. SKU detail

Show:

- product/economics inputs;
- Ozon recommendation by cluster;
- economics by candidate cluster;
- demand-by-destination;
- fulfillment sources of selected destination;
- reverse donor view for selected origin;
- weekly local/non-local fulfillment history;
- probable-stockout evidence;
- reasoned allocation result.

### 4. Diagnostics

Show import and calculation blockers with direct navigation to the affected SKU/cluster/input.

## Explainability requirement

Every allocation and exclusion must have machine-readable reason codes and human-readable evidence.

Example:

```text
Moscow
Ozon: 120
Profit/unit: +181 ₽
ROI: 61%
Feasible: yes
Stockout risk: low
Allocated: 120
Reason: highest remaining expected contribution, within Ozon recommendation and warehouse capacity.
```

No opaque score may be the sole basis of a recommendation.

## Testing strategy

### Unit tests

Pure domain modules:

- cluster normalization;
- import row decoding;
- demand aggregation;
- fulfillment shares;
- weekly series;
- stockout detector;
- tariff lookup boundaries;
- expected logistics;
- spreadsheet-parity formulas;
- feasibility;
- optimizer constraints and tie-breaks.

### Fixture tests

Store sanitized/minimal fixtures derived from the provided report schemas. Do not commit seller-sensitive full raw reports unless explicitly approved.

### Spreadsheet regression tests

Create a compact golden fixture from several rows of the working unit-economics spreadsheet with inputs and expected outputs. The TypeScript engine must match these values within defined rounding tolerance.

### Integration tests

Exercise:

```text
fixture files
→ import
→ normalize
→ analytics
→ economics
→ feasibility
→ optimizer
→ plan result
```

### Browser smoke test

Verify the release can be opened from `file://`, import local fixture files and produce a plan without network access.

## Definition of MVP done

MVP is complete when a user can open the release locally, load the supported real Ozon reports without preprocessing, supply cost/available stock, load tariffs, inspect demand and fulfillment routes, see probable-stockout warnings, calculate forecast cluster economics, respect warehouse restrictions, allocate limited stock, and understand why every unit was or was not allocated.
