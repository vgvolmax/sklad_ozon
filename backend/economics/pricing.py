"""Quantity-independent pricing over explicit routes and current tariff tiers."""
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, localcontext

from backend.analytics.clean_routes import RouteDistributionCell
from backend.domain.contracts import ImportResult
from .tariffs import LogisticsContext, RouteProfileSource, expected_logistics
from .unit import calculate_unit_economics

ZERO = Decimal('0')
ONE = Decimal('1')
KOPEK = Decimal('.01')


class PricingTariffIndex:
    """Request-local route/volume index, preserving canonical tariff lookup."""
    def __init__(self, tariffs):
        if tariffs.record_sources and len(tariffs.record_sources) != len(tariffs.records):
            raise ValueError('tariff record_sources must align with records')
        self.tariffs = tariffs
        self.by_route = {}
        self.by_volume = {}
        for index, row in enumerate(tariffs.records):
            self.by_route.setdefault((row.origin_cluster_id, row.destination_cluster_id), []).append((index, row))

    def for_route(self, route, volume):
        key = route, volume
        if key not in self.by_volume:
            rows = [(i,r) for i,r in self.by_route.get(route, ())
                if r.min_volume_liters <= volume and (r.max_volume_liters is None or volume < r.max_volume_liters)]
            self.by_volume[key] = ImportResult(tuple(r for _,r in rows), (), self.tariffs.meta,
                tuple(self.tariffs.record_sources[i] for i,_ in rows) if self.tariffs.record_sources else ())
        return self.by_volume[key]


class PricingCalculator:
    """Reuse equivalent numeric calculations within one immutable read."""
    def __init__(self, tariffs, settings):
        self.tariffs = PricingTariffIndex(tariffs)
        self.settings = settings
        self.results = {}

    def calculate(self, product, routes, *, drr, margin, roi, goal, solve_target=True):
        routes = tuple(dict.fromkeys(tuple(r) for r in routes))
        # SKU/article/stock do not affect money and are not in the result.
        key = (product.price, product.cost, product.commission_rate, product.volume_liters,
               routes, drr, margin, roi, goal, solve_target)
        if key not in self.results:
            self.results[key] = calculate_pricing(product, self.tariffs, self.settings, routes,
                drr=drr, margin=margin, roi=roi, goal=goal, solve_target=solve_target)
        return self.results[key]


def resolve_drr(real, planned, fallback, *, report_present=False):
    if real is not None:
        return real, 'real'
    if report_present:
        return None, 'incomplete_report'
    return (planned, 'plan') if fallback else (ZERO, 'zero_assumption')


def _unit(product, tariffs, settings, route, price, drr):
    origin, destination = route
    # These are calculation weights, never observed/order quantities.
    profile = (RouteDistributionCell(product.sku, origin, destination, 1, 0, ONE),)
    logistics = expected_logistics(profile, tariffs.for_route(route, product.volume_liters), LogisticsContext(
        product.sku, origin, product.volume_liters, price, RouteProfileSource.GLOBAL))
    return calculate_unit_economics(replace(product, price=price), origin,
        logistics, replace(settings, advertising_rate=drr))


def _cents(value):
    return int((value / KOPEK).to_integral_value(rounding=ROUND_CEILING))


def _target(product, tariffs, settings, routes, drr, margin, roi, goal):
    if goal == 'roi' and (product.cost is None or product.cost <= ZERO):
        return None
    boundaries = {1}
    for route in routes:
        for row in tariffs.for_route(route, product.volume_liters).records:
            for bound in (row.min_price, row.max_price):
                if bound is not None:
                    boundaries.add(max(1, _cents(bound)))
    starts = sorted(boundaries)

    def meets(cents):
        price = cents * KOPEK
        for route in routes:
            unit = _unit(product, tariffs, settings, route, price, drr)
            if unit.profit_per_unit is None:
                return None
            required = margin * price if goal == 'margin' else roi * product.cost
            if unit.profit_per_unit < required:
                return False
        return True

    for index, lower in enumerate(starts):
        status = meets(lower)
        if status is None:
            continue
        if status:
            return lower * KOPEK
        upper = starts[index + 1] - 1 if index + 1 < len(starts) else None
        if upper is None:
            upper = max(lower + 1, _cents(max(product.price or ZERO, product.cost or ZERO, ONE)))
            for _ in range(40):
                if meets(upper):
                    break
                upper *= 2
            else:
                continue
        if upper < lower or not meets(upper):
            continue
        # Within one tariff interval the goal has no tariff jumps. Tax clipping
        # is handled by the canonical unit calculator for every currency point.
        while lower < upper:
            mid = (lower + upper) // 2
            if meets(mid):
                upper = mid
            else:
                lower = mid + 1
        return upper * KOPEK
    return None


def calculate_pricing(product, tariffs, settings, routes, *, drr, margin, roi, goal, solve_target=True):
    routes = tuple(dict.fromkeys(tuple(r) for r in routes))
    result = dict(profit_per_unit=None, profit_per_unit_before_ads=None,
        margin=None, roi=None, target_price=None, target_logistics=None,
        limiting_route=None, line_items={}, reason_codes=(), routes=[])
    if product.volume_liters is None or product.volume_liters <= ZERO:
        result['reason_codes'] = ('MISSING_PRODUCT_VOLUME',)
        return result
    if not routes:
        result['reason_codes'] = ('NO_CALCULATION_ROUTES',)
        return result
    if not isinstance(tariffs, PricingTariffIndex):
        tariffs = PricingTariffIndex(tariffs)
    with localcontext() as context:
        context.prec = 40
        if product.price is not None:
            units = [_unit(product, tariffs, settings, r, product.price, drr) for r in routes]
            before = [_unit(product, tariffs, settings, r, product.price, ZERO) for r in routes]
            result['reason_codes'] = tuple(sorted({c for u in units for c in u.blockers}))
            result['routes'] = [dict(origin=r[0], destination=r[1],
                profit=u.profit_per_unit, profit_before_ads=b.profit_per_unit,
                logistics=u.expected_logistics, margin=u.margin_rate, roi=u.roi, reason_codes=u.blockers)
                for r, u, b in zip(routes, units, before)]
            if all(u.profit_per_unit is not None for u in units):
                worst = min(units, key=lambda u: u.profit_per_unit)
                result.update(profit_per_unit=worst.profit_per_unit, margin=worst.margin_rate,
                    roi=worst.roi, line_items={item.code: item.amount for item in worst.line_items})
            if all(u.profit_per_unit is not None for u in before):
                result['profit_per_unit_before_ads'] = min(u.profit_per_unit for u in before)
        if solve_target and product.cost is not None and product.commission_rate is not None:
            target = _target(product, tariffs, settings, routes, drr, margin, roi, goal)
            result['target_price'] = target
            if target is not None:
                units = [_unit(product, tariffs, settings, r, target, drr) for r in routes]
                index = min(range(len(units)), key=lambda i: units[i].profit_per_unit -
                    (margin * target if goal == 'margin' else roi * product.cost))
                result.update(limiting_route=routes[index], target_logistics=units[index].expected_logistics)
        return result
