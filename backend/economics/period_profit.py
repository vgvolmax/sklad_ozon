"""One unit-profit basis, two quantities, and one store expense ledger."""
from collections import defaultdict
from decimal import Decimal, localcontext

ZERO = Decimal('0')
MODELED = {'commission', 'logistics', 'acquiring', 'returns'}
ADDITIONAL = {'storage', 'crossdock', 'cross_dock', 'acceptance', 'penalty', 'services'}


def expense_role(category):
    if category == 'advertising':
        return 'advertising'
    if category in MODELED:
        return 'already_in_unit_model'
    if category in ADDITIONAL:
        return 'additional_period_expense'
    return 'unclassified'


def build_period_profit(basis, period, quantities, finance, mode, *,
                        selected_skus=None, history_complete=True):
    if mode not in {'orders', 'buyouts'}:
        raise ValueError('Выберите заказы или выкупы.')
    start, end = period['from'], period['to']
    finances_cover = (finance is not None and finance.period_start <= start and
                      finance.period_end >= end)
    quantity_complete = history_complete if mode == 'orders' else finances_cover
    counts = defaultdict(lambda: dict(qty=0, purchased=0, returned=0, known=True))
    if mode == 'orders':
        for row in quantities:
            if start <= row.day <= end:
                counts[row.sku]['qty'] += row.quantity
    elif finances_cover:
        for row in finance.products:
            if not start <= row.day <= end:
                continue
            c = counts[row.sku]
            if row.quantity is None:
                c['known'] = False
            else:
                c['qty'] += row.quantity
                c['purchased'] += max(0, row.quantity)
                c['returned'] += max(0, -row.quantity)
    inputs = {p['sku']: p for p in basis}
    rows = []
    expenses = []
    with localcontext() as context:
        context.prec = 40
        for sku in sorted(set(inputs) | set(counts)):
            p = inputs.get(sku, {})
            c = counts[sku]
            quantity_known = c['known'] and quantity_complete
            q = c['qty'] if quantity_known else None
            u = p.get('profit_per_unit_before_ads')
            price = p.get('price')
            ready = quantity_known and (q == 0 or u is not None and p.get('pricing_complete', True))
            profit = (ZERO if q == 0 else u * q) if ready else None
            revenue = (ZERO if q == 0 else price * q) if q is not None and (q == 0 or price is not None) else None
            rows.append(dict(sku=sku, article=p.get('article', ''), name=p.get('name', 'Товар без текущей юнитки'),
                qty=q, purchased_qty=c['purchased'], returned_qty=c['returned'],
                quantity_known=quantity_known, profit_per_unit_before_ads=u,
                price=price, revenue=revenue, profit=profit, partial=not ready))
        grouped = defaultdict(lambda: ZERO)
        if finances_cover:
            for row in finance.expenses:
                if start <= row.day <= end:
                    grouped[row.category, row.label, expense_role(row.category)] += row.amount
        for (category, label, role), amount in sorted(grouped.items()):
            expenses.append(dict(category=category, label=label, role=role, amount=amount))
        ads = sum((e['amount'] for e in expenses if e['role'] == 'advertising'), ZERO) if finances_cover else None
        other = sum((e['amount'] for e in expenses if e['role'] == 'additional_period_expense'), ZERO) if finances_cover else None
        known = [p for p in rows if p['profit'] is not None]
        active = [p for p in rows if p['qty'] != 0]
        active_known = [p for p in active if p['profit'] is not None]
        before = (sum((p['profit'] for p in active_known), ZERO) if active_known
                  else ZERO if quantity_complete and not active else None)
        after = before - ads - other if before is not None and finances_cover else None
        revenue = sum((p['revenue'] for p in known if p['revenue'] is not None), ZERO)
        partial = (not quantity_complete or not finances_cover or any(p['partial'] for p in rows) or
                   any(e['role'] == 'unclassified' for e in expenses))
        selected = rows if selected_skus is None else [p for p in rows if p['sku'] in selected_skus]
        selected_known = [p for p in selected if p['profit'] is not None]
        return dict(mode=mode, period=period, products=selected,
            finance_snapshot_id=finance.snapshot_id if finances_cover else None,
            loaded_at=finance.loaded_at if finances_cover else None,
            expense_source='finance', quantity_complete=quantity_complete, expenses_complete=finances_cover,
            expenses=expenses, catalog_product_count=len(rows),
            selected_profit_before_common=sum((p['profit'] for p in selected_known), ZERO) if selected_known else None,
            totals=dict(qty=sum(p['qty'] or 0 for p in rows) if quantity_complete and all(p['quantity_known'] for p in rows) else None,
                covered_qty=sum(p['qty'] for p in known),
                uncovered_known_qty=sum(p['qty'] for p in rows if p['partial'] and p['qty'] is not None),
                purchased_qty=sum(p['purchased_qty'] for p in rows), returned_qty=sum(p['returned_qty'] for p in rows),
                sku_count=len(rows), covered_sku_count=len(known), uncovered_skus=[p['sku'] for p in rows if p['partial']],
                revenue_model=revenue if known else None, profit_before_common=before,
                advertising_total=ads, other_common_total=other, profit_after_common=after,
                margin=after / revenue if not partial and after is not None and revenue > 0 else None,
                partial=partial))
