from datetime import date
from pathlib import Path

from backend.analytics.daily import build_daily_order_facts
from backend.domain.contracts import OrderLifecycle, OrderRecord

AS_OF = date(2026, 8, 24)
ROOT = Path(__file__).parents[2]


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


def test_application_uses_one_daily_build_for_demand_and_routes():
    source = (ROOT / "backend/application.py").read_text(encoding="utf-8")

    assert "build_daily_order_facts(orders, as_of)" in source
    assert "aggregate_weekly_demand(daily_facts.demand, as_of)" in source
    assert "build_weekly_route_profile(daily_facts.fulfillment, as_of)" in source
    assert "demand = aggregate_demand(orders, as_of)" not in source
    assert "observed = build_route_profile(orders, as_of)" not in source


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
