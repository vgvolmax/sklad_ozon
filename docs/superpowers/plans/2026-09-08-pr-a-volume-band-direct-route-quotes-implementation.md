# PR-A Volume-Band Direct Route Quotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable volume-band direct Ozon route quote and route-specific unit-economics foundation without changing the current placement/optimizer/UI behavior.

**Architecture:** Keep historical `expected_logistics()` untouched as the observed/clean route-profile calculator. Add one pure direct `origin → destination` tariff lookup that reuses the same `TariffRow` source and returns exact lookup evidence; then feed a matched direct fee through the existing unit-economics formula via a shared internal calculator so historical and planned economics cannot drift.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Historical observed/clean route shares are evidence only and MUST NOT become future coverage weights.
- Route topology is reused primarily by `volume_band × origin_cluster × destination_cluster`; do not persist a route-affinity matrix per SKU.
- Geographic distance is not a fallback while tariff evidence exists.
- Missing, ambiguous or price-required tariff evidence remains incomplete; never fabricate or coerce a fee to zero.
- Existing `expected_logistics()` remains authoritative for historical/current origin-profile analysis.
- Existing tax/VAT/co-invest/buyout/FBO formula and spreadsheet parity must remain unchanged.
- Production code remains dependency-free beyond existing runtime requirements.
- Use TDD and keep this PR backend-only; do not connect Coverage Planner, snapshots or UI yet.

---

## File Structure

- Modify `backend/economics/tariffs.py` — own direct-route lookup contracts and pure matching logic beside existing historical expected-logistics logic.
- Modify `backend/economics/unit.py` — expose route-specific unit economics by sharing the current formula core, not duplicating it.
- Modify `backend/economics/__init__.py` — export the new public contracts/functions.
- Modify `tests/economics/test_tariffs.py` — direct quote lookup tests, including source-row and price-required behavior.
- Modify `tests/economics/test_unit.py` — prove direct-route economics parity and failure semantics.
- Modify `tests/economics/test_route_opportunity.py` only if needed to prove the existing historical/counterfactual path is unchanged after the internal economics refactor.

No application orchestration, supply optimizer, snapshot, API or frontend file changes belong in PR-A.

---

### Task 1: Define reusable direct-route quote contracts and validation

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**
- Produces: `VolumeBand(min_volume_liters: Decimal, max_volume_liters: Decimal | None)`
- Produces: `DirectRouteQuote(origin_cluster_id: str, destination_cluster_id: str, volume_band: VolumeBand | None, lookup_status: TariffLookupStatus, matched_fee: Decimal | None, matched_tariff_source_row: int | None, diagnostic_code: str | None)`
- Later tasks call: `quote_direct_route(...) -> DirectRouteQuote`

- [ ] **Step 1: Write failing contract-validation tests**

Add focused tests asserting that a band preserves the exact half-open tariff interval and a matched quote cannot exist without a fee/source identity.

```python
from decimal import Decimal
import pytest

from backend.economics.tariffs import DirectRouteQuote, TariffLookupStatus, VolumeBand


def test_volume_band_preserves_exact_interval():
    band = VolumeBand(Decimal("1"), Decimal("5"))
    assert band.min_volume_liters == Decimal("1")
    assert band.max_volume_liters == Decimal("5")


def test_direct_route_quote_requires_nonblank_route_identity():
    with pytest.raises(ValueError, match="origin_cluster_id"):
        DirectRouteQuote(
            "", "Казань", VolumeBand(Decimal("0"), Decimal("1")),
            TariffLookupStatus.MATCHED, Decimal("47"), 12, None,
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: FAIL because `VolumeBand` / `DirectRouteQuote` do not exist.

- [ ] **Step 3: Add the immutable contracts and validation**

Implement in `backend/economics/tariffs.py` near the existing tariff enums:

```python
@dataclass(frozen=True, slots=True)
class VolumeBand:
    min_volume_liters: Decimal
    max_volume_liters: Decimal | None

    def __post_init__(self) -> None:
        _validate_nonnegative_decimal(self.min_volume_liters, "min_volume_liters")
        if self.max_volume_liters is not None:
            _validate_nonnegative_decimal(self.max_volume_liters, "max_volume_liters")
            if self.max_volume_liters <= self.min_volume_liters:
                raise ValueError("max_volume_liters must be greater than min_volume_liters")


@dataclass(frozen=True, slots=True)
class DirectRouteQuote:
    origin_cluster_id: str
    destination_cluster_id: str
    volume_band: VolumeBand | None
    lookup_status: TariffLookupStatus
    matched_fee: Decimal | None
    matched_tariff_source_row: int | None
    diagnostic_code: str | None

    def __post_init__(self) -> None:
        if not self.origin_cluster_id.strip():
            raise ValueError("origin_cluster_id must be nonblank")
        if not self.destination_cluster_id.strip():
            raise ValueError("destination_cluster_id must be nonblank")
        if self.lookup_status is TariffLookupStatus.MATCHED:
            if self.matched_fee is None:
                raise ValueError("matched quote requires matched_fee")
            _validate_nonnegative_decimal(self.matched_fee, "matched_fee")
        elif self.matched_fee is not None:
            raise ValueError("incomplete quote must not contain matched_fee")
