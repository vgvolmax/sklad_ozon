# Ozon FBO Product Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Product Completion layer so the application independently estimates destination demand, compares it with Ozon, models route economics, produces Safe and Calculated plans under max-profit/max-margin objectives, and exposes the result through the approved decision UI and `Потоки спроса` flow analysis.

**Architecture:** Preserve the current SCOZ-lite runtime and the working ingestion/economics core. Add small pure Python decision modules around the existing analytics/economics/supply contracts, then expose one immutable analysis snapshot through the existing FastAPI boundary. Only after the snapshot contract is complete, migrate the vanilla frontend to the four-section Product Completion UI governed by `DESIGN.md` and `UX-CONTRACT.md`.

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
- Every PR runs its focused tests plus `python -m pytest -q`, `node --check frontend/assets/js/app.js` when JS exists, and `git diff --check`. Runtime-related changes also require the authoritative Windows portable smoke.

---

# Target file map

## Existing files intentionally extended

- `backend/domain/signals.py` — stockout evidence contract only.
- `backend/analytics/stockout.py` — historical route-shift inference and availability corroboration.
- `backend/analytics/clean_routes.py` — route-cleaning eligibility and auditable exclusions.
- `backend/ingestion/availability.py` — operational stock/inbound/OOS evidence and Ozon horizon metadata.
- `backend/ingestion/normalization.py` — keep harmless text normalization and explicit resolution behavior.
- `backend/project.py` — existing Project JSON manual mapping persistence remains the persistence boundary.
- `backend/economics/tariffs.py` — add profile-source levels without changing tariff lookup math.
- `backend/supply/contracts.py` — add calculated need, plan family and objective contracts.
- `backend/supply/optimizer.py` — support Safe/Calculated ceilings and max-profit/max-margin ordering.
- `backend/application.py` — orchestrate pure modules; do not move formulas here.
- `backend/api.py` — validate scenario inputs and serialize the immutable decision snapshot.
- `frontend/index.html` — four-section shell and canonical Product Completion surfaces.
- `frontend/assets/css/app.css` — one semantic token block mapped from `DESIGN.md`.
- `frontend/assets/js/app.js` — application boot/orchestration only after UI split.

## New focused modules

- `backend/ingestion/cluster_resolution.py` — canonical explicit cluster resolution across imported report records.
- `backend/analytics/demand_estimate.py` — robust completed-week demand regime and weekly-rate estimate.
- `backend/analytics/route_profiles.py` — four-level logistics profile selection/fallback.
- `backend/analytics/flows.py` — exact origin→destination quantities and destination shares for business flow views.
- `backend/decision/__init__.py` — public Product Completion decision contracts.
- `backend/decision/need.py` — horizon forecast, FBO/inbound subtraction, Ozon comparison.
- `backend/decision/contracts.py` — scenario, comparison, decision-row and immutable snapshot dataclasses.
- `backend/decision/explanations.py` — localized human-readable reason generation from structured evidence.
- `backend/decision/snapshot.py` — assemble the immutable Product Completion snapshot from completed core results.
- `backend/economics/route_opportunity.py` — route-specific current vs local counterfactual economics.
- `frontend/assets/js/core.js` — router, immutable snapshot state, formatters and persisted presentation preferences.
- `frontend/assets/js/components.js` — canonical `DataTable`, `SearchField`, `Notice`, `DetailDrawer`, `RankedBars` owners.
- `frontend/assets/js/flow.js` — canonical `FlowView` owner only.

---

# PR1 — Historical stockout and clean-route correctness

## Task 1: Separate historical evidence, cleaning eligibility and current corroboration

**Files:**
- Modify: `backend/domain/signals.py`
- Modify: `backend/analytics/stockout.py`
- Test: `tests/analytics/test_stockout_distortion.py`

**Interfaces:**
- Consumes: existing `RouteProfile`, `AvailabilityRecord`, `StockoutThresholds`.
- Produces: `StockoutSignal.historical_evidence_strength: SignalConfidence`, `StockoutSignal.route_cleaning_eligible: bool`, existing `availability_corroboration`, existing displayed `confidence`.

- [ ] **Step 1: Write the failing historical-evidence regression**

Add a case where the route shift meets all strong thresholds but current destination availability is positive. Assert the signal is still cleaning-eligible.

```python
def test_strong_historical_shift_is_cleaning_eligible_with_current_stock_recovered():
    signal = _detect_strong_shift(current_available=7)
    assert signal.historical_evidence_strength is SignalConfidence.HIGH
    assert signal.route_cleaning_eligible is True
    assert signal.availability_corroboration is AvailabilityCorroboration.NEUTRAL
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/analytics/test_stockout_distortion.py::test_strong_historical_shift_is_cleaning_eligible_with_current_stock_recovered -q
```

Expected: FAIL because the current contract has no separate historical strength/cleaning flag and positive current stock only yields MEDIUM confidence.

- [ ] **Step 3: Extend the signal contract without deleting current fields**

Use the following shape so existing distortion code can continue reading `confidence` while clean-route logic gets an explicit historical decision:

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

For the already-approved strong threshold set, `historical_evidence_strength = HIGH` and `route_cleaning_eligible = True`. Current zero availability may add corroboration/reasoning but is not required for eligibility.

- [ ] **Step 4: Keep displayed confidence auditable**

Implement one explicit helper in `stockout.py`:

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

Do not let a current positive snapshot downgrade strong historical evidence.

- [ ] **Step 5: Run focused GREEN and regressions**

```bash
python -m pytest tests/analytics/test_stockout_distortion.py -q
python -m pytest tests/analytics -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/domain/signals.py backend/analytics/stockout.py tests/analytics/test_stockout_distortion.py
git commit -m "fix: separate stockout history from current corroboration"
```

