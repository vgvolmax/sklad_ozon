# PR1 True Demand & Daily Fulfillment Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one canonical backend daily facts layer so destination demand is routing-independent, weekly demand/routes are derived from the same normalized facts, and donor dispatch can never inflate the donor cluster's calculated need.

**Architecture:** Normalize each `OrderRecord` once into two independent daily analytical populations: destination demand and fulfilled origin→destination routing. Existing weekly demand/routes become compatibility aggregations of those daily results; application orchestration builds daily facts once and reuses them. No daily matrix is added to the browser snapshot in PR1.

**Tech Stack:** Python 3 dataclasses, existing analytics/domain modules, pytest; no new dependencies; existing vanilla JS/runtime remain untouched.

**Spec:** `docs/superpowers/specs/2026-09-03-pr1-true-demand-daily-fulfillment-design.md`

## Global Constraints

- `destination_cluster` owns customer demand; `origin_cluster` is physical fulfillment only.
- Origin routing must never change destination demand, `DemandEstimate`, `NeedComparison`, Safe/Calculated need ceilings or plan quantity inputs.
- Demand and fulfillment lifecycle populations remain different; `IN_PROGRESS` may be demand without fulfilled routing.
- No fabricated latent/lost demand.
- Existing M1/M2/L formulas, horizon logic, stock/inbound subtraction and MAX_MARGIN behavior are unchanged.
- `None` remains unknown; do not coerce unknowns to zero.
- Python owns business logic; frontend receives no new business calculations.
- Do not add raw daily facts to `AnalysisSnapshot` or API presentation JSON in PR1.
- Do not add dependencies, React, npm, Playwright or Selenium.
- Preserve existing current incomplete ISO-week exclusion behavior for weekly demand and weekly routes.
- Demand and fulfillment keep separate future/undated exclusion counters.
- No PII in daily analytical contracts.

---

## File Structure

### Create

`backend/analytics/daily.py`
- immutable daily contracts;
- single-pass `build_daily_order_facts()`;
- no weekly aggregation or stockout logic.

`tests/analytics/test_daily_facts.py`
- daily aggregation/lifecycle/date/privacy/business-invariant tests.

### Modify

`backend/analytics/demand.py`
- add `aggregate_weekly_demand(DailyDemandResult, ...)`;
- keep `aggregate_demand(orders, ...)` compatibility wrapper.

`backend/analytics/routes.py`
- add `build_weekly_route_profile(DailyFulfillmentResult, ...)`;
- keep `build_route_profile(orders, ...)` compatibility wrapper.

`backend/analytics/__init__.py`
- export daily contracts/builders and new weekly helpers.

`backend/application.py`
- build daily facts once;
- derive demand and observed routes from daily facts;
- include daily facts in internal `AnalysisResult` for later PR2 consumption.

`tests/analytics/test_demand_routes.py`
- prove old wrapper and explicit daily path are identical;
- preserve population-specific window counters and weekly shares.

`tests/api/test_product_completion_acceptance.py`
- add end-to-end origin-permutation/donor-inflation proof;
- prove browser snapshot does not contain daily raw facts.

Do not modify `frontend/**`, `backend/economics/**`, `backend/supply/**`, optimizer formulas, `start.bat` or portable bootstrap.

---

### Task 1: Add canonical daily facts contracts and single-pass aggregation

**Files:**
- Create: `backend/analytics/daily.py`
- Create: `tests/analytics/test_daily_facts.py`

**Interfaces:**
- Consumes: `OrderRecord`, `validate_order`, `is_net_demand`, `is_fulfilled_route`, `parse_source_date`.
- Produces: `DailyDemandCell`, `DailyFulfillmentCell`, `DailyDemandResult`, `DailyFulfillmentResult`, `DailyOrderFacts`, `build_daily_order_facts(orders, as_of)`.

- [ ] **Step 1: Write the daily demand vs fulfillment lifecycle test**

Create `tests/analytics/test_daily_facts.py` with this helper and first test:

