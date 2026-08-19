# Ozon FBO Unit Economics & Supply Optimizer — Design

## Status

Reviewed MVP product design based on the working unit-economics spreadsheet and the provided Ozon reports.

This document is the architectural source of truth for implementation.

## Product goal

Build a fully local browser application that:

1. accepts Ozon's own FBO supply recommendations;
2. reconstructs where customer demand actually arose;
3. separates customer demand from the cluster that happened to fulfill it;
4. detects probable stockout-driven substitution between clusters;
5. evaluates the economics of placing a SKU in each relevant cluster;
6. respects current warehouse restrictions;
7. allocates limited seller stock across Ozon-recommended clusters to maximize expected absolute profit;
8. exposes counterfactual placement comparisons when Ozon's recommendation may be distorted by historical substitution.

The product does **not** replace Ozon's demand forecast.

It separates four questions:

1. **Where did customer demand arise?** — delivery cluster.
2. **From where did Ozon physically fulfill that demand?** — origin/dispatch cluster.
3. **Is an Ozon recommendation potentially distorted by a cluster acting as a donor during another cluster's probable stockout?**
4. **Where is the next available unit economically preferable to place?** — unit-economics assessment and optimizer output.

A shipment `Казань → Москва` is Moscow demand fulfilled from Kazan. It is never Kazan demand merely because Kazan dispatched it.

---

# 1. MVP scope

## In scope

- FBO only.
- Fully local browser execution.
- Import of:
  - `Доступность товаров` XLSX;
  - `Ограничение складов по товарам` XLSX;
  - `orders.csv`;
  - Ozon logistics tariff XLSX or a workbook containing the tariff sheet;
  - seller product economics / cost / available stock XLSX or CSV;
  - manual corrections to product economics and cluster mappings.
- Historical demand-by-destination analysis.
- Fulfillment source matrix and reverse donor matrix.
- Order lifecycle filtering for demand and actual fulfillment analytics.
- Exclusion of incomplete/current periods from stockout baselines.
- Probable stockout detection.
- Corroboration of stockout signals with current Ozon availability evidence where available, including `daysWithoutStock`.
- Detection of recommendation distortion when a recommended origin historically acted as a replacement origin for another cluster's probable stockout.
- Observed and stockout-cleaned route profiles.
- Forecast unit economics for `SKU × placement cluster`.
- Counterfactual placement assessment for relevant clusters, including clusters with zero Ozon recommendation.
- Warehouse feasibility filter.
- Limited-stock optimizer bounded by Ozon recommendation quantities in MVP.
- Explainable recommendation statuses and evidence.
- Local persistence for slowly changing inputs.

## Explicitly out of scope

- FBS optimization.
- Ozon API.
- Automatic report download.
- Automatic creation of supply orders.
- Own demand forecasting or ML.
- Historical daily stock balance import.
- Claiming a stockout as confirmed without direct stock history.
- Automatically increasing an allocation above the Ozon recommended quantity because of a probable stockout.
- Cloud/backend/multi-user features.

---

# 2. Runtime and development constraints

The distributed application must run without Node.js, Python, a local web server, installation, accounts or network access.

User flow:

```text
unpack/download release
→ open index.html
→ load local XLSX/CSV files
→ calculate locally in the browser
```

Development tooling may use Node.js.

The release is a static offline bundle using classic browser scripts/assets and must work from `file://`.

No runtime CDN dependency is allowed. XLSX/CSV parsing libraries must be bundled or vendored into the release.

Raw user files and personal data must never be sent anywhere.

---

# 3. Architectural style

Use functional core / imperative shell:

- import adapters know Ozon report peculiarities;
- canonical domain models do not know Excel/CSV column names;
- analytics, economics, feasibility and optimizer are pure functions where practical;
- persistence stores only normalized business data and configuration;
- UI contains no business formulas.

Report column names, sheet names, CSV quirks and malformed workbook metadata terminate at the importer boundary.

---

# 4. Source modules

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
    report-meta.ts

  importers/
    workbook.ts
    csv.ts
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
    order-status.ts

  analytics/
    order-populations.ts
    demand-matrix.ts
    fulfillment-matrix.ts
    weekly-series.ts
    stockout-detector.ts
    recommendation-distortion.ts
    route-profile.ts

  economics/
    tariff-index.ts
    tariff-lookup.ts
    expected-logistics.ts
    unit-economics.ts

  supply/
    feasibility.ts
    placement-assessment.ts
    cluster-candidate.ts
    optimizer.ts

  persistence/
    store.ts
    indexeddb-store.ts
    memory-store.ts

  ui/
    shell.ts
    upload-view.ts
    dashboard-view.ts
    sku-view.ts
    plan-view.ts
    diagnostics-view.ts
    components/

