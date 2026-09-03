# Ozon FBO Product Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Current Product Completion correction (2026-09-03):** The product has one optimization strategy, `MAX_MARGIN`, and no user-selectable objective. The API defaults an omitted objective to `max_margin` and rejects legacy `max_profit` and unsupported `max_volume`. Within a single SKU, destination price is constant, so profit/unit and margin-rate rankings are equivalent. Historical steps below describe the implementation evolution and do not override this current contract.

**Goal:** Implement the approved Product Completion layer so the application independently estimates destination demand, compares it with Ozon, models route economics, produces Safe and Calculated plans under max-profit/max-margin objectives, and exposes the result through the approved decision UI and `Потоки спроса` flow analysis.

**Architecture:** Preserve the current SCOZ-lite runtime and the working ingestion/economics core. Add small pure Python modules around the existing analytics/economics/supply contracts, then assemble one immutable business-facing analysis snapshot through the existing FastAPI boundary. Only after the snapshot contract is complete, migrate the vanilla frontend to the four-section Product Completion UI governed by `DESIGN.md` and `UX-CONTRACT.md`.

**Tech Stack:** Python 3.13.14; FastAPI 0.139.2; Uvicorn 0.51.0; openpyxl 3.1.5; python-multipart 0.0.32; pytest 8.4.2; httpx 0.28.1; stdlib `csv`/JSON/date/Decimal; committed vanilla HTML/CSS/JavaScript; no npm/build/framework.

**Spec:** `docs/superpowers/specs/2026-09-02-ozon-fbo-product-completion-design.md`

**UI contracts:** `/DESIGN.md`, `/UX-CONTRACT.md`

## Global Constraints

- `destination_cluster` is customer-demand geography; `origin_cluster` is physical fulfillment origin. `Казань → Москва` is Moscow demand fulfilled from Kazan.
- Route cleaning and demand-history eligibility are separate mechanisms. A route-substitution week may be excluded from clean route history without erasing valid destination demand.
- Current availability may corroborate historical stockout evidence but may not be required to mark a strong historical route-shift period cleaning-eligible.
- Ozon recommendation is a comparison/control signal. It caps Safe Plan only; it does not cap Calculated Plan.
- Demand determines quantity. Economics determines placement priority. Economics never creates demand.
- Demand forecast uses the latest eligible completed weeks, excludes the current incomplete ISO week, uses `M1 → M2 → L`, ±10% regime thresholds, 50% confirmed impulse, and ±20% adjustment cap exactly as specified.
- No hidden safety stock. User-selected horizon days are the whole coverage target.
- `calculated_need_qty = max(0, ceil(raw_demand_forecast - current_fbo_stock - included_inbound_qty))`; rounding occurs after subtraction.
- Unknown stock/inbound/tariff/economics values remain unknown and may block decisions; never coerce missing evidence to zero.
- Expected logistics fallback order is exactly: `SKU × origin clean → SKU × origin observed → origin all SKUs → global fulfilled profile`.
- The only allocation objectives are `Макс. прибыль` and `Макс. маржа`; there is no max-volume objective.
- Seller stock is allocated independently per SKU. Unused stock remains unallocated when eligible need is lower than available seller stock.
- All financial math remains `Decimal`; do not introduce binary-float business calculations.
- Python owns ingestion, demand, stockout, route economics, unit economics, feasibility, optimization and human-readable decision reasoning. Frontend performs presentation only.
- Frontend remains committed vanilla HTML/CSS/JavaScript with no npm, package manifest, TypeScript, framework, bundler or runtime CDN.
- Preserve fail-closed ingestion, tariff coverage without renormalization, PII boundary, tax/VAT/co-invest semantics, portable runtime, loopback bind and Windows smoke.
- Work outside `main`. Use RED/GREEN TDD for behavior changes. Each PR below must be independently reviewable and green before the next PR starts.
- Every PR runs its focused tests plus `python -m pytest -q`, `node --check frontend/assets/js/app.js` while that file is the only application script, and `git diff --check`. After the frontend split, syntax-check every committed JS file. Runtime-related changes also require the authoritative Windows portable smoke.

---

# Target file map

## Existing files intentionally extended

- `backend/domain/signals.py` — stockout evidence contract only.
- `backend/analytics/stockout.py` — historical route-shift inference and availability corroboration.
- `backend/analytics/clean_routes.py` — route-cleaning eligibility and auditable exclusions.
- `backend/ingestion/availability.py` — operational stock/inbound/OOS evidence and Ozon horizon metadata.
- `backend/ingestion/normalization.py` — harmless text normalization and explicit resolution behavior.
- `backend/project.py` — existing Project JSON manual-mapping persistence boundary.
- `backend/economics/tariffs.py` — route profile source levels without changing tariff lookup math.
- `backend/supply/contracts.py` — calculated need, plan family and objective contracts.
- `backend/supply/optimizer.py` — Safe/Calculated ceilings and max-profit/max-margin ordering.
- `backend/application.py` — orchestration only; business formulas remain in pure modules.
- `backend/api.py` — scenario validation, mapping persistence endpoints and snapshot serialization.
- `frontend/index.html` — four-section shell and Product Completion surfaces.
- `frontend/assets/css/app.css` — one semantic token block mapped from `DESIGN.md`.
- `frontend/assets/js/app.js` — boot/orchestration after the frontend split.

## New focused modules

- `backend/ingestion/cluster_resolution.py` — canonical explicit cluster resolution across imported report records.
- `backend/analytics/demand_estimate.py` — robust completed-week demand regime and weekly-rate estimate.
- `backend/analytics/route_profiles.py` — four-level logistics profile selection/fallback.
- `backend/analytics/flows.py` — exact origin→destination quantities and destination shares.
- `backend/decision/__init__.py` — public Product Completion decision contracts.
- `backend/decision/need.py` — horizon forecast, FBO/inbound subtraction and Ozon comparison.
- `backend/decision/contracts.py` — scenario, comparison, decision-row, flow-view and immutable snapshot dataclasses.
- `backend/decision/explanations.py` — localized human-readable reasons from structured evidence.
- `backend/decision/snapshot.py` — immutable Product Completion snapshot assembly.
- `backend/economics/route_opportunity.py` — route-specific current vs local counterfactual economics.
- `frontend/assets/js/core.js` — router, immutable snapshot state, formatters and persisted presentation preferences.
- `frontend/assets/js/components.js` — canonical `DataTable`, `SearchField`, `Notice`, `DetailDrawer`, `RankedBars` owners.
- `frontend/assets/js/flow.js` — canonical `FlowView` owner.

---

# PR1 — Historical stockout and clean-route correctness

## Task 1: Separate historical evidence, cleaning eligibility and current corroboration

**Files:**
- Modify: `backend/domain/signals.py`
- Modify: `backend/analytics/stockout.py`
- Test: `tests/analytics/test_stockout_distortion.py`

**Interfaces:**
- Consumes existing `RouteProfile`, `AvailabilityRecord`, `StockoutThresholds`.
- Adds `StockoutSignal.historical_evidence_strength: SignalConfidence`.
- Adds `StockoutSignal.route_cleaning_eligible: bool`.
- Preserves `availability_corroboration`, `confidence`, replacement evidence and explanation codes.

