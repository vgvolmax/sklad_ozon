from datetime import date, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from types import SimpleNamespace

from backend.analytics.stockout_episodes import DailyLocalityPoint
from backend.decision.impact import (ECONOMICS_BASIS_TEXT,
                                     build_stockout_impact_presentation)
from backend.economics.stockout_impact import (StockoutEpisodeImpact,
                                               aggregate_impacts)
from tests.economics.test_stockout_impact import impact

D=Decimal


def episode(sku, route, day=date(2026,8,17)):
    economics=aggregate_impacts((route,))
    return StockoutEpisodeImpact(f"{sku}::Москва::{day}::{day}::historical_complete",
        sku,"Москва",day,day,(day,),"historical_complete","high",route.quantity,
        route.quantity,0,route.quantity,D("0"),D("1"),D("1"),D("0"),(),economics,(route,))


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
