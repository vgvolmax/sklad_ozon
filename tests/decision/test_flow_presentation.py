from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from backend.analytics.stockout_episodes import DailyLocalityPoint
from backend.decision.snapshot import _views


def flow(sku, origin, destination, quantity):
    return SimpleNamespace(sku=sku, origin_cluster_id=origin,
                           destination_cluster_id=destination, quantity=quantity)


def daily(sku, destination, quantity):
    return DailyLocalityPoint(sku, destination, date(2026, 8, 1), quantity,
                              quantity, quantity, 0, Decimal(1), Decimal(0), ())


def test_destination_demand_is_not_inflated_by_origin_dispatch_and_is_evidence_invariant():
    rows = (flow("A", "Москва", "Москва", 500),
            flow("A", "Москва", "Казань", 300),
            flow("A", "Москва", "Тверь", 200))
    locality = (daily("A", "Москва", 500), daily("A", "Казань", 300),
                daily("A", "Тверь", 200))
    observed = _views(rows, (), (), daily_locality=locality)
    clean = _views(rows[:2], (), (), daily_locality=locality,
                   evidence_source="clean")
    destination = next(v for v in observed if v.mode == "destination" and v.key == "Москва")
    origin = next(v for v in observed if v.mode == "origin" and v.key == "Москва")
    kazan = next(v for v in observed if v.mode == "destination" and v.key == "Казань")
    assert destination.context_summary.own_destination_demand_qty == 500
    assert (origin.context_summary.own_destination_demand_qty,
            origin.context_summary.fulfilled_quantity,
            origin.context_summary.same_cluster_fulfilled_qty,
            origin.context_summary.cross_cluster_fulfilled_qty) == (500, 1000, 500, 500)
    assert kazan.context_summary.own_destination_demand_qty == 300
    assert next(v for v in clean if v.mode == "destination" and v.key == "Москва").context_summary.own_destination_demand_qty == 500


def test_top_eight_and_other_reconcile_and_route_keys_are_exact():
    rows = tuple(flow("A", f"O{i:02}", "D", i + 1) for i in range(20))
    view = next(v for v in _views(rows, (), ()) if v.mode == "destination")
    units = next(x for x in view.metric_overviews if x.metric == "units")
    assert len(units.top_route_keys) == 8
    assert units.other_route_count == 12
    assert units.top_quantity + units.other_quantity == view.total_quantity
    assert set(units.top_route_keys) <= {link.route_key for link in view.links}