- [ ] **Step 1: Write the failing historical-evidence regression**

Create two consecutive completed weeks for one SKU/destination where local share falls from at least 60% by at least 30 p.p., one external origin rises by at least 20 p.p., both weeks have at least 10 fulfilled units and demand retention is at least 60%. Supply current availability with a positive destination quantity.

Assert:

```python
assert signal.historical_evidence_strength is SignalConfidence.HIGH
assert signal.route_cleaning_eligible is True
assert signal.availability_corroboration is AvailabilityCorroboration.NEUTRAL
assert signal.confidence is SignalConfidence.HIGH
```

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_stockout_distortion.py -q
```

Expected: the new contract assertions fail because the current code ties HIGH confidence to current zero availability.

- [ ] **Step 3: Extend the immutable signal contract**

Use this field order so callers cannot confuse historical strength with displayed confidence:

```python
@dataclass(frozen=True, slots=True)
class StockoutSignal:
    sku: str
    destination_cluster_id: str
    historical_evidence_strength: SignalConfidence
    route_cleaning_eligible: bool
    confidence: SignalConfidence
    baseline_week: str
    observed_week: str
    baseline_local_share: Decimal
    observed_local_share: Decimal
    demand_retention: Decimal
    availability_corroboration: AvailabilityCorroboration
    replacement_origins: tuple[ReplacementOriginEvidence, ...]
    explanation_codes: tuple[str, ...]
```

The already-approved strong threshold set produces `historical_evidence_strength=HIGH` and `route_cleaning_eligible=True` before current availability is consulted.

- [ ] **Step 4: Make displayed confidence explicit**

Add this helper to `stockout.py`:

```python
def _display_confidence(
    historical: SignalConfidence,
    corroboration: AvailabilityCorroboration,
) -> SignalConfidence:
    if historical is SignalConfidence.HIGH:
        return SignalConfidence.HIGH
    if corroboration is AvailabilityCorroboration.SUPPORTS:
        return SignalConfidence.HIGH
    return historical
```

Current positive availability cannot downgrade a strong historical shift.

- [ ] **Step 5: Preserve distortion semantics**

Update construction/call sites in `backend/analytics/distortion.py` and tests only as required by the expanded dataclass. Distortion confidence may still consume displayed `signal.confidence`; it must not determine route-cleaning eligibility.

- [ ] **Step 6: Run GREEN and analytics regressions**

```bash
python -m pytest tests/analytics/test_stockout_distortion.py -q
python -m pytest tests/analytics -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/domain/signals.py backend/analytics/stockout.py backend/analytics/distortion.py tests/analytics/test_stockout_distortion.py
git commit -m "fix: separate stockout history from current corroboration"
```

## Task 2: Exclude route periods by explicit historical eligibility

**Files:**
- Modify: `backend/analytics/clean_routes.py`
- Test: `tests/analytics/test_clean_routes.py`
- Regression: `tests/analytics/test_demand_routes.py`

**Interfaces:**
- Consumes `StockoutSignal.route_cleaning_eligible` from Task 1.
- Preserves `CleanRouteResult`, `observed_routes`, `clean_routes`, `excluded_routes` and summaries.

- [ ] **Step 1: Add RED exclusion test**

Build one observed route profile with a contaminated week and a `route_cleaning_eligible=True` signal whose current corroboration is neutral. Assert the contaminated week appears in `excluded_routes`, the corresponding quantity is absent from the aggregated clean quantity, and the original observed quantity is unchanged.

```python
assert {(row.iso_year, row.iso_week) for row in result.excluded_routes} == {(2026, 31)}
assert sum(row.quantity for row in result.observed_routes) == 30
assert sum(row.quantity for row in result.clean_routes) == 20
```

Add a second signal with `route_cleaning_eligible=False` and assert no quantity is excluded.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_clean_routes.py -q
```

- [ ] **Step 3: Replace confidence-threshold gating**

Build the exclusion lookup from `route_cleaning_eligible`. Keep `stockout_confidence` and `stockout_observed_week` in `ExcludedRouteEvidence` for audit. Delete `CleanRoutePolicy.minimum_exclusion_confidence` only if no public caller/test requires it; otherwise retain the type as deprecated compatibility data but do not let it override explicit eligibility.

- [ ] **Step 4: Prove destination demand was not altered**

```bash
python -m pytest tests/analytics/test_clean_routes.py tests/analytics/test_demand_routes.py -q
```

- [ ] **Step 5: Full PR1 verification**

```bash
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/clean_routes.py tests/analytics/test_clean_routes.py
git commit -m "fix: clean routes from historical substitution evidence"
```

**PR1 acceptance:** strong historical substitution is cleaning-eligible after stock recovery, current availability remains corroborating evidence, and destination-demand aggregation is unchanged.

---

# PR2 — Operational evidence, Ozon horizon and canonical cluster identity

## Task 3: Retain inbound/OOS/product evidence from the operational availability report

**Files:**
- Modify: `backend/ingestion/availability.py`
- Modify: `backend/analytics/stockout.py`
- Test: `tests/ingestion/test_availability.py`
- Test: `tests/analytics/test_stockout_distortion.py`

**Interfaces:**

Extend `AvailabilityRecord` with:

```python
product_name: str = ""
days_without_stock: int | None = None
inbound_quantity: int | None = None
```

Preserve `article`, `fbo_quantity`, `fbs_quantity`, `available_quantity` and `recommended_quantity`.

- [ ] **Step 1: Add RED parsing test using the real report headers**

Use headers including:

```text
Название товара
Рекомендуемая поставка, шт на 56 дней
Дней без остатка за 28 дней
Остаток FBO, шт
Остаток FBS, шт
Товары в пути на склад озон, шт
```

Assert product name, explicit zero vs blank optional values, inbound quantity, days-without-stock and FBO/FBS quantities are preserved.

- [ ] **Step 2: Add RED Ozon-horizon test**

Assert returned `ImportResult.meta.recommendation_horizon_days == 56` when one recommendation header contains `на 56 дней`.

If two recognized recommendation columns contain conflicting horizons, assert one `CONFLICTING_RECOMMENDATION_HORIZON` error and `recommendation_horizon_days is None`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/ingestion/test_availability.py -q
```

- [ ] **Step 4: Parse optional integer evidence fail-closed**

Blank optional values return `None`; explicit zero stays `0`; malformed/negative values produce `INVALID_NUMBER` with the correct field and skip that malformed row.

Use a header-horizon parser equivalent to:

```python
_RECOMMENDATION_HORIZON = re.compile(r"(?:на|за)\s+(\d+)\s+дн", re.IGNORECASE)
```

Use `dataclasses.replace(report_context, recommendation_horizon_days=horizon)` for the returned metadata.

- [ ] **Step 5: Enrich stockout corroboration conservatively**

`days_without_stock > 0` may produce `SUPPORTS`. `days_without_stock == 0` remains `NEUTRAL` unless report metadata explicitly proves that the measured OOS period overlaps the historical observed week. Do not infer contradiction from a current in-stock state.

- [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/ingestion/test_availability.py tests/analytics/test_stockout_distortion.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/availability.py backend/analytics/stockout.py tests/ingestion/test_availability.py tests/analytics/test_stockout_distortion.py
git commit -m "feat: retain availability evidence and Ozon horizon"
```

