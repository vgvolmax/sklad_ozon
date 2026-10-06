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
    def post_json(self, path, body, *, policy, check_cancelled=None):
        if check_cancelled:
            check_cancelled()
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


@pytest.mark.parametrize('commission_credit,delivery_charge', [(100, 0), (0, -50)])
def test_zero_sale_adjustments_do_not_create_or_erase_buyouts(commission_credit, delivery_charge):
    from backend.economics.period_profit import build_period_profit
    adjustment = posting('adjustment', total_amount=money(commission_credit + delivery_charge))
    p = adjustment['posting']['products'][0]
    p['commission'].update(sale_amount=money(0), sale_price=money(1000),
        commission=money(commission_credit))
    p['delivery']['total_accrued'] = money(delivery_charge)
    snapshot = fetch(Client([{'accruals': [posting(), adjustment], 'last_id': ''}]))
    assert snapshot.products[1].quantity == 0
    report = build_period_profit([dict(sku='100', price=D('1000'),
        profit_per_unit_before_ads=D('150'), pricing_complete=True)],
        {'from': DAY, 'to': DAY}, (), snapshot, 'buyouts')
    assert report['totals']['qty'] == report['totals']['purchased_qty'] == 3
    assert report['totals']['profit_after_common'] == D('450')
    assert report['totals']['partial'] is False


@pytest.mark.parametrize('sale_price,compensation', [(None, 100), (None, 0), (0, 0)])
def test_ambiguous_zero_sale_never_inherits_original_posting(sale_price, compensation):
    p = posting(total_amount=money(compensation))
    p['posting']['products'][0]['commission'].update(sale_amount=money(0),
        sale_price=None if sale_price is None else money(sale_price), commission=money(compensation))
    p['posting']['products'][0]['delivery']['total_accrued'] = money(0)
    snapshot = fetch(Client([{'accruals': [p], 'last_id': ''}]))
    assert snapshot.products[0].quantity is None


def test_missing_sale_amount_is_not_an_explicit_zero_sale():
    p = posting(total_amount=money(100))
    commission = p['posting']['products'][0]['commission']
    commission.pop('sale_amount')
    commission.update(sale_price=money(1000), commission=money(100))
    p['posting']['products'][0]['delivery']['total_accrued'] = money(0)
    assert fetch(Client([{'accruals': [p], 'last_id': ''}])).products[0].quantity is None


@pytest.mark.parametrize('seller_price', [None, 0])
def test_missing_sale_amount_and_seller_price_keep_buyouts_unknown(seller_price):
    from backend.economics.period_profit import build_period_profit
    p = posting(total_amount=money(100))
    commission = p['posting']['products'][0]['commission']
    commission.pop('sale_amount')
    commission.update(seller_price=None if seller_price is None else money(seller_price),
        sale_price=money(1000), commission=money(100))
    p['posting']['products'][0]['delivery']['total_accrued'] = money(0)
    client = Client([{'accruals': [p], 'last_id': ''}])
    snapshot = fetch(client)
    assert snapshot.products[0].quantity is None
    assert not any(path.endswith('/get') for path, _ in client.calls)
    report = build_period_profit([dict(sku='100', price=D('1000'),
        profit_per_unit_before_ads=D('150'), pricing_complete=True)],
        {'from': DAY, 'to': DAY}, (), snapshot, 'buyouts')
    assert report['totals']['qty'] is None
    assert report['totals']['profit_before_common'] is None
    assert report['totals']['partial'] is True


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


def test_progress_inside_a_day_exposes_work_before_posting_lookup():
    p = posting()
    p['posting']['products'][0]['commission']['sale_price'] = None
    client = Client([{'accruals': [p], 'last_id': ''}])
    events = []
    def progress(value):
        events.append((value.copy(), len(client.calls)))
    importlib.import_module('backend.ozon.adapters.finance').fetch_finance(
        client, DAY, DAY, 'account-1', progress_callback=progress)
    lookup = [v for v, calls in events if v.get('stage') == 'posting' and calls == 2]
    assert lookup, 'Long posting lookups must publish progress before the request.'
    assert lookup[0]['day'] == DAY.isoformat() and lookup[0]['page'] == 1
    assert lookup[0]['processed'] == 0 and lookup[0]['page_total'] == 1
    assert events[-1][0]['current'] == 1 and events[-1][0]['processed'] == 1
    assert all('12345-1' not in str(event) for event in events)


