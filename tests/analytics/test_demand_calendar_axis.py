from datetime import date
from decimal import Decimal

from backend.analytics.demand import aggregate_demand
from backend.analytics.demand_estimate import estimate_destination_demand
from backend.domain.contracts import OrderLifecycle, OrderRecord


AS_OF = date(2026, 8, 26)  # 2026-W35; W34 is the last completed ISO week.


def order(*, sku="SKU-A", quantity=10, iso_week=31, destination="Москва"):
    accepted = date.fromisocalendar(2026, iso_week, 1)
    return OrderRecord(
        sku=sku,
        quantity=quantity,
        origin_cluster="Москва",
        destination_cluster=destination,
        lifecycle=OrderLifecycle.FULFILLED,
        accepted_at=accepted.isoformat(),
    )


def estimate_for(orders, *, sku="SKU-A", destination="Москва"):
    demand = aggregate_demand(orders, AS_OF)
    estimate = next(
        item
        for item in estimate_destination_demand(demand)
        if item.sku == sku and item.destination_cluster_id == destination
    )
    return demand, estimate


def test_completed_calendar_axis_fills_internal_and_trailing_zero_weeks():
    demand, estimate = estimate_for((
        order(iso_week=31, quantity=10),
        order(iso_week=34, quantity=10),
    ))

    assert demand.window.included_weeks == (
        (2026, 31),
        (2026, 32),
        (2026, 33),
        (2026, 34),
    )
    assert estimate.eligible_week_count == 4
    assert estimate.latest_week_qty == Decimal("10")
    assert estimate.current_weekly_rate == Decimal("5")


def test_unrelated_sku_activity_does_not_change_existing_demand_estimate():
    baseline_orders = (
        order(iso_week=31, quantity=10),
        order(iso_week=34, quantity=10),
    )
    variant_orders = baseline_orders + (
        order(sku="SKU-B", iso_week=32, quantity=100),
        order(sku="SKU-B", iso_week=33, quantity=100),
    )

    baseline_demand, baseline = estimate_for(baseline_orders)
    variant_demand, variant = estimate_for(variant_orders)

    assert baseline_demand.window.included_weeks == variant_demand.window.included_weeks
    assert baseline == variant


def test_last_completed_week_is_zero_when_sales_stopped_one_week_earlier():
    demand, estimate = estimate_for((order(iso_week=33, quantity=10),))

    assert demand.window.included_weeks == ((2026, 33), (2026, 34))
    assert estimate.eligible_week_count == 2
    assert estimate.latest_week_qty == Decimal("0")
    assert estimate.current_weekly_rate == Decimal("5")


def test_new_sku_starts_at_its_own_first_observed_week_but_keeps_later_zero_week():
    orders = tuple(order(sku="SKU-OLD", iso_week=week, quantity=5) for week in range(27, 35)) + (
        order(sku="SKU-NEW", iso_week=33, quantity=10),
    )

    demand = aggregate_demand(orders, AS_OF)
    estimate = next(item for item in estimate_destination_demand(demand) if item.sku == "SKU-NEW")

    assert demand.window.included_weeks[0] == (2026, 27)
    assert demand.window.included_weeks[-1] == (2026, 34)
    assert estimate.eligible_week_count == 2
    assert estimate.latest_week_qty == Decimal("0")
    assert estimate.current_weekly_rate == Decimal("5")


def test_current_week_does_not_enter_calendar_axis():
    orders = (
        order(iso_week=34, quantity=10),
        OrderRecord(
            sku="SKU-A",
            quantity=999,
            origin_cluster="Москва",
            destination_cluster="Москва",
            lifecycle=OrderLifecycle.FULFILLED,
            accepted_at=date.fromisocalendar(2026, 35, 1).isoformat(),
        ),
    )

    demand, estimate = estimate_for(orders)

    assert demand.window.included_weeks == ((2026, 34),)
    assert demand.window.excluded_current_week_observations == 1
    assert estimate.latest_week_qty == Decimal("10")