## Task 4: Add one explicit semantic cluster-resolution pass

**Files:**
- Create: `backend/ingestion/cluster_resolution.py`
- Modify: `backend/ingestion/__init__.py`
- Modify: `backend/api.py`
- Test: `tests/ingestion/test_cluster_resolution.py`
- Regression: `tests/api/test_analysis.py`
- Regression: existing Project JSON tests under `tests/`

**Interfaces:**

Define:

```python
@dataclass(frozen=True, slots=True)
class ClusterResolutionResult:
    availability: tuple[AvailabilityRecord, ...]
    restrictions: tuple[RestrictionRecord, ...]
    orders: tuple[OrderRecord, ...]
    tariffs: tuple[TariffRow, ...]
    diagnostics: tuple[ImportDiagnostic, ...]
```

Public function signature:

```text
resolve_analysis_clusters(
    availability: Iterable[AvailabilityRecord],
    restrictions: Iterable[RestrictionRecord],
    orders: Iterable[OrderRecord],
    tariffs: Iterable[TariffRow],
    manual_mappings: Mapping[str, str],
) -> ClusterResolutionResult
```

Resolution rules:

1. Canonical exact-label universe = all normalized tariff origin/destination labels plus explicit manual-mapping targets that resolve to a tariff label.
2. Exact normalized/casefold match to exactly one canonical tariff label resolves automatically.
3. Manual mapping source overrides exact aliases and must target one canonical tariff label.
4. Never translate, shorten, geographically guess or fuzzy-match.
5. An unresolved operational origin/destination/cluster emits `UNRESOLVED_CLUSTER`; the affected analytical record is omitted from resolved outputs so downstream financial decisions fail closed.
6. `INVALID_MANUAL_CLUSTER_TARGET` is emitted when a manual target is not present in the canonical tariff-label universe.
7. Keep the original normalized source label in diagnostic text; do not persist raw workbook rows.

- [ ] **Step 1: Write RED cases**

Cover exact case-insensitive identity, manual override, unresolved order destination, unresolved order origin, unresolved availability cluster, unresolved restriction cluster and invalid manual target.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/ingestion/test_cluster_resolution.py -q
```

- [ ] **Step 3: Implement with `dataclasses.replace`**

Call the existing `normalize_cluster_label()` and `resolve_cluster_id()` utilities; do not create a second normalization policy.

- [ ] **Step 4: Wire the resolver before analytics**

In `run_analysis_pipeline()`, resolve cluster identities after all reports are parsed and before article joining/application analysis. In PR2, pass an explicit empty manual mapping so exact operational fixtures remain compatible. PR6 replaces that empty mapping with persisted Project JSON mappings. Add resolver diagnostics to the existing diagnostic stream.

- [ ] **Step 5: Verify existing Project JSON mapping round-trip**

Locate the current Project JSON test file and prove `manual_cluster_mappings` saves/loads exactly. Add a focused regression only if that behavior is not already asserted.

- [ ] **Step 6: Run GREEN and PR2 verification**

```bash
python -m pytest tests/ingestion/test_cluster_resolution.py tests/api/test_analysis.py -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add backend/ingestion/cluster_resolution.py backend/ingestion/__init__.py backend/api.py tests/ingestion/test_cluster_resolution.py tests/api/test_analysis.py
git commit -m "feat: resolve cluster identity before analysis"
```

**PR2 acceptance:** real availability retains FBO/FBS/inbound/OOS evidence and Ozon horizon; analytical cluster identity has one explicit non-fuzzy resolver.

---

# PR3 — Independent demand estimate and calculated need

## Task 5: Implement `M1 → M2 → L` destination-demand estimator

**Files:**
- Create: `backend/analytics/demand_estimate.py`
- Modify: `backend/analytics/__init__.py`
- Test: `tests/analytics/test_demand_estimate.py`

**Interfaces:**

```python
class DemandRegime(str, Enum):
    GROWTH = "growth"
    STABLE = "stable"
    DECLINE = "decline"
    TRANSITION = "transition"
    INCOMPLETE = "incomplete"

@dataclass(frozen=True, slots=True)
class DemandEstimate:
    sku: str
    destination_cluster_id: str
    eligible_week_count: int
    m1: Decimal | None
    m2: Decimal | None
    latest_week_qty: Decimal | None
    regime: DemandRegime
    regime_confirmed: bool | None
    raw_adjustment: Decimal
    applied_adjustment: Decimal
    current_weekly_rate: Decimal | None
    confidence: SignalConfidence
    explanation_codes: tuple[str, ...]
```

Public function signature:

```text
estimate_destination_demand(demand: DemandResult) -> tuple[DemandEstimate, ...]
```

Rules:

- Use completed weeks from `DemandResult.window.included_weeks`, sorted chronologically.
- For an existing `SKU × destination` series, a completed source week with no net-demand cell contributes zero.
- Full model uses the latest 8 eligible completed weeks only.
- `M1 = median(weeks 1–4)`, `M2 = median(weeks 5–8)`, `L = week 8`.
- For `M1 > 0`: growth when change `> +10%`, decline when `< -10%`, stable within ±10% inclusive.
- `M1 == 0 and M2 > 0` is `TRANSITION`; never emit infinite growth.
- Growth confirmed when `L > 1.10 × M2`; decline confirmed when `L < 0.90 × M2`; stability confirmed within `M2 ±10%` inclusive.
- Confirmed growth/decline: `raw_adjustment = 0.5 × (L - M2)`; applied adjustment is clamped to ±20% of M2.
- Stable, transition and unconfirmed growth/decline use the baseline median with zero applied adjustment.
- 4–7 eligible weeks: median of all eligible weeks, no trend adjustment, confidence at most MEDIUM.
- 1–3 eligible weeks: median of available weeks, no trend adjustment, LOW confidence.
- 0 eligible weeks: no numeric estimate; do not emit a fake zero rate.

- [ ] **Step 1: Write the parameterized RED suite**

Cover confirmed growth, confirmed decline, exact ±10% stable boundaries, 50% impulse, ±20% cap, last-week contradiction, 4–7 fallback, 1–3 fallback, transition from zero and a route-substitution week that remains valid destination demand.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_demand_estimate.py -q
```

- [ ] **Step 3: Implement pure Decimal math**

Use `statistics.median` on integer weekly quantities converted to `Decimal`. The estimator consumes `DemandResult` only and knows nothing about Ozon recommendation, stock, inbound, routes or economics.

- [ ] **Step 4: Run GREEN and demand regressions**

```bash
python -m pytest tests/analytics/test_demand_estimate.py tests/analytics/test_demand_routes.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/demand_estimate.py backend/analytics/__init__.py tests/analytics/test_demand_estimate.py
git commit -m "feat: estimate current destination demand regime"
```

## Task 6: Compute arbitrary-horizon need and Ozon comparison

**Files:**
- Modify: `backend/supply/contracts.py` to add the shared objective enum only.
- Create: `backend/decision/__init__.py`
- Create: `backend/decision/contracts.py`
- Create: `backend/decision/need.py`
- Test: `tests/decision/test_need.py`

**Interfaces:**

Add to `backend/supply/contracts.py`:

```python
class AllocationObjective(str, Enum):
    MAX_PROFIT = "max_profit"
    MAX_MARGIN = "max_margin"
```

