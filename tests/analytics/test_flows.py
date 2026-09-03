from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, getcontext, localcontext

from backend.analytics.clean_routes import CleanRouteResult, RouteDistributionCell
from backend.analytics.flows import aggregate_clean_flows, aggregate_observed_flows
from backend.analytics.routes import build_route_profile
from backend.domain.contracts import OrderLifecycle, OrderRecord


def profile():
    rows=(("X","Москва","Москва",60),("X","Казань","Москва",40),
          ("X","Казань","Казань",30),("X","Самара","Казань",10))
    return build_route_profile((OrderRecord(sku=s,accepted_at="2026-08-17",origin_cluster=o,
        destination_cluster=d,quantity=q,lifecycle=OrderLifecycle.FULFILLED) for s,o,d,q in rows),date(2026,8,31))


def test_observed_shares_reconcile_per_sku_destination_and_are_deterministic():
    old=getcontext().prec
    try:
        getcontext().prec=2
        flows=aggregate_observed_flows(profile())
        by_destination={d:[f for f in flows if f.destination_cluster_id==d] for d in {f.destination_cluster_id for f in flows}}
        assert sum(f.quantity for f in by_destination["Москва"])==100
        assert sum(f.destination_share for f in by_destination["Москва"])==Decimal("1.0")
        assert sum(f.quantity for f in by_destination["Казань"])==40
        assert sum(f.destination_share for f in by_destination["Казань"])==Decimal("1.0")
        assert getcontext().prec==2
    finally: getcontext().prec=old


def test_clean_flows_use_only_clean_population():
    cells=(RouteDistributionCell("X","Москва","Москва",50,1,Decimal("0.5")),
           RouteDistributionCell("X","Казань","Москва",20,1,Decimal("0.5")))
    clean=CleanRouteResult((),cells,(),())
    flows=aggregate_clean_flows(clean)
    assert sum(f.quantity for f in flows)==70
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        assert [f.destination_share for f in flows]==[Decimal(20)/Decimal(70),Decimal(50)/Decimal(70)]
