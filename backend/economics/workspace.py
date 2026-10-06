"""Read-only target scenarios over selected-period route economics evidence.

The historical quantity is delivered route evidence, not paid/bought units.
The shortfall is a modeled comparison at current input rates, not an actual loss.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from backend.project import EconomicsSettings
from .period import resolve_period, route_quantities
from .daily_series import period_price_means
from .pricing import resolve_drr

ZERO = Decimal("0")
ONE = Decimal("1")


def _decimal(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError(f"{field} must be a decimal number")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not result.is_finite() or not ZERO <= result <= maximum:
        raise ValueError(f"{field} is outside the allowed range")
    return result


def validate_targets(margin, roi, goal, planned_drr):
    """Return fractions; reject all invalid finance inputs before calculating."""
    if goal not in {"margin", "roi"}:
        raise ValueError("goal must be margin or roi")
    return (_decimal(margin, "margin", Decimal("0.95")),
            _decimal(roi, "roi", Decimal("10")), goal,
            _decimal(planned_drr, "planned_drr", Decimal("0.90")))


def _profit_at_price(price, cost, logistics, commission_rate, settings, drr):
    realization = price * (ONE - settings.co_invest_rate)
    vat = realization * settings.vat_rate / (ONE + settings.vat_rate)
    payout = price * (ONE - commission_rate - settings.acquiring_rate - drr) - logistics
    tax_base = (realization - vat if settings.tax_system == "usn_income"
                else payout - cost - vat)
    income_tax = max(ZERO, tax_base * settings.income_tax_rate)
    return payout - vat - income_tax - cost


def _target_price(current_price, cost, logistics, commission_rate, settings, drr,
                  target_margin, target_roi, goal):
    """Find the minimum positive price at unchanged rates and route logistics."""
    if current_price is None or cost is None or logistics is None or cost <= 0:
        return None
    if settings.tax_system not in {"usn_income", "usn_income_minus_expenses"}:
        return None
    target = target_margin if goal == "margin" else target_roi

    def deficit(price):
        profit = _profit_at_price(price, cost, logistics, commission_rate, settings, drr)
        return profit - (target * (price if goal == "margin" else cost))

    with localcontext() as context:
        context.prec = 40
        kopek = Decimal("0.01")
        lower = 1
        if deficit(kopek) >= 0:
            return kopek
        upper = max(1, int((current_price / kopek).to_integral_value(
            rounding="ROUND_CEILING")))
        if deficit(upper * kopek) < 0:
            for _ in range(40):
                upper *= 2
                if deficit(upper * kopek) >= 0:
                    break
            else:
                return None
        # Search prices on the actual currency grid. Decimal bisection followed
        # by ceiling can add a kopek when the exact minimum already meets the goal.
        while lower < upper:
            mid = (lower + upper) // 2
            if deficit(mid * kopek) >= 0:
                upper = mid
            else:
                lower = mid + 1
        return upper * kopek


def _aggregate(rows, margin_target, roi_target, goal):
    qty = sum(row["qty"] for row in rows)
    known = [row for row in rows if row["profit"] is not None]
    covered = sum(row["qty"] for row in known)
    if covered:
        with localcontext() as context:
            context.prec = 40
            profit_sum = sum((row["profit"] * row["qty"] for row in known), ZERO)
            price_sum = sum((row["price"] * row["qty"] for row in known), ZERO)
            cost_sum = sum((row["cost"] * row["qty"] for row in known), ZERO)
            profit = profit_sum / covered
            margin = profit_sum / price_sum if price_sum else None
            roi = profit_sum / cost_sum if cost_sum else None
    else:
        profit = margin = roi = None
    before_known = [row for row in rows if row['profit_before_ads'] is not None]
    before_qty = sum(row['qty'] for row in before_known)
    before_ads = sum((row['profit_before_ads'] * row['qty'] for row in before_known), ZERO) if before_qty else None
    gap = sum((row["gap"] for row in known), ZERO) if covered else None
    proposed = [row["target_price"] for row in rows]
    target_price = (max(proposed) if proposed and all(x is not None for x in proposed)
                    else None)
    return {"qty": qty, "covered_qty": covered, "profit_per_unit": profit,
            "profit_before_ads_total": before_ads, "before_ads_covered_qty": before_qty,
            "margin": margin, "roi": roi, "modeled_shortfall": gap,
            "target_price_all_routes": target_price,
            "partial": covered != qty, "no_observations": qty == 0,
            "below_margin": margin is not None and margin < margin_target,
            "below_roi": roi is not None and roi < roi_target,
            "below_goal": (margin if goal == "margin" else roi) is not None
                and (margin if goal == "margin" else roi) <
                (margin_target if goal == "margin" else roi_target)}


def build_economics_workspace(snapshot, *, margin, roi, goal, planned_drr,
                              per_sku_drr=None, real_drr=None, per_sku_cost=None,
                              period_from=None, period_to=None, daily_evidence=None,
                              use_planned_drr=False, reported_skus=(), extra_identities=()):
    margin, roi, goal, planned_drr = validate_targets(margin, roi, goal, planned_drr)
    if not isinstance(use_planned_drr, bool):
        raise ValueError('use_planned_drr must be boolean')
    settings: EconomicsSettings | None = snapshot.economics_settings
    if settings is None:
        raise ValueError("analysis has no economics settings")
    rates = {sku: (None if value is None else _decimal(value, 'real_drr', Decimal('1e24')))
             for sku, value in (real_drr or {}).items()}
    costs = per_sku_cost or {}
    overrides = {}
    for sku, value in (per_sku_drr or {}).items():
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("per_sku_drr has an invalid SKU")
        overrides[sku] = _decimal(value, "planned_drr", Decimal("0.90"))
    unit_by_sku = {}
    for unit in snapshot.unit_economics:
        unit_by_sku.setdefault(unit.sku, unit)
    identity = {row.sku: (row.article, row.product_name) for row in snapshot.decision_rows}
    for sku, article, name in getattr(snapshot, 'economics_catalog_identities', ()):
        old = identity.get(sku, ('', ''))
        identity[sku] = (article or old[0], name or old[1])
    for sku, article, name in extra_identities:
        identity.setdefault(sku, (article, name))
    evidence = getattr(snapshot, 'economics_period_evidence', None)
    period = resolve_period(evidence, period_from, period_to)
    selected = (route_quantities(evidence.daily_routes, period['from'], period['to'])
                if evidence is not None else None)
    valuations = evidence.route_economics if evidence is not None else snapshot.route_economics
    by_sku = defaultdict(list)
    covered_route_keys = set()
    for route in valuations:
        key = route.sku, route.origin_cluster_id, route.destination_cluster_id
        quantity = selected.get(key, [0])[0] if selected is not None else route.observed_qty
        if quantity <= 0:
            continue
        covered_route_keys.add((route.sku, route.origin_cluster_id,
                                route.destination_cluster_id))
        unit = unit_by_sku.get(route.sku)
        price = route.price_per_unit
        cost = costs.get(route.sku, unit.cost if unit else None)
        logistics = route.route_cost_rub
        model_rate, _ = resolve_drr(rates.get(route.sku), overrides.get(route.sku, planned_drr),
            use_planned_drr, report_present=route.sku in reported_skus)
        profit = before_ads = None
        inputs_ready = (unit is not None and unit.price is not None and unit.price > 0
                        and unit.commission is not None and price is not None and price > 0
                        and cost is not None and logistics is not None
                        and settings.tax_system in {'usn_income', 'usn_income_minus_expenses'})
        # A saved cost can repair MISSING_COST, but cannot certify unknown
        # route coverage. Local-alternative blockers do not affect this route.
        if route.current_profit_per_unit is None:
            cost_repaired = (route.sku in costs and unit is not None and unit.cost is None and
                'CURRENT_ECONOMICS_INCOMPLETE' in route.reason_codes and
                not {'CURRENT_ROUTE_INCOMPLETE', 'MISSING_OR_ZERO_REALIZATION'} &
                    set(route.reason_codes))
            inputs_ready = inputs_ready and cost_repaired
        if inputs_ready:
            with localcontext() as context:
                context.prec = 40
                profit = (_profit_at_price(price, cost, logistics,
                    unit.commission / unit.price, settings, model_rate) if model_rate is not None else None)
                before_ads = _profit_at_price(price, cost, logistics,
                    unit.commission / unit.price, settings, ZERO)
        complete = inputs_ready and profit is not None
        drr = overrides.get(route.sku, planned_drr)
        if inputs_ready:
            commission_rate = unit.commission / unit.price
            target_price = _target_price(price, cost, logistics, commission_rate,
                                         settings, drr, margin, roi, goal)
        else:
            target_price = None
        if complete:
            required_profit = (margin * price if goal == "margin" else roi * cost)
            gap = max(ZERO, required_profit - profit) * quantity
        else:
            gap = None
        by_sku[route.sku].append({
            "origin": route.origin_cluster_id, "destination": route.destination_cluster_id,
            "qty": quantity, "price": price, "cost": cost,
            "profit": profit if complete else None,
            "profit_before_ads": before_ads,
            "margin": profit / price if complete else None,
            "roi": profit / cost if complete and cost else None,
            "logistics": logistics, "gap": gap, "target_price": target_price,
            "reason_codes": route.reason_codes if not complete else (),
        })
    missing_routes = defaultdict(int)
    if selected is not None:
        for key, (quantity, _) in selected.items():
            if key not in covered_route_keys and quantity > 0:
                missing_routes[key] += quantity
    else:
        for observed in snapshot.observed_routes.routes:
            key = (observed.sku, observed.origin_cluster_id, observed.destination_cluster_id)
            if key not in covered_route_keys:
                missing_routes[key] += observed.quantity
    for (sku, origin, destination), quantity in sorted(missing_routes.items()):
        by_sku[sku].append({
            "origin": origin, "destination": destination, "qty": quantity,
            "price": None, "cost": None, "profit": None, "profit_before_ads": None, "margin": None,
            "roi": None, "logistics": None, "gap": None,
            "target_price": None, "reason_codes": ("NO_ROUTE_ECONOMICS",),
        })
    for sku in identity:
        by_sku.setdefault(sku, [])
    if evidence is None:
        weeks = snapshot.observed_routes.window.included_weeks
        period = ({'from': date.fromisocalendar(*min(weeks), 1),
                   'to': date.fromisocalendar(*max(weeks), 7)} if weeks else None)
    price_summaries = period_price_means(
        daily_evidence if daily_evidence is not None else getattr(snapshot, 'daily_order_evidence', None),
        period, by_sku)
    products = []
    for sku in sorted(by_sku):
        routes = by_sku[sku]
        article, name = identity.get(sku, ("", ""))
        unit = unit_by_sku.get(sku)
        summary = _aggregate(routes, margin, roi, goal)
        applied, source = resolve_drr(rates.get(sku), overrides.get(sku, planned_drr),
            use_planned_drr, report_present=sku in reported_skus)
        target_price = summary['target_price_all_routes']
        buyer_prices = price_summaries[sku]
        with localcontext() as context:
            context.prec = 40
            buyer_prices['target_buyer_price'] = (
                (target_price * (ONE - buyer_prices['spp_mean'])).quantize(
                    Decimal('.01'), rounding=ROUND_HALF_UP)
                if target_price is not None and buyer_prices['spp_mean'] is not None else None)
        current_price = unit.price if unit else None
        delta = target_price - current_price if target_price is not None and current_price else None
        action = ('lower' if delta < 0 else 'raise' if delta > 0 else 'keep') if delta is not None else None
        groups = {}
        for role, field in (("destination", "destination"), ("origin", "origin")):
            keys = sorted({row[field] for row in routes})
            groups[role] = [{"key": key, **_aggregate(
                [row for row in routes if row[field] == key], margin, roi, goal),
                "routes": [row for row in routes if row[field] == key]}
                for key in keys]
        products.append({"sku": sku, "article": article, "name": name,
                         "price": unit.price if unit else None,
                         "cost": costs.get(sku, unit.cost if unit else None),
                         "commission_rate": (unit.commission / unit.price if unit and
                                              unit.commission is not None and unit.price else None),
                         "commission_per_unit": unit.commission if unit else None,
                         "real_drr_rate": rates.get(sku),
                         "applied_drr_rate": applied,
                         "applied_drr_source": source,
                         "drr_zero_assumed": source == 'zero_assumption',
                         "assumed_drr_rate": applied,
                         "planned_drr_rate": overrides.get(sku, planned_drr),
                         "price_action": action, "price_delta": delta,
                         "price_delta_rate": delta / current_price if delta is not None else None,
                         "buyer_prices": buyer_prices,
                         **summary, "groups": groups})
    return {"period": period, "observation_period": resolve_period(evidence),
            "history_complete": evidence.complete if evidence is not None else True,
            "evidence": "fulfilled_selected_period" if evidence else "fulfilled_completed_weeks",
            "target_margin": margin, "target_roi": roi, "goal": goal,
            "planned_drr": planned_drr, "products": products,
            "modeled_shortfall": (sum((p["modeled_shortfall"] for p in products
                                       if p["modeled_shortfall"] is not None), ZERO)
                                  if any(p["covered_qty"] for p in products) else None),
            "incomplete_sku_count": sum(p["partial"] or p["no_observations"] for p in products)}