Add to `backend/decision/contracts.py`:

```python
class HorizonComparability(str, Enum):
    SAME_HORIZON = "same_horizon"
    DIFFERENT_HORIZON = "different_horizon"
    OZON_HORIZON_UNKNOWN = "ozon_horizon_unknown"
    OZON_RECOMMENDATION_MISSING = "ozon_recommendation_missing"

@dataclass(frozen=True, slots=True)
class ScenarioSettings:
    horizon_days: int
    include_inbound: bool
    objective: AllocationObjective

@dataclass(frozen=True, slots=True)
class NeedComparison:
    sku: str
    destination_cluster_id: str
    current_weekly_rate: Decimal | None
    horizon_days: int
    raw_demand_forecast: Decimal | None
    current_fbo_stock: int | None
    inbound_qty: int | None
    inbound_included: bool
    calculated_need_qty: int | None
    ozon_recommended_qty: int | None
    ozon_horizon_days: int | None
    delta_qty: int | None
    delta_pct: Decimal | None
    comparability: HorizonComparability
    complete: bool
    blocker_codes: tuple[str, ...]
```

Public functions:

```text
forecast_horizon(weekly_rate: Decimal, horizon_days: int) -> Decimal
calculate_need(
    *,
    sku: str,
    destination_cluster_id: str,
    weekly_rate: Decimal | None,
    horizon_days: int,
    fbo_stock: int | None,
    inbound_qty: int | None,
    include_inbound: bool,
    ozon_recommended_qty: int | None,
    ozon_horizon_days: int | None,
) -> NeedComparison
```

- [ ] **Step 1: Add RED exact-math test**

```python
def test_need_rounds_up_only_after_stock_and_inbound_subtraction():
    result = calculate_need(
        sku="SKU-1",
        destination_cluster_id="Москва",
        weekly_rate=Decimal("10"),
        horizon_days=10,
        fbo_stock=3,
        inbound_qty=2,
        include_inbound=True,
        ozon_recommended_qty=8,
        ozon_horizon_days=10,
    )
    assert result.raw_demand_forecast == Decimal("100") / Decimal("7")
    assert result.calculated_need_qty == 10
```

- [ ] **Step 2: Add RED incomplete/comparison cases**

Test inbound off, zero floor, unknown FBO stock, unknown inbound with inclusion on, missing demand estimate, same horizon, different horizon, unknown Ozon horizon, missing Ozon recommendation and Ozon zero without dividing by zero for `delta_pct`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/decision/test_need.py -q
```

- [ ] **Step 4: Implement exact helpers**

```python
def forecast_horizon(weekly_rate: Decimal, horizon_days: int) -> Decimal:
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days <= 0:
        raise ValueError("horizon_days must be a positive integer")
    return weekly_rate * Decimal(horizon_days) / Decimal(7)


def integer_need(raw_forecast: Decimal, fbo_stock: int, inbound: int) -> int:
    raw_need = raw_forecast - Decimal(fbo_stock) - Decimal(inbound)
    rounded = int(raw_need.to_integral_value(rounding=ROUND_CEILING))
    return max(0, rounded)
```

When `include_inbound=False`, known inbound remains visible but subtraction uses zero. When `include_inbound=True` and inbound is unknown, calculated need is incomplete rather than assuming zero.

- [ ] **Step 5: Implement Ozon comparison without rescaling**

`delta_qty = calculated_need_qty - ozon_recommended_qty` may be shown for orientation on different horizons, but `comparability` must explicitly say `DIFFERENT_HORIZON`. `delta_pct` is `None` when Ozon recommendation is zero or missing.

- [ ] **Step 6: Run GREEN and PR3 verification**

```bash
python -m pytest tests/decision/test_need.py tests/analytics/test_demand_estimate.py -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add backend/supply/contracts.py backend/decision tests/decision
git commit -m "feat: calculate independent horizon need"
```

**PR3 acceptance:** backend can explainably produce current weekly demand, arbitrary-horizon forecast and calculated need independently of Ozon; no safety buffer and no Ozon rescaling exist.

---

# PR4 — Four-level route profiles and route-specific economics

## Task 7: Implement auditable four-level route-profile selection

**Files:**
- Create: `backend/analytics/route_profiles.py`
- Modify: `backend/economics/tariffs.py`
- Modify: `backend/economics/__init__.py`
- Modify: `backend/application.py`
- Test: `tests/analytics/test_route_profiles.py`
- Test: `tests/economics/test_tariffs.py`
- Regression: `tests/api/test_analysis.py`

**Interfaces:**

Extend `RouteProfileSource` exactly:

```python
class RouteProfileSource(str, Enum):
    CLEAN = "clean"
    OBSERVED = "observed"
    ORIGIN_ALL_SKUS = "origin_all_skus"
    GLOBAL = "global"
```

Add:

```python
@dataclass(frozen=True, slots=True)
class RouteProfileSelection:
    sku: str
    origin_cluster_id: str
    source: RouteProfileSource
    sample_quantity: int
    sample_observation_count: int
    confidence: SignalConfidence
    profile: tuple[RouteDistributionCell, ...]
```

Public signature:

```text
select_route_profile(
    sku: str,
    origin_cluster_id: str,
    clean: CleanRouteResult,
    observed: RouteProfile,
) -> RouteProfileSelection
```

Fallback order is fixed. Origin-all-SKUs and global fallbacks create synthetic `RouteDistributionCell` values with the requested target SKU and candidate origin while preserving the fallback destination proportions and sample counts.

Confidence mapping is explicit and deterministic:

```text
CLEAN → HIGH
OBSERVED → MEDIUM
ORIGIN_ALL_SKUS → LOW
GLOBAL → LOW
```

Application code maps this `SignalConfidence` to existing placement `RouteConfidence` by value until the duplicate enum is removed in a separately reviewed refactor.

- [ ] **Step 1: Add four RED tests, one per source level**

The global test must use an origin with no direct history and assert the synthetic profile uses that candidate origin for tariff lookup while its destination proportions come from global fulfilled history.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_route_profiles.py -q
```

- [ ] **Step 3: Implement selection/aggregation**

Do not change tariff matching or renormalize uncovered tariff shares. `expected_logistics()` receives the selected profile and the extended source enum.

- [ ] **Step 4: Replace `clean_profile or observed_profile` in `application.py`**

Every logistics result must preserve the actual source level and sample size.

- [ ] **Step 5: Run GREEN**

```bash
python -m pytest tests/analytics/test_route_profiles.py tests/economics/test_tariffs.py tests/api/test_analysis.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/route_profiles.py backend/economics/tariffs.py backend/economics/__init__.py backend/application.py tests/analytics/test_route_profiles.py tests/economics/test_tariffs.py tests/api/test_analysis.py
git commit -m "feat: add complete route profile fallback hierarchy"
```

## Task 8: Model each observed route against a feasible local counterfactual

