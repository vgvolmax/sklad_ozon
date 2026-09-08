# PR-A Volume-Band Direct Route Quotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable direct Ozon `origin → destination` tariff quote keyed by current tariff dimensions and route-specific unit economics without changing current placement, optimizer, snapshot, API or UI behavior.

**Architecture:** Keep historical `expected_logistics()` authoritative for observed/clean route-profile economics. Extract only its tariff-row selection rule into one private matcher, add a direct quote that calls that matcher without any route history, and expose a route-specific economics wrapper that reuses the existing spreadsheet-parity unit-economics arithmetic rather than copying the formula.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

## Global Constraints

- Historical observed/clean route shares are evidence only and MUST NOT become future coverage weights.
- Do not persist `SKU × origin × destination` affinity data.
- Direct tariff lookup uses current route + volume interval and only uses price when the source tariff rows require price to resolve one fee.
- Geographic distance is not a fallback.
- Missing, ambiguous and price-required tariff evidence stays incomplete; never fabricate or coerce a fee to zero.
- Existing `expected_logistics()` outputs, diagnostics, uncovered-share behavior and spreadsheet-parity economics must remain unchanged.
- PR-A is backend foundation only. Do not modify `backend/application.py`, `backend/supply/*`, decision snapshots, API routes or frontend files.
- Use TDD and commit after each independently green task.

---

## File Structure

- Modify `backend/economics/tariffs.py` — `VolumeBand`, `DirectRouteQuote`, shared private tariff matcher, `quote_direct_route()`.
- Modify `backend/economics/unit.py` — one shared base-tariff arithmetic core plus `calculate_direct_route_economics()`.
- Modify `backend/economics/__init__.py` — export only the approved new public surface.
- Modify `tests/economics/test_tariffs.py` — direct quote and historical-regression tests.
- Modify `tests/economics/test_unit.py` — direct-route economics parity/fail-closed tests.
- Run existing `tests/economics/test_route_opportunity.py` and `tests/api/test_product_completion_acceptance.py` unchanged as regressions.

---

### Task 1: Add direct-route quote contracts

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class VolumeBand:
    min_volume_liters: Decimal
    max_volume_liters: Decimal | None


@dataclass(frozen=True, slots=True)
class DirectRouteQuote:
    origin_cluster_id: str
    destination_cluster_id: str
    volume_band: VolumeBand | None
    lookup_status: TariffLookupStatus
    matched_fee: Decimal | None
    matched_tariff_source_row: int | None
    diagnostic_code: str | None
```

- [ ] **Step 1: Add exact test fixtures and failing contract tests**

Append to `tests/economics/test_tariffs.py` using the repository contracts directly:

```python
from decimal import Decimal
import pytest

from backend.domain.contracts import ImportResult, ReportMeta, TariffRow
from backend.economics.tariffs import DirectRouteQuote, TariffLookupStatus, VolumeBand


def _tariff_result(*rows: TariffRow) -> ImportResult[TariffRow]:
    return ImportResult(
        tuple(rows),
        (),
        ReportMeta("tariffs.xlsx", "2026-09-08T08:00:00+00:00"),
        tuple(range(10, 10 + len(rows))),
    )


def _tariff(
    origin: str,
    destination: str,
    min_volume: str,
    max_volume: str | None,
    fee: str,
    *,
    min_price: str | None = None,
    max_price: str | None = None,
) -> TariffRow:
    return TariffRow(
        origin,
        destination,
        Decimal(min_volume),
        None if max_volume is None else Decimal(max_volume),
        None if min_price is None else Decimal(min_price),
        None if max_price is None else Decimal(max_price),
        Decimal(fee),
    )


def test_volume_band_preserves_half_open_interval():
    assert VolumeBand(Decimal("1"), Decimal("5")) == VolumeBand(
        Decimal("1"), Decimal("5")
    )


def test_volume_band_rejects_nonincreasing_upper_bound():
    with pytest.raises(ValueError, match="max_volume_liters"):
        VolumeBand(Decimal("1"), Decimal("1"))