## Task 2: Make clean-route exclusion depend on explicit cleaning eligibility

**Files:**
- Modify: `backend/analytics/clean_routes.py`
- Test: `tests/analytics/test_clean_routes.py`

**Interfaces:**
- Consumes: `StockoutSignal.route_cleaning_eligible` from Task 1.
- Produces: same `CleanRouteResult` public shape; exclusion evidence stays auditable.

- [ ] **Step 1: Add RED regression**

```python
def test_clean_routes_exclude_strong_historical_shift_even_when_current_availability_is_neutral():
    result = build_clean_route_profile(observed_profile, (strong_neutral_signal,))
    assert result.excluded_routes
    assert all(cell.iso_week != contaminated_week for cell in result.clean_routes)
```

Also add a negative test proving a non-cleaning-eligible signal remains observed.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_clean_routes.py -q
```

Expected: at least the neutral-current-stock case fails under the old minimum-HIGH-confidence policy.

- [ ] **Step 3: Replace confidence-gated exclusion with explicit eligibility**

Build the exclusion lookup from `signal.route_cleaning_eligible`. Preserve `stockout_confidence` and `observed_week` in `ExcludedRouteEvidence`; do not delete observed history.

- [ ] **Step 4: Prove demand history was not changed**

Run the existing demand-route tests together with clean-route tests:

```bash
python -m pytest tests/analytics/test_clean_routes.py tests/analytics/test_demand_routes.py -q
```

- [ ] **Step 5: Full PR1 verification and commit**

```bash
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

```bash
git add backend/analytics/clean_routes.py tests/analytics/test_clean_routes.py
git commit -m "fix: clean routes from historical substitution evidence"
```

**PR1 acceptance:** strong historical route substitution is cleanable even after stock recovery; current availability remains corroborating evidence; destination demand aggregation is unchanged.

---

# PR2 — Operational evidence, horizon metadata and canonical cluster identity

## Task 3: Retain inbound/OOS/product evidence from the real availability report

**Files:**
- Modify: `backend/ingestion/availability.py`
- Test: `tests/ingestion/test_availability.py`
- Test fixture use: `tests/api/test_analysis.py::_real_four_files`

**Interfaces:**
- Produces additions to `AvailabilityRecord`:

```python
product_name: str = ""
days_without_stock: int | None = None
inbound_quantity: int | None = None
```

- Produces `ImportResult.meta.recommendation_horizon_days` when the Ozon header contains a horizon such as `56 дней`.

- [ ] **Step 1: Add RED parsing test using the real operational headers**

Assert one row with `Дней без остатка за 28 дней = 3`, `Товары в пути на склад озон, шт = 11`, and recommendation header `...на 56 дней` yields exactly those values and horizon 56.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/ingestion/test_availability.py -q
```

- [ ] **Step 3: Parse optional evidence fail-closed**

Use the existing non-negative integer parser semantics. Blank optional values return `None`; explicit zero stays `0`; malformed/negative values produce `INVALID_NUMBER` on the specific field and skip the malformed row.

Extract one recommendation horizon from matched recommendation headers with a regex equivalent to:

```python
_RECOMMENDATION_HORIZON = re.compile(r"(?:на|за)\s+(\d+)\s+дн", re.IGNORECASE)
```

If multiple matched recommendation columns expose conflicting horizons, emit one structural error `CONFLICTING_RECOMMENDATION_HORIZON` and leave the horizon unknown rather than choosing one.

- [ ] **Step 4: Enrich corroboration without claiming historical inventory**

Update stockout availability evidence so `days_without_stock > 0` may produce `SUPPORTS`. Do not use current `days_without_stock == 0` as historical contradiction unless the report period explicitly overlaps the observed stockout week; without overlap it remains `NEUTRAL`.

- [ ] **Step 5: Run focused GREEN**

```bash
python -m pytest tests/ingestion/test_availability.py tests/analytics/test_stockout_distortion.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/ingestion/availability.py backend/analytics/stockout.py tests/ingestion/test_availability.py tests/analytics/test_stockout_distortion.py
git commit -m "feat: retain availability evidence and Ozon horizon"
```

## Task 4: Add one explicit cluster-resolution pass before analytics

**Files:**
- Create: `backend/ingestion/cluster_resolution.py`
- Modify: `backend/ingestion/__init__.py`
- Test: `tests/ingestion/test_cluster_resolution.py`
- Modify later integration point only after focused tests: `backend/api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ClusterResolutionResult:
    availability: tuple[AvailabilityRecord, ...]
    restrictions: tuple[RestrictionRecord, ...]
    orders: tuple[OrderRecord, ...]
    tariffs: tuple[TariffRow, ...]
    diagnostics: tuple[ImportDiagnostic, ...]


def resolve_analysis_clusters(
    availability: Iterable[AvailabilityRecord],
    restrictions: Iterable[RestrictionRecord],
    orders: Iterable[OrderRecord],
    tariffs: Iterable[TariffRow],
    manual_mappings: Mapping[str, str],
) -> ClusterResolutionResult:
    ...
```

Resolution rules:

1. Build the canonical exact-label universe from tariff origin/destination labels plus explicit manual-mapping targets.
2. Exact normalized/casefold match to one canonical label resolves automatically.
3. Manual mapping overrides exact aliases.
4. Never translate, shorten, geographically guess or fuzzy-match.
5. A label that cannot be resolved produces `UNRESOLVED_CLUSTER`; preserve the raw normalized value in diagnostic context but remove/block the affected analytical record from resolved outputs.
6. A manual target absent from the canonical universe produces `INVALID_MANUAL_CLUSTER_TARGET`.

- [ ] **Step 1: Write explicit RED cases**

Cover exact case-insensitive identity, manual override, unresolved order destination, unresolved availability cluster, and invalid manual target.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/ingestion/test_cluster_resolution.py -q
```