**Files:**
- Create: `backend/analytics/flows.py`
- Create: `backend/economics/route_opportunity.py`
- Modify: `backend/economics/__init__.py`
- Test: `tests/analytics/test_flows.py`
- Test: `tests/economics/test_route_opportunity.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class FulfillmentFlowCell:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    destination_share: Decimal
    observation_count: int

@dataclass(frozen=True, slots=True)
class RouteOpportunity:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    observed_qty: int
    destination_share: Decimal
    route_cost_rub: Decimal | None
    route_cost_pct_of_realization: Decimal | None
    current_profit_per_unit: Decimal | None
    current_margin_rate: Decimal | None
    local_route_cost_rub: Decimal | None
    local_route_cost_pct_of_realization: Decimal | None
    local_profit_per_unit: Decimal | None
    local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None
    profit_delta_per_unit: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]
```

Public signatures:

```text
aggregate_observed_flows(observed: RouteProfile) -> tuple[FulfillmentFlowCell, ...]
aggregate_clean_flows(clean: CleanRouteResult) -> tuple[FulfillmentFlowCell, ...]
calculate_route_opportunity(
    flow: FulfillmentFlowCell,
    product: ProductEconomicsInput,
    tariffs: ImportResult[TariffRow],
    settings: EconomicsSettings,
    local_feasibility: SupplyFeasibility,
) -> RouteOpportunity
```

- [ ] **Step 1: Add RED flow reconciliation tests**

For every `SKU × destination`, observed flow quantities must sum to fulfilled destination quantity and destination shares must sum to 1. Clean flows reconcile to clean route quantities, not observed demand.

- [ ] **Step 2: Add RED current-vs-local economics test**

Construct `Казань → Москва` and `Москва → Москва` tariffs. Assert:

```python
assert result.route_cost_pct_of_realization == result.route_cost_rub / realization
assert result.margin_delta_pp == (result.local_margin_rate - result.current_margin_rate) * Decimal("100")
assert result.observed_profit_opportunity_rub == result.profit_delta_per_unit * result.observed_qty
```

Add a case where local placement is more expensive and prove negative `margin_delta_pp` and negative ruble effect are preserved rather than clamped to zero.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/analytics/test_flows.py tests/economics/test_route_opportunity.py -q
```

- [ ] **Step 4: Build route-specific one-cell logistics profiles**

For the current route create a one-cell `RouteDistributionCell` with share `Decimal("1")`, observed quantity and current origin/destination. Calculate route-specific unit economics with the existing `calculate_unit_economics()`.

For the local counterfactual create the equivalent one-cell profile with `origin_cluster_id = destination_cluster_id`. Hold product/economics settings constant; only route/placement-dependent logistics changes.

- [ ] **Step 5: Fail closed for incomplete local comparison**

If local placement is physically prohibited, route tariff coverage is incomplete, realization is zero/unknown or unit economics is incomplete, return `complete=False`, null comparison values and exact reason codes. Never return zero benefit as a substitute for unknown.

- [ ] **Step 6: Keep observed-period and forecast-horizon rubles distinct**

This task produces `observed_profit_opportunity_rub` only. No forecast ruble opportunity is added until a caller has both a forecast volume and an explicit route-share assumption.

- [ ] **Step 7: Run GREEN and PR4 verification**

```bash
python -m pytest tests/analytics/test_flows.py tests/economics/test_route_opportunity.py tests/economics -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add backend/analytics/flows.py backend/economics/route_opportunity.py backend/economics/__init__.py tests/analytics/test_flows.py tests/economics/test_route_opportunity.py
git commit -m "feat: model route economics and local opportunity"
```

**PR4 acceptance:** every placement can use all four logistics fallback levels; observed fulfillment routes expose exact current-vs-local modeled economics, including negative local effects and explicit incompleteness.

---

# PR5 — Safe/Calculated plans and scenario allocator

## Task 9: Carry independent need through placement assessment

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/placement.py`
- Test: `tests/supply/test_placement.py`

**Interfaces:**

Add to `backend/supply/contracts.py`:

```python
class PlanFamily(str, Enum):
    SAFE = "safe"
    CALCULATED = "calculated"
```

Add `calculated_need_qty: int | None` to both `PlacementInput` and `PlacementAssessment`. `None` means own need is incomplete; it never means zero.

- [ ] **Step 1: Add RED contract/propagation tests**

Assert calculated need survives `compare_placements()`, negative values are rejected and `None` remains `None`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 3: Implement minimal propagation**

Do not change physical feasibility semantics. Existing restriction state, eligible warehouses and `max_supply_qty` remain authoritative.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/supply/contracts.py backend/supply/placement.py tests/supply/test_placement.py
git commit -m "feat: carry calculated need into placement assessments"
```

## Task 10: Generalize optimizer for plan family and allocation objective

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/__init__.py`
- Modify: `backend/application.py`
- Test: `tests/supply/test_optimizer.py`

**Interfaces:**

Public optimizer signature:

```text
optimize_allocations(
    candidates: Iterable[PlacementAssessment],
    available_stock: int,
    thresholds: OptimizerThresholds,
    *,
    plan_family: PlanFamily,
    objective: AllocationObjective,
) -> OptimizationResult
```

Extend `OptimizationResult` with:

```python
plan_family: PlanFamily
objective: AllocationObjective
```

Preserve `objective_profit` as total modeled plan profit for reporting compatibility.

Ceilings:

```text
Safe = min(Ozon recommendation, calculated need, physical ceiling)
Calculated = min(calculated need, physical ceiling)
```

When `physical_ceiling is None`, warehouse quantity does not further cap the corresponding plan ceiling. When `calculated_need_qty is None`, both plan families are incomplete for that candidate because the approved Safe ceiling also includes own need.

Eligibility remains blocked by incomplete economics and configured minimum profit/margin/ROI thresholds.

Stable ordering:

1. chosen objective: `profit_per_unit` descending for MAX_PROFIT; `margin_rate` descending for MAX_MARGIN;
2. higher route confidence;
3. lower distortion risk;
4. larger calculated need;
5. stable cluster id.

- [ ] **Step 1: Add RED plan-ceiling test**

Candidate: Ozon 5, need 12, physical 20. Assert Safe automatic ceiling 5 and Calculated automatic ceiling 12.

- [ ] **Step 2: Add RED objective-divergence test**

Use two clusters where A has higher profit/unit but lower margin and B has lower profit/unit but higher margin. With seller stock insufficient to cover both, MAX_PROFIT must allocate to A first and MAX_MARGIN to B first.

- [ ] **Step 3: Add RED tie/remainder tests**

Prove deterministic output for equal primary scores, and prove seller stock above all eligible plan ceilings remains unallocated.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

- [ ] **Step 5: Implement objective-specific stable sort**

Keep the existing least-significant-first stable-sort pattern; do not perform arithmetic on Decimal sort keys.

- [ ] **Step 6: Produce both alternative plans per SKU**

For the selected objective and one SKU seller-stock amount, call the optimizer twice against the same placement assessments: once `PlanFamily.SAFE`, once `PlanFamily.CALCULATED`. Safe allocation is not subtracted before Calculated; they are alternative scenarios.

- [ ] **Step 7: Run GREEN and PR5 verification**

```bash
python -m pytest tests/supply/test_optimizer.py tests/supply/test_placement.py -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add backend/supply backend/application.py tests/supply
git commit -m "feat: allocate Safe and Calculated plan scenarios"
```

**PR5 acceptance:** fixed per-SKU seller stock is allocated under max-profit or max-margin; Safe and Calculated are alternative plans under one selected objective; Calculated Plan is independent of Ozon quantity.

