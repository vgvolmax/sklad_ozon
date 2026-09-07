from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from types import SimpleNamespace

import pytest

from backend.analytics.daily import DailyFulfillmentCell, DailyFulfillmentResult
from backend.economics.stockout_impact import (RouteQuantityImpact,
    RouteDayQuantityImpact, StockoutEpisodeImpact, aggregate_impacts,
    apply_route_quantity, build_stockout_episode_impacts,
    deduplicate_route_day_impacts)
from backend.economics.route_opportunity import RouteCounterfactual

D = Decimal


def impact(sku="A", quantity=10, current=D("140"), local=D("40"),
           current_profit=D("20"), local_profit=D("120"), price=D("500"),
           complete=True, reasons=()):
    return RouteQuantityImpact(sku, "Казань", "Москва", quantity,
        current if complete else None, local if complete else None,
        (current-local)*quantity if complete else None,
        current_profit if complete else None, local_profit if complete else None,
        current_profit/price if complete else None, local_profit/price if complete else None,
        (local_profit-current_profit)/price*100 if complete else None,
        local_profit-current_profit if complete else None,
        (local_profit-current_profit)*quantity if complete else None,
        price if complete else None, D("450") if complete else None,
        complete, reasons)


def test_exact_route_and_negative_signs_are_preserved():
    core = RouteCounterfactual("A", "Казань", "Москва", D("140"), D("0.2"),
        D("20"), D("0.04"), D("40"), D("0.1"), D("120"), D("0.24"),
        D("20"), D("100"), D("500"), D("450"), True, ())
    result = apply_route_quantity(core, 10)
    assert result.extra_logistics_rub == D("1000")
    assert result.profit_loss_or_opportunity_rub == D("1000")
    negative = impact(current=D("20"), local=D("80"),
                      current_profit=D("120"), local_profit=D("60"))
    assert negative.extra_logistics_rub < 0
    assert negative.margin_delta_pp < 0
    assert negative.profit_delta_per_unit < 0
    assert negative.profit_loss_or_opportunity_rub < 0


def test_two_donor_weighting_and_incomplete_aggregate_fail_closed():
    a = impact(quantity=60); b = impact(sku="B", quantity=40, price=D("1000"),
                                       current_profit=D("100"), local_profit=D("150"))
    total = aggregate_impacts((a, b))
    assert total.quantity == 100
    assert total.extra_logistics_rub == a.extra_logistics_rub + b.extra_logistics_rub
    assert total.profit_loss_or_opportunity_rub == (
        a.profit_loss_or_opportunity_rub + b.profit_loss_or_opportunity_rub)
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        expected = (a.current_profit_per_unit*60+b.current_profit_per_unit*40)/(a.price_per_unit*60+b.price_per_unit*40)
    assert total.weighted_current_margin_rate == expected
    assert expected != (a.current_margin_rate+b.current_margin_rate)/2
    blocked = aggregate_impacts((a, impact(quantity=40, complete=False,
                                            reasons=("CURRENT_ROUTE_INCOMPLETE",))))
    assert blocked.quantity == 100 and not blocked.complete
    assert blocked.extra_logistics_rub is blocked.margin_delta_pp is None
    assert blocked.profit_delta_per_unit is blocked.profit_loss_or_opportunity_rub is None


def test_episode_uses_sparse_affected_dates_and_external_routes_only():
    episode = SimpleNamespace(sku="A", destination_cluster_id="Москва",
        start_date=date(2026,8,17), end_date=date(2026,8,21),
        affected_dates=(date(2026,8,17), date(2026,8,18)),
        evidence_scope=SimpleNamespace(value="operational_current_week"), confidence="high",
        baseline_local_share=D("1"), representative_local_share=D("0"), reason_codes=())
    cells = tuple(DailyFulfillmentCell("A", day, origin, "Москва", qty, 1) for day, origin, qty in (
        (date(2026,8,17), "Казань", 60), (date(2026,8,18), "Тверь", 40),
        (date(2026,8,18), "Москва", 5), (date(2026,8,19), "Казань", 900)))
    tariffs = SimpleNamespace(records=())
    # Missing product deliberately proves the episode and exact quantities survive.
    result = build_stockout_episode_impacts((episode,), DailyFulfillmentResult(cells,0,0),
        (), {}, tariffs, SimpleNamespace(), {})[0]
    assert result.external_quantity == 100 and result.local_quantity == 5
    assert sum(route.quantity for route in result.routes) == 100
    assert [(item.day, item.quantity) for item in result.route_day_impacts] == [
        (date(2026,8,17), 60), (date(2026,8,18), 40)]
    assert result.episode_id.endswith("::operational_current_week")
    assert not result.economics.complete
    assert result.economics.reason_codes == ("MISSING_PRODUCT_ECONOMICS",)


def test_conflicting_factual_route_day_evidence_fails_fast():
    day = date(2026, 9, 3)
    def evidence(quantity):
        route = impact("A", quantity)
        component = RouteDayQuantityImpact(
            "A", day, "Казань", "Москва", quantity, route)
        economics = aggregate_impacts((route,))
        return StockoutEpisodeImpact(
            f"episode-{quantity}", "A", "Москва", day, day, (day,),
            "historical_complete", "high", quantity, quantity, 0, quantity,
            D("0"), D("1"), D("1"), D("0"), (), economics, (route,),
            (component,))

    with pytest.raises(ValueError, match="conflicting stockout factual route-day evidence"):
        deduplicate_route_day_impacts((evidence(10), evidence(12)))