tests/
  fixtures/
  importers/
  analytics/
  economics/
  supply/
  integration/
  browser/
```

---

# 5. Canonical report metadata

All imported datasets carry explicit metadata.

```ts
export interface ReportMeta {
  sourceName: string;
  importedAt: string;
  reportGeneratedAt: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  recommendationHorizonDays: number | null;
}
```

Operational reports from materially different dates must be surfaced as a warning.

The UI must never silently present a restored old report as current.

---

# 6. Canonical domain contracts

```ts
export type Sku = string;
export type SellerArticle = string;
export type ClusterId = string;
export type WarehouseId = string;
export type IsoDateTime = string;

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
  reportDate: string | null;
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

export type OrderLifecycle =
  | 'fulfilled'
  | 'in_progress'
  | 'cancelled'
  | 'unknown';

export interface OrderRecord {
  acceptedAt: IsoDateTime;
  plannedShipAt: IsoDateTime | null;
  handedToDeliveryAt: IsoDateTime | null;
  deliveredAt: IsoDateTime | null;
  lifecycle: OrderLifecycle;
  rawStatus: string;
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

No buyer name, address, INN/KPP, legal-entity name, payment details or other unnecessary personal/customer fields may enter canonical state or IndexedDB.

The orders importer extracts only fields required by the product and discards the rest immediately after decoding each raw row.

---

# 7. Import result contract

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
  meta: ReportMeta;
}
```

Malformed individual rows do not crash the full import.

Missing mandatory columns are file-level errors.

---

# 8. Ozon XLSX robustness requirement

The provided real Ozon workbooks contain worksheets whose XML `dimension` may incorrectly declare `A1` while the sheet actually contains hundreds or thousands of rows.

The workbook reader must not trust worksheet `dimension` as the authoritative used range.

Required behavior:

1. parse populated worksheet cells/rows even if `dimension=A1` is wrong;
2. detect suspicious workbook metadata;
3. emit an importer diagnostic such as `WORKSHEET_DIMENSION_REPAIRED`;
4. prove behavior with a sanitized regression fixture reproducing the malformed dimension pattern.

A normal synthetic XLSX fixture alone is insufficient acceptance evidence.

---

# 9. Cluster normalization

There is no hard-coded master cluster list.

Cluster IDs are derived from imported data.

Automatic normalization may handle only harmless formatting differences: whitespace, case, punctuation and explicitly known aliases.

Semantically ambiguous names are never silently merged. They require a visible manual mapping, persisted locally.

---

# 10. Order lifecycle populations

Orders are used for two different analytical purposes and therefore require two explicit populations.

## 10.1 Net demand observations

Used to estimate where non-cancelled customer demand arose.

```text
fulfilled + in_progress
```

Cancelled orders are excluded from net demand by default.

## 10.2 Fulfilled route observations

Used to learn actual origin → destination fulfillment behavior and stockout substitution.

Only orders classified as `fulfilled` are included.

`in_progress`, `cancelled` and `unknown` statuses are excluded from actual-route shares.

## 10.3 Incomplete periods

The current ISO week and any week without sufficient completed fulfillment must not be used as an ordinary baseline/comparison period in stockout detection.

The UI may display current-week demand separately, but stockout inference must be based on completed historical periods.

---

# 11. Demand model

Demand is attributed exclusively by `destinationClusterId`.

```ts
export interface DemandCell {
  sku: Sku;
  destinationClusterId: ClusterId;
  quantity: number;
  orderCount: number;
}
```

The demand matrix answers:

> Where did buyers request the product?

It must never infer demand from origin shipments.

---

# 12. Fulfillment matrix and donor matrix

Actual-route analytics use fulfilled route observations only.

For each `SKU × destination cluster`:

```ts
export interface FulfillmentShare {
  sku: Sku;
  destinationClusterId: ClusterId;
  originClusterId: ClusterId;
  quantity: number;
  share: number;
}
```

Also build the reverse view:

```text
SKU × origin cluster → destination clusters
```

Two metrics remain distinct:

- **Destination local fulfillment share** = demand in D fulfilled from D / all fulfilled demand in D.
- **Origin local share** = units shipped O → O / all fulfilled units shipped from O.

---

# 13. Weekly route series

For each completed ISO week and `SKU × destination cluster` calculate:

- fulfilled demand quantity;
- local fulfilled quantity/share;
- quantities/shares by external origin;
- fulfilled order count.

Keep net-demand volume separately when useful for demand stability checks.

---

# 14. Probable stockout detector

Historical daily stocks are not available in MVP; the detector produces a hypothesis, not a confirmed fact.

Allowed wording:

```text
Вероятный stockout Москвы
```

Strong route evidence:

1. destination demand remains broadly stable;
2. local fulfillment share falls materially;
3. one or more external origins rise materially;
4. the sample is sufficient;
5. the comparison uses completed periods.

Initial configurable thresholds:

- prior local share >= 60%;
- local share drop >= 30 percentage points;
- external replacement rise >= 20 percentage points;
- minimum fulfilled weekly quantity = 10;
- demand retention >= 60% of baseline.

```ts
export interface StockoutSignal {
  sku: Sku;
  destinationClusterId: ClusterId;
  confidence: 'low' | 'medium' | 'high';
  baselineWeek: string;
  observedWeek: string;
  baselineLocalShare: number;
  observedLocalShare: number;
  demandRetention: number;
  availabilityCorroboration: 'supports' | 'neutral' | 'contradicts';
  replacementOrigins: Array<{
    originClusterId: ClusterId;
    shareBefore: number;
    shareAfter: number;
  }>;
  explanationCodes: string[];
}
```

## Availability corroboration

If the current `Доступность товаров` record for the same `SKU × destination cluster` shows evidence such as `daysWithoutStock > 0`, the detector may raise confidence or append corroborating evidence.

Because availability is a current snapshot, it must not be used to fabricate a historical stock fact for a specific past date.

A contradictory current snapshot may reduce confidence but cannot erase strong historical route evidence automatically.

---

# 15. Recommendation distortion signal

A stockout belongs to the **destination that lost local fulfillment**.

A potentially distorted recommendation may belong to a **different origin cluster that acted as donor**.

These must be separate contracts.

Example:

```text
Probable stockout: Moscow
Replacement origin: Kazan
Ozon recommendation: Kazan +150
```

The application must be able to flag the Kazan recommendation because Kazan historically fulfilled Moscow's substituted demand.

```ts
export interface RecommendationDistortionSignal {
  sku: Sku;
  recommendedClusterId: ClusterId;
  confidence: 'low' | 'medium' | 'high';
  affectedDestinations: Array<{
    destinationClusterId: ClusterId;
    stockoutConfidence: 'low' | 'medium' | 'high';
    donorShareAfter: number;
    donorShareIncrease: number;
  }>;
  explanationCodes: string[];
}
```

A distortion signal does **not** change Ozon's quantity automatically in MVP.

It changes trust/explainability and enables counterfactual comparison.

---

# 16. Route profiles for expected logistics

For each candidate placement origin estimate destination probabilities.

Maintain:

- `observed` profile — all eligible fulfilled historical routes;
- `clean` profile — excludes fulfilled routes from high-confidence stockout-substitution weeks for affected destinations.

Fallback hierarchy:

1. `SKU × origin cluster` clean profile;
2. `SKU × origin cluster` observed profile;
3. origin cluster across all SKUs;
4. global fulfilled route profile.

Each profile carries source, sample size and confidence.

No cancelled or in-progress order may enter route probabilities.

---

# 17. Tariff import and tariff engine

Tariffs are user-loaded and persisted locally, not compiled into source.

The importer must accept:

1. a tariff-only workbook;
2. the existing unit-economics workbook containing a tariff sheet such as `Логистика с 28 августа 2026г.`.

The importer detects the tariff sheet by required column signatures, not only by exact sheet name.

The existing workbook may optionally provide initial product parameters such as commission, volume, price and cost where recognizable. These imports are convenience only and remain editable.

Tariff rows are indexed by:

```text
origin cluster
× destination cluster
× volume interval
× optional price interval
```

Missing tariff coverage is a calculation blocker, never zero cost.

---

# 18. Expected logistics

For candidate origin O:

```text
E(logistics | SKU, O)
= Σ P(destination_i | SKU, O)
  × tariff(volume, O, destination_i, price)