---

# PR6 — Immutable decision snapshot, mappings and API contract

## Task 11: Define exact business-facing snapshot and flow contracts

**Files:**
- Complete: `backend/decision/contracts.py`
- Create: `backend/decision/explanations.py`
- Create: `backend/decision/snapshot.py`
- Modify: `backend/decision/__init__.py`
- Test: `tests/decision/test_snapshot.py`

**Interfaces:**

Add exact view contracts:

```python
@dataclass(frozen=True, slots=True)
class DiagnosticView:
    severity: str
    code: str
    message: str
    sku: str | None = None
    cluster_id: str | None = None
    destination_cluster_id: str | None = None

@dataclass(frozen=True, slots=True)
class InputStatusView:
    ok: bool
    record_count: int
    diagnostics: tuple[DiagnosticView, ...]

@dataclass(frozen=True, slots=True)
class DecisionSummary:
    sku_count: int
    decision_row_count: int
    total_ozon_recommended_qty: int
    total_calculated_need_qty: int
    total_safe_plan_qty: int
    total_calculated_plan_qty: int
    expected_calculated_plan_profit: Decimal
    disagreement_row_count: int
    incomplete_row_count: int

@dataclass(frozen=True, slots=True)
class RouteSkuBreakdown:
    sku: str
    article: str
    product_name: str
    quantity: int
    route_share: Decimal
    destination_demand_share: Decimal
    margin_delta_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None

@dataclass(frozen=True, slots=True)
class FlowLinkView:
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    destination_share: Decimal
    margin_delta_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    route_economics_complete: bool
    route_reason_codes: tuple[str, ...]
    sku_breakdown: tuple[RouteSkuBreakdown, ...]

@dataclass(frozen=True, slots=True)
class FlowView:
    mode: str
    key: str
    total_quantity: int
    local_share: Decimal | None
    external_share: Decimal | None
    donor_count: int
    links: tuple[FlowLinkView, ...]

@dataclass(frozen=True, slots=True)
class FlowViewAggregates:
    observed_views: tuple[FlowView, ...]
    clean_views: tuple[FlowView, ...]

@dataclass(frozen=True, slots=True)
class DecisionRow:
    sku: str
    article: str
    product_name: str
    destination_cluster_id: str
    demand: DemandEstimate | None
    need: NeedComparison
    safe_plan_qty: int | None
    calculated_plan_qty: int | None
    current_fbo_stock: int | None
    inbound_qty: int | None
    route_external_share: Decimal | None
    route_margin_opportunity_pp: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    expected_plan_profit: Decimal | None
    confidence: SignalConfidence
    status_codes: tuple[str, ...]
    explanations: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    snapshot_id: str
    created_at: str
    report_meta: dict[str, ReportMeta]
    freshness_warnings: tuple[str, ...]
    scenario: ScenarioSettings
    input_statuses: dict[str, InputStatusView]
    summary: DecisionSummary
    decision_rows: tuple[DecisionRow, ...]
    demand_estimates: tuple[DemandEstimate, ...]
    observed_routes: RouteProfile
    clean_routes: CleanRouteResult
    stockout_signals: tuple[StockoutSignal, ...]
    distortion_signals: tuple[RecommendationDistortionSignal, ...]
    route_economics: tuple[RouteOpportunity, ...]
    unit_economics: tuple[UnitEconomicsResult, ...]
    safe_allocations: tuple[OptimizationResult, ...]
    calculated_allocations: tuple[OptimizationResult, ...]
    flow_view_aggregates: FlowViewAggregates
    diagnostics: tuple[DiagnosticView, ...]
```

For both plan quantities, `None` means that the plan is unavailable and could
not be calculated from sufficient evidence.  `0` means that calculation
completed and the resulting plan quantity is genuinely zero.

`FlowView.mode` is restricted by constructor validation to exactly `destination`, `origin`, or `sku`.

- [ ] **Step 1: Add RED decision-row reconciliation test**

Assert one `SKU × destination` row joins the correct demand estimate, Ozon recommendation, own need, Safe quantity, Calculated quantity, route economics and product identity.

- [ ] **Step 2: Add RED flow reconciliation test**

For every `FlowLinkView`, `sum(item.quantity for item in sku_breakdown) == link.quantity`. For destination views, link quantities sum to view total and destination shares sum to 1 when total is positive.

- [ ] **Step 3: Add RED explanation test**

Assert user-facing explanations include meaningful Russian text and raw backend codes are not the only strings. Technical codes remain in `status_codes`/diagnostics.

- [ ] **Step 4: Implement localized explanations in Python**

Generate messages from structured evidence. Required examples include the concepts:

```text
Рекомендация Ozon может быть занижена: часть спроса кластера исполнялась из других кластеров во время вероятного дефицита.
Рост спроса подтверждается последней полной неделей.
Горизонты различаются: Ozon 56 дней, наш расчёт 67 дней.
```

- [ ] **Step 5: Build deterministic summary values**

Sum quantities and rubles only. Never sum percentages. `expected_calculated_plan_profit` equals the sum of calculated-plan allocation expected profits for the selected objective.

- [ ] **Step 6: Run GREEN**

```bash
python -m pytest tests/decision/test_snapshot.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/decision tests/decision
git commit -m "feat: assemble Product Completion decision snapshot"
```

## Task 12: Wire scenario validation, Project mappings, freshness and snapshot serialization

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/api.py`
- Modify: `backend/project.py` only if a narrow helper is needed for atomic mapping persistence.
- Test: `tests/api/test_analysis.py`
- Create: `tests/api/test_project_mappings.py`

**Interfaces:**

Multipart scenario fields:

```text
horizon_days=<positive integer>
include_inbound=true|false
optimization_objective=max_profit|max_margin
```

Migration defaults when omitted by the pre-PR7 frontend:

```text
horizon_days = unique Ozon recommendation horizon when known, otherwise 56
include_inbound = true
optimization_objective = max_profit
```

Minimal mapping endpoints backed by `data/project.json`:

```text
GET /api/project/mappings
PUT /api/project/mappings
```

`PUT` accepts one JSON object of nonblank string source→target mappings, validates it through Project rules and saves atomically. Tests inject a temporary project path; production defaults to the existing `data/` persistence boundary.

- [ ] **Step 1: Add RED scenario validation tests**

Reject zero/negative/non-integer horizon, invalid boolean and unsupported objective with stable code/field pairs.

- [ ] **Step 2: Add RED mapping round-trip test**

Write one mapping through `PUT`, read it through `GET`, then run analysis with a source alias and prove the resolver produces the canonical cluster. No test may write the developer's real `data/project.json`.

- [ ] **Step 3: Add RED snapshot parity assertions**

Ordinary and streamed analysis must return equivalent `snapshot` content after removing only volatile `snapshot_id`, `created_at` and import timestamps. Existing streaming progress ordering/request-id/PII tests remain.

- [ ] **Step 4: Preserve the old response shape for one frontend migration PR**

During PR6 return `snapshot` plus current legacy analytical fields. New Product Completion frontend code must use `snapshot`; legacy fields are compatibility only.

- [ ] **Step 5: Populate freshness/comparability metadata without guessing**

Use existing `ReportMeta`. Missing report periods/horizons stay unknown. Different Ozon/user horizons produce a visible comparability warning but do not by themselves fail the whole analysis.

- [ ] **Step 6: Run GREEN and PR6 verification**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_project_mappings.py tests/decision -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add backend/application.py backend/api.py backend/project.py tests/api
git commit -m "feat: expose immutable Product Completion snapshot"
```

