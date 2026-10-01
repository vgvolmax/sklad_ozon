"""Article-level costs; manual values survive later economics imports."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from backend.ingestion.supplier_packaging import normalize_supplier_article
from backend.project import CostPriceRecord


def parse_cost(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Введите себестоимость числом от 0 до 1 000 000 000 000 ₽.')
    try:
        cost = Decimal(str(value).strip().replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Введите себестоимость числом.') from None
    if not cost.is_finite() or not 0 <= cost <= Decimal('1000000000000'):
        raise ValueError('Себестоимость должна быть конечным неотрицательным числом.')
    return cost


def set_cost(project, article, value, *, product_name=''):
    article = normalize_supplier_article(article)
    existing = project.cost_prices.get(article)
    cost = parse_cost(value)
    name = product_name or (existing.product_name if existing else '')
    if existing and existing.cost == cost and existing.source == 'manual' and existing.product_name == name:
        return project, article
    record = CostPriceRecord(cost, 'manual', datetime.now(timezone.utc).isoformat(), name)
    return replace(project, cost_prices={**project.cost_prices, article: record}), article


def import_costs(project, products, names=None):
    """Keep consistent imported article costs; never replace a manual cost."""
    names = names or {}
    grouped = {}
    for product in products:
        if not product.article or product.cost is None:
            continue
        article = normalize_supplier_article(product.article)
        grouped.setdefault(article, []).append(product)
    costs = dict(project.cost_prices)
    for article, rows in grouped.items():
        values = {row.cost for row in rows}
        if len(values) != 1:
            continue
        old = costs.get(article)
        name = next((names.get(row.sku, '') for row in rows if names.get(row.sku)), '')
        if old and old.source == 'manual':
            if name and not old.product_name:
                costs[article] = replace(old, product_name=name)
            continue
        cost = parse_cost(next(iter(values)))
        if old and old.cost == cost and (not name or name == old.product_name):
            continue
        costs[article] = CostPriceRecord(cost, 'import', datetime.now(timezone.utc).isoformat(),
                                         name or (old.product_name if old else ''))
    return replace(project, cost_prices=costs)


def apply_costs(products, project):
    rows = []
    for product in products:
        record = project.cost_prices.get(product.article)
        if record and (record.source == 'manual' or product.cost is None):
            product = replace(product, cost=record.cost)
        rows.append(product)
    return tuple(rows)


def cost_fingerprint(project):
    values = {article: (format(record.cost.normalize(), 'f'), record.source)
              for article, record in sorted(project.cost_prices.items())}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def cost_items(project):
    return [{'article': article, 'product_name': record.product_name, 'cost': record.cost,
             'source': record.source, 'updated_at': record.updated_at}
            for article, record in sorted(project.cost_prices.items())]
