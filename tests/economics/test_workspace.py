from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

import backend.application  # Import order required by the existing analytics/economics packages.
from backend.economics.workspace import (_profit_at_price, build_economics_workspace,
                                         validate_targets, _target_price)
from backend.project import EconomicsSettings


def sample_snapshot(*, partial=False):
    d = Decimal
    settings = EconomicsSettings(d('.01'), d('.05'), d('1'), d('0'),
                                 'usn_income', d('.06'), d('0'), d('0'))
    unit = NS(sku='SKU', price=d('100'), cost=d('40'), commission=d('25'))
    def route(origin, destination, quantity, logistics, profit):
        return NS(sku='SKU', origin_cluster_id=origin,
                  destination_cluster_id=destination, observed_qty=quantity,
                  price_per_unit=d('100'), route_cost_rub=d(logistics),
                  current_profit_per_unit=None if partial and origin == 'Казань' else d(profit),
                  reason_codes=('MISSING_ROUTE',) if partial and origin == 'Казань' else ())
    window = NS(included_weeks=((2026, 38), (2026, 39)))
    return NS(economics_settings=settings, unit_economics=(unit,),
              route_economics=(route('Москва', 'Москва', 10, '10', '13'),
                               route('Казань', 'Москва', 5, '30', '-7')),
              decision_rows=(NS(sku='SKU', article='26572', product_name='Розетка'),),
              observed_routes=NS(window=window, routes=()))


def workspace(snapshot, **kwargs):
    kwargs.setdefault('real_drr', {'SKU': '.05'})
    return build_economics_workspace(snapshot, margin='0.20', roi='0.40',
                                     goal='margin', planned_drr='0.05', **kwargs)


@pytest.mark.parametrize('goal,expected', [('margin', '69.77'), ('roi', '60.32')])
def test_target_can_lower_price_and_still_reaches_selected_goal(goal, expected):
    d = Decimal
    settings = sample_snapshot().economics_settings
    price = _target_price(d('100'), d('20'), d('10'), d('.25'), settings,
                          d('.05'), d('.20'), d('.40'), goal)
    assert price == d(expected)
    threshold = lambda p: p * d('.20') if goal == 'margin' else d('8')
    assert _profit_at_price(price, d('20'), d('10'), d('.25'), settings, d('.05')) >= threshold(price)
    smaller = price - d('.01')
    assert _profit_at_price(smaller, d('20'), d('10'), d('.25'), settings, d('.05')) < threshold(smaller)


def test_before_ad_profit_is_independent_of_real_drr():
    before = workspace(sample_snapshot(), real_drr={'SKU': '.05'})['products'][0]
    after = workspace(sample_snapshot(), real_drr={'SKU': '.20'})['products'][0]
    assert before['profit_before_ads_total'] == after['profit_before_ads_total'] == Decimal('170')
    assert before['profit_per_unit'] != after['profit_per_unit']


def test_lower_price_direction_uses_all_routes():
    snap = sample_snapshot()
    snap.unit_economics[0].cost = Decimal('20')
    for route in snap.route_economics:
        route.route_cost_rub = Decimal('10')
    p = workspace(snap)['products'][0]
    assert p['price_action'] == 'lower'
    assert p['price_delta'] == Decimal('-30.23')
    assert p['price_delta_rate'] == Decimal('-.3023')


def test_unreachable_target_does_not_suggest_a_price():
    d = Decimal
    assert _target_price(d('100'), d('20'), d('10'), d('.25'),
        sample_snapshot().economics_settings, d('.90'), d('.20'), d('.40'), 'margin') is None


@pytest.mark.parametrize('goal,cost,current,expected', [
    ('margin', '80', '100.01', '100.00'),
    ('margin', '80', '1000', '100.00'),
    ('roi', '20', '1000', '28.00'),
])
def test_exact_kopek_price_is_the_minimum(goal, cost, current, expected):
    d = Decimal
    settings = EconomicsSettings(d('0'), d('0'), d('1'), d('0'),
                                 'usn_income', d('0'), d('0'), d('0'))
    price = _target_price(d(current), d(cost), d('0'), d('0'), settings,
                          d('0'), d('.20'), d('.40'), goal)
    assert price == d(expected)
    threshold = lambda p: p * d('.20') if goal == 'margin' else d(cost) * d('.40')
    assert _profit_at_price(price, d(cost), d('0'), d('0'), settings, d('0')) >= threshold(price)
    smaller = price - d('.01')
    assert _profit_at_price(smaller, d(cost), d('0'), d('0'), settings, d('0')) < threshold(smaller)


