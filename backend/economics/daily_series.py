"""Unit-weighted daily SPP and buyer prices on the historical order calendar."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext

from backend.analytics._weeks import parse_source_date
from backend.domain.economics_daily import DailyOrderEvidence, DailyOrderMetric
from .period import resolve_period


def _price(value):
    try:
        price = Decimal(str(value))
        return price if price.is_finite() and price >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def build_daily_evidence(orders, coverage, *, orders_complete=True,
                         source_coverage=None, diagnostics=()):
    complete = (orders_complete and (source_coverage is None or source_coverage.demand_complete)
                and not any(d.severity == 'error' for d in diagnostics))
    incomplete = set(source_coverage.demand_incomplete_skus if source_coverage else ())
    quantities = defaultdict(int)
    amounts = defaultdict(lambda: [Decimal(0), 0, Decimal(0), 0])
    with localcontext() as context:
        context.prec = 40
        for order in orders:
            day = parse_source_date(order.accepted_at)
            if day is None or type(order.quantity) is not int or order.quantity < 0:
                incomplete.add(order.sku)
                continue
            if not coverage.period_start <= day <= coverage.period_end or order.quantity == 0:
                continue
            key = order.sku, day
            quantities[key] += order.quantity
            explicit_base = getattr(order, 'spp_base_price', None)
            base = _price(explicit_base if explicit_base is not None else order.seller_price)
            paid = _price(getattr(order, 'buyer_price', None))
            if paid is not None:
                amounts[key][2] += paid * order.quantity
                amounts[key][3] += order.quantity
            if base is not None and base > 0 and paid is not None and paid <= base:
                amounts[key][0] += (base - paid) / base * order.quantity
                amounts[key][1] += order.quantity
        rows = []
        for (sku, day), quantity in sorted(quantities.items()):
            spp_sum, spp_qty, buyer_sum, buyer_qty = amounts[sku, day]
            rows.append(DailyOrderMetric(sku, day, quantity,
                spp_sum / spp_qty if spp_qty else None,
                buyer_sum / buyer_qty if buyer_qty else None, spp_qty, buyer_qty))
    return DailyOrderEvidence(coverage.period_start, coverage.period_end, complete,
                              tuple(sorted(incomplete)), tuple(rows))


def daily_series(evidence, sku, *, period_from=None, period_to=None, granularity='day'):
    if not isinstance(granularity, str) or granularity not in {'day', 'week'}:
        raise ValueError('Выберите представление по дням или неделям.')
    period = resolve_period(evidence, period_from, period_to)
    if evidence is None:
        return {'period': None, 'days': [], 'spp_min': None, 'spp_max': None,
                'buyer_price_min': None, 'buyer_price_max': None,
                'ordered_qty': None, 'complete': False,
                'reason': 'Пересчитайте план, чтобы получить историю заказов.'}
    complete = evidence.complete and sku not in evidence.incomplete_skus
    observed = {row.day: row for row in evidence.days if row.sku == sku
                and period['from'] <= row.day <= period['to']}
    days = []
    day = period['from']
    while day <= period['to']:
        row = observed.get(day)
        days.append({'day': day, 'orders': row.quantity if row else (0 if complete else None),
                     'spp': row.spp if row else None,
                     'buyer_price_mean': row.buyer_price_mean if row else None,
                     'spp_priced_qty': row.spp_priced_qty if row else 0,
                     'buyer_priced_qty': row.buyer_priced_qty if row else 0})
        day += timedelta(days=1)
    if granularity == 'week':
        groups = defaultdict(list)
        for row in days:
            groups[row['day'] - timedelta(days=row['day'].weekday())].append(row)
        weeks = []
        with localcontext() as context:
            context.prec = 40
            for rows in groups.values():
                known = [r['orders'] for r in rows if r['orders'] is not None]
                orders = sum(known) if known and (sum(known) > 0 or len(known) == len(rows)) else None
                week = {'day': rows[0]['day'], 'to': rows[-1]['day'], 'orders': orders}
                for field, coverage in (('spp', 'spp_priced_qty'),
                                        ('buyer_price_mean', 'buyer_priced_qty')):
                    priced = sum(r[coverage] for r in rows if r[field] is not None)
                    week[coverage] = priced
                    week[field] = (sum((r[field] * r[coverage] for r in rows
                                       if r[field] is not None), Decimal(0)) / priced
                                   if priced else None)
                weeks.append(week)
        days = weeks
    spp_values = [row['spp'] for row in days if row['spp'] is not None]
    buyer_values = [row['buyer_price_mean'] for row in days if row['buyer_price_mean'] is not None]
    reasons = []
    if not complete:
        reasons.append('История заказов неполная: показаны известные заказы, пропуски не равны нулю.')
    if any(row.quantity > min(row.spp_priced_qty, row.buyer_priced_qty) for row in observed.values()):
        reasons.append('Для части заказов нет корректной пары цен. Средние показаны по известным ценам; подсказка содержит покрытие. Обновите данные Ozon, затем пересчитайте план.')
    return {'period': period, 'granularity': granularity,
            'days': days, 'spp_min': min(spp_values) if spp_values else None,
            'spp_max': max(spp_values) if spp_values else None,
            'buyer_price_min': min(buyer_values) if buyer_values else None,
            'buyer_price_max': max(buyer_values) if buyer_values else None,
            'complete': complete, 'ordered_qty': sum(row.quantity for row in observed.values()),
            'reason': ' '.join(reasons)}
