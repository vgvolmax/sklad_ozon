from datetime import date
from decimal import Decimal as D
import importlib
import pytest

DAY = date(2026, 9, 1)


def money(value):
    return {'amount': str(value), 'currency': 'RUB'}


def posting(identity='1', **extra):
    return {'accrual_id': identity, 'accrued_category': 'POSTING', 'date': '2026-09-01',
        'unit_number': '12345-1', 'total_amount': money(1800), 'posting': {
            'delivery_schema': 'FBO', 'products': [{'sku': '100', 'commission': {
                'seller_price': money(1000), 'sale_price': money(400), 'sale_amount': money(1200),
                'commission': money(900), 'sale_commission': money(-1800), 'bonus': money(1800)},
                'delivery': {'total_accrued': money(-300), 'services': []}}]}, **extra}


class Client:
    def __init__(self, pages, types=None):
        self.pages = iter(pages); self.calls = []; self.types = types or []
    def post_json(self, path, body, *, policy):
        self.calls.append((path, body.copy()))
        if path.endswith('/types'): return {'accrual_types': self.types}
        if path.endswith('/by-day'): return next(self.pages)
        if path.endswith('/get'):
            return {'result': {'posting_number': body['posting_number'], 'products': [{'sku': '100', 'quantity': 3}]}}
        raise AssertionError(path)


def fetch(client, end=DAY):
    return importlib.import_module('backend.ozon.adapters.finance').fetch_finance(
        client, DAY, end, 'account-1')


def test_multiunit_net_and_nested_fees_are_not_added_twice():
    s = fetch(Client([{'accruals': [posting()], 'last_id': ''}]))
    p = s.products[0]
    assert p.quantity == 3 and p.revenue == D('3000') and p.net_amount == D('1800')
    assert sum(e.amount for e in s.expenses if e.sku is None) == 0
    assert sum(p.net_amount for p in s.products) == D('1800')


def test_fully_discounted_sale_still_has_goods_cost_quantity():
    p = posting(total_amount=money(1800))
    commission = p['posting']['products'][0]['commission']
    commission.update(sale_amount=money(0), sale_price=money(0), commission=money(2100))
    client = Client([{'accruals': [p], 'last_id': ''}])
    s = fetch(client)
    assert s.products[0].quantity == 3
    assert s.products[0].revenue == D('3000')
    assert any(path.endswith('/get') for path, _ in client.calls)


def test_unknown_partial_return_never_inherits_whole_original_posting():
    p = posting(total_amount=money(-600))
    p['posting']['products'][0]['commission'].update(sale_amount=money(-400), sale_price=None)
    client = Client([{'accruals': [p], 'last_id': ''}])
    s = fetch(client)
    assert s.products[0].quantity is None
    assert not any(path.endswith('/get') for path, _ in client.calls)


def test_all_pages_and_days_are_loaded_and_duplicate_accruals_are_not_recounted():
    p = posting()
    p2 = posting('2', date='2026-09-02')
    c = Client([{'accruals': [p], 'last_id': 'next'}, {'accruals': [p], 'last_id': ''},
                {'accruals': [p2], 'last_id': ''}])
    s = fetch(c, date(2026, 9, 2))
    assert len(s.products) == 2
    calls = [body for path, body in c.calls if path.endswith('/by-day')]
    assert calls == [{'date': '2026-09-01', 'last_id': ''},
                     {'date': '2026-09-01', 'last_id': 'next'},
                     {'date': '2026-09-02', 'last_id': ''}]


def test_partial_return_uses_returned_units_not_full_original_posting():
    p = posting(total_amount=money(-600))
    comm = p['posting']['products'][0]['commission']
    comm.update(sale_amount=money(-400), sale_price=money(-400), commission=money(-100))
    p['posting']['products'][0]['delivery']['total_accrued'] = money(-100)
    s = fetch(Client([{'accruals': [p], 'last_id': ''}]))
    assert s.products[0].quantity == -1 and s.products[0].revenue == D('-1000')
    assert s.products[0].net_amount == D('-600')


def test_common_and_item_advertising_and_unknown_categories_remain_visible():
    item = {'accrual_id': '2', 'accrued_category': 'ITEM', 'date': '2026-09-01',
            'unit_number': '', 'total_amount': money(-100),
            'item_fees': {'fees': [{'sku': '100', 'fees': [{'type_id': 41, 'accrued': money(-100)}]}]}}
    common = {'accrual_id': '3', 'accrued_category': 'NON_ITEM', 'date': '2026-09-01',
              'unit_number': '', 'total_amount': money(-50),
              'non_item_fee': {'type_id': 9999, 'accrued': money(-50)}}
    s = fetch(Client([{'accruals': [item, common], 'last_id': ''}],
                     [{'id': 41, 'name': 'Advertisement', 'description': 'Продвижение товаров'}]))
    assert s.products[0].quantity == 0 and s.products[0].net_amount == D('-100')
    assert [(e.category, e.amount, e.sku) for e in s.expenses] == [
        ('advertising', D('100'), '100'), ('other', D('50'), None)]


@pytest.mark.parametrize('changes', [{'total_amount': money('NaN')},
    {'total_amount': {'amount': '10', 'currency': 'USD'}}, {'date': '2026-08-31'}])
def test_bad_money_currency_or_day_does_not_become_zero(changes):
    with pytest.raises(ValueError):
        fetch(Client([{'accruals': [posting(**changes)], 'last_id': ''}]))


def test_cursor_loop_and_conflicting_duplicates_reject_the_load():
    with pytest.raises(ValueError):
        fetch(Client([{'accruals': [posting()], 'last_id': 'loop'},
                      {'accruals': [posting('2')], 'last_id': 'loop'}]))
    with pytest.raises(ValueError):
        fetch(Client([{'accruals': [posting(), posting(total_amount=money(2000))], 'last_id': ''}]))
