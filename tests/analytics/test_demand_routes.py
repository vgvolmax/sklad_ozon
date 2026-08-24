from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from backend.analytics.demand import aggregate_demand
from backend.analytics.routes import build_route_profile
from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.domain.invariants import DomainValidationError


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


def baseline_orders():
    return (
        order(quantity=800),
        order(quantity=200, origin="Казань", destination="Москва"),
        order(quantity=100, origin="Казань", destination="Казань"),
        order(
            quantity=100,
            origin="Казань",
            destination="Москва",
            lifecycle=OrderLifecycle.CANCELLED,
        ),
    )


def test_demand_is_weekly_quantity_by_destination_not_origin():
    result = aggregate_demand(baseline_orders(), AS_OF)

    assert [(cell.destination_cluster_id, cell.quantity, cell.observation_count)
            for cell in result.cells] == [
        ("Казань", 100, 1),
        ("Москва", 1000, 2),
    ]
    assert {(cell.iso_year, cell.iso_week) for cell in result.cells} == {(2026, 34)}
    assert result.window.included_weeks == ((2026, 34),)


def test_fulfilled_routes_preserve_direction_and_decimal_shares():
    result = build_route_profile(baseline_orders(), AS_OF)
    routes = {(cell.origin_cluster_id, cell.destination_cluster_id): cell
              for cell in result.routes}

    assert routes[("Москва", "Москва")].quantity == 800
    assert routes[("Казань", "Москва")].quantity == 200
    assert routes[("Казань", "Казань")].quantity == 100
    assert routes[("Москва", "Москва")].share_of_destination == Decimal("0.8")
    assert routes[("Казань", "Москва")].share_of_destination == Decimal("0.2")
    assert routes[("Казань", "Казань")].share_of_origin == Decimal(100) / Decimal(300)
    assert all(isinstance(cell.share_of_destination, Decimal) for cell in result.routes)


def test_in_progress_enters_demand_but_not_fulfilled_routes():
    orders = baseline_orders() + (
        order(quantity=50, origin="Казань", destination="Москва",
              lifecycle=OrderLifecycle.IN_PROGRESS),
    )

    demand = aggregate_demand(orders, AS_OF)
    routes = build_route_profile(orders, AS_OF)

    assert next(cell for cell in demand.cells
                if cell.destination_cluster_id == "Москва").quantity == 1050
    route = next(cell for cell in routes.routes
                 if (cell.origin_cluster_id, cell.destination_cluster_id)
                 == ("Москва", "Москва"))
    assert route.quantity == 800
    assert route.share_of_destination == Decimal("0.8")


def test_cancelled_and_unknown_are_excluded_from_both_populations():
    excluded = (
        order(quantity=50, lifecycle=OrderLifecycle.CANCELLED),
        order(quantity=60, lifecycle=OrderLifecycle.UNKNOWN),
    )

    assert aggregate_demand(excluded, AS_OF).cells == ()
    assert build_route_profile(excluded, AS_OF).routes == ()


@pytest.mark.parametrize("function,result_field", [
    (aggregate_demand, "cells"),
    (build_route_profile, "routes"),
])
def test_window_reports_current_future_and_undated_exclusions(function, result_field):
    orders = (
        order(accepted_at="2026-08-24T10:00:00+03:00"),
        order(accepted_at="2026-08-25"),
        order(accepted_at=""),
        order(accepted_at="not-a-date"),
    )

    result = function(orders, AS_OF)

    assert getattr(result, result_field) == ()
    assert result.window.current_iso_year == 2026
    assert result.window.current_iso_week == 35
    assert result.window.excluded_current_week_observations == 1
    assert result.window.excluded_future_observations == 1
    assert result.window.excluded_undated_observations == 2


@pytest.mark.parametrize("accepted_at", [
    "2026-08-23T23:30:00-10:00",
    "2026-08-20T12:00:00",
    "2026-08-20T12:00:00Z",
])
def test_supported_timestamps_use_source_calendar_date(accepted_at):
    result = aggregate_demand(
        (order(accepted_at=accepted_at),), AS_OF,
    )

    assert [(cell.iso_year, cell.iso_week) for cell in result.cells] == [(2026, 34)]


def test_history_and_skus_have_independent_weekly_denominators():
    orders = (
        order(quantity=10, accepted_at="2026-08-13"),  # W33
        order(quantity=20),  # W34
        order(sku="SKU-2", quantity=30),
        order(sku="SKU-2", quantity=10, origin="Казань"),
    )

    demand = aggregate_demand(orders, AS_OF)
    profile = build_route_profile(orders, AS_OF)

    assert [(cell.iso_week, cell.sku, cell.quantity) for cell in demand.cells] == [
        (33, "SKU-1", 10),
        (34, "SKU-1", 20),
        (34, "SKU-2", 40),
    ]
    assert [(cell.iso_week, cell.sku) for cell in profile.routes] == [
        (33, "SKU-1"),
        (34, "SKU-1"),
        (34, "SKU-2"),
        (34, "SKU-2"),
    ]
    sku_2 = [cell for cell in profile.routes if cell.sku == "SKU-2"]
    assert {cell.share_of_destination for cell in sku_2} == {
        Decimal("0.75"), Decimal("0.25"),
    }


@pytest.mark.parametrize("bad_order", [
    order(quantity=-1),
    order(sku=" "),
    order(origin=""),
    order(destination=""),
])
@pytest.mark.parametrize("function", [aggregate_demand, build_route_profile])
def test_invalid_canonical_orders_fail_explicitly(function, bad_order):
    with pytest.raises(DomainValidationError):
        function((bad_order,), AS_OF)


def test_results_and_nested_contracts_are_immutable():
    demand = aggregate_demand((order(),), AS_OF)
    routes = build_route_profile((order(),), AS_OF)

    with pytest.raises(Exception):
        replace(demand.cells[0], quantity=2).quantity = 3
    with pytest.raises(Exception):
        demand.window.as_of = date(2026, 1, 1)
    with pytest.raises(Exception):
        routes.routes[0].quantity = 2
