"""Decorate the read-only SKU workspace with independent pricing evidence."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from dataclasses import replace
from hashlib import sha256
import json

from .pricing import PricingCalculator
from .workspace import _aggregate

ZERO = Decimal('0')


def enrich_pricing(snapshot, report, scenario_routes, *, current_costs=None):
    if not isinstance(scenario_routes, dict) or len(scenario_routes) > 1000:
        raise ValueError('Неверный список расчётных маршрутов.')
    for sku, pairs in scenario_routes.items():
        if (not isinstance(sku, str) or not isinstance(pairs, list) or len(pairs) > 100 or
                any(not isinstance(pair, list) or len(pair) != 2 or
                    any(not isinstance(v, str) or not v.strip() for v in pair) for pair in pairs)):
            raise ValueError('Выберите существующие маршруты SKU.')
    tariffs = getattr(snapshot, 'economics_tariffs', None)
    products = {p.sku: p for p in getattr(snapshot, 'economics_pricing_inputs', ())}
    if tariffs is None:
        for p in report['products']:
            covered = p.get('before_ads_covered_qty', p['covered_qty'])
            p['profit_per_unit_before_ads'] = (p['profit_before_ads_total'] / covered
                if covered and p['profit_before_ads_total'] is not None else None)
            p['pricing_complete'] = covered == p['qty'] and not p['no_observations']
        return
    historical = getattr(snapshot, 'economics_period_evidence', None)
    history = historical.route_economics if historical is not None else snapshot.route_economics
    calculator = PricingCalculator(tariffs, snapshot.economics_settings)
    options = {}
    for row in tariffs.records:
        options.setdefault(row.origin_cluster_id, set()).add(row.destination_cluster_id)
    for p in report['products']:
        product = products.get(p['sku'])
        if product is None:
            p.update(profit_per_unit_before_ads=None, pricing_complete=False)
            continue
        if p['sku'] in (current_costs or {}):
            product = replace(product, cost=current_costs[p['sku']])
        p['route_options'] = {o: sorted(ds) for o, ds in sorted(options.items())}
        observed = [r for r in history if r.sku == p['sku'] and r.observed_qty > 0]
        p['calculation_kind'] = 'history' if observed else 'no_sales'
        selected_rows = [r for g in p['groups']['destination'] for r in g['routes']]
        rows = selected_rows
        if not rows and observed:
            rows = [dict(origin=r.origin_cluster_id, destination=r.destination_cluster_id,
                         qty=r.observed_qty) for r in observed]
            p['basis_source'] = 'loaded_history'
        else:
            p['basis_source'] = 'selected_period' if observed else 'scenario_worst_route'
        pairs = [(r['origin'], r['destination']) for r in rows]
        if not observed:
            pairs = list(dict.fromkeys(tuple(r) for r in scenario_routes.get(p['sku'], [])))
            for origin, destination in pairs:
                if destination not in p['route_options'].get(origin, []):
                    raise ValueError('Расчётный маршрут отсутствует в тарифах.')
            rows = [dict(origin=o, destination=d, qty=1) for o, d in pairs]
        p['calculation_routes'] = pairs
        p['basis_period'] = (report['period'] if p['basis_source'] == 'selected_period' else
                             report['observation_period'] if observed else None)
        with localcontext() as context:
            context.prec = 40
            applied = p['applied_drr_rate']
            current = [calculator.calculate(product,
                [(r['origin'], r['destination'])], drr=applied if applied is not None else ZERO,
                margin=report['target_margin'], roi=report['target_roi'], goal=report['goal'], solve_target=False) for r in rows]
            target = calculator.calculate(product, pairs,
                drr=p['planned_drr_rate'], margin=report['target_margin'], roi=report['target_roi'], goal=report['goal'])
            valid = [(r, c) for r, c in zip(rows, current) if c['profit_per_unit_before_ads'] is not None]
            covered = sum(r['qty'] for r, _ in valid)
            total = sum(r['qty'] for r in rows)
            complete = bool(rows) and covered == total
            def mean(field):
                values = [(r['qty'], c[field]) for r, c in valid if c[field] is not None]
                if not values:
                    return None
                if not observed:
                    return min(v for _, v in values) if complete else None
                return sum((q*v for q, v in values), ZERO) / sum(q for q, _ in values)
            before = mean('profit_per_unit_before_ads')
            profit = mean('profit_per_unit') if applied is not None else None
            if observed and valid:
                codes = set.intersection(*(set(c['line_items']) for _, c in valid))
                line_items = {code: sum((r['qty']*c['line_items'][code] for r, c in valid), ZERO) / covered
                              for code in codes}
            elif valid and complete:
                line_items = min((c for _, c in valid), key=lambda c: c['profit_per_unit'])['line_items']
            else:
                line_items = {}
            if applied is None:
                line_items = {k:v for k,v in line_items.items() if k not in {
                    'ADVERTISING_AND_SERVICES', 'OZON_WITHHOLDINGS', 'PAYOUT', 'INCOME_TAX', 'TOTAL_TAX', 'PROFIT_PER_UNIT'}}
            # Cluster values use exactly the same calculator and upload cost as
            # their parent card. History weights are never fabricated for new SKUs.
            refreshed = []
            for r, c in zip(rows, current):
                route_profit = c['profit_per_unit'] if applied is not None else None
                required = (report['target_margin'] * product.price if report['goal'] == 'margin' and product.price is not None
                            else report['target_roi'] * product.cost if product.cost is not None else None)
                route = c['routes'][0] if c['routes'] else {}
                refreshed.append(dict(origin=r['origin'], destination=r['destination'], qty=r['qty'],
                    price=product.price, cost=product.cost, profit=route_profit,
                    profit_before_ads=c['profit_per_unit_before_ads'],
                    margin=route_profit/product.price if route_profit is not None and product.price else None,
                    roi=route_profit/product.cost if route_profit is not None and product.cost else None,
                    logistics=route.get('logistics'),
                    gap=max(ZERO, required-route_profit)*r['qty'] if required is not None and route_profit is not None else None,
                    target_price=calculator.calculate(product,
                        [(r['origin'],r['destination'])], drr=p['planned_drr_rate'],
                        margin=report['target_margin'], roi=report['target_roi'], goal=report['goal'])['target_price'],
                    reason_codes=c['reason_codes']))
            if selected_rows:
                p.update(_aggregate(refreshed, report['target_margin'], report['target_roi'], report['goal']))
                p['groups'] = {role:[dict(key=key, **_aggregate([r for r in refreshed if r[field] == key],
                    report['target_margin'],report['target_roi'],report['goal']),
                    routes=[r for r in refreshed if r[field] == key])
                    for key in sorted({r[field] for r in refreshed})]
                    for role,field in (('destination','destination'),('origin','origin'))}
            p.update(cost=product.cost, cost_source='manual_current' if p['sku'] in (current_costs or {}) else 'import' if product.cost is not None else 'missing',
                price=product.price, commission_rate=product.commission_rate,
                commission_per_unit=product.price * product.commission_rate if product.price is not None and product.commission_rate is not None else None,
                volume_liters=product.volume_liters, profit_per_unit_before_ads=before,
                pricing_complete=complete, profit_per_unit=profit,
                margin=profit / product.price if profit is not None and product.price else None,
                roi=profit / product.cost if profit is not None and product.cost else None,
                target_price_all_routes=target['target_price'], limiting_route=target['limiting_route'],
                pricing_reason_codes=target['reason_codes'], line_items=line_items)
            p['pricing_issues'] = [dict(origin=r['origin'], destination=r['destination'],
                reason_codes=r['reason_codes']) for r in refreshed if r['target_price'] is None]
            p['partial'] = not complete or applied is None
            p['below_margin'] = p['margin'] is not None and p['margin'] < report['target_margin']
            p['below_roi'] = p['roi'] is not None and p['roi'] < report['target_roi']
            p['below_goal'] = p['below_margin'] if report['goal'] == 'margin' else p['below_roi']
            delta = target['target_price'] - product.price if target['target_price'] is not None and product.price else None
            p.update(price_delta=delta, price_delta_rate=delta/product.price if delta is not None else None,
                price_action=('lower' if delta < 0 else 'raise' if delta > 0 else 'keep') if delta is not None else None)
            if p.get('buyer_prices') is not None:
                spp = p['buyer_prices']['spp_mean']
                p['buyer_prices']['target_buyer_price'] = ((target['target_price'] * (1-spp)).quantize(
                    Decimal('.01'), rounding=ROUND_HALF_UP) if target['target_price'] is not None and spp is not None else None)
    # Deliberately exclude goals and DRR: they cannot alter the before-ad basis.
    facts = [(p['sku'], str(p.get('price')), str(p.get('profit_per_unit_before_ads')),
              p.get('pricing_complete'), p.get('calculation_routes')) for p in report['products']]
    report['pricing_basis_id'] = sha256(json.dumps([snapshot.snapshot_id, facts], sort_keys=True).encode()).hexdigest()