```python
from datetime import date

from backend.analytics.daily import build_daily_order_facts
from backend.domain.contracts import OrderLifecycle, OrderRecord

AS_OF = date(2026, 8, 24)


def order(
    *,
    sku="SKU-1",
    quantity=1,
    origin="Москва",
    destination="Москва",
    lifecycle=OrderLifecycle.FULFILLED,
    accepted_at="2026-08-20T12:00:00+03:00",
):
    return OrderRecord(
        sku=sku,
        quantity=quantity,
        origin_cluster=origin,
        destination_cluster=destination,
        lifecycle=lifecycle,
        accepted_at=accepted_at,
    )


def test_daily_facts_keep_demand_and_fulfillment_populations_separate():
    facts = build_daily_order_facts((
        order(quantity=10, lifecycle=OrderLifecycle.FULFILLED),
        order(quantity=5, lifecycle=OrderLifecycle.IN_PROGRESS),
        order(quantity=7, lifecycle=OrderLifecycle.CANCELLED),
    ), AS_OF)

    assert [(x.destination_cluster_id, x.quantity, x.observation_count)
            for x in facts.demand.cells] == [("Москва", 15, 2)]
    assert [(x.origin_cluster_id, x.destination_cluster_id, x.quantity,
             x.observation_count) for x in facts.fulfillment.cells] == [
        ("Москва", "Москва", 10, 1),
    ]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python -m pytest tests/analytics/test_daily_facts.py::test_daily_facts_keep_demand_and_fulfillment_populations_separate -q
```

Expected: FAIL during import because `backend.analytics.daily` does not exist.

- [ ] **Step 3: Implement the immutable daily contracts and minimal builder**

Create `backend/analytics/daily.py`:

```python
"""Canonical daily destination-demand and fulfillment facts."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from backend.domain.contracts import OrderRecord
from backend.domain.invariants import is_fulfilled_route, is_net_demand, validate_order

from ._weeks import parse_source_date


@dataclass(frozen=True, slots=True)
class DailyDemandCell:
    sku: str
    day: date
    destination_cluster_id: str
    quantity: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class DailyFulfillmentCell:
    sku: str
    day: date
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    observation_count: int


@dataclass(frozen=True, slots=True)
class DailyDemandResult:
    cells: tuple[DailyDemandCell, ...]
    excluded_future_observations: int
    excluded_undated_observations: int


@dataclass(frozen=True, slots=True)
class DailyFulfillmentResult:
    cells: tuple[DailyFulfillmentCell, ...]
    excluded_future_observations: int
    excluded_undated_observations: int


@dataclass(frozen=True, slots=True)
class DailyOrderFacts:
    demand: DailyDemandResult
    fulfillment: DailyFulfillmentResult


def build_daily_order_facts(
    orders: Iterable[OrderRecord],
    as_of: date,
) -> DailyOrderFacts:
    demand_totals: dict[tuple[date, str, str], list[int]] = defaultdict(lambda: [0, 0])
    fulfillment_totals: dict[tuple[date, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    demand_future = demand_undated = 0
    fulfillment_future = fulfillment_undated = 0

    for order in orders:
        validate_order(order)
        demand_eligible = is_net_demand(order)
        fulfillment_eligible = is_fulfilled_route(order)
        if not demand_eligible and not fulfillment_eligible:
            continue

        event_date = parse_source_date(order.accepted_at)
        if event_date is None:
            if demand_eligible:
                demand_undated += 1
            if fulfillment_eligible:
                fulfillment_undated += 1
            continue
        if event_date > as_of:
            if demand_eligible:
                demand_future += 1
            if fulfillment_eligible:
                fulfillment_future += 1
            continue

        if demand_eligible:
            aggregate = demand_totals[(event_date, order.sku, order.destination_cluster)]
            aggregate[0] += order.quantity
            aggregate[1] += 1
        if fulfillment_eligible:
            aggregate = fulfillment_totals[(
                event_date, order.sku, order.origin_cluster, order.destination_cluster,
            )]
            aggregate[0] += order.quantity
            aggregate[1] += 1

    demand_cells = tuple(
        DailyDemandCell(sku, day, destination, quantity, count)
        for (day, sku, destination), (quantity, count)
        in sorted(demand_totals.items())
    )
    fulfillment_cells = tuple(
        DailyFulfillmentCell(sku, day, origin, destination, quantity, count)
        for (day, sku, origin, destination), (quantity, count)
        in sorted(fulfillment_totals.items())
    )
    return DailyOrderFacts(
        DailyDemandResult(demand_cells, demand_future, demand_undated),
        DailyFulfillmentResult(
            fulfillment_cells, fulfillment_future, fulfillment_undated,
        ),
    )
```