```

Result includes:

- expected fee;
- tariff coverage;
- route profile source;
- route confidence;
- missing destinations.

Partial tariff coverage is visible and prevents a green recommendation.

---

# 19. Spreadsheet-parity unit economics

The working spreadsheet is the regression oracle.

The engine must represent all material spreadsheet inputs explicitly rather than hiding them in UI or constants.

```ts
export type TaxSystem =
  | 'usn_income'
  | 'usn_income_minus_expenses'
  | 'osno'
  | 'manual';

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
  sku: Sku;
  placementClusterId: ClusterId;
  price: number;
  cost: number;
  commissionRate: number;
  expectedLogistics: number;
  settings: EconomicsSettings;
}
```

If the spreadsheet represents one of these concepts with different exact semantics, the golden fixture is authoritative and the engine must reproduce the spreadsheet's order of operations.

Optimizer thresholds are **not** part of `EconomicsSettings`.

```ts
export interface OptimizerThresholds {
  minProfitPerUnit: number;
  minMarginRate: number;
  minRoi: number;
}
```

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
  coInvest: number;
  vat: number;
  incomeTax: number;
  tax: number;
  cost: number;
  profitPerUnit: number;
  marginRate: number;
  roi: number;
  complete: boolean;
  blockers: string[];
}
```

