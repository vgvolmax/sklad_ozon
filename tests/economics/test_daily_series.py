from datetime import date
from decimal import Decimal

import pytest

from backend.analytics._weeks import ObservationCoverage
from backend.domain.contracts import OrderLifecycle, OrderRecord


def order(day, base, paid, qty=1, sku='100'):
    return OrderRecord(sku,qty,'Москва','Москва',OrderLifecycle.FULFILLED,
        accepted_at=day,seller_price=base,buyer_price=paid)


def test_daily_spp_and_buyer_price_are_unit_weighted_means_inside_coverage():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    evidence = build_daily_evidence([order('2026-09-01',100,40,2),order('2026-09-01',200,100),
        order('2026-09-03',100,50)],ObservationCoverage(date(2026,9,1),date(2026,9,3)))
    series = daily_series(evidence,'100')
    assert [d['orders'] for d in series['days']] == [3,0,1]
    assert series['days'][0]['spp'] == pytest.approx(Decimal('1.7') / 3)
    assert series['days'][0]['buyer_price_mean'] == Decimal('60')
    assert series['days'][0]['spp_priced_qty'] == series['days'][0]['buyer_priced_qty'] == 3
    assert series['days'][1]['spp'] is None
    assert series['spp_min'] == Decimal('.5') and series['spp_max'] == series['days'][0]['spp']
    assert series['buyer_price_min'] == 50 and series['buyer_price_max'] == 60
    assert series['ordered_qty'] == 4


def test_missing_buyer_price_preserves_known_mean_with_explicit_coverage():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    evidence = build_daily_evidence([order('2026-09-01',100,40),order('2026-09-01',100,None)],
        ObservationCoverage(date(2026,9,1),date(2026,9,2)))
    series = daily_series(evidence,'100')
    assert series['days'][0]['orders'] == 2
    assert series['days'][0]['spp'] == Decimal('.6')
    assert series['days'][0]['buyer_price_mean'] == 40
    assert series['days'][0]['spp_priced_qty'] == series['days'][0]['buyer_priced_qty'] == 1
    assert series['reason']


def test_buyer_mean_is_available_independently_of_spp_base_and_zero_is_real():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    series = daily_series(build_daily_evidence([order('2026-09-01',0,40,2),
        order('2026-09-01',100,0)], ObservationCoverage(date(2026,9,1),date(2026,9,2))), '100')
    assert series['days'][0]['buyer_price_mean'] == pytest.approx(Decimal(80) / 3)
    assert series['days'][0]['buyer_priced_qty'] == 3
    assert series['days'][0]['spp'] == 1 and series['days'][0]['spp_priced_qty'] == 1
    assert series['days'][1]['buyer_price_mean'] is None


def test_constant_spp_zero_spp_and_free_price_are_real_values():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    evidence = build_daily_evidence([order('2026-09-01',100,100),order('2026-09-02',100,0)],
        ObservationCoverage(date(2026,9,1),date(2026,9,2)))
    series = daily_series(evidence,'100')
    assert [d['spp'] for d in series['days']] == [0,1]


@pytest.mark.parametrize('base,paid', [(0,0),(100,101),(100,-1),(100,float('nan'))])
def test_invalid_price_pair_preserves_orders_but_not_spp(base,paid):
    from backend.economics.daily_series import build_daily_evidence, daily_series
    series = daily_series(build_daily_evidence([order('2026-09-01',base,paid)],
        ObservationCoverage(date(2026,9,1),date(2026,9,2))),'100')
    assert series['days'][0]['orders'] == 1 and series['days'][0]['spp'] is None


def test_incomplete_history_does_not_turn_empty_days_into_zero_orders():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    evidence = build_daily_evidence([order('2026-09-01',100,40)],
        ObservationCoverage(date(2026,9,1),date(2026,9,2)),orders_complete=False)
    series = daily_series(evidence,'100')
    assert series['complete'] is False
    assert series['days'][1]['orders'] is None