- [ ] **Step 3: Implement with `dataclasses.replace` only**

Do not teach individual importers separate geography rules. `resolve_analysis_clusters()` is the one semantic identity pass after syntactic parsing.

- [ ] **Step 4: Wire into `run_analysis_pipeline()` with an empty mapping first**

Call the resolver after all reports are parsed and before article/economics analysis. Add resolver diagnostics to the existing diagnostic collection. This integration must preserve current exact-label fixtures unchanged.

- [ ] **Step 5: Verify Project JSON already round-trips manual mappings**

Run the existing project tests. Add a regression only if current coverage does not prove exact persistence of `manual_cluster_mappings`.

```bash
python -m pytest tests/ingestion/test_cluster_resolution.py tests/test_project.py tests/api/test_analysis.py -q
```

- [ ] **Step 6: Full PR2 verification and commit**

```bash
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

```bash
git add backend/ingestion backend/api.py tests/ingestion tests/test_project.py tests/api/test_analysis.py
git commit -m "feat: resolve cluster identity before analysis"
```

**PR2 acceptance:** real availability retains FBO, FBS, inbound and days-without-stock evidence; Ozon horizon is explicit; cluster identity has one non-fuzzy semantic resolution path.

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


def estimate_destination_demand(demand: DemandResult) -> tuple[DemandEstimate, ...]:
    ...
```

Implementation rules:

- Use completed weeks from `DemandResult.window.included_weeks`, sorted chronologically.
- For an existing `SKU × destination` series, a completed source week with no net-demand row contributes zero, not a missing observation.
- Use only the latest 8 eligible weeks for the full model.
- 8+ weeks: `M1 = median(first 4)`, `M2 = median(last 4)`, `L = latest`.
- `M1 > 0`: growth `> +10%`, decline `< -10%`, stable inclusive inside ±10%.
- `M1 == 0 and M2 > 0`: `TRANSITION`, no infinite percentage.
- Growth confirmation: `L > 1.10 × M2`; decline confirmation: `L < 0.90 × M2`; stable confirmation: `0.90 × M2 <= L <= 1.10 × M2`.
- Confirmed growth/decline: `raw_adjustment = 0.5 × (L - M2)`; applied adjustment clamped to ±20% of `M2`.
- Stable/unconfirmed growth/decline/transition: weekly rate is the baseline median with zero applied adjustment.
- 4–7 weeks: median of all eligible weeks, no trend adjustment, confidence at most MEDIUM.
- 1–3 weeks: median of available weeks, no trend adjustment, LOW confidence.
- 0 weeks: no estimate; do not emit a fake zero-rate row.

- [ ] **Step 1: Write the parameterized RED suite**

Include exact cases for growth confirmation, decline, stable ±10% boundaries, impulse cap, contradiction, 4–7 fallback, 1–3 fallback, transition from zero, current-week exclusion inherited from `aggregate_demand`, and a substitution week that remains destination demand.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_demand_estimate.py -q
```

- [ ] **Step 3: Implement using `Decimal` and `statistics.median` over integer quantities converted to Decimal**

Keep estimator pure; it consumes `DemandResult` only and knows nothing about Ozon recommendations or economics.

- [ ] **Step 4: Run GREEN plus demand regressions**

```bash
python -m pytest tests/analytics/test_demand_estimate.py tests/analytics/test_demand_routes.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/analytics/demand_estimate.py backend/analytics/__init__.py tests/analytics/test_demand_estimate.py
git commit -m "feat: estimate current destination demand regime"
```

## Task 6: Compute horizon need and Ozon comparison without rescaling Ozon

**Files:**
- Create: `backend/decision/__init__.py`
- Create: `backend/decision/need.py`
- Create: `backend/decision/contracts.py`
- Test: `tests/decision/test_need.py`

**Interfaces:**

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
    objective: str

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

- [ ] **Step 1: Add RED tests for exact quantity math**

```python
def test_need_rounds_up_only_after_stock_and_inbound_subtraction():
    result = calculate_need(weekly_rate=Decimal("10"), horizon_days=10,
                            fbo_stock=3, inbound_qty=2, include_inbound=True)
    assert result.raw_demand_forecast == Decimal("100") / Decimal("7")
    assert result.calculated_need_qty == 10
```

Also test inbound off, zero floor, unknown FBO stock, unknown inbound when inclusion is enabled, missing own estimate, same/different/unknown Ozon horizon, and Ozon zero without division-by-zero delta percent.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/decision/test_need.py -q
```

- [ ] **Step 3: Implement pure helpers**

```python
def forecast_horizon(weekly_rate: Decimal, horizon_days: int) -> Decimal:
    return weekly_rate * Decimal(horizon_days) / Decimal(7)


def integer_need(raw_forecast: Decimal, fbo_stock: int, inbound: int) -> int:
    raw_need = raw_forecast - Decimal(fbo_stock) - Decimal(inbound)
    return max(0, int(raw_need.to_integral_value(rounding=ROUND_CEILING)))
```

`include_inbound=False` means inbound subtraction is exactly zero even if a known inbound value is displayed. `include_inbound=True` with unknown inbound blocks the calculated need instead of assuming zero.

- [ ] **Step 4: Implement Ozon comparison without rescaling**

`delta_qty = calculated_need_qty - ozon_recommended_qty` may be displayed even on different horizons, but `comparability` must explicitly label the mismatch. `delta_pct` is `None` when Ozon recommendation is `0` or missing.