---

# 20. Supply feasibility

For each `SKU × cluster` derive:

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

If all warehouses reject the SKU, the cluster is infeasible.

Ambiguous per-warehouse maximum semantics must be interpreted conservatively and surfaced with a reason code instead of blindly summed.

---

# 21. Placement assessment vs optimization candidate

These are deliberately separate.

## Placement assessment

The application may economically assess a relevant cluster even when Ozon recommends zero units there.

This enables the user to compare:

```text
Kazan +100 vs Moscow +100
```

when Kazan may be a donor for Moscow stockout.

```ts
export interface PlacementAssessment {
  sku: Sku;
  clusterId: ClusterId;
  ozonRecommendedQty: number;
  feasibility: SupplyFeasibility;
  economics: UnitEconomicsResult;
  distortionSignal: RecommendationDistortionSignal | null;
  routeConfidence: 'low' | 'medium' | 'high';
  statusCodes: string[];
}
```

Relevant clusters include at minimum:

- clusters with Ozon recommendation > 0;
- the SKU's demand destinations;
- replacement origins implicated by stockout signals;
- stockout-affected destinations needed for counterfactual comparison.

## Optimization candidate

Automatic allocation in MVP is narrower:

```text
Ozon recommendation > 0
AND feasible
AND economics complete
AND above user thresholds
```

A counterfactual cluster with zero Ozon recommendation can be shown but automatic allocation remains capped at zero in MVP.

---

# 22. Optimizer

For each SKU:

```text
0 <= allocation(cluster)
allocation(cluster) <= Ozon recommended quantity
allocation(cluster) <= feasible cluster quantity
Σ allocation(cluster) <= seller available stock
```

Objective:

```text
maximize Σ allocation(cluster) × expected profit per unit(cluster)
```

With linear homogeneous units, deterministic greedy allocation by expected profit/unit is sufficient for MVP after filters and constraints.

Tie breaks:

1. higher profit/unit;
2. higher route confidence;
3. lower recommendation-distortion risk;
4. higher Ozon recommended quantity;
5. stable cluster ID.

---

# 23. Recommendation statuses

Minimum machine-readable codes:

- `OK`;
- `LOW_ECONOMICS`;
- `NEGATIVE_ECONOMICS`;
- `PROBABLE_STOCKOUT`;
- `PROBABLE_RECOMMENDATION_DISTORTION`;
- `SUPPLY_BLOCKED`;
- `INCOMPLETE_DATA`;
- `INCOMPLETE_TARIFF_COVERAGE`;
- `LOW_ROUTE_CONFIDENCE`;
- `COUNTERFACTUAL_ONLY`.

UI renders Russian labels and evidence from codes.

No opaque score is allowed as the sole explanation.

---

# 24. Local persistence

Persist slowly changing inputs only by default:

- tariff dataset + metadata;
- product economics inputs;
- manual cluster mappings;
- economics settings;
- optimizer thresholds.

Operational datasets may be restored only if their source/report dates remain visibly labelled as stale/current.

No raw CSV/XLSX row and no customer PII is persisted.

---

# 25. UI information architecture

## Data/import screen

Operational Ozon data:

- Availability;
- Warehouse restrictions;
- Orders history.

Economics:

- Tariffs / source workbook;
- product parameters / cost / available stock;
- global economics settings;
- optimizer thresholds.

Each file card shows:

- source file;
- report period/date;
- import timestamp;
- rows accepted/rejected;
- SKU count;
- validation status.

Warn when operational report dates do not align.

## Dashboard / supply plan

Show:

- analyzed SKUs;
- Ozon recommended units;
- seller available units;
- allocated units;
- expected profit;
- negative-economics recommendations;
- probable stockout destinations;
- recommendations with probable distortion;
- blocked routes;
- incomplete SKUs.

## SKU detail

Show four distinct views:

