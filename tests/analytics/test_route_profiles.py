from datetime import date
from decimal import Decimal, getcontext

import pytest

from backend.analytics.clean_routes import CleanRouteResult, RouteDistributionCell
from backend.analytics.route_profiles import select_route_profile
from backend.analytics.routes import build_route_profile
from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.domain.signals import SignalConfidence
from backend.economics import RouteProfileSource


def observed(*rows):
    orders = [OrderRecord(sku=s, accepted_at="2026-08-17", origin_cluster=o,
                          destination_cluster=d, quantity=q,
                          lifecycle=OrderLifecycle.FULFILLED) for s,o,d,q in rows]
    return build_route_profile(orders, date(2026,8,31))


def clean(*cells):
    return CleanRouteResult((), tuple(cells), (), ())


def test_fixed_fallback_hierarchy_and_audit_population():
    obs = observed(("X","O","observed",20), ("Y","O","all",80), ("Z","D","global",900))
    exact_clean = RouteDistributionCell("X","O","clean",1,1,Decimal("1"))
    result = select_route_profile("X","O",clean(exact_clean),obs)
    assert result.source is RouteProfileSource.CLEAN
    assert result.confidence is SignalConfidence.HIGH
    assert result.profile == (exact_clean,)

    result = select_route_profile("X","O",clean(),obs)
    assert result.source is RouteProfileSource.OBSERVED
    assert result.confidence is SignalConfidence.MEDIUM
    assert [c.destination_cluster_id for c in result.profile] == ["observed"]

    result = select_route_profile("NEW","O",clean(),obs)
    assert result.source is RouteProfileSource.ORIGIN_ALL_SKUS
    assert result.confidence is SignalConfidence.LOW
    assert {(c.sku,c.origin_cluster_id) for c in result.profile} == {("NEW","O")}
    assert result.sample_quantity == sum(c.quantity for c in result.profile) == 100
    assert result.sample_observation_count == sum(c.observation_count for c in result.profile) == 2

    result = select_route_profile("NEW","TULA",clean(),obs)
    assert result.source is RouteProfileSource.GLOBAL
    assert {(c.sku,c.origin_cluster_id) for c in result.profile} == {("NEW","TULA")}
    assert result.sample_quantity == 1000
    assert sum(c.share for c in result.profile) == Decimal("1")


def test_empty_global_and_decimal_context_isolation():
    obs = observed()
    old = getcontext().prec
    try:
        getcontext().prec = 2
        result = select_route_profile("X","O",clean(),obs)
        assert result.profile == () and result.sample_quantity == 0
        assert result.source is RouteProfileSource.GLOBAL
        assert getcontext().prec == 2
    finally:
        getcontext().prec = old


@pytest.mark.parametrize("sku,origin", [(1,"O"),("X",None),(" ","O"),("X","")])
def test_invalid_identity_fails_fast(sku,origin):
    with pytest.raises((TypeError,ValueError)):
        select_route_profile(sku,origin,clean(),observed())
