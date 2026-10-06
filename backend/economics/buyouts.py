"""Management profit over realized units and known signed finance accruals."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

ZERO = Decimal('0')


@dataclass(frozen=True, slots=True)
class FinanceProductLine:
    day: date
    sku: str
    quantity: int | None
    revenue: Decimal | None
    net_amount: Decimal


@dataclass(frozen=True, slots=True)
class FinanceExpense:
    day: date
    category: str
    label: str
    amount: Decimal  # Positive expense; negative credit. SKU means already in product net.
    sku: str | None = None


@dataclass(frozen=True, slots=True)
class FinanceSnapshot:
    snapshot_id: str
    credential_context_id: str
    period_start: date
    period_end: date
    products: tuple[FinanceProductLine, ...]
    expenses: tuple[FinanceExpense, ...]
    loaded_at: str


def _sum(values):
    return sum(values, ZERO)


def _totals(products):
    complete = [p for p in products if p['profit'] is not None]
    return {'sku_count': len(products), 'covered_sku_count': len(complete),
        'purchased_qty': sum(p['purchased_qty'] for p in products),
        'returned_qty': sum(p['returned_qty'] for p in products),
        'qty': sum(p['qty'] for p in products),
        'revenue': _sum(p['revenue'] for p in products if p['revenue'] is not None),
        'cost_total': _sum(p['cost_total'] for p in complete),
        'profit': _sum(p['profit'] for p in complete) if complete or not products else None,
        'partial': len(complete) != len(products)}


def build_buyout_report(snapshot, products, names, *, search='', filter='all'):
    if not isinstance(search, str) or len(search) > 200:
        raise ValueError('Поиск должен быть строкой длиной до 200 символов.')
    if filter not in ('all', 'loss', 'incomplete'):
        raise ValueError('Выберите существующий фильтр выкупов.')
    costs = {}
    for p in products:
        if p.sku in costs and costs[p.sku] != p.cost:
            raise ValueError('Несколько себестоимостей одного SKU в загруженных данных.')
        costs[p.sku] = p.cost
    grouped = defaultdict(list)
    for line in snapshot.products:
        grouped[line.sku].append(line)
    rows = []
    with localcontext() as context:
        context.prec = 40
        for sku, lines in sorted(grouped.items()):
            known_qty = all(line.quantity is not None for line in lines)
            quantity = sum(line.quantity or 0 for line in lines)
            purchased = sum(max(0, line.quantity or 0) for line in lines)
            returned = sum(max(0, -(line.quantity or 0)) for line in lines)
            revenue = _sum(line.revenue for line in lines if line.revenue is not None)
            revenue_known = all(line.revenue is not None for line in lines)
            cost = costs.get(sku)
            if cost is not None and (not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0):
                raise ValueError('Некорректная загруженная себестоимость.')
            # Fee-only products do not require a cost; unknown realized quantity does.
            cost_total = (cost * quantity if cost is not None else ZERO if quantity == 0 else None) if known_qty else None
            net = _sum(line.net_amount for line in lines)
            profit = net - cost_total if cost_total is not None else None
            article, name = names.get(sku, ('', 'Товар без текущего наименования'))
            rows.append({'sku': sku, 'article': article, 'name': name,
                'purchased_qty': purchased, 'returned_qty': returned, 'qty': quantity,
                'quantity_known': known_qty, 'revenue': revenue if revenue_known else None,
                'net_proceeds': net, 'cost': cost, 'cost_total': cost_total,
                'known_expenses': revenue - net if revenue_known else None,
                'profit': profit, 'partial': profit is None,
                'profit_per_unit': profit / quantity if profit is not None and quantity > 0 else None})
        needle = search.strip().casefold()
        selected = [p for p in rows if (not needle or needle in ' '.join(
            str(p[k]) for k in ('sku', 'article', 'name')).casefold()) and
            (filter == 'all' or filter == 'loss' and p['profit'] is not None and p['profit'] < 0
             or filter == 'incomplete' and p['partial'])]
        totals = _totals(rows)
        common = _sum(e.amount for e in snapshot.expenses if e.sku is None)
        totals.update({'profit_before_common': totals.pop('profit'),
            'common_expenses': common,
            'advertising_spend': _sum(e.amount for e in snapshot.expenses if e.category == 'advertising'),
            'selected_sku_count': len(selected)})
        totals['profit_after_known_expenses'] = (totals['profit_before_common'] - common
            if totals['profit_before_common'] is not None else None)
        breakdown = defaultdict(lambda: {'amount': ZERO, 'product_amount': ZERO, 'common_amount': ZERO})
        for e in snapshot.expenses:
            b = breakdown[e.category, e.label]
            b['amount'] += e.amount
            b['product_amount' if e.sku is not None else 'common_amount'] += e.amount
        expenses = [{'category': category, 'label': label, **value}
                    for (category, label), value in sorted(breakdown.items())]
    return {'finance_snapshot_id': snapshot.snapshot_id,
        'period': {'from': snapshot.period_start, 'to': snapshot.period_end},
        'loaded_at': snapshot.loaded_at, 'evidence': 'realized_finance_period',
        'products': selected, 'catalog_product_count': len(rows),
        'totals': totals, 'selected_totals': _totals(selected), 'expenses': expenses,
        'cost_basis': 'current_uploaded', 'advertising_source': 'finance'}
