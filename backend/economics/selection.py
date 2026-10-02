"""Canonical Economics product selection, shared by the workspace and export."""
from decimal import Decimal

FILTERS = frozenset(('all', 'below', 'margin', 'roi', 'cluster', 'incomplete', 'lower'))


def select_products(products, *, search='', filter='all'):
    if not isinstance(search, str) or len(search) > 200:
        raise ValueError('Поиск должен быть строкой не длиннее 200 символов.')
    if not isinstance(filter, str) or filter not in FILTERS:
        raise ValueError('Неизвестный фильтр экономики.')
    query = search.strip().casefold()
    result = []
    for product in products:
        groups = [g for role in ('destination', 'origin')
                  for g in product['groups'][role]]
        labels = [product['article'], product['sku'], product['name'],
                  *(g['key'] for g in groups)]
        if query and not any(query in str(label or '').casefold() for label in labels):
            continue
        matches = {
            'all': True, 'below': product['below_goal'],
            'margin': product['below_margin'], 'roi': product['below_roi'],
            'cluster': any(g['below_margin'] or g['below_roi'] for g in groups),
            'incomplete': product['partial'] or product['no_observations'],
            'lower': product['price_action'] == 'lower',
        }
        if matches[filter]:
            result.append(product)
    return sorted(result, key=lambda p: (
        -(p['modeled_shortfall'] or Decimal('0')), p['article'], p['sku']))