- [ ] **Step 5: Run GREEN and full PR3 regression**

```bash
python -m pytest tests/decision/test_need.py tests/analytics/test_demand_estimate.py -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add backend/decision tests/decision
git commit -m "feat: calculate independent horizon need"
```

**PR3 acceptance:** the backend can explainably produce current weekly demand, arbitrary-horizon forecast and calculated need independently of Ozon; no safety buffer and no Ozon horizon rescaling exist.

---

# PR4 — Four-level route profiles and route-specific economics

## Task 7: Implement auditable route-profile selection

**Files:**
- Create: `backend/analytics/route_profiles.py`
- Modify: `backend/economics/tariffs.py`
- Modify: `backend/economics/__init__.py`
- Test: `tests/analytics/test_route_profiles.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**

Extend `RouteProfileSource` exactly with:

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
    confidence: RouteConfidence
    profile: tuple[RouteDistributionCell, ...]


def select_route_profile(
    sku: str,
    origin_cluster_id: str,
    clean: CleanRouteResult,
    observed: RouteProfile,
) -> RouteProfileSelection:
    ...
```

Fallback order is fixed and tested. Origin-all-SKUs/global fallbacks create synthetic profile cells with the requested target SKU and candidate origin but preserve aggregate destination shares and sample size. Do not renormalize tariff uncovered share later.

- [ ] **Step 1: Add four explicit RED tests, one per fallback level**

The global test must use an origin with no direct history and assert the synthetic profile still uses that candidate origin for tariff lookup while destination proportions come from global fulfilled history.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/analytics/test_route_profiles.py -q
```

- [ ] **Step 3: Implement selector and extend source enum**

Do not change `expected_logistics()` tariff matching except to accept the new enum values in `LogisticsContext`.

- [ ] **Step 4: Replace the `clean_profile or observed_profile` selection in `application.py` only after selector tests pass**

Each resulting logistics record must expose the actual fallback source, sample quantity and existing coverage diagnostics.

- [ ] **Step 5: Run focused GREEN**

```bash
python -m pytest tests/analytics/test_route_profiles.py tests/economics/test_tariffs.py tests/api/test_analysis.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/analytics/route_profiles.py backend/economics/tariffs.py backend/economics/__init__.py backend/application.py tests/analytics/test_route_profiles.py tests/economics/test_tariffs.py tests/api/test_analysis.py
git commit -m "feat: add complete route profile fallback hierarchy"
```

## Task 8: Model each observed origin→destination route against a local counterfactual

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

- [ ] **Step 1: Add RED flow reconciliation tests**

Assert all origin quantities into one destination sum to destination demand and destination shares sum to 1 for each `SKU × destination` with fulfilled demand.

- [ ] **Step 2: Add RED route-economics test**

Construct one `Казань → Москва` tariff and one local `Москва → Москва` tariff. Assert route cost percentage uses realization, margin delta is in percentage points (`(local_margin-current_margin) * 100`), and observed opportunity equals `profit_delta_per_unit × observed_qty`.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/analytics/test_flows.py tests/economics/test_route_opportunity.py -q
```

- [ ] **Step 4: Build route-specific one-cell logistics profiles**

For a selected route, create a one-cell profile with `share=Decimal("1")` so `calculate_unit_economics()` receives the exact route tariff rather than the candidate origin's blended expected fee. Local counterfactual is the same SKU/destination with `origin_cluster_id = destination_cluster_id`.

If local placement is physically infeasible, tariff coverage is not complete, realization is zero/unknown, or unit economics is incomplete, return `complete=False` and exact reason codes; never emit zero benefit.

- [ ] **Step 5: Keep historical and forecast ₽ values separate**

This task produces `observed_profit_opportunity_rub` only. Do not manufacture forecast opportunity until a later caller has a valid forecast quantity and route-share basis.

- [ ] **Step 6: Run GREEN and PR4 verification**

```bash
python -m pytest tests/analytics/test_flows.py tests/economics/test_route_opportunity.py tests/economics -q
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 7: Commit**

```bash
git add backend/analytics/flows.py backend/economics/route_opportunity.py backend/economics/__init__.py tests/analytics/test_flows.py tests/economics/test_route_opportunity.py
git commit -m "feat: model route economics and local opportunity"
```

**PR4 acceptance:** every placement can select a logistics profile through all four fallback levels; observed fulfillment routes expose exact current-vs-local modeled economics with explicit incompleteness.

---

# PR5 — Safe/Calculated plans and scenario allocator

## Task 9: Extend placement contracts with independent need

**Files:**
- Modify: `backend/supply/contracts.py`
- Modify: `backend/supply/placement.py`
- Test: `tests/supply/test_placement.py`

**Interfaces:**

Add:

```python
class PlanFamily(str, Enum):
    SAFE = "safe"
    CALCULATED = "calculated"

class AllocationObjective(str, Enum):
    MAX_PROFIT = "max_profit"
    MAX_MARGIN = "max_margin"