- [ ] **Step 4: Run the lifecycle test and verify GREEN**

Run:

```bash
python -m pytest tests/analytics/test_daily_facts.py::test_daily_facts_keep_demand_and_fulfillment_populations_separate -q
```

Expected: `1 passed`.

- [ ] **Step 5: Add donor-inflation and external-fulfillment tests**

Append:

```python
def test_daily_destination_demand_is_not_inflated_by_donor_dispatch():
    facts = build_daily_order_facts((
        order(quantity=500, origin="Москва", destination="Москва"),
        order(quantity=300, origin="Москва", destination="Казань"),
        order(quantity=200, origin="Москва", destination="Тверь"),
    ), AS_OF)

    demand = {x.destination_cluster_id: x.quantity for x in facts.demand.cells}
    assert demand == {"Казань": 300, "Москва": 500, "Тверь": 200}
    assert sum(x.quantity for x in facts.fulfillment.cells
               if x.origin_cluster_id == "Москва") == 1000


def test_daily_external_fulfillment_still_belongs_to_destination_demand():
    facts = build_daily_order_facts((
        order(quantity=300, origin="Москва", destination="Казань"),
    ), AS_OF)

    assert [(x.destination_cluster_id, x.quantity) for x in facts.demand.cells] == [
        ("Казань", 300),
    ]
    assert [(x.origin_cluster_id, x.destination_cluster_id, x.quantity)
            for x in facts.fulfillment.cells] == [("Москва", "Казань", 300)]
```

- [ ] **Step 6: Add population-specific date exclusion test**

Append:

```python
def test_daily_exclusions_are_population_specific():
    facts = build_daily_order_facts((
        order(lifecycle=OrderLifecycle.IN_PROGRESS, accepted_at=""),
        order(lifecycle=OrderLifecycle.IN_PROGRESS, accepted_at="2026-08-25"),
        order(lifecycle=OrderLifecycle.FULFILLED, accepted_at=""),
        order(lifecycle=OrderLifecycle.FULFILLED, accepted_at="2026-08-25"),
    ), AS_OF)

    assert facts.demand.excluded_undated_observations == 2
    assert facts.demand.excluded_future_observations == 2
    assert facts.fulfillment.excluded_undated_observations == 1
    assert facts.fulfillment.excluded_future_observations == 1
```

- [ ] **Step 7: Run the new daily suite**

Run:

```bash
python -m pytest tests/analytics/test_daily_facts.py -q
```

Expected: all tests PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add backend/analytics/daily.py tests/analytics/test_daily_facts.py
git commit -m "feat: add canonical daily order facts"
```

---

### Task 2: Derive weekly destination demand from daily demand

**Files:**
- Modify: `backend/analytics/demand.py`
- Modify: `tests/analytics/test_demand_routes.py`

**Interfaces:**
- Consumes: `DailyDemandResult` from Task 1.
- Produces: `aggregate_weekly_demand(daily, as_of, week_policy) -> DemandResult`; preserves `aggregate_demand(orders, as_of, week_policy)`.

- [ ] **Step 1: Add explicit daily-path equivalence test**

In `tests/analytics/test_demand_routes.py`, import:

```python
from backend.analytics.daily import build_daily_order_facts
from backend.analytics.demand import aggregate_demand, aggregate_weekly_demand
```

Add:

```python
def test_weekly_demand_explicit_daily_path_matches_compatibility_wrapper():
    orders = baseline_orders() + (
        order(quantity=50, lifecycle=OrderLifecycle.IN_PROGRESS),
        order(accepted_at="2026-08-24T10:00:00+03:00"),
        order(accepted_at="2026-08-25"),
        order(accepted_at=""),
    )
    daily = build_daily_order_facts(orders, AS_OF)

    assert aggregate_weekly_demand(daily.demand, AS_OF) == aggregate_demand(
        orders, AS_OF,
    )
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/analytics/test_demand_routes.py::test_weekly_demand_explicit_daily_path_matches_compatibility_wrapper -q
```

Expected: FAIL because `aggregate_weekly_demand` is not defined.

- [ ] **Step 3: Implement `aggregate_weekly_demand` and wrapper**

Refactor `backend/analytics/demand.py` so the core weekly logic consumes `DailyDemandResult`:

```python
from backend.analytics.daily import DailyDemandResult, build_daily_order_facts