**PR6 acceptance:** backend/API owns all Product Completion math/reasoning; a successful run returns one immutable snapshot with scenario/report context; manual mappings persist through Project JSON; existing frontend remains functional until PR7.

---

# PR7 — Product shell, Data workflow and Plan decision UI

Before editing PR7, reread `DESIGN.md` and `UX-CONTRACT.md` from the implementation branch. If Frontend Design Premium runtime is available, run its strict static audit before and after the PR and record actual findings.

## Task 13: Introduce canonical shell, design tokens and immutable client state

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assets/css/app.css`
- Create: `frontend/assets/js/core.js`
- Create: `frontend/assets/js/components.js`
- Modify: `frontend/assets/js/app.js`
- Create: `tests/frontend/test_product_shell.py`
- Create: `tests/frontend/test_ui_state.py`

**Interfaces:**

Top-level sections exactly:

```text
План
Потоки спроса
Экономика
Данные
```

`SkladOzon.AppState` initial shape:

```javascript
{
  snapshot: null,
  staleSnapshot: false,
  section: 'plan',
  scenario: { horizonDays: 56, includeInbound: true },
  planView: { search: '', quickFilter: 'all', sort: null, page: 1, pageSize: 50, columns: [] },
  selectedDecisionKey: null,
  flowView: { mode: 'destination', metric: 'units', selectedKey: null, selectedRoute: null }
}
```

- [ ] **Step 1: Add RED static shell test**

Use Python `html.parser` plus text/attribute assertions to prove all four nav targets, stable loading/error/result regions, accessible labels and local script references. Assert there is no CDN URL, framework bundle or inline demand/economics formula.

- [ ] **Step 2: Add RED pure-state Node test**

Test hash route parse/serialize, filter resetting page to 1, page clamping, search clear, section Back/Forward state and `staleSnapshot=true` after scenario changes without mutating the current snapshot object.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_ui_state.py -q
```

- [ ] **Step 4: Map `DESIGN.md` to one runtime token block**

Define the approved canvas/surface/text/border/ozon/model/warning/success/danger/focus roles and approved radius/spacing values once under `:root`. Do not duplicate those semantic hex values in screen-local CSS.

- [ ] **Step 5: Implement hash routing and safe persistence**

URL/hash may preserve section/search/filter/sort/page/pageSize. `localStorage` may contain presentation preferences and scenario defaults only. Do not put file names/paths, raw reports, diagnostics payloads or buyer data in URL/localStorage.

- [ ] **Step 6: Implement shared owners once**

`components.js` defines `SkladOzon.DataTable`, `SearchField`, `Notice`, `DetailDrawer`, `ProgressPanel`, `RankedBars` and shared formatters. Screens call these owners instead of implementing equivalents.

- [ ] **Step 7: Run GREEN and syntax checks**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_ui_state.py -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/app.js
```

- [ ] **Step 8: Commit**

```bash
git add frontend tests/frontend
git commit -m "feat: add Product Completion application shell"
```

## Task 14: Build `Данные`, scenario controls, decision line, plan table and SKU drawer

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assets/css/app.css`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/js/components.js`
- Create: `tests/frontend/test_plan_view.py`
- Modify: `tests/api/test_analysis.py` only if the UI migration reveals a concrete backend contract defect.

**Behavior:**

- `Данные` owns file import, freshness, economics settings, manual mappings and diagnostics.
- `План` owns horizon, inbound flag and `Пересчитать план`; optimization is fixed to margin priority.
- A successful old snapshot remains visible during recalculation. Changed scenario is visibly `Требуется пересчёт`.
- Failed recalculation preserves the prior snapshot and labels it previous; file selections/settings remain.
- Decision line order is always `Ozon → Наша потребность → План`.
- Fast filters exactly: `Все`, `Есть расхождение`, `Вероятный дефицит`, `Дорогая логистика`, `Неполная экономика`, `Заблокировано`.
- Pagination default 50 with choices 25/50/100. Eight or more visible columns require the `Колонки` chooser.
- Drawer order exactly: Решение → Динамика спроса → Как исполняется спрос → Ozon vs наша модель → Экономика → Доказательства и диагностика.

- [ ] **Step 1: Add RED rendering-model tests**

Use a sanitized snapshot fixture. Assert decision-line values, different-horizon text, exact quick-filter row keys and absence of raw `RECOMMENDATION_DISTORTION_SIGNAL` from primary explanation text.

- [ ] **Step 2: Add RED drawer/focus-state tests**

Keep focus bookkeeping in pure helpers that Node can test: opening stores originating control id and returns drawer heading id; closing returns the stored origin id. Escape uses the same close path.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

- [ ] **Step 4: Move current import form into `Данные`**

Keep `/api/analysis/stream` transport and existing progress details. Add scenario fields to FormData. Keep duplicate-submit prevention.

- [ ] **Step 5: Render Plan exclusively from `snapshot.summary` and `snapshot.decision_rows`**

Frontend may format provided values into Russian numbers, percentages, p.p. and rubles. It may not derive demand, need, margins, route economics or allocation quantities.

- [ ] **Step 6: Implement Data mapping edit/save flow**

Load mappings through `GET /api/project/mappings`; save through `PUT`. Show validation errors inline. Do not auto-create fuzzy mappings.

- [ ] **Step 7: Remove raw stockout/distortion JSON from primary UI**

Technical codes remain only in drawer diagnostic disclosure and Data diagnostics.

- [ ] **Step 8: Verify browser interaction**

Record actual browser evidence in the PR description for nav, search clear, filters, sorting, page controls, column chooser, drawer open/close/Escape/focus return, 200% zoom, narrow width and reduced-motion behavior.

- [ ] **Step 9: Full PR7 verification**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 10: Commit**

```bash
git add frontend tests/frontend tests/api/test_analysis.py
git commit -m "feat: build Product Completion decision workflow"
```

**PR7 acceptance:** user imports data in `Данные`, recalculates a selected scenario, sees `Ozon → Наша потребность → План`, filters/sorts/pages the decision table, edits manual mappings and opens an explainable SKU/cluster drawer without raw JSON as the primary UX.

---

# PR8 — `Потоки спроса`, Economics view and end-to-end acceptance

## Task 15: Implement visual demand→fulfillment explorer

**Files:**
- Create: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/components.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/assets/css/app.css`
- Create: `tests/frontend/test_flow_view.py`
- Modify: `tests/decision/test_snapshot.py` only if a rendering test exposes a missing backend aggregate.

**Interfaces:**

Modes exactly:

```text
destination → По кластеру спроса
origin      → По кластеру отгрузки
sku         → По артикулу
```

Metrics exactly:

```text
units      → Штуки
share      → Доля спроса, %
margin_pp  → Потери маржи, п.п.
profit_rub → Потери прибыли, ₽
```

`SkladOzon.FlowView` consumes only `snapshot.flow_view_aggregates`. `SkladOzon.RankedBars` consumes one selected `FlowLinkView.sku_breakdown`.