```

Add `calculated_need_qty: int | None` to `PlacementInput` and `PlacementAssessment`. `None` means the independent need is incomplete and blocks Calculated Plan for that cluster; it is not zero.

- [ ] **Step 1: Add RED placement contract tests**

Assert need identity is preserved through `compare_placements()`, negative need is rejected, and `None` remains incomplete.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 3: Implement minimal contract propagation**

Do not change physical feasibility logic. Existing warehouse restrictions/max quantity semantics stay authoritative.

- [ ] **Step 4: Run GREEN**

```bash
python -m pytest tests/supply/test_placement.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/supply/contracts.py backend/supply/placement.py tests/supply/test_placement.py
git commit -m "feat: carry calculated need into placement assessments"
```

## Task 10: Generalize optimizer for two plan families and two objectives

**Files:**
- Modify: `backend/supply/optimizer.py`
- Modify: `backend/supply/__init__.py`
- Test: `tests/supply/test_optimizer.py`

**Interfaces:**

Change public call to:

```python
def optimize_allocations(
    candidates: Iterable[PlacementAssessment],
    available_stock: int,
    thresholds: OptimizerThresholds,
    *,
    plan_family: PlanFamily,
    objective: AllocationObjective,
) -> OptimizationResult:
    ...
```

Extend `OptimizationResult` with `plan_family` and `objective` while preserving `objective_profit` as total modeled plan profit for reporting compatibility.

Ceilings:

```python
safe_ceiling = min(ozon_recommended_qty, calculated_need_qty, physical_ceiling)
calculated_ceiling = min(calculated_need_qty, physical_ceiling)
```

Treat `physical_ceiling=None` as unbounded by warehouse quantity, not zero.

Eligibility remains blocked by incomplete economics and configured minimum profit/margin/ROI thresholds.

Ordering:

1. chosen objective (`profit_per_unit` descending or `margin_rate` descending);
2. higher route confidence;
3. lower distortion confidence/risk;
4. larger `calculated_need_qty`;
5. stable `cluster_id`.

- [ ] **Step 1: Write RED tests for plan ceilings**

Include one candidate where Ozon=5, need=12, physical=20 and assert Safe ceiling 5 vs Calculated ceiling 12.

- [ ] **Step 2: Write RED objective divergence test**

Use two clusters where cluster A has higher profit/unit but lower margin and cluster B has lower profit/unit but higher margin. With stock insufficient for both, assert `MAX_PROFIT` and `MAX_MARGIN` allocate to different first clusters.

- [ ] **Step 3: Add deterministic-tie and unallocated-remainder tests**

Prove identical inputs always produce the same decisions; stock above all eligible need remains unallocated.

- [ ] **Step 4: Run RED**

```bash
python -m pytest tests/supply/test_optimizer.py -q
```

- [ ] **Step 5: Implement objective-specific stable sort without Decimal arithmetic in keys**

Preserve the current least-significant-first stable-sort technique. For max-margin, reject candidates whose margin is unavailable through existing eligibility classification.

- [ ] **Step 6: Produce both plans in application orchestration**

For each SKU and selected objective, call the optimizer twice with the same seller stock and assessments: once `SAFE`, once `CALCULATED`. Do not mutate or subtract Safe allocation before calculating Calculated; they are alternative plans, not sequential reservations.

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

**PR5 acceptance:** one fixed per-SKU seller stock can be allocated under max-profit or max-margin; Safe and Calculated plans are alternative outputs under the same objective; Calculated Plan is independent of Ozon quantity.

---

# PR6 — Immutable decision snapshot and API contract

## Task 11: Assemble business-facing decision contracts and explanations

**Files:**
- Complete: `backend/decision/contracts.py`
- Create: `backend/decision/explanations.py`
- Create: `backend/decision/snapshot.py`
- Modify: `backend/decision/__init__.py`
- Test: `tests/decision/test_snapshot.py`

**Interfaces:**

Define at minimum:

```python
@dataclass(frozen=True, slots=True)
class DecisionRow:
    sku: str
    article: str
    product_name: str
    destination_cluster_id: str
    demand: DemandEstimate | None
    need: NeedComparison
    safe_plan_qty: int
    calculated_plan_qty: int
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
    report_meta: dict[str, object]
    freshness_warnings: tuple[str, ...]
    scenario: ScenarioSettings
    input_statuses: dict[str, object]
    summary: dict[str, object]
    decision_rows: tuple[DecisionRow, ...]
    demand_estimates: tuple[DemandEstimate, ...]
    observed_routes: object
    clean_routes: object
    stockout_signals: tuple[StockoutSignal, ...]
    distortion_signals: tuple[RecommendationDistortionSignal, ...]
    route_economics: tuple[RouteOpportunity, ...]
    unit_economics: tuple[UnitEconomicsResult, ...]
    safe_allocations: tuple[OptimizationResult, ...]
    calculated_allocations: tuple[OptimizationResult, ...]
    flow_view_aggregates: dict[str, object]
    diagnostics: tuple[AnalysisDiagnostic, ...]
