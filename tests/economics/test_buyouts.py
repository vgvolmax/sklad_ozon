from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace as NS
import importlib
import pytest


def api():
    return importlib.import_module('backend.economics.buyouts')


def snapshot(lines=(), expenses=()):
    m = api()
    return m.FinanceSnapshot('finance-1', 'account-1', date(2026, 9, 1),
        date(2026, 9, 30), tuple(lines), tuple(expenses), '2026-10-02T10:00:00+00:00')


def test_multiple_units_returns_and_known_expenses_count_once():
    m = api()
    source = snapshot([
        m.FinanceProductLine(date(2026, 9, 1), '100', 3, D('3000'), D('1800')),
        m.FinanceProductLine(date(2026, 9, 30), '100', -1, D('-1000'), D('-600')),
        m.FinanceProductLine(date(2026, 9, 2), '100', 0, D('0'), D('-100')),
    ], [m.FinanceExpense(date(2026, 9, 2), 'advertising', 'Реклама', D('100'), '100'),
        m.FinanceExpense(date(2026, 9, 3), 'crossdock', 'Кросс-докинг', D('50'))])
    r = m.build_buyout_report(source, [NS(sku='100', cost=D('200'))],
                             {'100': ('ART', 'Товар')})
    p = r['products'][0]
    assert (p['purchased_qty'], p['returned_qty'], p['qty']) == (3, 1, 2)
    assert p['revenue'] == D('2000') and p['cost_total'] == D('400')
    assert p['profit'] == D('700')
    assert r['totals']['profit_before_common'] == D('700')
    assert r['totals']['common_expenses'] == D('50')
    assert r['totals']['profit_after_known_expenses'] == D('650')
    assert r['totals']['advertising_spend'] == D('100')


def test_filter_does_not_subtract_store_expenses_from_selected_sku():
    m = api()
    source = snapshot([m.FinanceProductLine(date(2026, 9, 1), sku, 1, D('1000'), D('600'))
                       for sku in ('100', '200')],
        [m.FinanceExpense(date(2026, 9, 2), 'advertising', 'Реклама', D('100'))])
    r = m.build_buyout_report(source, [NS(sku=s, cost=D('200')) for s in ('100', '200')],
        {'100': ('DUP', 'Первый'), '200': ('DUP', 'Второй')}, search='ВТОРОЙ')
    assert [p['sku'] for p in r['products']] == ['200']
    assert r['selected_totals']['profit'] == D('400')
    assert r['totals']['profit_after_known_expenses'] == D('700')
    assert r['totals']['selected_sku_count'] == 1 and r['totals']['sku_count'] == 2


def test_unknown_cost_and_return_quantity_are_partial_not_zero():
    m = api()
    source = snapshot([m.FinanceProductLine(date(2026, 9, 1), 'OLD', 2, D('200'), D('100')),
                       m.FinanceProductLine(date(2026, 9, 2), '100', None, None, D('-50'))])
    r = m.build_buyout_report(source, [], {})
    assert r['totals']['partial']
    assert r['totals']['profit_before_common'] is None
    assert all(p['profit'] is None for p in r['products'])
    assert {p['sku'] for p in r['products']} == {'OLD', '100'}


def test_fee_only_period_and_positive_adjustments_have_real_result():
    m = api()
    r = m.build_buyout_report(snapshot(expenses=[
        m.FinanceExpense(date(2026, 9, 1), 'other', 'Возврат платы', D('-20')),
        m.FinanceExpense(date(2026, 9, 2), 'storage', 'Хранение', D('100'))]), [], {})
    assert r['totals']['profit_after_known_expenses'] == D('-80')
    assert r['totals']['purchased_qty'] == 0 and not r['totals']['partial']


@pytest.mark.parametrize('extra', [{'search': []}, {'filter': 'invalid'}, {'search': 'x'*201}])
def test_invalid_selection_does_not_silently_export_everything(extra):
    with pytest.raises(ValueError):
        api().build_buyout_report(snapshot(), [], {}, **extra)


def test_finance_calculation_imports_in_a_fresh_process():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', 'from backend.economics.buyouts import build_buyout_report'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