def test_exact_tax_breakpoint_price_and_lower_direction():
    d = Decimal
    snap = sample_snapshot()
    snap.economics_settings = EconomicsSettings(d('0'), d('0'), d('1'), d('0'),
        'usn_income_minus_expenses', d('.15'), d('0'), d('0'))
    snap.unit_economics[0].cost = d('80')
    snap.unit_economics[0].commission = d('0')
    snap.unit_economics[0].price = d('80.01')
    for route in snap.route_economics:
        route.price_per_unit = d('80.01')
        route.route_cost_rub = d('0')
    product = build_economics_workspace(snap, margin='0', roi='0', goal='margin',
        planned_drr='0')['products'][0]
    assert product['target_price_all_routes'] == d('80.00')
    assert product['price_action'] == 'lower'
    assert product['price_delta'] == d('-.01')


def test_product_and_both_cluster_roles_reconcile_without_double_count():
    report = workspace(sample_snapshot())
    product = report['products'][0]
    assert report['period'] == {'from': date(2026, 9, 14), 'to': date(2026, 9, 27)}
    assert report['evidence'] == 'fulfilled_completed_weeks'
    assert product['qty'] == product['covered_qty'] == 15
    assert product['commission_rate'] == Decimal('.25')
    assert product['modeled_shortfall'] == report['modeled_shortfall'] == Decimal('205')
    assert product['below_margin'] and product['below_roi']
    assert len(product['groups']['origin']) == 2
    assert len(product['groups']['destination']) == 1
    for role in ('origin', 'destination'):
        assert sum(group['qty'] for group in product['groups'][role]) == 15
        assert sum(group['modeled_shortfall'] for group in product['groups'][role]) == 205


def test_price_uses_planned_drr_but_historical_gap_uses_original_rates():
    before = workspace(sample_snapshot())['products'][0]
    after = workspace(sample_snapshot(), per_sku_drr={'SKU': '.10'})['products'][0]
    assert after['target_price_all_routes'] > before['target_price_all_routes']
    assert before['target_price_all_routes'] > Decimal('100')
    assert after['modeled_shortfall'] == before['modeled_shortfall'] == 205
    assert after['real_drr_rate'] == Decimal('.05')
    assert after['planned_drr_rate'] == Decimal('.10')


def test_recommended_price_reaches_margin_on_the_most_expensive_route():
    snapshot = sample_snapshot()
    product = workspace(snapshot)['products'][0]
    price = product['target_price_all_routes']
    args = (Decimal('40'), Decimal('30'), Decimal('.25'),
            snapshot.economics_settings, Decimal('.05'))
    assert _profit_at_price(price, *args) >= price * Decimal('.20')
    assert _profit_at_price(price - Decimal('.01'), *args) < (price - Decimal('.01')) * Decimal('.20')


def test_partial_route_excludes_unknown_and_blocks_one_price_for_all_routes():
    product = workspace(sample_snapshot(partial=True))['products'][0]
    assert product['qty'] == 15 and product['covered_qty'] == 10
    assert product['partial'] is True
    assert product['modeled_shortfall'] == 70
    assert product['target_price_all_routes'] is None


def test_new_catalog_sku_without_route_is_visible_but_not_a_zero_loss():
    snapshot = sample_snapshot()
    snapshot.decision_rows += (NS(sku='NEW', article='100', product_name='Новый товар'),)
    report = workspace(snapshot)
    new = next(p for p in report['products'] if p['sku'] == 'NEW')
    assert new['no_observations'] is True and new['qty'] == 0
    assert new['modeled_shortfall'] is None and new['target_price_all_routes'] is None
    assert report['incomplete_sku_count'] == 1


def test_observed_route_without_economics_is_partial_not_absent():
    snapshot = sample_snapshot()
    snapshot.observed_routes.routes = (
        NS(sku='SKU', origin_cluster_id='Самара',
           destination_cluster_id='Москва', quantity=3),)
    product = workspace(snapshot)['products'][0]
    assert product['qty'] == 18 and product['covered_qty'] == 15
    assert product['partial'] is True
    assert product['target_price_all_routes'] is None
    assert len(product['groups']['origin']) == 3