```

Do not add SKU to either contract.

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: add direct route quote contracts"
```

---

### Task 2: Extract one tariff-row matcher and implement direct lookup

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**
- Consumes: existing `ImportResult[TariffRow]`, `TariffLookupStatus`, `_contains()`
- Produces:

```python
def quote_direct_route(
    tariffs: ImportResult[TariffRow],
    *,
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
) -> DirectRouteQuote:
    ...
```

- [ ] **Step 1: Write failing direct-lookup behavior tests**

Cover all canonical states with explicit tariff fixtures:

```python
def test_direct_route_quote_matches_by_route_and_volume(tariffs_result):
    quote = quote_direct_route(
        tariffs_result,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert quote.lookup_status is TariffLookupStatus.MATCHED
    assert quote.matched_fee == Decimal("47")
    assert quote.volume_band == VolumeBand(Decimal("0"), Decimal("1"))


def test_direct_route_quote_reports_price_required(price_banded_tariffs):
    quote = quote_direct_route(
        price_banded_tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=None,
    )
    assert quote.lookup_status is TariffLookupStatus.MISSING
    assert quote.matched_fee is None
    assert quote.diagnostic_code == "PRICE_REQUIRED_FOR_TARIFF_LOOKUP"


def test_direct_route_quote_does_not_use_historical_route_share(tariffs_result):
    cheap = quote_direct_route(
        tariffs_result,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert cheap.matched_fee == Decimal("47")
```

Also test MISSING, AMBIGUOUS and `record_sources` alignment.

- [ ] **Step 2: Run the direct-lookup tests and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: new tests fail because `quote_direct_route` is absent.

- [ ] **Step 3: Extract private matching logic used by both APIs**

Create a private helper returning volume candidates and exact matches:

```python
def _matching_tariff_rows(
    tariffs: ImportResult[TariffRow],
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
):
    volume_candidates = [
        (index, row) for index, row in enumerate(tariffs.records)
        if row.origin_cluster_id == origin_cluster_id
        and row.destination_cluster_id == destination_cluster_id
        and _contains(volume_liters, row.min_volume_liters, row.max_volume_liters)
    ]
    matches = [
        (index, row) for index, row in volume_candidates
        if row.min_price is None and row.max_price is None
        or price is not None and _contains(price, row.min_price, row.max_price)
    ]
    return volume_candidates, matches
```

Refactor the existing `expected_logistics()` loop to call this helper without changing its output contracts or diagnostics.

- [ ] **Step 4: Implement `quote_direct_route`**

Use the same helper and exact current source-row semantics:

```python
def quote_direct_route(...):
    _validate_nonnegative_decimal(volume_liters, "volume_liters")
    if price is not None:
        _validate_nonnegative_decimal(price, "price")
    if tariffs.record_sources and len(tariffs.record_sources) != len(tariffs.records):
        raise ValueError("tariff record_sources must align with records")

    volume_candidates, matches = _matching_tariff_rows(
        tariffs, origin_cluster_id, destination_cluster_id, volume_liters, price
    )
    if len(matches) == 1:
        index, row = matches[0]
        return DirectRouteQuote(
            origin_cluster_id,
            destination_cluster_id,
            VolumeBand(row.min_volume_liters, row.max_volume_liters),
            TariffLookupStatus.MATCHED,
            row.logistics_fee,
            tariffs.record_sources[index] if tariffs.record_sources else None,
            None,
        )
    if len(matches) > 1:
        return DirectRouteQuote(
            origin_cluster_id, destination_cluster_id, None,
            TariffLookupStatus.AMBIGUOUS, None, None, "AMBIGUOUS_TARIFF_MATCH",
        )
    price_required = price is None and volume_candidates and all(
        row.min_price is not None or row.max_price is not None
        for _, row in volume_candidates
    )
    return DirectRouteQuote(
        origin_cluster_id, destination_cluster_id, None,
        TariffLookupStatus.MISSING, None, None,
        "PRICE_REQUIRED_FOR_TARIFF_LOOKUP" if price_required else "MISSING_TARIFF",
    )
```

The quote must not consult `RouteDistributionCell`, observed routes or clean routes.

- [ ] **Step 5: Run direct and historical tariff tests**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: PASS, including all pre-existing `expected_logistics()` tests.