```

The exact nested types may be focused dataclasses instead of `object`/dict in implementation; the serialized top-level field names above are fixed.

- [ ] **Step 1: Add RED snapshot identity/reconciliation tests**

Assert one `SKU × destination` row joins the correct demand estimate, Ozon recommendation, own need, Safe allocation and Calculated allocation. Assert raw backend codes are not the only explanation strings.

- [ ] **Step 2: Add RED flow aggregate tests**

`flow_view_aggregates` must support destination, origin and SKU viewpoints and exact route-to-SKU breakdown totals. Assert each selected route breakdown sums to route quantity.

- [ ] **Step 3: Implement localized explanations in Python**

Examples are generated from structured values, not stored as opaque magic strings in frontend:

```python
"Рекомендация Ozon может быть занижена: часть спроса кластера исполнялась из других кластеров во время вероятного дефицита."
"Рост спроса подтверждается последней полной неделей."
"Горизонты различаются: Ozon 56 дней, наш расчёт 67 дней."
```

Keep technical codes alongside for diagnostics.

- [ ] **Step 4: Build deterministic summaries**

Summary must include at least total Ozon recommendation, total calculated need, total Safe Plan, total Calculated Plan, selected-objective expected profit, and count of disagreement/incomplete rows. Do not sum percentages.

- [ ] **Step 5: Run GREEN**

```bash
python -m pytest tests/decision/test_snapshot.py -q
```

- [ ] **Step 6: Commit**

```bash
git add backend/decision tests/decision
git commit -m "feat: assemble Product Completion decision snapshot"
```

## Task 12: Wire scenario inputs, mappings, freshness and snapshot serialization through FastAPI

**Files:**
- Modify: `backend/application.py`
- Modify: `backend/api.py`
- Modify: `backend/project.py` only where a minimal mapping endpoint needs existing persistence helpers
- Test: `tests/api/test_analysis.py`
- Test: `tests/api/test_project.py` if new project endpoints are added

**Interfaces:**

Required multipart scenario fields:

```text
horizon_days=<positive integer>
include_inbound=true|false
optimization_objective=max_profit|max_margin
```

Default compatibility values for clients that omit the new fields during the migration PR:

```text
horizon_days = Ozon recommendation horizon when uniquely known, otherwise 56
include_inbound = true
optimization_objective = max_profit
```

Expose a minimal local mapping API backed by the existing `data/project.json` Project JSON boundary:

```text
GET /api/project/mappings
PUT /api/project/mappings
```

`PUT` accepts only an object of nonblank string source→target mappings, validates through Project loading/saving rules, and atomically saves. Do not expose raw reports or PII through Project JSON.

- [ ] **Step 1: Add RED validation tests for scenario inputs**

Reject zero/negative horizon, non-integer horizon, invalid boolean and unsupported objective with stable error codes/fields.

- [ ] **Step 2: Add RED mapping persistence test**

Write one mapping, reload it, and prove the next analysis resolves the mapped raw label. Use a temporary project path injected in tests; never mutate developer `data/`.

- [ ] **Step 3: Add RED immutable-snapshot API assertions**

Both `/api/analysis` and `/api/analysis/stream` must return the same `snapshot` payload except volatile `snapshot_id`, `created_at` and import timestamps. Preserve the current streamed progress protocol.

- [ ] **Step 4: Keep the legacy top-level analytical fields for one UI migration PR only**

During PR6, return `snapshot` plus existing fields so current frontend remains usable. Mark the legacy shape internally as compatibility output; do not make new frontend code depend on it.

- [ ] **Step 5: Implement freshness/comparability warnings**

Populate report metadata from existing `ReportMeta`. If report periods/horizons are missing, expose unknown rather than guessing. If Ozon horizon differs from selected horizon, the decision row gets comparability warning but analysis still completes when other evidence is complete.

- [ ] **Step 6: Run focused GREEN and API parity**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_project.py tests/decision -q
```

- [ ] **Step 7: Full PR6 verification**

```bash
python -m pytest -q
node --check frontend/assets/js/app.js
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add backend/application.py backend/api.py backend/project.py tests/api
git commit -m "feat: expose immutable Product Completion snapshot"
```

**PR6 acceptance:** backend/API fully owns Product Completion math and explanations; one successful run yields an immutable snapshot with scenario/report context; manual mappings persist through Project JSON; current frontend still works until PR7.

---

# PR7 — Product shell, Data workflow and Plan decision UI

Before any PR7 edit, reread `DESIGN.md` and `UX-CONTRACT.md` from current branch. If Frontend Design Premium runtime is available, run its strict static audit before and after this PR and record actual findings in the PR description.

## Task 13: Introduce the canonical UI shell, tokens and immutable client state

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assets/css/app.css`
- Create: `frontend/assets/js/core.js`
- Create: `frontend/assets/js/components.js`
- Modify: `frontend/assets/js/app.js`
- Test: `tests/frontend/test_product_shell.py`
- Test: `tests/frontend/test_ui_state.py`

**Interfaces:**

Top-level sections exactly:

```text
План
Потоки спроса
Экономика
Данные
```

`SkladOzon.AppState` owns:

```javascript
{
  snapshot: null,
  staleSnapshot: false,
  section: 'plan',
  scenario: { horizonDays: 56, includeInbound: true, objective: 'max_profit' },
  planView: { search: '', quickFilter: 'all', sort: null, page: 1, pageSize: 50, columns: [] },
  selectedDecisionKey: null,
  flowView: { mode: 'destination', metric: 'units', selectedKey: null, selectedRoute: null }
}
```

- [ ] **Step 1: Add RED static contract test**

Use Python `html.parser`/text assertions to prove all four nav sections, stable result regions, accessible labels and local script references exist; assert no CDN URL, framework bundle or inline business formula.

- [ ] **Step 2: Add RED pure-state Node test**

Test hash route parse/serialize, filter page reset, page clamping, search clear and `staleSnapshot=true` after scenario changes without mutating the current snapshot object.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/frontend/test_product_shell.py tests/frontend/test_ui_state.py -q
```

- [ ] **Step 4: Map `DESIGN.md` into one CSS token block**

Define the approved semantic variables once under `:root`, including canvas/surface/text/border/ozon/model/warning/success/danger/focus and approved radii/spacing. No duplicate screen-local hex values for those roles.

- [ ] **Step 5: Implement hash routing and persistent presentation preferences**

Use hash route state for section/search/filter/sort/page/pageSize where safe. Store only presentation preferences and scenario defaults in `localStorage`; never put file names/paths, raw reports or buyer data in URL/localStorage.

- [ ] **Step 6: Implement canonical shared owners once**

`components.js` defines `SkladOzon.DataTable`, `SearchField`, `Notice`, `DetailDrawer`, `ProgressPanel` and shared formatting helpers. Screen code calls them rather than creating equivalent screen-local controls.

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
- Test: `tests/frontend/test_plan_view.py`
- Test: `tests/api/test_analysis.py` only if UI migration exposes a backend compatibility gap