def test_direct_quote_rejects_blank_origin():
    with pytest.raises(ValueError, match="origin_cluster_id"):
        DirectRouteQuote(
            "",
            "Казань",
            VolumeBand(Decimal("0"), Decimal("1")),
            TariffLookupStatus.MATCHED,
            Decimal("47"),
            10,
            None,
        )


def test_matched_direct_quote_requires_fee():
    with pytest.raises(ValueError, match="matched_fee"):
        DirectRouteQuote(
            "Москва",
            "Казань",
            VolumeBand(Decimal("0"), Decimal("1")),
            TariffLookupStatus.MATCHED,
            None,
            10,
            None,
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: collection/import failure because `VolumeBand` and `DirectRouteQuote` do not exist.

- [ ] **Step 3: Implement the contracts in `backend/economics/tariffs.py`**

Insert after `TariffLookupStatus`:

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
                raise ValueError(
                    "max_volume_liters must be greater than min_volume_liters"
                )


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
        if not isinstance(self.origin_cluster_id, str) or not self.origin_cluster_id.strip():
            raise ValueError("origin_cluster_id must be nonblank")
        if not isinstance(self.destination_cluster_id, str) or not self.destination_cluster_id.strip():
            raise ValueError("destination_cluster_id must be nonblank")
        if not isinstance(self.lookup_status, TariffLookupStatus):
            raise TypeError("lookup_status must be TariffLookupStatus")
        if self.lookup_status is TariffLookupStatus.MATCHED:
            if self.volume_band is None:
                raise ValueError("matched quote requires volume_band")
            if self.matched_fee is None:
                raise ValueError("matched quote requires matched_fee")
            _validate_nonnegative_decimal(self.matched_fee, "matched_fee")
        else:
            if self.matched_fee is not None:
                raise ValueError("incomplete quote must not contain matched_fee")
            if self.volume_band is not None:
                raise ValueError("incomplete quote must not contain volume_band")
```

`matched_tariff_source_row` may remain `None` when the source ImportResult has no `record_sources`; matched fee + route + volume band are the required business identity.

- [ ] **Step 4: Run the focused tests and verify GREEN**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: add direct route quote contracts"
```

---

### Task 2: Share exact tariff-row matching and implement `quote_direct_route()`

**Files:**
- Modify: `backend/economics/tariffs.py`
- Modify: `tests/economics/test_tariffs.py`

**Interfaces:**

```python
def quote_direct_route(
    tariffs: ImportResult[TariffRow],
    *,
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
) -> DirectRouteQuote:
```

Private matcher used by both `expected_logistics()` and `quote_direct_route()`:

```python
def _matching_tariff_rows(
    tariffs: ImportResult[TariffRow],
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
) -> tuple[list[tuple[int, TariffRow]], list[tuple[int, TariffRow]]]:
```

- [ ] **Step 1: Add failing direct-lookup tests**

```python
from backend.economics.tariffs import quote_direct_route


def test_direct_quote_matches_route_and_volume_and_preserves_source_row():
    tariffs = _tariff_result(
        _tariff("Москва", "Казань", "0", "1", "47"),
        _tariff("Москва", "Казань", "1", "5", "63"),
        _tariff("Питер", "Казань", "0", "1", "52"),
    )
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert quote.lookup_status is TariffLookupStatus.MATCHED
    assert quote.volume_band == VolumeBand(Decimal("0"), Decimal("1"))
    assert quote.matched_fee == Decimal("47")
    assert quote.matched_tariff_source_row == 10
    assert quote.diagnostic_code is None


def test_direct_quote_requires_price_when_all_volume_candidates_are_price_banded():
    tariffs = _tariff_result(
        _tariff(
            "Москва", "Казань", "0", "1", "47",
            min_price="0", max_price="1000",
        ),
        _tariff(
            "Москва", "Казань", "0", "1", "55",
            min_price="1000", max_price=None,
        ),
    )
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=None,
    )
    assert quote.lookup_status is TariffLookupStatus.MISSING
    assert quote.matched_fee is None
    assert quote.diagnostic_code == "PRICE_REQUIRED_FOR_TARIFF_LOOKUP"


def test_direct_quote_reports_ambiguous_match():
    tariffs = _tariff_result(
        _tariff("Москва", "Казань", "0", "1", "47"),
        _tariff("Москва", "Казань", "0", "1", "48"),
    )
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert quote.lookup_status is TariffLookupStatus.AMBIGUOUS
    assert quote.diagnostic_code == "AMBIGUOUS_TARIFF_MATCH"


def test_direct_quote_reports_missing_route():
    tariffs = _tariff_result(_tariff("Питер", "Казань", "0", "1", "52"))
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert quote.lookup_status is TariffLookupStatus.MISSING
    assert quote.diagnostic_code == "MISSING_TARIFF"
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: direct quote tests fail because `quote_direct_route()` is undefined.

- [ ] **Step 3: Implement the shared matcher exactly once**

Add before `expected_logistics()`:

```python
def _matching_tariff_rows(
    tariffs: ImportResult[TariffRow],
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
) -> tuple[list[tuple[int, TariffRow]], list[tuple[int, TariffRow]]]:
    volume_candidates = [
        (index, row)
        for index, row in enumerate(tariffs.records)
        if row.origin_cluster_id == origin_cluster_id
        and row.destination_cluster_id == destination_cluster_id
        and _contains(volume_liters, row.min_volume_liters, row.max_volume_liters)
    ]
    matches = [
        (index, row)
        for index, row in volume_candidates
        if (
            row.min_price is None
            and row.max_price is None
            or price is not None
            and _contains(price, row.min_price, row.max_price)
        )
    ]
    return volume_candidates, matches
```

In `expected_logistics()` replace only the existing `volume_candidates = [...]` and `matches = [...]` blocks with:

```python
volume_candidates, matches = _matching_tariff_rows(
    tariffs,
    context.origin_cluster_id,
    route.destination_cluster_id,
    context.volume_liters,
    context.price,
)
```

Do not change any historical coverage arithmetic or diagnostics.

- [ ] **Step 4: Implement `quote_direct_route()`**

```python
def quote_direct_route(
    tariffs: ImportResult[TariffRow],
    *,
    origin_cluster_id: str,
    destination_cluster_id: str,
    volume_liters: Decimal,
    price: Decimal | None,
) -> DirectRouteQuote:
    if not isinstance(origin_cluster_id, str) or not origin_cluster_id.strip():
        raise ValueError("origin_cluster_id must be nonblank")
    if not isinstance(destination_cluster_id, str) or not destination_cluster_id.strip():
        raise ValueError("destination_cluster_id must be nonblank")
    _validate_nonnegative_decimal(volume_liters, "volume_liters")
    if price is not None:
        _validate_nonnegative_decimal(price, "price")
    if tariffs.record_sources and len(tariffs.record_sources) != len(tariffs.records):
        raise ValueError("tariff record_sources must align with records")

    volume_candidates, matches = _matching_tariff_rows(
        tariffs,
        origin_cluster_id,
        destination_cluster_id,
        volume_liters,
        price,
    )
    if len(matches) == 1:
        index, matched = matches[0]
        return DirectRouteQuote(
            origin_cluster_id,
            destination_cluster_id,
            VolumeBand(matched.min_volume_liters, matched.max_volume_liters),
            TariffLookupStatus.MATCHED,
            matched.logistics_fee,
            tariffs.record_sources[index] if tariffs.record_sources else None,
            None,
        )
    if len(matches) > 1:
        return DirectRouteQuote(
            origin_cluster_id,
            destination_cluster_id,
            None,
            TariffLookupStatus.AMBIGUOUS,
            None,
            None,
            "AMBIGUOUS_TARIFF_MATCH",
        )
    price_required = (
        price is None
        and bool(volume_candidates)
        and all(
            row.min_price is not None or row.max_price is not None
            for _, row in volume_candidates
        )
    )
    return DirectRouteQuote(
        origin_cluster_id,
        destination_cluster_id,
        None,
        TariffLookupStatus.MISSING,
        None,
        None,
        "PRICE_REQUIRED_FOR_TARIFF_LOOKUP" if price_required else "MISSING_TARIFF",
    )
```

- [ ] **Step 5: Run direct + historical tariff tests**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: PASS, including all existing `expected_logistics()` tests.

- [ ] **Step 6: Commit**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: add direct Ozon route tariff lookup"
```

---

### Task 3: Reuse unit-economics arithmetic for direct routes

**Files:**
- Modify: `backend/economics/unit.py`
- Modify: `tests/economics/test_unit.py`
- Regression: `tests/economics/test_route_opportunity.py`

**Interfaces:**

```python
def calculate_direct_route_economics(
    product: ProductEconomicsInput,
    origin_cluster_id: str,
    quote: DirectRouteQuote,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
```

Private arithmetic core:

```python
def _calculate_from_resolved_tariff(
    product: ProductEconomicsInput,
    placement_cluster_id: str,
    base_delivery_tariff: Decimal | None,
    logistics_complete: bool,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
```

- [ ] **Step 1: Characterize current unit economics before refactor**

Run the existing suite first:

```bash
python -m pytest tests/economics/test_unit.py tests/economics/test_route_opportunity.py -q
```

Expected: PASS. Save this output as the regression baseline.

- [ ] **Step 2: Add a failing direct-route fail-closed test**

Append to `tests/economics/test_unit.py` using the file's existing valid product/settings fixture names. If the file does not expose reusable pytest fixtures, construct the same `ProductEconomicsInput` and `EconomicsSettings` values used by its first complete-economics test; do not create new business assumptions.

The test body itself must be:

```python
quote = DirectRouteQuote(
    "Москва",
    "Казань",
    None,
    TariffLookupStatus.MISSING,
    None,
    None,
    "MISSING_TARIFF",
)
result = calculate_direct_route_economics(product, "Москва", quote, settings)
assert result.sku == product.sku
assert result.placement_cluster_id == "Москва"
assert result.complete is False
assert result.base_delivery_tariff is None
assert "INCOMPLETE_LOGISTICS_COVERAGE" in result.blockers
```

- [ ] **Step 3: Add a failing matched-fee parity test**

Use the same complete product/settings fixture and this quote:

```python
quote = DirectRouteQuote(
    "Москва",
    "Казань",
    VolumeBand(Decimal("0"), Decimal("1")),
    TariffLookupStatus.MATCHED,
    Decimal("47"),
    10,
    None,
)
direct = calculate_direct_route_economics(product, "Москва", quote, settings)
assert direct.base_delivery_tariff == Decimal("47")
assert direct.complete is True
```

Then construct the existing `ExpectedLogisticsResult` in the same test with `coverage_status=LogisticsCoverageStatus.COMPLETE`, `expected_fee=Decimal("47")`, the same product SKU/origin and otherwise zero/empty audit fields, call `calculate_unit_economics()`, and assert:

```python
assert direct == historical
```

This proves one arithmetic path.

- [ ] **Step 4: Run the new tests and verify RED**

```bash
python -m pytest tests/economics/test_unit.py -q
```

Expected: import failure because `calculate_direct_route_economics()` does not exist.

- [ ] **Step 5: Perform a mechanical extraction of the current arithmetic**

In `backend/economics/unit.py`:

1. Keep the first four identity checks in `calculate_unit_economics()` unchanged.
2. Keep the current `LogisticsCoverageStatus` validation/resolution in that wrapper unchanged.
3. Move the code beginning with current line `price = None if product.price is None else _decimal(product.price, "price")` through the final `return UnitEconomicsResult(...)` into `_calculate_from_resolved_tariff()`.
4. Delete only the moved block from the wrapper.
5. End the wrapper with:

```python
return _calculate_from_resolved_tariff(
    product,
    placement_cluster_id,
    base_delivery_tariff,
    logistics_complete,
    settings,
)
```

Inside the extracted helper, remove the old references to `logistics.coverage_status` and `logistics.expected_fee`; it receives the already resolved `base_delivery_tariff` and `logistics_complete`. Every commission, acquiring, buyout, reverse-logistics, advertising, payout, co-invest, VAT, income-tax, cost, profit, margin, ROI, line-item and rounding statement remains byte-for-behavior equivalent to the pre-refactor function.

- [ ] **Step 6: Implement the direct wrapper**

Add imports:

```python
from .tariffs import DirectRouteQuote, TariffLookupStatus
```

Add:

```python
def calculate_direct_route_economics(
    product: ProductEconomicsInput,
    origin_cluster_id: str,
    quote: DirectRouteQuote,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
    if not isinstance(origin_cluster_id, str) or not origin_cluster_id.strip():
        raise ValueError("origin_cluster_id must be nonblank")
    if quote.origin_cluster_id != origin_cluster_id:
        raise ValueError("origin/quote mismatch")
    matched = quote.lookup_status is TariffLookupStatus.MATCHED
    return _calculate_from_resolved_tariff(
        product,
        origin_cluster_id,
        quote.matched_fee if matched else None,
        matched,
        settings,
    )
```

- [ ] **Step 7: Run unit + route-opportunity regressions**

```bash
python -m pytest tests/economics/test_unit.py tests/economics/test_route_opportunity.py -q
```

Expected: PASS and the parity assertion `direct == historical` is green.

- [ ] **Step 8: Commit**

```bash
git add backend/economics/unit.py tests/economics/test_unit.py
git commit -m "feat: calculate economics for direct routes"
```

---

### Task 4: Export the new foundation and verify no product behavior change

**Files:**
- Modify: `backend/economics/__init__.py`
- Modify: `tests/economics/test_tariffs.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**

Public exports:

```python
VolumeBand
DirectRouteQuote
quote_direct_route
calculate_direct_route_economics
```

- [ ] **Step 1: Add a failing export smoke test**

```python
def test_direct_route_foundation_is_exported():
    from backend.economics import (
        DirectRouteQuote,
        VolumeBand,
        calculate_direct_route_economics,
        quote_direct_route,
    )

    assert DirectRouteQuote.__name__ == "DirectRouteQuote"
    assert VolumeBand.__name__ == "VolumeBand"
    assert callable(calculate_direct_route_economics)
    assert callable(quote_direct_route)
```

- [ ] **Step 2: Run the smoke test and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py::test_direct_route_foundation_is_exported -q
```

Expected: import failure until `backend/economics/__init__.py` exports the names.

- [ ] **Step 3: Export only the approved public names**

Follow the current explicit imports/`__all__` style in `backend/economics/__init__.py`. Do not export `_matching_tariff_rows` or `_calculate_from_resolved_tariff`.

- [ ] **Step 4: Run PR-A regression suite**

```bash
python -m pytest \
  tests/economics/test_tariffs.py \
  tests/economics/test_unit.py \
  tests/economics/test_route_opportunity.py \
  tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full repository verification**

```bash
python -m pytest -q
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow_timeline.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: every command exits 0.

- [ ] **Step 6: Commit**

```bash
git add backend/economics/__init__.py tests/economics/test_tariffs.py
git commit -m "test: verify direct route economics foundation"
```

---

## PR-A Acceptance Gate

Fresh verification must prove:

```bash
python -m pytest -q
```

- Direct quote uses exact current tariff route/volume/price lookup rules and contains no historical-flow input.
- Matching source-row lineage is preserved when `record_sources` exists.
- Missing, ambiguous and price-required evidence stays incomplete.
- Existing `expected_logistics()` tests remain unchanged and green.
- Direct-route and historical unit economics with the same base tariff are exactly equal.
- Existing route-opportunity and Product Completion acceptance tests remain green.
- No application, supply, snapshot, API or frontend behavior is changed by PR-A.