1. **Demand view** — where buyers were located.
2. **Destination fulfillment view** — who fulfilled a selected destination's demand.
3. **Origin donor view** — where stock from a selected origin actually went.
4. **Placement comparison** — economics of relevant candidate/counterfactual clusters.

Stockout detail shows:

- baseline vs observed local share;
- replacement origins;
- demand retention;
- availability corroboration;
- confidence.

If Kazan is implicated in Moscow's stockout and Ozon recommends Kazan, Kazan's row must explicitly show the link to Moscow.

---

# 26. Testing strategy

## Import tests

- Cyrillic headers and locale numbers.
- CSV BOM and delimiter handling.
- Exact orders status mapping.
- PII does not appear in canonical output.
- Malformed Ozon `dimension=A1` workbook fixture imports all actual rows.
- Tariff sheet auto-detection inside a multi-sheet workbook.

## Lifecycle tests

Given statuses:

```text
Доставлен
Отменён
Доставляется
Ожидает отгрузки
Ожидает сборки
```

verify:

- cancelled is excluded from net demand and route analytics;
- fulfilled contributes to demand and route analytics;
- in-progress may contribute to current net demand but not historical fulfilled-route shares;
- current incomplete week is excluded from stockout baseline/comparison.

## Demand/route invariant test

Synthetic fulfilled data:

```text
800 Moscow → Moscow
200 Kazan → Moscow
100 Kazan → Kazan
```

Expected:

```text
Moscow demand = 1000
Kazan demand = 100
Moscow local fulfillment share = 80%
Kazan origin local share = 100 / 300 = 33.33%
```

## Stockout test

```text
week 1: Moscow demand 100, Moscow local 90%, Kazan donor 5%
week 2: Moscow demand 95, Moscow local 20%, Kazan donor 65%
```

Expected:

- `Вероятный stockout Москвы`;
- Kazan listed as replacement origin;
- a Kazan recommendation can receive `PROBABLE_RECOMMENDATION_DISTORTION`;
- Moscow and Kazan both appear in placement comparison.

Negative controls:

- demand collapse;
- insufficient sample;
- low prior local share;
- no replacement-origin increase;
- incomplete current week.

## Spreadsheet regression

Create 5–10 sanitized golden cases from the working workbook covering:

- local and intercluster logistics;
- commission;
- acquiring;
- advertising/services;
- buyout treatment;
- tax system;
- VAT where applicable;
- co-invest where applicable;
- cost;
- profit;
- margin;
- ROI.

Application results must match spreadsheet outputs within explicit rounding tolerance.

## Optimizer tests

Assert:

- allocation never exceeds Ozon recommendation;
- allocation never exceeds feasible capacity;
- total never exceeds seller available stock;
- blocked/incomplete/below-threshold candidates receive zero;
- counterfactual-only clusters are not silently allocated above Ozon zero recommendation;
- expected plan profit equals line contributions;
- result is deterministic.

## Integration tests

```text
real-schema fixture files
→ import
→ lifecycle populations
→ demand/routes
→ stockout
→ recommendation distortion
→ route profiles
→ tariffs/economics
→ placement assessments
→ feasibility
→ optimizer
→ explainable plan
```

## Browser smoke test

Open the built release from `file://`, import fixtures without network access and produce an explainable plan.

---

# 27. Manual validation checkpoints

After route analytics, manually check several SKUs against the real reports.

After stockout detection, manually validate 5–10 `Вероятный stockout` signals against historical evidence available in Ozon. Record confirmed/not-confirmed results outside the automatic decision path.

If the heuristic proves reliable, it can be trusted as a high-value diagnostic while still remaining formally probabilistic until historical stock data are added.

Before optimizer merge, verify spreadsheet parity on real golden examples.

---

# 28. Definition of MVP done

MVP is complete when the user can:

1. open the release locally;
2. load the real Ozon reports without preprocessing;
3. load the existing tariff/unit-economics workbook or a tariff workbook;
4. see exact report dates and diagnostics;
5. inspect demand by delivery cluster;
6. inspect fulfillment sources by destination;
7. inspect where each origin's stock actually went;
8. see probable stockout signals based only on completed/eligible order history;
9. see when an Ozon recommendation may be distorted because the recommended cluster acted as donor for another cluster's stockout;
10. compare the economics of recommended and relevant counterfactual placements;
11. respect warehouse restrictions;
12. enter/edit cost and available stock;
13. reproduce the spreadsheet's unit economics;
14. allocate limited stock within Ozon recommendation ceilings to maximize expected absolute profit;
15. understand every allocation, exclusion and warning;
16. perform all of the above without transmitting seller or customer data externally.