- [ ] **Step 6: Commit the matcher/quote slice**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: add direct Ozon route tariff lookup"
```

---

### Task 3: Add direct-route unit economics without duplicating formulas

**Files:**
- Modify: `backend/economics/unit.py`
- Test: `tests/economics/test_unit.py`

**Interfaces:**
- Consumes: `DirectRouteQuote`, current `ProductEconomicsInput`, `EconomicsSettings`
- Produces:

```python
def calculate_direct_route_economics(
    product: ProductEconomicsInput,
    origin_cluster_id: str,
    quote: DirectRouteQuote,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
    ...
```

- [ ] **Step 1: Write failing parity and incomplete-evidence tests**

```python
def test_direct_route_economics_matches_single_route_expected_logistics(product, settings, tariffs):
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=product.volume_liters,
        price=product.price,
    )
    direct = calculate_direct_route_economics(product, "Москва", quote, settings)
    assert direct.base_delivery_tariff == quote.matched_fee
    assert direct.complete is True


def test_direct_route_economics_fails_closed_on_missing_quote(product, settings):
    quote = DirectRouteQuote(
        "Москва", "Казань", None, TariffLookupStatus.MISSING,
        None, None, "MISSING_TARIFF",
    )
    result = calculate_direct_route_economics(product, "Москва", quote, settings)
    assert result.complete is False
    assert "INCOMPLETE_LOGISTICS_COVERAGE" in result.blockers
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python -m pytest tests/economics/test_unit.py -q
```

Expected: FAIL because `calculate_direct_route_economics` is absent.

- [ ] **Step 3: Extract the current unit formula into one private core**

Refactor `calculate_unit_economics()` so validation of product/settings and all arithmetic lives in one helper taking only the resolved base delivery tariff and logistics completeness:

```python
def _calculate_unit_economics_core(
    product: ProductEconomicsInput,
    placement_cluster_id: str,
    base_delivery_tariff: Decimal | None,
    logistics_complete: bool,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
    ...  # move the existing arithmetic here verbatim
```

The body is the existing calculation, not a rewritten formula. Existing `calculate_unit_economics()` resolves `ExpectedLogisticsResult` and delegates to the core.

- [ ] **Step 4: Implement the direct-route wrapper**

```python
def calculate_direct_route_economics(product, origin_cluster_id, quote, settings):
    if quote.origin_cluster_id != origin_cluster_id:
        raise ValueError("origin/quote mismatch")
    matched = quote.lookup_status is TariffLookupStatus.MATCHED
    return _calculate_unit_economics_core(
        product,
        origin_cluster_id,
        quote.matched_fee if matched else None,
        matched,
        settings,
    )
```

Do not alter buyout/reverse-logistics treatment: a direct route quote supplies the same one-way base tariff input the spreadsheet formula already expects.

- [ ] **Step 5: Run unit economics and route-opportunity regression tests**

```bash
python -m pytest tests/economics/test_unit.py tests/economics/test_route_opportunity.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the economics slice**

```bash
git add backend/economics/unit.py tests/economics/test_unit.py tests/economics/test_route_opportunity.py
git commit -m "feat: calculate economics for direct routes"
```

---

### Task 4: Export the public API and prove no application behavior changed

**Files:**
- Modify: `backend/economics/__init__.py`
- Test: `tests/economics/test_tariffs.py`
- Test: `tests/economics/test_unit.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**
- Public exports: `VolumeBand`, `DirectRouteQuote`, `quote_direct_route`, `calculate_direct_route_economics`
- Does not modify: `backend/application.py`, `backend/supply/*`, snapshots/API/frontend

- [ ] **Step 1: Add import/export smoke assertions**

```python
def test_direct_route_api_is_exported():
    from backend.economics import (
        DirectRouteQuote,
        VolumeBand,
        calculate_direct_route_economics,
        quote_direct_route,
    )
    assert DirectRouteQuote is not None
    assert VolumeBand is not None
    assert callable(quote_direct_route)
    assert callable(calculate_direct_route_economics)
```

- [ ] **Step 2: Run the export test and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py::test_direct_route_api_is_exported -q
```

Expected: FAIL until `backend/economics/__init__.py` exports the new names.

- [ ] **Step 3: Export only the approved direct-route API**

Update `backend/economics/__init__.py` imports/`__all__` according to its existing style. Do not export private matching/core helpers.

- [ ] **Step 4: Run PR-A regression suite**

```bash
python -m pytest tests/economics/test_tariffs.py tests/economics/test_unit.py tests/economics/test_route_opportunity.py tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 5: Run the full repository suite**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit final export/regression slice**

```bash
git add backend/economics/__init__.py tests/economics/test_tariffs.py tests/economics/test_unit.py
git commit -m "test: verify direct route economics foundation"
```

---

## PR-A Acceptance Gate

Before opening PR-A, verify all of the following from fresh command output:

```bash
python -m pytest -q
```

- Direct quote is determined by current tariff row, route and volume band; historical share is absent from the API.
- Two SKUs with the same volume/price lookup conditions can call the same route lookup and receive the same route ordering without persisted SKU affinity data.
- Missing / ambiguous / price-required evidence remains incomplete.
- `record_sources` row lineage is preserved on matched direct quotes.
- Historical `expected_logistics()` results and route-opportunity tests remain unchanged.
- Direct route economics and historical unit economics use one arithmetic core.
- No application orchestration, optimizer, snapshot/API or frontend behavior changed in this PR.