- [ ] **Step 1: Add RED rendering-model test**

Given one destination with 78% local, 14% Kazan and 8% Samara, assert three exact link models with textual values. Selecting Kazan→Moscow must expose route units/share/economics and ranked SKU quantities summing exactly to link quantity.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/frontend/test_flow_view.py -q
```

- [ ] **Step 3: Implement cluster cards as comparison controls**

Each card shows total demand, local %, external %, donor count, route-cost effect and observed local-placement ruble effect when complete. Missing economics shows `Не рассчитано` and a reason, never zero.

- [ ] **Step 4: Implement focused hub-and-spoke SVG**

One selected destination/origin is central. Link width encodes the active metric, but every link has exact text in an adjacent accessible control/list. Do not build a global all-cluster Sankey/chord.

Every interactive node/link is keyboard selectable. Color and width are never the only carriers of meaning.

- [ ] **Step 5: Implement route context and ranked SKU bars**

Show units, destination share, current route cost ₽/% realization, current margin, local margin, delta p.p., observed ruble effect and completeness. Bars show SKU/article/product, units, route share, destination-demand share and available economics.

- [ ] **Step 6: Implement observed/clean fulfillment-evidence switch**

The switch changes fulfillment evidence only. It never reassigns destination demand. Display which evidence source drives the current business conclusion.

- [ ] **Step 7: Run GREEN and reconciliation**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/decision/test_snapshot.py -q
node --check frontend/assets/js/flow.js
```

- [ ] **Step 8: Commit**

```bash
git add frontend tests/frontend tests/decision/test_snapshot.py
git commit -m "feat: add visual demand fulfillment flow explorer"
```

## Task 16: Finish `Экономика` and prove complete Product Completion behavior

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/js/components.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/api/test_analysis.py`
- Create: `tests/integration/test_product_completion.py`
- Modify: `README.md` only after implementation acceptance is actually verified.

**Acceptance fixture requirements:** one sanitized multi-SKU/multi-cluster scenario containing:

- at least 8 completed weeks for one SKU/destination;
- one confirmed growth series;
- one historical route substitution that remains cleaning-eligible after current stock recovery;
- one donor cluster;
- one Ozon recommendation different from own need;
- one known inbound quantity;
- one physical warehouse cap;
- one route where local economics is better;
- one route where local economics is not better;
- two placements whose max-profit and max-margin ordering differ;
- one incomplete tariff/economics case proving fail-closed behavior.

- [ ] **Step 1: Write end-to-end RED integration test**

Post real-shaped sanitized files to `/api/analysis` and assert in one coherent snapshot: M1/M2/L, weekly rate, need, horizon comparability, Safe quantity, Calculated quantity, selected objective, route cost %, margin p.p., observed ruble effect, flow totals and human-readable explanations.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/integration/test_product_completion.py -q
```

If the test is already GREEN, verify it still contains every listed assertion; do not weaken the fixture merely to produce a failure.

- [ ] **Step 3: Implement `Экономика` from snapshot values only**

Expose realization, commission, acquiring, base/FBO delivery, expected logistics, advertising/services, Ozon withholdings/co-invest, VAT, income tax, total tax, cost, profit/unit, margin, ROI and completeness/blockers. Route comparison uses backend current/local values only.

- [ ] **Step 4: Remove frontend dependency on PR6 legacy analytical fields**

Once Plan/Flow/Economics/Data all read `snapshot`, delete compatibility rendering code. Backend legacy fields may remain only if an explicit external compatibility need is documented; otherwise remove them together with tests that require the obsolete top-level response.

- [ ] **Step 5: Run the full automated suite**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 6: Run authoritative Windows portable acceptance**

Use repository CI/Windows smoke unchanged unless a real Product Completion runtime defect requires an isolated fix. Confirm `start.bat`, offline reuse, loopback bind, UI/assets and data preservation.

- [ ] **Step 7: Run real-browser UI acceptance**

Record actual results for:

1. `План`, `Потоки спроса`, `Экономика`, `Данные` navigation and Back/Forward.
2. successful analysis, stable progress and failed recalculation preserving previous snapshot.
3. 25/50/100 pagination, search clear, filters, sorting and column chooser.
4. drawer open/close/Escape and focus return.
5. all three flow modes and all four metrics.
6. route selection and SKU breakdown exact totals.
7. observed vs clean evidence label.
8. 200% zoom and narrow viewport with all functions reachable.
9. keyboard access to nav, cluster cards, flow nodes/links, bars, drawer and table controls.
10. reduced motion and forced-colors/high-contrast operability.
11. no raw backend code as the only business explanation.
12. no external font/CDN/network dependency after runtime bootstrap.

If Frontend Design Premium runtime is available, run its strict audit and reconcile any durable visual/interaction correction with `DESIGN.md`/`UX-CONTRACT.md` in the same PR.

- [ ] **Step 8: Update README with verified release facts only**

State Product Completion implementation status and keep runtime instructions unchanged. Do not claim an acceptance item that was not actually executed.

- [ ] **Step 9: Final commit**

```bash
git add frontend tests README.md
git commit -m "feat: complete Ozon FBO Product Completion"
```

**PR8 acceptance:** all Product Completion design acceptance criteria are covered by automated checks plus recorded browser/runtime evidence; the product provides the approved decision workflow, visual flow analysis and detailed economics instead of a raw analytics table.

---

# Cross-PR review gates

Do not collapse these gates into one change set.

1. **After PR1:** validate stockout methodology before forecast/optimizer code depends on it.
2. **After PR2:** validate operational evidence, Ozon horizon and cluster identity before demand/economics comparison uses them.
3. **After PR3:** validate demand/need math numerically before economics prioritizes placements.
4. **After PR4:** validate route fallback and route economics before optimizer consumes placement values.
5. **After PR5:** validate Safe/Calculated and max-profit/max-margin semantics before they become product recommendations.
6. **After PR6:** freeze the immutable snapshot/API contract before frontend migration.
7. **After PR7:** validate decision workflow before adding the more visual flow mode.
8. **After PR8:** validate full product acceptance and runtime regression.

# Spec coverage self-check

- Historical stockout evidence and route cleaning: PR1.
- Availability enrichment, Ozon horizon and explicit cluster identity: PR2.
- Independent demand estimate, short-history fallback, arbitrary horizon, inbound, no buffer and Ozon comparison: PR3.
- Four-level route fallback, route cost %, local counterfactual, final-margin p.p. and observed-period ruble effect: PR4.
- Safe Plan, Calculated Plan, max-profit, max-margin and fixed per-SKU seller stock: PR5.
- Immutable snapshot, human explanations, freshness, mappings and streaming parity: PR6.
- `План`, `Данные`, decision line, table/filter/pagination/drawer, async resilience and design tokens: PR7.
- `Потоки спроса` destination/origin/SKU modes, four metrics, route drill-down, SKU bars, observed/clean evidence, `Экономика`, accessibility and final acceptance: PR8.

No Product Completion business formula is delegated to the frontend. No runtime/bootstrap redesign, Ozon API automation, ML forecasting, inferred lost demand, hidden safety stock, global Sankey/chord primary view, cloud/multi-user subsystem or unrelated backend rewrite is introduced by this plan.
