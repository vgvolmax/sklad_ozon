from dataclasses import replace
from decimal import Decimal as D

import pytest
import backend.application
from backend.domain.contracts import ProductEconomicsInput, TariffRow, ImportResult, ReportMeta
from backend.project import EconomicsSettings


def inputs(price=D('100'), cost=D('40')):
    return ProductEconomicsInput('NEW', 'ART', cost, 0, price, D('.25'), D('1'))


def settings():
    return EconomicsSettings(D('.01'), D('.05'), D('1'), D('0'),
                             'usn_income', D('.06'), D('0'), D('0'))


def tariffs(*rows):
    return ImportResult(tuple(rows) or (tier('A', 'B', '10'),), (), ReportMeta('tariffs.xlsx', '2026-10-05'))


def tier(origin, destination, fee, lower=None, upper=None):
    return TariffRow(origin, destination, D('0'), None,
        D(lower) if lower is not None else None, D(upper) if upper is not None else None, D(fee))


def calc(product=None, table=None, routes=(('A', 'B'),), goal='margin', margin='.20', drr='.05'):
    from backend.economics.pricing import calculate_pricing
    return calculate_pricing(product or inputs(), table or tariffs(), settings(), routes,
        drr=D(drr), margin=D(margin), roi=D('.4'), goal=goal)


def test_no_sales_or_current_price_does_not_block_target():
    r = calc(inputs(None))
    assert r['target_price'] == D('116.28')
    assert r['profit_per_unit'] is None
    assert r['profit_per_unit_before_ads'] is None


def test_current_components_and_before_ad_basis_are_separate():
    r = calc()
    assert r['profit_per_unit'] == D('13')
    assert r['profit_per_unit_before_ads'] == D('18')
    assert r['target_price'] == D('116.28')
    assert r['line_items']['COMMISSION'] == D('25')


def test_lower_price_and_zero_cost_margin_are_supported():
    assert calc(margin='.05')['target_price'] == D('86.21')
    assert calc(inputs(cost=D('0')))['target_price'] == D('23.26')
    assert calc(inputs(cost=D('0')), goal='roi')['target_price'] is None


def test_price_search_rechecks_tariff_after_price_crosses_tier():
    r = calc(inputs(D('90')), tariffs(tier('A', 'B', '10', upper='100'),
                                      tier('A', 'B', '40', lower='100')))
    assert r['target_price'] == D('186.05')
    assert r['target_logistics'] == D('40')


def test_universal_price_can_cross_another_routes_expensive_tier():
    r = calc(table=tariffs(tier('A', 'B', '10', upper='150'),
                          tier('A', 'B', '1000', lower='150'),
                          tier('A', 'C', '30')), routes=(('A', 'B'), ('A', 'C')))
    assert r['target_price'] == D('2418.61')
    assert r['limiting_route'] == ('A', 'B')


@pytest.mark.parametrize('rows', [
    (tier('A', 'C', '10'),),
    (tier('A', 'B', '10'), tier('A', 'B', '20')),
])
def test_missing_or_ambiguous_tariff_is_unknown_not_free(rows):
    r = calc(table=tariffs(*rows))
    assert r['target_price'] is None and r['profit_per_unit'] is None
    assert r['reason_codes']


def test_goal_can_be_unreachable_without_excessive_growth_or_fake_price():
    r = calc(replace(inputs(), commission_rate=D('1')))
    assert r['target_price'] is None


@pytest.mark.parametrize('real,planned,fallback,present,rate,source', [
    (D('0'), D('.15'), True, True, D('0'), 'real'),
    (D('.08'), D('.15'), True, True, D('.08'), 'real'),
    (None, D('0'), True, False, D('0'), 'plan'),
    (None, D('.15'), True, False, D('.15'), 'plan'),
    (None, D('.15'), False, False, D('0'), 'zero_assumption'),
    (None, D('.15'), True, True, None, 'incomplete_report'),
])
def test_drr_policy_preserves_zero_and_report_failure(real, planned, fallback, present, rate, source):
    from backend.economics.pricing import resolve_drr
    assert resolve_drr(real, planned, fallback, report_present=present) == (rate, source)


def test_real_advertising_can_exceed_revenue():
    result = calc(drr='1.2')
    assert result['profit_per_unit'] == D('-102')
    assert result['profit_per_unit_before_ads'] == D('18')


def test_missing_tariff_identifies_its_route():
    r = calc(table=tariffs(tier('A','B','10')),routes=(('A','B'),('A','C')))
    bad = next(route for route in r['routes'] if route['destination']=='C')
    assert 'INCOMPLETE_LOGISTICS_COVERAGE' in bad['reason_codes']
    assert r['target_price'] is None
