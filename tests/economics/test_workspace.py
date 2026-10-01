from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

import backend.application  # Import order required by the existing analytics/economics packages.
from backend.economics.workspace import (_profit_at_price, build_economics_workspace,
                                         validate_targets)
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
