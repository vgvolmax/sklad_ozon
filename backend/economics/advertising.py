"""Overall DRR: uploaded cost / all-order seller revenue over the same days.

All posting lifecycle states and FBO/FBS contribute to ordered revenue.
This is an orders metric, not a delivered/bought/payout ledger.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext

from backend.analytics._weeks import parse_source_date
from backend.domain.advertising import OrderRevenueDay, OrderRevenueEvidence


def build_order_revenue(orders, coverage, *, source_coverage=None, diagnostics=()):
    complete = (source_coverage is None or source_coverage.demand_complete)
    complete = complete and not any(d.severity == 'error' for d in diagnostics)
    incomplete = set(source_coverage.demand_incomplete_skus if source_coverage else ())
    totals = defaultdict(lambda: Decimal('0'))
    for order in orders:
        day = parse_source_date(order.accepted_at)
        if day is None:
            incomplete.add(order.sku); continue
        if not coverage.period_start <= day <= coverage.period_end: continue
        try: price = Decimal(str(order.seller_price))
        except Exception:
            incomplete.add(order.sku); continue
        if (not price.is_finite() or price <= 0 or type(order.quantity) is not int or order.quantity < 0):
            incomplete.add(order.sku); continue
        totals[order.sku, day] += price * order.quantity
    return OrderRevenueEvidence(coverage.period_start, coverage.period_end, complete,
        tuple(sorted(incomplete)), tuple(OrderRevenueDay(sku, day, total)
            for (sku, day), total in sorted(totals.items())))


def _periods(days):
    result = []
    for day in sorted(days):
        if result and result[-1]['to'] + timedelta(days=1) == day:
            result[-1]['to'] = day
        else: result.append({'from': day, 'to': day})
    return result


def real_drr_by_sku(data, evidence, skus, *, period_from=None, period_to=None):
    by_sku = defaultdict(list)
    for row in data.days:
        if (row.sku in skus and (period_from is None or row.day >= period_from)
                and (period_to is None or row.day <= period_to)):
            by_sku[row.sku].append(row)
    revenue = {(r.sku, r.day): r.revenue for r in evidence.days} if evidence else {}
    result = {}
    for sku in skus:
        rows = by_sku[sku]
        days = {r.day for r in rows}
        spend = sum((r.spend for r in rows), Decimal('0')) if rows else None
        reason = None
        order_revenue = None
        rate = None
        if not rows: reason = 'Нет рекламного отчёта для товара за выбранный период.'
        elif evidence is None: reason = 'Пересчитайте план, чтобы получить сумму всех заказов.'
        elif not evidence.complete or sku in evidence.incomplete_skus:
            reason = 'История или цены заказов неполные. Обновите данные и пересчитайте план.'
        elif min(days) < evidence.period_start or max(days) > evidence.period_end:
            reason = 'История заказов не покрывает период рекламы. Обновите данные и пересчитайте план.'
        else:
            order_revenue = sum((revenue.get((sku, day), Decimal('0')) for day in days), Decimal('0'))
            if order_revenue == 0:
                reason = 'За период рекламы нет заказов на положительную сумму.'
            else:
                with localcontext() as context:
                    context.prec = 40
                    rate = spend / order_revenue
        result[sku] = {'rate': rate, 'spend': spend, 'order_revenue': order_revenue,
                       'periods': _periods(days), 'day_count': len(days), 'reason': reason}
    return result