**Interfaces/behavior:**

- `Данные` owns file import, freshness, economics settings, mappings and diagnostics.
- `План` owns horizon/inbound/objective controls and `Пересчитать план`.
- Old successful snapshot remains visible during recalculation; changed scenario visibly marks `Требуется пересчёт`.
- On failure the old snapshot remains and is labelled previous; selected files/settings are preserved.
- Decision line order is always `Ozon → Наша потребность → План`.
- Main table fast filters exactly: `Все`, `Есть расхождение`, `Вероятный дефицит`, `Дорогая логистика`, `Неполная экономика`, `Заблокировано`.
- Pagination default 50 with 25/50/100 choices; 8+ visible columns require column chooser.
- Drawer order exactly: Decision → Demand dynamics → Fulfillment → Ozon vs model → Economics → Evidence/diagnostics.

- [ ] **Step 1: Add RED rendering-state tests over a sanitized snapshot fixture**

Assert decision line displays all three values, different-horizon warning is text-visible, filter predicates return exact row keys, and raw `RECOMMENDATION_DISTORTION_SIGNAL` is absent from the primary rendered explanation.

- [ ] **Step 2: Add RED drawer order/focus-state tests on pure component state helpers**

Without adding a DOM dependency, keep focus bookkeeping in explicit functions that can be Node-tested: opening stores origin control id and targets drawer heading id; close returns stored origin id.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/frontend/test_plan_view.py -q
```

- [ ] **Step 4: Move the existing import form into `Данные` without changing the streaming transport**

Continue using `/api/analysis/stream`; update request FormData with the scenario fields. Keep current progress detail labels and duplicate-submit prevention.

- [ ] **Step 5: Render plan only from `snapshot.decision_rows` and summary**

Frontend may format decimals/percent/currency but may not derive forecast, margins, route deltas or allocation quantities.

- [ ] **Step 6: Remove raw stockout/distortion JSON from the primary screen**

Technical codes remain inside the drawer diagnostics disclosure and Data diagnostics area only.

- [ ] **Step 7: Verify keyboard/text behavior manually in a real browser**

Record evidence in the PR description for: nav, search clear, quick filters, sort, page controls, column chooser, drawer open/close/Escape, focus return, 200% zoom, narrow width and `prefers-reduced-motion`.

- [ ] **Step 8: Full PR7 verification and commit**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/app.js
git diff --check
```

```bash
git add frontend tests/frontend tests/api/test_analysis.py
git commit -m "feat: build Product Completion decision workflow"
```

**PR7 acceptance:** user can import data in `Данные`, recalculate one scenario, inspect `Ozon → Наша потребность → План`, filter/sort/page the decision table and open an explainable SKU/cluster drawer without seeing raw JSON as the primary UX.

---

# PR8 — `Потоки спроса`, Economics view and end-to-end Product Completion acceptance

## Task 15: Implement the visual demand→fulfillment explorer

**Files:**
- Create: `frontend/assets/js/flow.js`
- Modify: `frontend/assets/js/components.js`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/assets/css/app.css`
- Test: `tests/frontend/test_flow_view.py`
- Test: `tests/decision/test_snapshot.py` for any missing aggregate contract discovered by rendering tests

**Interfaces:**

Modes exactly:

```text
destination → По кластеру спроса
origin      → По кластеру отгрузки
sku         → По артикулу
```

Metrics exactly:

```text
units        → Штуки
share        → Доля спроса, %
margin_pp    → Потери маржи, п.п.
profit_rub   → Потери прибыли, ₽
```

`SkladOzon.FlowView` receives only `snapshot.flow_view_aggregates`; `SkladOzon.RankedBars` receives the selected route SKU breakdown.

- [ ] **Step 1: Add RED pure rendering-model tests**

Given one destination with 78% local, 14% Kazan and 8% Samara, assert exactly three link models with exact text equivalents. Selecting Kazan→Moscow must expose its units/share/economics and ranked SKU rows whose quantities sum to route quantity.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/frontend/test_flow_view.py -q
```

- [ ] **Step 3: Implement cluster cards as comparison controls, not KPI decoration**

Each card shows demand, local %, external %, donor count, route-cost effect and observed local-placement opportunity when complete. Missing economics displays `Не рассчитано` plus reason; never zero.

- [ ] **Step 4: Implement focused hub-and-spoke SVG**

One selected destination/origin is central. Use link width for the active metric but always render exact text in an adjacent accessible list/control. Do not implement a global all-cluster Sankey/chord.

Every interactive node/link must be keyboard selectable. SVG color/width cannot be the only carrier of value.

- [ ] **Step 5: Implement route context and ranked bars**

Route context displays current route vs local counterfactual: units, destination share, route cost ₽/% realization, current margin, local margin, delta p.p., observed opportunity ₽ and completeness. Ranked bars show SKU/article, quantity, route share, destination-demand share and economics.

- [ ] **Step 6: Implement observed/clean evidence switch**

The switch changes fulfillment evidence only. It must not reassign destination demand. Display which evidence source drives the business conclusion.

- [ ] **Step 7: Run GREEN plus snapshot reconciliation**

```bash
python -m pytest tests/frontend/test_flow_view.py tests/decision/test_snapshot.py -q
node --check frontend/assets/js/flow.js
```

- [ ] **Step 8: Commit**

```bash
git add frontend tests/frontend tests/decision/test_snapshot.py
git commit -m "feat: add visual demand fulfillment flow explorer"
```

