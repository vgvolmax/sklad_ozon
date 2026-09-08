# PR-A Route Cost Index & Direct Route Quotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two separate tariff-derived planning primitives without changing current product behavior: a SKU-independent `RouteCostIndex` that describes the structural relative cost of an `origin → destination` pair across the complete Ozon tariff matrix, and a precise `DirectRouteQuote` used for the actual economics of a concrete SKU.

**Architecture:** Keep the imported Ozon route matrix as the raw source of truth and keep historical `expected_logistics()` unchanged. Build `RouteCostIndex` by normalizing each non-local route fee against the median fee of the same exact `price interval × volume interval`, then aggregate those normalized ratios per route pair. Separately expose one direct tariff matcher for a concrete product volume/price and reuse the existing spreadsheet-parity unit economics formula. `RouteCostIndex` is topology evidence; `DirectRouteQuote` is the monetary decision input for a concrete SKU.

**Tech Stack:** Python 3, frozen dataclasses, `Decimal`, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-selected-supply-network-coverage-planner-design.md`

**Approved implementation clarification (2026-09-08):** Route topology must also expose a SKU-independent normalized `RouteCostIndex`. This clarification does not supersede the spec rule that actual non-local placement uses complete current tariff evidence for the concrete SKU; the index is supplemental structural evidence and a deterministic tie-break/explanation signal, not a replacement for `DirectRouteQuote`.

## Global Constraints

- Historical observed/clean route shares remain evidence only and MUST NOT become future coverage weights.
- Cross-docking/FBO supply-delivery tariffs are outside this matrix and MUST NOT enter `RouteCostIndex` or direct customer-delivery route economics.
- Do not persist `SKU × origin × destination` affinity/index data.
- `RouteCostIndex` identity is only `origin_cluster_id × destination_cluster_id`.
- The normalized cell ratio must compare fees only inside the same exact tariff class: `min_volume_liters`, `max_volume_liters`, `min_price`, `max_price`.
- Local rows (`origin == destination`) are excluded from the normalization population and from `RouteCostIndex`; LOCAL remains a separate product rule in PR-B.
- Do not hard-code product labels such as `<0.8 = good` or `>1.3 = bad` in backend logic. Version 1 exposes the numeric index, coverage and spread only.
- Missing/ambiguous tariff evidence is never fabricated or coerced to zero.
- Existing `expected_logistics()` outputs, diagnostics, uncovered-share behavior and spreadsheet-parity unit economics must remain unchanged.
- Existing normalized `TariffRow` remains the raw source contract; do not add a second tariff file format in this PR.
- PR-A is backend foundation only. Do not modify `backend/application.py`, `backend/supply/*`, decision snapshots, API routes or frontend files.
- Use TDD and commit after each independently green task.

---

## File Structure

- Modify `backend/economics/tariffs.py` — tariff-class contracts, exact tariff matcher, `DirectRouteQuote`, `RouteCostIndex`, deterministic median/IQR helpers, index builder.
- Modify `backend/economics/unit.py` — shared resolved-base-tariff economics core and `calculate_direct_route_economics()`.
- Modify `backend/economics/__init__.py` — export the new public contracts/functions.
- Modify `tests/economics/test_tariffs.py` — direct quote, route-index normalization, coverage/spread and historical-regression tests.
- Modify `tests/economics/test_unit.py` — direct-route economics parity/fail-closed tests.
- Run existing `tests/economics/test_route_opportunity.py` and `tests/api/test_product_completion_acceptance.py` unchanged as regressions.

No application, supply-planner, snapshot, API or frontend changes belong in PR-A.

---

### Task 1: Define exact tariff-class, direct-quote and route-index contracts

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class TariffClass:
    min_volume_liters: Decimal
    max_volume_liters: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None


@dataclass(frozen=True, slots=True)
class DirectRouteQuote:
    origin_cluster_id: str
    destination_cluster_id: str
    tariff_class: TariffClass | None
    lookup_status: TariffLookupStatus
    matched_fee: Decimal | None
    matched_tariff_source_row: int | None
    diagnostic_code: str | None


@dataclass(frozen=True, slots=True)
class RouteCostIndex:
    origin_cluster_id: str
    destination_cluster_id: str
    index_value: Decimal
    coverage_ratio: Decimal
    spread_iqr: Decimal
    observed_class_count: int
    eligible_class_count: int
```

- [ ] **Step 1: Add failing contract tests**

Append exact fixtures to `tests/economics/test_tariffs.py`:

```python
from decimal import Decimal
import pytest

from backend.economics.tariffs import DirectRouteQuote, RouteCostIndex, TariffClass, TariffLookupStatus


def test_tariff_class_preserves_price_and_volume_intervals():
    item = TariffClass(
        Decimal("1"), Decimal("5"), Decimal("300"), Decimal("1000")
    )
    assert item.min_volume_liters == Decimal("1")
    assert item.max_volume_liters == Decimal("5")
    assert item.min_price == Decimal("300")
    assert item.max_price == Decimal("1000")


def test_tariff_class_rejects_nonincreasing_volume_interval():
    with pytest.raises(ValueError, match="max_volume_liters"):
        TariffClass(Decimal("1"), Decimal("1"), None, None)


def test_route_cost_index_rejects_local_identity():
    with pytest.raises(ValueError, match="non-local"):
        RouteCostIndex(
            "Москва", "Москва", Decimal("1"), Decimal("1"),
            Decimal("0"), 1, 1,
        )


def test_route_cost_index_validates_coverage_and_counts():
    with pytest.raises(ValueError, match="coverage_ratio"):
        RouteCostIndex(
            "Москва", "Казань", Decimal("1"), Decimal("1.1"),
            Decimal("0"), 1, 1,
        )
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: import/attribute failures because the new contracts do not exist.

- [ ] **Step 3: Implement immutable contracts and validation**

Add helpers and dataclasses in `backend/economics/tariffs.py`:

```python
def _validate_interval(lower: Decimal | None, upper: Decimal | None, name: str) -> None:
    if lower is not None:
        _validate_nonnegative_decimal(lower, f"min_{name}")
    if upper is not None:
        _validate_nonnegative_decimal(upper, f"max_{name}")
    if lower is not None and upper is not None and upper <= lower:
        raise ValueError(f"max_{name} must be greater than min_{name}")


@dataclass(frozen=True, slots=True)
class TariffClass:
    min_volume_liters: Decimal
    max_volume_liters: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None

    def __post_init__(self) -> None:
        _validate_interval(self.min_volume_liters, self.max_volume_liters, "volume_liters")
        _validate_interval(self.min_price, self.max_price, "price")


@dataclass(frozen=True, slots=True)
class DirectRouteQuote:
    origin_cluster_id: str
    destination_cluster_id: str
    tariff_class: TariffClass | None
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
            if self.tariff_class is None or self.matched_fee is None:
                raise ValueError("matched quote requires tariff_class and matched_fee")
            _validate_nonnegative_decimal(self.matched_fee, "matched_fee")
        elif self.tariff_class is not None or self.matched_fee is not None:
            raise ValueError("incomplete quote must not contain matched tariff data")


@dataclass(frozen=True, slots=True)
class RouteCostIndex:
    origin_cluster_id: str
    destination_cluster_id: str
    index_value: Decimal
    coverage_ratio: Decimal
    spread_iqr: Decimal
    observed_class_count: int
    eligible_class_count: int

    def __post_init__(self) -> None:
        if not self.origin_cluster_id.strip() or not self.destination_cluster_id.strip():
            raise ValueError("route identities must be nonblank")
        if self.origin_cluster_id == self.destination_cluster_id:
            raise ValueError("RouteCostIndex is non-local only")
        _validate_nonnegative_decimal(self.index_value, "index_value")
        _validate_nonnegative_decimal(self.coverage_ratio, "coverage_ratio")
        _validate_nonnegative_decimal(self.spread_iqr, "spread_iqr")
        if self.coverage_ratio > Decimal("1"):
            raise ValueError("coverage_ratio must be at most 1")
        if isinstance(self.observed_class_count, bool) or not isinstance(self.observed_class_count, int):
            raise TypeError("observed_class_count must be int")
        if isinstance(self.eligible_class_count, bool) or not isinstance(self.eligible_class_count, int):
            raise TypeError("eligible_class_count must be int")
        if self.observed_class_count <= 0 or self.eligible_class_count <= 0:
            raise ValueError("route index counts must be positive")
        if self.observed_class_count > self.eligible_class_count:
            raise ValueError("observed_class_count cannot exceed eligible_class_count")
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: define tariff topology contracts"
```

---

### Task 2: Extract one exact direct tariff matcher and preserve historical behavior

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

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

- [ ] **Step 1: Add exact direct-lookup tests**

Use the existing `TariffRow` constructor and a local helper returning `ImportResult[TariffRow]`. Cover:

```python
def test_direct_quote_matches_route_volume_price_and_source_row():
    rows = (
        TariffRow("Москва", "Казань", Decimal("0"), Decimal("1"),
                  Decimal("0"), Decimal("300"), Decimal("40")),
        TariffRow("Москва", "Казань", Decimal("0"), Decimal("1"),
                  Decimal("300"), None, Decimal("47")),
    )
    tariffs = ImportResult(
        rows, (), ReportMeta("tariffs.xlsx", "2026-09-08T08:00:00+00:00"), (11, 12)
    )
    quote = quote_direct_route(
        tariffs,
        origin_cluster_id="Москва",
        destination_cluster_id="Казань",
        volume_liters=Decimal("0.8"),
        price=Decimal("500"),
    )
    assert quote.lookup_status is TariffLookupStatus.MATCHED
    assert quote.matched_fee == Decimal("47")
    assert quote.tariff_class == TariffClass(
        Decimal("0"), Decimal("1"), Decimal("300"), None
    )
    assert quote.matched_tariff_source_row == 12
```

Also add explicit MISSING, AMBIGUOUS and `PRICE_REQUIRED_FOR_TARIFF_LOOKUP` cases.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: direct quote behavior tests fail.

- [ ] **Step 3: Add one shared matcher**

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

Replace only the duplicate row-selection block inside `expected_logistics()` with this helper. Do not alter historical coverage arithmetic or diagnostics.

- [ ] **Step 4: Implement `quote_direct_route()`**

```python
def quote_direct_route(tariffs, *, origin_cluster_id, destination_cluster_id,
                       volume_liters, price):
    if not origin_cluster_id.strip() or not destination_cluster_id.strip():
        raise ValueError("route identities must be nonblank")
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
            TariffClass(
                row.min_volume_liters, row.max_volume_liters,
                row.min_price, row.max_price,
            ),
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
    price_required = (
        price is None
        and bool(volume_candidates)
        and all(row.min_price is not None or row.max_price is not None
                for _, row in volume_candidates)
    )
    return DirectRouteQuote(
        origin_cluster_id, destination_cluster_id, None,
        TariffLookupStatus.MISSING, None, None,
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
git commit -m "feat: add exact direct route tariff lookup"
```

---

### Task 3: Build deterministic SKU-independent `RouteCostIndex`

**Files:**
- Modify: `backend/economics/tariffs.py`
- Test: `tests/economics/test_tariffs.py`

**Interfaces:**

```python
def build_route_cost_indices(
    tariffs: ImportResult[TariffRow],
) -> tuple[RouteCostIndex, ...]:
```

Definition for each non-local tariff class `c`:

```text
class_median[c] = median(fee for every non-local route row in class c)
ratio[origin,destination,c] = fee(origin,destination,c) / class_median[c]
RouteCostIndex(origin,destination) = median(ratios for that pair)
```

The denominator excludes LOCAL rows. A class is eligible for the index only when it contains at least one non-local row and its median fee is strictly positive.

- [ ] **Step 1: Add exact median and normalization tests**

```python
def test_route_cost_index_normalizes_inside_same_price_and_volume_class():
    rows = (
        TariffRow("A", "X", Decimal("0"), Decimal("1"), Decimal("0"), Decimal("300"), Decimal("10")),
        TariffRow("B", "X", Decimal("0"), Decimal("1"), Decimal("0"), Decimal("300"), Decimal("20")),
        TariffRow("C", "X", Decimal("0"), Decimal("1"), Decimal("0"), Decimal("300"), Decimal("30")),
        TariffRow("A", "A", Decimal("0"), Decimal("1"), Decimal("0"), Decimal("300"), Decimal("1")),
    )
    result = build_route_cost_indices(ImportResult(
        rows, (), ReportMeta("tariffs.xlsx", "2026-09-08T08:00:00+00:00")
    ))
    by_pair = {(x.origin_cluster_id, x.destination_cluster_id): x for x in result}
    assert by_pair[("A", "X")].index_value == Decimal("0.5")
    assert by_pair[("B", "X")].index_value == Decimal("1")
    assert by_pair[("C", "X")].index_value == Decimal("1.5")
    assert ("A", "A") not in by_pair
```

- [ ] **Step 2: Add a two-class test proving price/volume effects are removed before route aggregation**

```python
def test_route_cost_index_aggregates_normalized_classes_not_absolute_fees():
    rows = (
        TariffRow("A", "X", Decimal("0"), Decimal("1"), None, None, Decimal("10")),
        TariffRow("B", "X", Decimal("0"), Decimal("1"), None, None, Decimal("20")),
        TariffRow("A", "X", Decimal("1"), Decimal("5"), None, None, Decimal("100")),
        TariffRow("B", "X", Decimal("1"), Decimal("5"), None, None, Decimal("200")),
    )
    result = build_route_cost_indices(ImportResult(
        rows, (), ReportMeta("tariffs.xlsx", "2026-09-08T08:00:00+00:00")
    ))
    by_pair = {(x.origin_cluster_id, x.destination_cluster_id): x for x in result}
    assert by_pair[("A", "X")].index_value == Decimal("0.6666666666666666666666666666666666666667")
    assert by_pair[("B", "X")].index_value == Decimal("1.333333333333333333333333333333333333333")
```

These exact values follow from per-class median `15` and `150`, then median of identical ratios.

- [ ] **Step 3: Add deterministic statistics helpers**

Use local decimal context precision 40 and define median exactly:

```python
def _median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _iqr(values: tuple[Decimal, ...]) -> Decimal:
    ordered = tuple(sorted(values))
    if not ordered:
        raise ValueError("iqr requires at least one value")
    if len(ordered) == 1:
        return Decimal("0")
    middle = len(ordered) // 2
    lower = ordered[:middle]
    upper = ordered[-middle:]
    return _median(upper) - _median(lower)
```

This is the canonical Tukey-hinges style used by this feature; do not switch quartile definitions silently.

- [ ] **Step 4: Implement tariff-class grouping and duplicate fail-closed behavior**

```python
def _tariff_class(row: TariffRow) -> TariffClass:
    return TariffClass(
        row.min_volume_liters, row.max_volume_liters,
        row.min_price, row.max_price,
    )
```

Build a dictionary keyed by `(origin, destination, TariffClass)`. If the same key appears more than once, exclude that route/class cell from index ratios rather than averaging ambiguous source rows. The index builder itself returns only valid indices; ambiguity remains visible through existing tariff-import/data-quality diagnostics and through reduced `coverage_ratio`.

- [ ] **Step 5: Implement `build_route_cost_indices()`**

Algorithm:

```python
from collections import defaultdict


def build_route_cost_indices(tariffs):
    cells = defaultdict(list)
    all_classes = set()
    for row in tariffs.records:
        if row.origin_cluster_id == row.destination_cluster_id:
            continue
        key = _tariff_class(row)
        all_classes.add(key)
        cells[(row.origin_cluster_id, row.destination_cluster_id, key)].append(row.logistics_fee)

    unambiguous = {
        key: fees[0]
        for key, fees in cells.items()
        if len(fees) == 1
    }
    fees_by_class = defaultdict(list)
    for (_, _, tariff_class), fee in unambiguous.items():
        fees_by_class[tariff_class].append(fee)

    medians = {
        tariff_class: _median(tuple(fees))
        for tariff_class, fees in fees_by_class.items()
        if fees and _median(tuple(fees)) > Decimal("0")
    }
    eligible_classes = tuple(sorted(
        medians,
        key=lambda x: (
            x.min_volume_liters,
            Decimal("Infinity") if x.max_volume_liters is None else x.max_volume_liters,
            Decimal("-1") if x.min_price is None else x.min_price,
            Decimal("Infinity") if x.max_price is None else x.max_price,
        ),
    ))
    ratios = defaultdict(list)
    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_EVEN
        for (origin, destination, tariff_class), fee in unambiguous.items():
            baseline = medians.get(tariff_class)
            if baseline is not None:
                ratios[(origin, destination)].append(fee / baseline)

        result = []
        eligible_count = len(eligible_classes)
        if eligible_count == 0:
            return ()
        for (origin, destination), values in sorted(ratios.items()):
            ratio_values = tuple(values)
            result.append(RouteCostIndex(
                origin,
                destination,
                _median(ratio_values),
                Decimal(len(ratio_values)) / Decimal(eligible_count),
                _iqr(ratio_values),
                len(ratio_values),
                eligible_count,
            ))
    return tuple(result)
```

If the implementation discovers that Ozon tariff classes are not globally identical across routes, keep the exact interval tuple as the class identity; do not infer or remap intervals.

- [ ] **Step 6: Add coverage and spread tests**

Use three eligible classes where one pair is missing one class and assert:

```python
assert index.observed_class_count == 2
assert index.eligible_class_count == 3
assert index.coverage_ratio == Decimal("2") / Decimal("3")
```

Use ratios `(0.8, 1.0, 1.2, 1.4)` and assert `_iqr(...) == Decimal("0.4")` under the fixed hinges definition.

- [ ] **Step 7: Add order/permutation determinism test**

For all permutations of the same small tariff matrix, assert `build_route_cost_indices()` returns the same tuple.

- [ ] **Step 8: Run focused tests and verify GREEN**

```bash
python -m pytest tests/economics/test_tariffs.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/economics/tariffs.py tests/economics/test_tariffs.py
git commit -m "feat: derive route cost index from Ozon matrix"
```

---

### Task 4: Add direct-route unit economics without duplicating the spreadsheet formula

**Files:**
- Modify: `backend/economics/unit.py`
- Test: `tests/economics/test_unit.py`
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

- [ ] **Step 1: Add failing direct-economics parity test**

Create one matched `DirectRouteQuote` whose fee equals a single-route `ExpectedLogisticsResult.expected_fee`; assert both public economics functions return equal `UnitEconomicsResult` values for the same product/settings/origin.

- [ ] **Step 2: Add fail-closed quote test**

For `TariffLookupStatus.MISSING`, assert:

```python
result.complete is False
"INCOMPLETE_LOGISTICS_COVERAGE" in result.blockers
result.base_delivery_tariff is None
```

- [ ] **Step 3: Run tests and verify RED**

```bash
python -m pytest tests/economics/test_unit.py -q
```

Expected: direct-economics function absent.

- [ ] **Step 4: Extract only the resolved logistics input from `calculate_unit_economics()`**

Create:

```python
def _calculate_unit_economics_core(
    product: ProductEconomicsInput,
    placement_cluster_id: str,
    base_delivery_tariff: Decimal | None,
    logistics_complete: bool,
    settings: EconomicsSettings,
) -> UnitEconomicsResult:
```

Move the existing code beginning with product/settings decimal validation and ending with `return UnitEconomicsResult(...)` into this helper. Replace only the current `ExpectedLogisticsResult` validation/resolution with the two explicit parameters. Keep every arithmetic expression, blocker code, line item and rounding behavior unchanged.

Existing `calculate_unit_economics()` validates logistics identity/status exactly as today, resolves `base_delivery_tariff` and `logistics_complete`, then delegates to the core.

- [ ] **Step 5: Implement direct wrapper**

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

- [ ] **Step 6: Run economics regressions**

```bash
python -m pytest tests/economics/test_unit.py tests/economics/test_route_opportunity.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/economics/unit.py tests/economics/test_unit.py tests/economics/test_route_opportunity.py
git commit -m "feat: calculate economics for direct routes"
```

---

### Task 5: Export the public API and prove current application behavior is unchanged

**Files:**
- Modify: `backend/economics/__init__.py`
- Test: `tests/economics/test_tariffs.py`
- Test: `tests/economics/test_unit.py`
- Regression: `tests/api/test_product_completion_acceptance.py`

**Public exports:**

```python
TariffClass
DirectRouteQuote
RouteCostIndex
quote_direct_route
build_route_cost_indices
calculate_direct_route_economics
```

- [ ] **Step 1: Add public import smoke test**

```python
def test_new_tariff_planning_api_is_public():
    from backend.economics import (
        DirectRouteQuote,
        RouteCostIndex,
        TariffClass,
        build_route_cost_indices,
        calculate_direct_route_economics,
        quote_direct_route,
    )
    assert all((DirectRouteQuote, RouteCostIndex, TariffClass,
                build_route_cost_indices, calculate_direct_route_economics,
                quote_direct_route))
```

- [ ] **Step 2: Export only those names from `backend/economics/__init__.py`**

Do not export private median/matcher helpers.

- [ ] **Step 3: Run focused suite**

```bash
python -m pytest tests/economics/test_tariffs.py tests/economics/test_unit.py tests/economics/test_route_opportunity.py -q
```

Expected: PASS.

- [ ] **Step 4: Run current product acceptance regression**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: PASS; PR-A has not changed the current plan pipeline.

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/economics/__init__.py tests/economics/test_tariffs.py tests/economics/test_unit.py
git commit -m "feat: expose tariff topology planning API"
```

---

## PR-A Acceptance Gate

PR-A is complete only when all of the following are true:

1. Existing historical `expected_logistics()` behavior is unchanged.
2. Direct route lookup is independent from observed/clean route history.
3. `RouteCostIndex` is independent from SKU/product identity.
4. Normalization is inside identical price+volume tariff classes before route-pair aggregation.
5. LOCAL rows are excluded from index baselines and outputs.
6. Absolute route fees of different tariff classes are never medianed together before normalization.
7. Index coverage and IQR are explicit and deterministic.
8. No hardcoded `0.8/1.3` algorithm thresholds exist.
9. Direct SKU economics still uses the exact matched route fee, not `RouteCostIndex`.
10. Cross-docking tariffs are not consumed.
11. Existing spreadsheet-parity arithmetic and current Product Completion acceptance tests remain green.
12. No application/supply/snapshot/API/frontend behavior changed in this PR.
