"""Recognized service scopes; generic fee words cannot prove model coverage."""
import re


def _key(value):
    return re.sub(r'[^a-zа-я0-9]', '', value.casefold().replace('ё', 'е'))


# Exact names/descriptions establish the service, independent of amount sign.
# Unknown/new names remain visible as unclassified rather than being guessed
# from generic commission/delivery/refund/placement substrings.
_SCOPES = {
    'advertising': (
        'Advertising', 'Advertisement', 'Ads', 'Реклама', 'Продвижение товаров',
        'Оплата за клик', 'Возврат расходов на рекламу',
    ),
    'crossdock': ('CrossDock', 'CrossDocking', 'Кросс-докинг', 'Кросс-докинг товаров'),
    'storage': (
        'Storage', 'StorageFee', 'Хранение', 'Хранение товаров',
        'Плата за хранение товаров', 'Услуги хранения', 'Возврат платы за хранение товаров',
    ),
    'acceptance': ('Acceptance', 'Приёмка товаров', 'Услуга приёмки товаров'),
    'penalty': ('Penalty', 'Fine', 'Штраф', 'Штраф за нарушение'),
    'services': (
        'SupplyInbound', 'InboundDelivery', 'Доставка товаров на склад Ozon',
        'Доставка товаров на склад Озон', 'Услуга доставки товаров на склад Ozon',
        'Возврат стоимости доставки на склад',
    ),
    'commission': (
        'SellerSaleCommission', 'SaleCommission', 'Sale commission',
        'Commission for sale', 'Комиссия за продажу',
    ),
    'acquiring': ('Acquiring', 'PaymentAcquiring', 'Эквайринг', 'Комиссия за эквайринг'),
    'logistics': (
        'CustomerDelivery', 'Delivery to customer', 'Доставка покупателю',
        'Доставка до покупателя', 'LastMile', 'Последняя миля',
        'Возврат стоимости доставки покупателю',
    ),
    'returns': (
        'CustomerReturnLogistics', 'Customer return logistics',
        'Обратная логистика', 'Обратная логистика от покупателя',
    ),
}
_CATEGORIES = {_key(alias): category for category, aliases in _SCOPES.items() for alias in aliases}


def classify_expense(name, description=''):
    categories = set()
    for text in (name, description):
        key = _key(text)
        category = _CATEGORIES.get(key)
        if category is None and key.endswith('refund'):
            category = _CATEGORIES.get(key[:-len('refund')])
        if category is not None:
            categories.add(category)
    # Conflicting recognized scopes also require investigation, not precedence.
    return categories.pop() if len(categories) == 1 else 'other'
