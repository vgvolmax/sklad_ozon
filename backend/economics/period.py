"""Inclusive Economics calendar selection, independent of planning windows."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from backend.domain.economics_daily import EconomicsPeriodEvidence


def resolve_period(evidence, period_from=None, period_to=None):
    if period_from is None and period_to is None:
        return ({'from': evidence.period_start, 'to': evidence.period_end}
                if evidence is not None else None)
    if evidence is None:
        raise ValueError('Пересчитайте план, чтобы выбрать период экономики.')
    dates = []
    for raw in (period_from, period_to):
        try:
            if not isinstance(raw, str) or len(raw) != 10:
                raise ValueError
            parsed = date.fromisoformat(raw)
            if parsed.isoformat() != raw:
                raise ValueError
            dates.append(parsed)
        except ValueError as exc:
            raise ValueError('Укажите обе даты периода в формате ГГГГ-ММ-ДД.') from exc
    start, end = dates
    if start > end:
        raise ValueError('Начало периода должно быть не позже конца.')
    if start < evidence.period_start or end > evidence.period_end:
        raise ValueError('Период расчёта должен находиться внутри истории заказов.')
    return {'from': start, 'to': end}


def route_quantities(cells, start, end):
    totals = defaultdict(lambda: [0, 0])
    for cell in cells:
        if start <= cell.day <= end:
            total = totals[cell.sku, cell.origin_cluster_id, cell.destination_cluster_id]
            total[0] += cell.quantity
            total[1] += cell.observation_count
    return totals


def build_period_evidence(orders, coverage, products, tariffs, settings, *, complete=True):
    # Reuse canonical fulfillment eligibility and finance formulas. Only the
    # calendar window is different from completed-week Plan/Flow observations.
    from backend.analytics.daily import build_daily_order_facts
    from backend.analytics.flows import FulfillmentFlowCell
    from backend.economics.route_opportunity import calculate_route_opportunity

    cells = tuple(c for c in build_daily_order_facts(orders, coverage.period_end).fulfillment.cells
                  if coverage.period_start <= c.day <= coverage.period_end)
    totals = route_quantities(cells, coverage.period_start, coverage.period_end)
    destinations = defaultdict(int)
    for (sku, _, destination), (quantity, _) in totals.items():
        destinations[sku, destination] += quantity
    products_by_sku = {p.sku: p for p in products}
    routes = []
    for (sku, origin, destination), (quantity, count) in sorted(totals.items()):
        if quantity <= 0:
            continue
        flow = FulfillmentFlowCell(sku, origin, destination, quantity,
            Decimal(quantity) / destinations[sku, destination], count)
        routes.append(calculate_route_opportunity(flow, products_by_sku.get(sku),
                                                  tariffs, settings, None))
    return EconomicsPeriodEvidence(coverage.period_start, coverage.period_end,
                                    cells, tuple(routes), complete)