def test_margin_and_roi_flags_are_independent_of_selected_pricing_goal():
    report = build_economics_workspace(sample_snapshot(), margin='0', roi='0.40',
                                       goal='margin', planned_drr='0.05', real_drr={'SKU': '.05'})
    product = report['products'][0]
    assert product['below_goal'] is False
    assert product['below_margin'] is False and product['below_roi'] is True
    assert product['groups']['destination'][0]['below_roi'] is True


@pytest.mark.parametrize('margin,roi,goal,drr', [
    ('NaN', '.4', 'margin', '.05'), ('1', '.4', 'margin', '.05'),
    ('.2', '-1', 'roi', '.05'), ('.2', '.4', 'other', '.05'),
    ('.2', '.4', 'margin', '.91'),
])
def test_invalid_financial_targets_are_rejected(margin, roi, goal, drr):
    with pytest.raises(ValueError):
        validate_targets(margin, roi, goal, drr)


def test_real_drr_changes_current_metrics_but_not_original_snapshot():
    snapshot = sample_snapshot()
    before = workspace(snapshot)['products'][0]
    after = workspace(snapshot, real_drr={'SKU': '.10'})['products'][0]
    assert abs(after['profit_per_unit'] - before['profit_per_unit'] + Decimal('5')) < Decimal('1e-25')
    assert after['margin'] < before['margin'] and after['roi'] < before['roi']
    assert after['target_price_all_routes'] == before['target_price_all_routes']
    assert snapshot.economics_settings.advertising_rate == Decimal('.05')


def test_cost_is_visible_even_when_route_economics_is_incomplete():
    snapshot = sample_snapshot(partial=True)
    snapshot.unit_economics[0].commission = None
    product = workspace(snapshot)['products'][0]
    assert product['cost'] == Decimal('40')
    assert product['price'] == Decimal('100')
    assert product['margin'] is None


def test_saved_cost_repairs_observed_route_even_if_another_placement_lacks_tariffs():
    snapshot = sample_snapshot()
    snapshot.unit_economics[0].cost = None
    snapshot.unit_economics[0].blockers = ('MISSING_COST', 'INCOMPLETE_LOGISTICS_COVERAGE')
    for route in snapshot.route_economics:
        route.current_profit_per_unit = None
        route.reason_codes = ('CURRENT_ECONOMICS_INCOMPLETE',)
    product = workspace(snapshot, per_sku_cost={'SKU': Decimal('40')})['products'][0]
    assert product['covered_qty'] == 15
    assert product['modeled_shortfall'] == 205
    assert product['target_price_all_routes'] is not None
    snapshot.route_economics[1].reason_codes += ('CURRENT_ROUTE_INCOMPLETE',)
    product = workspace(snapshot, per_sku_cost={'SKU': Decimal('40')})['products'][0]
    assert product['covered_qty'] == 10
    assert product['target_price_all_routes'] is None


def test_unknown_real_drr_uses_explicit_zero_and_keeps_current_scenario():
    product = workspace(sample_snapshot(),real_drr={})['products'][0]
    assert product['real_drr_rate'] is None
    assert product['applied_drr_rate'] == 0
    assert product['drr_zero_assumed'] is True
    assert product['covered_qty'] == 15
    assert product['modeled_shortfall'] == 130
    assert product['commission_per_unit'] == Decimal('25')


def test_optional_plan_fallback_changes_current_profit_but_not_before_ad_basis():
    original = workspace(sample_snapshot(), real_drr={})['products'][0]
    planned = workspace(sample_snapshot(), real_drr={}, use_planned_drr=True)['products'][0]
    assert planned['real_drr_rate'] is None
    assert planned['applied_drr_rate'] == Decimal('.05')
    assert planned['applied_drr_source'] == 'plan'
    assert planned['profit_per_unit'].quantize(Decimal('.01')) == Decimal('6.33')
    assert planned['profit_before_ads_total'] == original['profit_before_ads_total']


def test_incomplete_uploaded_report_is_not_replaced_by_zero_or_plan():
    product = workspace(sample_snapshot(), real_drr={}, use_planned_drr=True,
                        reported_skus={'SKU'})['products'][0]
    assert product['applied_drr_rate'] is None
    assert product['applied_drr_source'] == 'incomplete_report'
    assert product['profit_per_unit'] is None
