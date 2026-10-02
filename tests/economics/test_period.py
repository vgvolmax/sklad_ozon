from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from backend.analytics.daily import DailyFulfillmentCell
from tests.economics.test_workspace import sample_snapshot, workspace


def period_snapshot():
    from backend.domain.economics_daily import EconomicsPeriodEvidence
    snap = sample_snapshot()
    snap.economics_period_evidence = EconomicsPeriodEvidence(
        date(2026, 9, 1), date(2026, 9, 30), (
            DailyFulfillmentCell('SKU', date(2026, 9, 1), 'Москва', 'Москва', 2, 1),
            DailyFulfillmentCell('SKU', date(2026, 9, 2), 'Казань', 'Москва', 3, 1),
            DailyFulfillmentCell('SKU', date(2026, 9, 30), 'Москва', 'Москва', 7, 1),
        ), snap.route_economics)
    return snap


def test_period_changes_route_weights_and_keeps_original_snapshot():
    snap = period_snapshot()
    report = workspace(snap, period_from='2026-09-02', period_to='2026-09-30')
    p = report['products'][0]
    assert report['period'] == {'from': date(2026, 9, 2), 'to': date(2026, 9, 30)}
    assert report['observation_period']['from'] == date(2026, 9, 1)
    assert p['qty'] == p['covered_qty'] == 10
    assert p['modeled_shortfall'] == 130  # 3 × 27 + 7 × 7.
    for role in ('origin', 'destination'):
        assert sum(g['qty'] for g in p['groups'][role]) == 10
    assert snap.route_economics[0].observed_qty == 10
    assert snap.observed_routes.window.included_weeks == ((2026, 38), (2026, 39))


def test_default_uses_loaded_history_and_empty_period_has_no_fake_profit():
    snap = period_snapshot()
    assert workspace(snap)['products'][0]['qty'] == 12
    p = workspace(snap, period_from='2026-09-03', period_to='2026-09-29')['products'][0]
    assert p['qty'] == 0 and p['no_observations']
    assert p['profit_per_unit'] is None and p['modeled_shortfall'] is None


@pytest.mark.parametrize('start,end', [('2026-09-02', None),
    ('2026-09-03', '2026-09-02'), ('2026-08-31', '2026-09-02'),
    ('2026-09-01', '2026-10-01'), ('2026-9-1', '2026-09-02'),
    (True, '2026-09-02')])
def test_invalid_period_is_rejected(start, end):
    with pytest.raises(ValueError):
        workspace(period_snapshot(), period_from=start, period_to=end)


def test_unknown_period_route_remains_partial():
    snap = period_snapshot()
    from dataclasses import replace
    snap.economics_period_evidence = replace(snap.economics_period_evidence,
        daily_routes=snap.economics_period_evidence.daily_routes + (
            DailyFulfillmentCell('SKU', date(2026, 9, 2), 'Самара', 'Москва', 4, 1),))
    p = workspace(snap, period_from='2026-09-02', period_to='2026-09-02')['products'][0]
    assert p['qty'] == 7 and p['covered_qty'] == 3 and p['partial']
    assert p['target_price_all_routes'] is None


def test_weekly_means_use_priced_units_and_clip_edge_weeks():
    from backend.economics.daily_series import build_daily_evidence, daily_series
    from backend.analytics._weeks import ObservationCoverage
    from tests.economics.test_daily_series import order
    evidence = build_daily_evidence([
        order('2026-09-01', 100, 20, 1), order('2026-09-02', 100, 80, 3),
        order('2026-09-02', 100, None, 2), order('2026-09-07', 100, 50, 2)
    ], ObservationCoverage(date(2026, 9, 1), date(2026, 9, 8)))
    series = daily_series(evidence, '100', period_from='2026-09-02',
                          period_to='2026-09-07', granularity='week')
    assert len(series['days']) == 2
    first, second = series['days']
    assert first['day'] == date(2026, 9, 2) and first['to'] == date(2026, 9, 6)
    assert first['orders'] == 5 and first['spp'] == Decimal('.2')
    assert first['buyer_price_mean'] == 80 and first['spp_priced_qty'] == 3
    assert second['orders'] == 2 and second['buyer_price_mean'] == 50
    all_weeks = daily_series(evidence, '100', granularity='week')
    assert all_weeks['days'][0]['spp'] == Decimal('.35')
    assert all_weeks['days'][0]['buyer_price_mean'] == 65
    assert series['ordered_qty'] == 7


def test_advertising_clips_both_expense_and_all_order_revenue():
    from backend.economics.advertising import real_drr_by_sku
    data = NS(days=(NS(sku='SKU', day=date(2026, 9, 1), spend=Decimal(900)),
                    NS(sku='SKU', day=date(2026, 9, 2), spend=Decimal(10))))
    evidence = NS(complete=True, incomplete_skus=(), period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 3), days=(
            NS(sku='SKU', day=date(2026, 9, 1), revenue=Decimal(1000)),
            NS(sku='SKU', day=date(2026, 9, 2), revenue=Decimal(100))))
    result = real_drr_by_sku(data, evidence, {'SKU'},
        period_from=date(2026, 9, 2), period_to=date(2026, 9, 3))['SKU']
    assert result['spend'] == 10 and result['order_revenue'] == 100
    assert result['rate'] == Decimal('.1') and result['day_count'] == 1
