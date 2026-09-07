from datetime import date, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from types import SimpleNamespace

from backend.analytics.stockout_episodes import DailyLocalityPoint
from backend.decision.impact import (ECONOMICS_BASIS_TEXT,
                                     build_stockout_impact_presentation)
from backend.economics.stockout_impact import (StockoutEpisodeImpact,
    RouteDayQuantityImpact, aggregate_impacts)
from tests.economics.test_stockout_impact import impact

D=Decimal


def episode(sku, route, day=date(2026,8,17), days=None, scope="historical_complete"):
    days = tuple(days or (day,))
    daily_quantity = route.quantity // len(days)
    assert daily_quantity * len(days) == route.quantity
    route_days = tuple(RouteDayQuantityImpact(
        sku, route_day, route.origin_cluster_id, route.destination_cluster_id,
        daily_quantity, impact(sku, daily_quantity,
            route.current_route_cost_rub_per_unit,
            route.local_route_cost_rub_per_unit,
            route.current_profit_per_unit, route.local_profit_per_unit,
            route.price_per_unit, route.complete, route.reason_codes))
        for route_day in days)
    economics=aggregate_impacts((route,))
    return StockoutEpisodeImpact(f"{sku}::Москва::{days[0]}::{days[-1]}::{scope}",
        sku,"Москва",days[0],days[-1],days,scope,"high",route.quantity,
        route.quantity,0,route.quantity,D("0"),D("1"),D("1"),D("0"),(),economics,
        (route,),route_days)


def test_daily_series_is_destination_day_weighted_and_bounded():
    start=date(2026,1,1); locality=[]
    for offset in range(60):
        day=start+timedelta(days=offset)
        for sku, local, external in (("A",90,10),("B",1,9)):
            locality.append(DailyLocalityPoint(sku,"Москва",day,110,local+external,
                local,external,D(local)/D(local+external),D(external)/D(local+external),()))
    result=build_stockout_impact_presentation(tuple(locality),())
    assert len(result.destination_daily_series)==1
    assert len(result.destination_daily_series[0].points)==60
    point=result.destination_daily_series[0].points[0]
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        assert point.local_share==D("91")/D("110")
    assert point.local_share != D("0.5")
    assert point.local_fulfilled_qty+point.external_fulfilled_qty==point.fulfilled_quantity


def test_episode_destination_weighting_reconciliation_identity_and_basis_text():
    a=impact("A",60,price=D("100"),current_profit=D("10"),local_profit=D("20"))
    b=impact("B",40,price=D("1000"),current_profit=D("200"),local_profit=D("250"))
    episodes=(episode("A",a),episode("B",b))
    locality=(DailyLocalityPoint("A","Москва",date(2026,8,17),60,60,0,60,D("0"),D("1"),()),
              DailyLocalityPoint("B","Москва",date(2026,8,17),40,40,0,40,D("0"),D("1"),()))
    result=build_stockout_impact_presentation(locality,episodes,
                                               {"A":("ART-A","Name A")})
    summary=result.destination_summaries[0]
    assert result.economics_basis_text==ECONOMICS_BASIS_TEXT
    assert sum(x.external_quantity for x in summary.sku_breakdown)==summary.episode_external_quantity==100
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        assert summary.episode_economics.weighted_current_margin_rate==(D("10")*60+D("200")*40)/(D("100")*60+D("1000")*40)
    assert result.episodes[0].article=="ART-A"
    assert sum(d.quantity for e in result.episodes for d in e.donors)==100
    assert sum(d.share_of_episode_external_qty for d in result.episodes[0].donors)==D("1")


def test_overlapping_historical_and_operational_episodes_do_not_double_count_destination_impact():
    days = tuple(date(2026, 9, day) for day in range(2, 7))
    historical = episode("A", impact("A", 40), days=days[:4])
    operational = episode("A", impact("A", 50), days=days,
                          scope="operational_current_week")
    locality = tuple(
        DailyLocalityPoint("A", "Москва", date(2026, 9, day), 10, 10, 0, 10,
                           D("0"), D("1"), ())
        for day in range(2, 7)
    )

    result = build_stockout_impact_presentation(
        locality, (historical, operational)
    )

    assert [view.external_quantity for view in result.episodes] == [40, 50]
    summary = result.destination_summaries[0]
    assert summary.episode_external_quantity == 50
    assert summary.sku_breakdown[0].external_quantity == 50
    assert [view.economics.profit_loss_or_opportunity_rub
            for view in result.episodes] == [D("4000"), D("5000")]
    assert summary.episode_economics.profit_loss_or_opportunity_rub == D("5000")
    assert summary.episode_economics.extra_logistics_rub == D("5000")


def test_unique_factual_aggregation_keeps_different_skus():
    same_day = date(2026, 9, 3)
    a = episode("A", impact("A", 10), same_day)
    b = episode("B", impact("B", 20), same_day)
    locality = tuple(DailyLocalityPoint(
        sku, "Москва", day, quantity, quantity, 0, quantity, D("0"), D("1"), ())
        for sku, day, quantity in (("A", same_day, 10), ("B", same_day, 20)))
    summary = build_stockout_impact_presentation(
        locality, (a, b)).destination_summaries[0]
    assert summary.episode_external_quantity == 30
    assert {row.sku: row.external_quantity for row in summary.sku_breakdown} == {
        "A": 10, "B": 20}


def test_unique_factual_aggregation_sums_nonoverlapping_episodes():
    first_days = (date(2026, 9, 1), date(2026, 9, 2))
    later_days = (date(2026, 9, 5), date(2026, 9, 6))
    episodes = (episode("A", impact("A", 20), days=first_days),
                episode("A", impact("A", 30), days=later_days))
    quantities = [(day, 10) for day in first_days]
    quantities.extend((day, 15) for day in later_days)
    locality = tuple(DailyLocalityPoint(
        "A", "Москва", day, quantity, quantity, 0, quantity,
        D("0"), D("1"), ()) for day, quantity in quantities)
    summary = build_stockout_impact_presentation(
        locality, episodes).destination_summaries[0]
    assert summary.episode_external_quantity == 50