def aggregate_weekly_demand(
    daily: DailyDemandResult,
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    require_completed_iso_weeks(week_policy)
    current_week = as_of.isocalendar()[:2]
    totals: dict[tuple[int, int, str, str], list[int]] = {}
    included_weeks: set[tuple[int, int]] = set()
    excluded_current = 0

    for cell in daily.cells:
        iso = cell.day.isocalendar()
        week = (iso.year, iso.week)
        if week == current_week:
            excluded_current += cell.observation_count
            continue
        included_weeks.add(week)
        key = (iso.year, iso.week, cell.sku, cell.destination_cluster_id)
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += cell.quantity
        aggregate[1] += cell.observation_count

    cells = tuple(
        DemandCell(sku, year, week, destination, quantity, count)
        for (year, week, sku, destination), (quantity, count)
        in sorted(totals.items())
    )
    return DemandResult(
        cells,
        make_window(
            as_of=as_of,
            included_weeks=included_weeks,
            excluded_current=excluded_current,
            excluded_future=daily.excluded_future_observations,
            excluded_undated=daily.excluded_undated_observations,
        ),
    )


def aggregate_demand(
    orders: Iterable[OrderRecord],
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> DemandResult:
    daily = build_daily_order_facts(orders, as_of)
    return aggregate_weekly_demand(daily.demand, as_of, week_policy)
```

Remove the duplicate raw-order aggregation loop from `aggregate_demand`.

- [ ] **Step 4: Run all existing demand/route tests**

```bash
python -m pytest tests/analytics/test_demand_routes.py -q
```

Expected: all PASS, including current/future/undated window assertions.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/analytics/demand.py tests/analytics/test_demand_routes.py
git commit -m "refactor: derive weekly demand from daily facts"
```

---

### Task 3: Derive weekly fulfilled routes from daily fulfillment

**Files:**
- Modify: `backend/analytics/routes.py`
- Modify: `tests/analytics/test_demand_routes.py`

**Interfaces:**
- Consumes: `DailyFulfillmentResult` from Task 1.
- Produces: `build_weekly_route_profile(daily, as_of, week_policy) -> RouteProfile`; preserves `build_route_profile(orders, as_of, week_policy)`.

- [ ] **Step 1: Add explicit route equivalence test**

Import:

```python
from backend.analytics.routes import build_route_profile, build_weekly_route_profile
```

Add:

```python
def test_weekly_routes_explicit_daily_path_matches_compatibility_wrapper():
    orders = baseline_orders() + (
        order(quantity=50, lifecycle=OrderLifecycle.IN_PROGRESS),
        order(accepted_at="2026-08-24T10:00:00+03:00"),
        order(accepted_at="2026-08-25"),
        order(accepted_at=""),
    )
    daily = build_daily_order_facts(orders, AS_OF)

    assert build_weekly_route_profile(
        daily.fulfillment, AS_OF,
    ) == build_route_profile(orders, AS_OF)
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/analytics/test_demand_routes.py::test_weekly_routes_explicit_daily_path_matches_compatibility_wrapper -q
```

Expected: FAIL because `build_weekly_route_profile` is not defined.

- [ ] **Step 3: Implement weekly route aggregation from daily cells**

Refactor `backend/analytics/routes.py`:

```python
from backend.analytics.daily import DailyFulfillmentResult, build_daily_order_facts


def build_weekly_route_profile(
    daily: DailyFulfillmentResult,
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> RouteProfile:
    require_completed_iso_weeks(week_policy)
    current_week = as_of.isocalendar()[:2]
    totals: dict[tuple[int, int, str, str, str], list[int]] = {}
    included_weeks: set[tuple[int, int]] = set()
    excluded_current = 0

    for cell in daily.cells:
        iso = cell.day.isocalendar()
        week = (iso.year, iso.week)
        if week == current_week:
            excluded_current += cell.observation_count
            continue
        included_weeks.add(week)
        key = (
            iso.year, iso.week, cell.sku,
            cell.origin_cluster_id, cell.destination_cluster_id,
        )
        aggregate = totals.setdefault(key, [0, 0])
        aggregate[0] += cell.quantity
        aggregate[1] += cell.observation_count

    destination_totals: dict[tuple[int, int, str, str], int] = {}
    origin_totals: dict[tuple[int, int, str, str], int] = {}
    for (year, week, sku, origin, destination), (quantity, _) in totals.items():
        destination_key = (year, week, sku, destination)
        origin_key = (year, week, sku, origin)
        destination_totals[destination_key] = destination_totals.get(destination_key, 0) + quantity
        origin_totals[origin_key] = origin_totals.get(origin_key, 0) + quantity

    routes = tuple(
        RouteCell(
            sku=sku,
            iso_year=year,
            iso_week=week,
            origin_cluster_id=origin,
            destination_cluster_id=destination,
            quantity=quantity,
            observation_count=count,
            share_of_destination=(
                Decimal(quantity) / Decimal(destination_totals[(year, week, sku, destination)])
            ),
            share_of_origin=(
                Decimal(quantity) / Decimal(origin_totals[(year, week, sku, origin)])
            ),
        )
        for (year, week, sku, origin, destination), (quantity, count)
        in sorted(totals.items())
        if quantity > 0
    )
    return RouteProfile(
        routes=routes,
        window=make_window(
            as_of=as_of,
            included_weeks=included_weeks,
            excluded_current=excluded_current,
            excluded_future=daily.excluded_future_observations,
            excluded_undated=daily.excluded_undated_observations,
        ),
    )


def build_route_profile(
    orders: Iterable[OrderRecord],
    as_of: date,
    week_policy: WeekPolicy = WeekPolicy.COMPLETED_ISO_WEEKS,
) -> RouteProfile:
    daily = build_daily_order_facts(orders, as_of)
    return build_weekly_route_profile(daily.fulfillment, as_of, week_policy)
```

Delete the previous raw-order aggregation loop from `build_route_profile`.

- [ ] **Step 4: Run route regression suite**

```bash
python -m pytest tests/analytics/test_demand_routes.py -q
```

Expected: all PASS, including exact Decimal shares and window counts.

- [ ] **Step 5: Commit Task 3**

```bash
git add backend/analytics/routes.py tests/analytics/test_demand_routes.py
git commit -m "refactor: derive weekly routes from daily facts"
```

---

### Task 4: Export the new analytics interfaces

**Files:**
- Modify: `backend/analytics/__init__.py`
- Test: `tests/analytics/test_daily_facts.py`

**Interfaces:**
- Produces package-level imports for all PR1 daily contracts and weekly helpers.

- [ ] **Step 1: Add package-export regression**

Append to `tests/analytics/test_daily_facts.py`:

```python
def test_daily_interfaces_are_exported_from_analytics_package():
    import backend.analytics as analytics

    for name in (
        "DailyDemandCell",
        "DailyFulfillmentCell",
        "DailyDemandResult",
        "DailyFulfillmentResult",
        "DailyOrderFacts",
        "build_daily_order_facts",
        "aggregate_weekly_demand",
        "build_weekly_route_profile",
    ):
        assert hasattr(analytics, name)
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/analytics/test_daily_facts.py::test_daily_interfaces_are_exported_from_analytics_package -q
```

Expected: FAIL because exports have not been added.

- [ ] **Step 3: Add imports and `__all__` entries**

In `backend/analytics/__init__.py` import:

```python
from .daily import (
    DailyDemandCell,
    DailyDemandResult,
    DailyFulfillmentCell,
    DailyFulfillmentResult,
    DailyOrderFacts,
    build_daily_order_facts,
)
from .demand import DemandCell, DemandResult, aggregate_demand, aggregate_weekly_demand
from .routes import RouteCell, RouteProfile, build_route_profile, build_weekly_route_profile
```

Add all new public names to `__all__`.

- [ ] **Step 4: Run package and analytics tests**

```bash
python -m pytest tests/analytics/test_daily_facts.py tests/analytics/test_demand_routes.py -q
```

Expected: all PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add backend/analytics/__init__.py tests/analytics/test_daily_facts.py
git commit -m "feat: export daily analytics contracts"
```

---

### Task 5: Make application orchestration build daily facts exactly once

**Files:**
- Modify: `backend/application.py`
- Test: `tests/analytics/test_daily_facts.py`
- Test: existing application/API tests reached by focused run below

**Interfaces:**
- Consumes: `build_daily_order_facts`, `aggregate_weekly_demand`, `build_weekly_route_profile`.
- Produces: internal `AnalysisResult.daily_facts: DailyOrderFacts` for PR2.

- [ ] **Step 1: Add a direct application contract test using monkeypatch counters**

Append to `tests/analytics/test_daily_facts.py` a source-structure regression that protects the orchestration boundary without reproducing all application fixtures:

```python
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_application_uses_one_daily_build_for_demand_and_routes():
    source = (ROOT / "backend/application.py").read_text(encoding="utf-8")

    assert "build_daily_order_facts(orders, as_of)" in source
    assert "aggregate_weekly_demand(daily_facts.demand, as_of)" in source
    assert "build_weekly_route_profile(daily_facts.fulfillment, as_of)" in source
    assert "demand = aggregate_demand(orders, as_of)" not in source
    assert "observed = build_route_profile(orders, as_of)" not in source
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m pytest tests/analytics/test_daily_facts.py::test_application_uses_one_daily_build_for_demand_and_routes -q
```

Expected: FAIL on the first three assertions.

- [ ] **Step 3: Update imports and orchestration**

In `backend/application.py`, replace direct weekly builders with:

```python
from backend.analytics.daily import DailyOrderFacts, build_daily_order_facts
from backend.analytics.demand import aggregate_weekly_demand, DemandResult
from backend.analytics.routes import build_weekly_route_profile, RouteProfile
```

Near the beginning of `analyze()`:

```python
progress("demand")
daily_facts = build_daily_order_facts(orders, as_of)
demand = aggregate_weekly_demand(daily_facts.demand, as_of)
demand_estimates = estimate_destination_demand(demand)
...
progress("routes")
observed = build_weekly_route_profile(daily_facts.fulfillment, as_of)
```

- [ ] **Step 4: Add `daily_facts` to internal `AnalysisResult`**

Keep all non-default fields before default fields. Use this exact dataclass shape around the current fields:

```python
@dataclass(frozen=True, slots=True)
class AnalysisResult:
    daily_facts: DailyOrderFacts
    demand: DemandResult
    observed_routes: RouteProfile
    clean_routes: CleanRouteResult
    stockouts: tuple
    distortions: tuple
    logistics: tuple
    economics: tuple
    placements: tuple
    allocations: tuple
    safe_allocations: tuple
    summary: AnalysisSummary
    diagnostics: tuple[AnalysisDiagnostic, ...]
    demand_estimates: tuple = ()
    needs: tuple = ()
    route_economics: tuple = ()
```

Update the final return to pass `daily_facts` first:

```python
return AnalysisResult(
    daily_facts,
    demand,
    observed,
    clean,
    stockouts,
    distortions,
    tuple(logistics_results),
    tuple(economics_results),
    placements,
    allocations,
    safe_allocations,
    summary,
    tuple(diagnostics),
    tuple(demand_estimates),
    tuple(needs),
    tuple(route_opportunities),
)
```

Do not add `daily_facts` to `assemble_snapshot()`.

- [ ] **Step 5: Run focused backend suites and repair only direct constructor fallout**

Run:

```bash
python -m pytest \
  tests/analytics/test_daily_facts.py \
  tests/analytics/test_demand_routes.py \
  tests/analytics/test_demand_estimate.py \
  tests/analytics/test_stockout_distortion.py \
  tests/analytics/test_clean_routes.py \
  -q
```

Expected: all PASS. If a test directly constructs `AnalysisResult`, update that test to supply a valid `DailyOrderFacts`; do not weaken the new required field or add `None` as a production default.

- [ ] **Step 6: Commit Task 5**

```bash
git add backend/application.py tests/analytics/test_daily_facts.py
git commit -m "refactor: reuse daily facts across analysis"
```

---

### Task 6: Prove origin permutation cannot change demand estimate or need

**Files:**
- Modify: `tests/api/test_product_completion_acceptance.py`

**Interfaces:**
- Consumes: existing upload/API acceptance fixture and final serialized snapshot.
- Produces: end-to-end regression protecting destination-demand planning semantics across ingestion → analytics → need → snapshot.

- [ ] **Step 1: Add a helper that rewrites only origin clusters in acceptance orders**

Inside `tests/api/test_product_completion_acceptance.py`, add a small deterministic variant builder next to `_build_product_completion_acceptance_files()`:

```python
def _build_origin_permuted_acceptance_files():
    files = _build_product_completion_acceptance_files()
    name, payload = files["orders_file"]
    text = payload.decode("utf-8")
    text = text.replace("Москва;Москва;Доставлен", "Омск;Москва;Доставлен")
    text = text.replace("Казань;Самара;Доставлен", "Уфа;Самара;Доставлен")
    files["orders_file"] = (name, text.encode("utf-8"))
    return files
```

The replacement changes only origin values; destination, SKU, quantity, lifecycle and accepted date remain unchanged.

- [ ] **Step 2: Add the end-to-end invariant test**

```python
def test_product_completion_origin_routing_cannot_change_destination_demand_or_need():
    from tests.api.test_analysis import _analysis_data, _post_analysis

    baseline_response = _post_analysis(
        files=_build_product_completion_acceptance_files(),
        data=_analysis_data(),
    )
    permuted_response = _post_analysis(
        files=_build_origin_permuted_acceptance_files(),
        data=_analysis_data(),
    )
    assert baseline_response.status_code == 200, baseline_response.text
    assert permuted_response.status_code == 200, permuted_response.text

    baseline = baseline_response.json()["snapshot"]
    permuted = permuted_response.json()["snapshot"]

    def demand_projection(snapshot):
        return [
            (row["sku"], row["destination_cluster_id"], row["m1"], row["m2"],
             row["latest_week_qty"], row["current_weekly_rate"])
            for row in snapshot["demand_estimates"]
        ]

    def need_projection(snapshot):
        return [
            (row["sku"], row["destination_cluster_id"],
             row["need"]["raw_demand_forecast"],
             row["need"]["calculated_need_qty"])
            for row in snapshot["decision_rows"]
        ]

    assert demand_projection(permuted) == demand_projection(baseline)
    assert need_projection(permuted) == need_projection(baseline)

    baseline_observed = baseline["observed_routes"]["routes"]
    permuted_observed = permuted["observed_routes"]["routes"]
    assert baseline_observed != permuted_observed
```

- [ ] **Step 3: Run and verify the test behavior**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py::test_product_completion_origin_routing_cannot_change_destination_demand_or_need -q
```

Expected after Tasks 1–5: PASS. If it fails because the route permutation creates missing tariffs/economics and blocks the request, narrow the assertion input to the application/analytics layer rather than adding fake tariffs or changing production fail-closed economics. The protected invariant is demand/need, not completeness of the altered routes.

- [ ] **Step 4: Add browser-payload boundary regression**

Add:

```python
def test_product_completion_snapshot_does_not_serialize_daily_fact_matrix(product_completion_payload):
    snapshot = product_completion_payload["snapshot"]

    assert "daily_facts" not in snapshot
    assert "daily_demand" not in snapshot
    assert "daily_fulfillment" not in snapshot
```

- [ ] **Step 5: Run the full Product Completion acceptance file**

```bash
python -m pytest tests/api/test_product_completion_acceptance.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add tests/api/test_product_completion_acceptance.py
git commit -m "test: lock destination demand against origin routing"
```

---

### Task 7: Add direct origin-permutation property at the analytics layer

**Files:**
- Modify: `tests/analytics/test_daily_facts.py`
- Modify: `tests/analytics/test_demand_routes.py`

**Interfaces:**
- Proves the invariant independently of API/economics fixtures.

- [ ] **Step 1: Add daily origin-permutation test**

Append to `tests/analytics/test_daily_facts.py`:

```python
def test_changing_only_origins_changes_fulfillment_but_not_daily_demand():
    base = (
        order(quantity=10, origin="Москва", destination="Казань"),
        order(quantity=20, origin="Москва", destination="Тверь"),
    )
    permuted = (
        order(quantity=10, origin="Новосибирск", destination="Казань"),
        order(quantity=20, origin="Омск", destination="Тверь"),
    )

    left = build_daily_order_facts(base, AS_OF)
    right = build_daily_order_facts(permuted, AS_OF)

    assert left.demand == right.demand
    assert left.fulfillment != right.fulfillment
```

- [ ] **Step 2: Add weekly and estimate origin-permutation test**

In `tests/analytics/test_demand_routes.py`, import `estimate_destination_demand` and add:

```python
def test_changing_only_origins_changes_routes_not_weekly_demand_or_estimate():
    base = (
        order(quantity=10, origin="Москва", destination="Казань",
              accepted_at="2026-08-13"),
        order(quantity=20, origin="Москва", destination="Казань"),
    )
    permuted = (
        order(quantity=10, origin="Новосибирск", destination="Казань",
              accepted_at="2026-08-13"),
        order(quantity=20, origin="Омск", destination="Казань"),
    )

    left_demand = aggregate_demand(base, AS_OF)
    right_demand = aggregate_demand(permuted, AS_OF)
    left_routes = build_route_profile(base, AS_OF)
    right_routes = build_route_profile(permuted, AS_OF)

    assert left_demand == right_demand
    assert estimate_destination_demand(left_demand) == estimate_destination_demand(right_demand)
    assert left_routes != right_routes
```

- [ ] **Step 3: Run analytics invariant tests**

```bash
python -m pytest \
  tests/analytics/test_daily_facts.py \
  tests/analytics/test_demand_routes.py \
  tests/analytics/test_demand_estimate.py \
  -q
```

Expected: all PASS.

- [ ] **Step 4: Commit Task 7**

```bash
git add tests/analytics/test_daily_facts.py tests/analytics/test_demand_routes.py
git commit -m "test: prove routing-independent destination demand"
```

---

### Task 8: Final compatibility, scope and release verification

**Files:**
- No new production scope.
- Repair only regressions directly caused by the PR1 interface changes.

**Interfaces:**
- Verifies the merge gate from the PR1 spec.

- [ ] **Step 1: Run all analytics tests**

```bash
python -m pytest tests/analytics -q
```

Expected: `0 failed`.

- [ ] **Step 2: Run decision, economics and supply regressions**

```bash
python -m pytest tests/decision tests/economics tests/supply -q
```

Expected: `0 failed`.

- [ ] **Step 3: Run API regressions**

```bash
python -m pytest tests/api -q
```

Expected: `0 failed`.

- [ ] **Step 4: Run full pytest**

```bash
python -m pytest -q
```

Expected: `0 failed`; do not exclude API, Windows-related Python tests or legacy suites.

- [ ] **Step 5: Run JS syntax checks even though frontend is untouched**

```bash
node --check frontend/assets/js/core.js
node --check frontend/assets/js/components.js
node --check frontend/assets/js/flow.js
node --check frontend/assets/js/app.js
```

Expected: all four commands exit `0`.

- [ ] **Step 6: Run whitespace/diff checks**

```bash
git diff --check
git status --short
git diff main...HEAD --stat
git diff main...HEAD --name-only
```

Expected:

- `git diff --check` has no output;
- no unexpected generated files;
- changed production files are limited to PR1 analytics/application scope;
- no `frontend/**`, economics, supply, runtime/bootstrap changes.

- [ ] **Step 7: Verify no daily facts leaked into presentation contracts**

Run:

```bash
git grep -n "daily_facts\|daily_demand\|daily_fulfillment" -- backend/decision frontend
```

Expected: no new snapshot/frontend serialization references. References in documentation/tests are allowed and should be inspected rather than mechanically deleted.

- [ ] **Step 8: Push and require fresh CI on the PR head**

Required GitHub Actions results:

```text
python-tests = success
windows-portable-smoke = success
```

The Windows job must execute, not be skipped.

- [ ] **Step 9: Record the PR evidence in the PR description**

Include:

```text
Base main SHA
Head SHA
Focused analytics result
Full pytest result
4 JS check results
Windows portable smoke result
Files changed
Donor-inflation invariant result
Origin-permutation invariant result
Snapshot no-daily-matrix result
```

Do not claim PR2 stockout episodes, financial loss or UI work as completed in PR1.

- [ ] **Step 10: Commit any test-only verification repair if necessary**

If Step 1–9 reveals a direct PR1 regression and a repair is required, commit it separately with a narrow message describing the actual issue. Do not bundle unrelated refactors.

---

## PR1 Acceptance Summary

The PR is ready to merge only if an independent reviewer can verify all of the following from code/tests:

```text
orders
  → one daily build
      → destination daily demand
      → origin→destination daily fulfillment

same destination orders + different origins
  → same daily demand
  → same weekly demand
  → same demand estimate
  → same calculated need
  → different fulfillment/routes
```

The merge must not introduce daily stockout episodes, financial-impact UI, diagnostics redesign or Flow redesign. Those remain separate PR2–PR5 responsibilities in the parent design.
