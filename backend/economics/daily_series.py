"""SPP and ordered units on the same calendar, using historical order prices."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext

from backend.analytics._weeks import parse_source_date
from backend.domain.economics_daily import DailyOrderEvidence, DailyOrderMetric


def build_daily_evidence(orders, coverage, *, orders_complete=True,
                         source_coverage=None, diagnostics=()):
    complete = (orders_complete and (source_coverage is None or source_coverage.demand_complete)
                and not any(d.severity == 'error' for d in diagnostics))
    incomplete = set(source_coverage.demand_incomplete_skus if source_coverage else ())
    quantities = defaultdict(int)
    amounts = defaultdict(lambda: [Decimal(0), Decimal(0)])
    invalid_pairs = set()
    for order in orders:
        day = parse_source_date(order.accepted_at)
        if day is None or type(order.quantity) is not int or order.quantity < 0:
            incomplete.add(order.sku)
            continue
        if not coverage.period_start <= day <= coverage.period_end or order.quantity == 0:
            continue
        key = order.sku, day
        quantities[key] += order.quantity
        try:
            explicit_base = getattr(order, 'spp_base_price', None)
            base = Decimal(str(explicit_base if explicit_base is not None else order.seller_price))
            paid = Decimal(str(order.buyer_price))
            if not base.is_finite() or not paid.is_finite() or base <= 0 or not 0 <= paid <= base:
                raise ValueError
        except (InvalidOperation, ValueError, AttributeError):
            invalid_pairs.add(key)
            continue
        amounts[key][0] += base * order.quantity
        amounts[key][1] += paid * order.quantity
    rows = []
    with localcontext() as context:
        context.prec = 40
        for (sku, day), quantity in sorted(quantities.items()):
            base, paid = amounts[sku, day]
            spp = (base - paid) / base if base and (sku, day) not in invalid_pairs else None
            rows.append(DailyOrderMetric(sku, day, quantity, spp))
    return DailyOrderEvidence(coverage.period_start, coverage.period_end, complete,
                              tuple(sorted(incomplete)), tuple(rows))


def daily_series(evidence, sku):
    if evidence is None:
        return {'period': None, 'days': [], 'spp_min': None, 'spp_max': None,
                'ordered_qty': None, 'complete': False,
                'reason': 'Пересчитайте план, чтобы получить историю заказов.'}
    complete = evidence.complete and sku not in evidence.incomplete_skus
    observed = {row.day: row for row in evidence.days if row.sku == sku}
    days = []
    day = evidence.period_start
    while day <= evidence.period_end:
        row = observed.get(day)
        days.append({'day': day, 'orders': row.quantity if row else (0 if complete else None),
                     'spp': row.spp if row else None})
        day += timedelta(days=1)
    values = [row['spp'] for row in days if row['spp'] is not None]
    missing_prices = any(row['orders'] and row['spp'] is None for row in days)
    reason = ('История заказов неполная: показаны известные заказы, пропуски не равны нулю.'
              if not complete else
              'Цена продавца или покупателя отсутствует либо некорректна для части заказов. Обновите историю; СПП этих дней не рассчитана.'
              if missing_prices else '')
    return {'period': {'from': evidence.period_start, 'to': evidence.period_end},
            'days': days, 'spp_min': min(values) if values else None,
            'spp_max': max(values) if values else None, 'complete': complete,
            'ordered_qty': sum(row.quantity for row in observed.values()), 'reason': reason}