def test_cancellation_inside_a_page_stops_before_next_seller_request():
    p = posting()
    p['posting']['products'][0]['commission']['sale_price'] = None
    client = Client([{'accruals': [p], 'last_id': ''}])
    def cancel_lookup(value):
        if value.get('stage') == 'posting':
            raise InterruptedError()
    with pytest.raises(InterruptedError):
        importlib.import_module('backend.ozon.adapters.finance').fetch_finance(
            client, DAY, DAY, 'account-1', progress_callback=cancel_lookup)
    assert not any(path.endswith('/get') for path, _ in client.calls)


@pytest.mark.parametrize('name,category', [
    ('Приёмка товаров', 'acceptance'), ('Штраф за нарушение', 'penalty'),
    ('Комиссия за продажу', 'commission'), ('Неизвестная услуга', 'other'),
    ('Возврат расходов на рекламу', 'advertising'),
])
def test_expense_category_retains_known_roles_and_unknown_services(name, category):
    from backend.ozon.adapters.finance import _category
    assert _category(name) == category


@pytest.mark.parametrize('name,description,accrued,category,profit,partial', [
    ('SupplyInbound', 'Доставка товаров на склад Ozon', -100, 'services', '350', False),
    ('SupplyInboundRefund', 'Возврат стоимости доставки на склад', 100, 'services', '550', False),
    ('OpaqueInboundType', 'Доставка товаров на склад Ozon', -100, 'services', '350', False),
    ('SellerSubscriptionRefund', 'Возврат стоимости подписки продавца', 100, 'other', '450', True),
    ('CommissionForSubscription', 'Комиссия за подписку', -100, 'other', '450', True),
    ('UnknownReturnsAfterPlacement', 'Возврат платы за новую услугу', 100, 'other', '450', True),
    ('Commission', 'Неизвестная комиссия', -100, 'other', '450', True),
    ('Delivery', 'Неизвестная доставка', -100, 'other', '450', True),
    ('Return', 'Неизвестный возврат', 100, 'other', '450', True),
    ('CustomerDelivery', 'Доставка покупателю', -100, 'logistics', '450', False),
    ('CustomerDeliveryRefund', 'Возврат стоимости доставки покупателю', 100, 'logistics', '450', False),
    ('CustomerReturnLogistics', 'Обратная логистика от покупателя', -100, 'returns', '450', False),
    ('SellerSaleCommission', 'Комиссия за продажу', -100, 'commission', '450', False),
    ('StorageRefund', 'Возврат платы за хранение товаров', 100, 'storage', '550', False),
    ('OpaqueAdvertisingType', 'Возврат расходов на рекламу', 100, 'advertising', '550', False),
    ('OpaqueAcceptanceType', 'Приёмка товаров', -100, 'acceptance', '350', False),
    ('Penalty', 'Штраф за нарушение', -100, 'penalty', '350', False),
    ('CrossDock', 'Кросс-докинг', -100, 'crossdock', '350', False),
])
def test_fee_scope_does_not_hide_unmodeled_expenses(name, description, accrued, category, profit, partial):
    from types import SimpleNamespace
    from backend.economics.period_profit import build_period_profit
    fee = {'accrual_id': 'fee', 'accrued_category': 'NON_ITEM', 'date': DAY.isoformat(),
        'total_amount': money(accrued), 'non_item_fee': {'type_id': 47, 'accrued': money(accrued)}}
    snapshot = fetch(Client([{'accruals': [posting(), fee], 'last_id': ''}],
        types=[{'id': 47, 'name': name, 'description': description}]))
    assert snapshot.expenses[-1].category == category
    assert snapshot.expenses[-1].amount == -D(accrued)
    basis = [dict(sku='100', price=D('1000'), profit_per_unit_before_ads=D('150'), pricing_complete=True)]
    for mode in ('orders', 'buyouts'):
        report = build_period_profit(basis, {'from': DAY, 'to': DAY},
            (SimpleNamespace(sku='100', day=DAY, quantity=3),), snapshot, mode)
        assert report['totals']['profit_after_common'] == D(profit)
        assert report['totals']['partial'] is partial
        assert any(e['role'] == 'unclassified' for e in report['expenses']) is partial