## Task 16: Finish Economics surface and full acceptance coverage

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/assets/js/app.js`
- Modify: `frontend/assets/js/components.js`
- Modify: `frontend/assets/css/app.css`
- Modify: `tests/api/test_analysis.py`
- Create: `tests/integration/test_product_completion.py`
- Modify: `README.md` only after implementation is actually complete

**Acceptance fixture:** build one sanitized multi-SKU/multi-cluster scenario with:

- at least 8 completed weeks for one SKU/destination;
- one confirmed growth series;
- one historical route substitution that is clean-route eligible after current stock recovery;
- one donor cluster;
- one Ozon recommendation that differs from own need;
- one known inbound quantity;
- one physical warehouse cap;
- one route where local economics is better;
- two placements whose max-profit and max-margin ordering differ;
- one incomplete tariff/economics case to prove fail-closed UI state.

- [ ] **Step 1: Write the end-to-end RED integration test**

Post real-shaped sanitized files to `/api/analysis` and assert all Product Completion acceptance values in one coherent snapshot: `M1/M2/L`, need, horizon comparability, Safe vs Calculated quantities, objective, route opportunity and flow totals.

- [ ] **Step 2: Run RED before filling any uncovered integration gap**

```bash
python -m pytest tests/integration/test_product_completion.py -q
```

If it passes immediately, the test must still prove every listed acceptance assertion; do not weaken the fixture merely to obtain GREEN.

- [ ] **Step 3: Implement the `Экономика` section from existing snapshot economics**

Expose full line items: realization, commission, acquiring, FBO/delivery, expected logistics, advertising/services, withholdings/co-invest, VAT/income tax, cost, profit/unit, margin, ROI, completeness/blockers. Route comparison uses backend current/local results only.

- [ ] **Step 4: Remove frontend dependency on PR6 legacy top-level analytical fields**

Once Plan/Flow/Economics/Data all read `snapshot`, remove compatibility rendering code. Backend may keep old fields only if external compatibility is intentionally required; otherwise remove them together with tests that enforce the old response shape and document the API version behavior.

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

Use the repository CI/Windows smoke unchanged unless Product Completion exposes a real runtime gap. Confirm `start.bat`, offline reuse, loopback bind, UI/assets and data preservation all remain green.

- [ ] **Step 7: Run the UI acceptance checklist in a real browser**

Verify and record:

1. `План`, `Потоки спроса`, `Экономика`, `Данные` navigation and Back/Forward.
2. successful analysis, visible progress, failed recalculation preserving prior snapshot.
3. 25/50/100 pagination, search clear, filters, sorting and column chooser.
4. drawer open/close/Escape and focus return.
5. all three flow modes and all four metrics.
6. route selection and SKU breakdown exact totals.
7. observed vs clean evidence label.
8. 200% zoom and narrow viewport without inaccessible controls.
9. keyboard access to nav, cards, flow nodes/links, bars, drawer and table controls.
10. reduced motion and forced-colors/high-contrast operability.
11. no raw backend code as the only business explanation.
12. no external font/CDN/network dependency after runtime bootstrap.

If Frontend Design Premium runtime is available, run the strict audit and reconcile `DESIGN.md` token mapping before completion.

- [ ] **Step 8: Update release-facing README status only with verified facts**

Add Product Completion implementation status and keep the existing runtime instructions unchanged. Do not claim an acceptance item that was not actually run.

- [ ] **Step 9: Final commit**

```bash
git add frontend tests README.md
git commit -m "feat: complete Ozon FBO Product Completion"
```

**PR8 acceptance:** all 15 Product Completion design acceptance criteria are demonstrably covered by automated and recorded browser/runtime evidence; the product is no longer a raw analytics table and provides the approved decision and flow workflows.

---

# Cross-PR review gates

Do not collapse these gates into one large change set.

1. **After PR1:** reviewer validates stockout methodology before any forecast/optimizer dependency is built on it.
2. **After PR2:** reviewer validates real input evidence, Ozon horizon and cluster identity before demand/economics comparisons use them.
3. **After PR3:** reviewer validates demand forecast and need math numerically before placement economics can prioritize it.
4. **After PR4:** reviewer validates fallback and route economics before optimizer consumes placement values.
5. **After PR5:** reviewer validates Safe/Calculated and max-profit/max-margin semantics before exposing them as product recommendations.
6. **After PR6:** reviewer freezes the snapshot/API contract before frontend migration.
7. **After PR7:** reviewer validates the decision workflow before the more visual flow mode is added.
8. **After PR8:** reviewer validates full product acceptance and runtime regression.

# Spec coverage self-check

- Historical stockout evidence / route cleaning: PR1.
- Availability enrichment / Ozon horizon / explicit cluster identity: PR2.
- Independent demand estimate / short history / arbitrary horizon / inbound / no buffer / Ozon comparison: PR3.
- Four-level route fallback / route cost % / local counterfactual / margin p.p. / observed opportunity ₽: PR4.
- Safe Plan / Calculated Plan / max-profit / max-margin / fixed per-SKU seller stock: PR5.
- Immutable snapshot / human explanations / freshness / mappings / streaming parity: PR6.
- `План`, `Данные`, decision line, table/filter/pagination/drawer, async resilience and design tokens: PR7.
- `Потоки спроса` destination/origin/SKU modes, four metrics, route drill-down, SKU bars, observed/clean evidence, `Экономика`, accessibility and final acceptance: PR8.

No Product Completion business formula is delegated to the frontend. No runtime/bootstrap redesign, Ozon API automation, ML forecasting, inferred lost demand, hidden safety stock, global Sankey/chord primary view, cloud/multi-user subsystem or unrelated backend rewrite is introduced by this plan.
