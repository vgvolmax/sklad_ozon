"""Read-only target scenarios over the completed-week route economics snapshot.

The historical quantity is delivered route evidence, not paid/bought units.
The shortfall is a modeled comparison at current input rates, not an actual loss.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext

from backend.project import EconomicsSettings

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
    """Find a non-decreasing price at unchanged rates and route logistics."""
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
        lower = max(current_price, Decimal("0.01"))
        if deficit(lower) >= 0:
            return lower
        upper = lower
        for _ in range(40):
            upper *= 2
            if deficit(upper) >= 0:
                break
        else:
            return None
        for _ in range(100):
            mid = (lower + upper) / 2
            if deficit(mid) >= 0:
                upper = mid
            else:
                lower = mid
        return upper.quantize(Decimal("0.01"), rounding="ROUND_CEILING")


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
    gap = sum((row["gap"] for row in known), ZERO) if covered else None
    proposed = [row["target_price"] for row in rows]
    target_price = (max(proposed) if proposed and all(x is not None for x in proposed)
                    else None)
    return {"qty": qty, "covered_qty": covered, "profit_per_unit": profit,
            "margin": margin, "roi": roi, "modeled_shortfall": gap,
            "target_price_all_routes": target_price,
            "partial": covered != qty, "no_observations": qty == 0,
            "below_margin": margin is not None and margin < margin_target,
            "below_roi": roi is not None and roi < roi_target,
            "below_goal": (margin if goal == "margin" else roi) is not None
                and (margin if goal == "margin" else roi) <
                (margin_target if goal == "margin" else roi_target)}


def build_economics_workspace(snapshot, *, margin, roi, goal, planned_drr,
                              per_sku_drr=None, modeled_drr=None, per_sku_cost=None):
    margin, roi, goal, planned_drr = validate_targets(margin, roi, goal, planned_drr)
    settings: EconomicsSettings | None = snapshot.economics_settings
    if settings is None:
        raise ValueError("analysis has no economics settings")
    model_rate = (settings.advertising_rate if modeled_drr is None else
                  _decimal(modeled_drr, 'modeled_drr', Decimal('.90')))
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
    by_sku = defaultdict(list)
    covered_route_keys = set()
    for route in snapshot.route_economics:
        covered_route_keys.add((route.sku, route.origin_cluster_id,
                                route.destination_cluster_id))
        unit = unit_by_sku.get(route.sku)
        price = route.price_per_unit
        cost = costs.get(route.sku, unit.cost if unit else None)
        logistics = route.route_cost_rub
        profit = route.current_profit_per_unit
        inputs_ready = (unit is not None and unit.price is not None and unit.price > 0
                        and unit.commission is not None and price is not None and price > 0
                        and cost is not None and logistics is not None
                        and settings.tax_system in {'usn_income', 'usn_income_minus_expenses'})
        if inputs_ready and (modeled_drr is not None or route.sku in costs):
            with localcontext() as context:
                context.prec = 40
                profit = _profit_at_price(price, cost, logistics,
                    unit.commission / unit.price, settings, model_rate)
        complete = inputs_ready and profit is not None
        drr = overrides.get(route.sku, planned_drr)
        if complete:
            commission_rate = unit.commission / unit.price
            target_price = _target_price(price, cost, logistics, commission_rate,
                                         settings, drr, margin, roi, goal)
            required_profit = (margin * price if goal == "margin" else roi * cost)
            gap = max(ZERO, required_profit - profit) * route.observed_qty
        else:
            target_price = None
            gap = None
        by_sku[route.sku].append({
            "origin": route.origin_cluster_id, "destination": route.destination_cluster_id,
            "qty": route.observed_qty, "price": price, "cost": cost,
            "profit": profit if complete else None,
            "margin": profit / price if complete else None,
            "roi": profit / cost if complete and cost else None,
            "logistics": logistics, "gap": gap, "target_price": target_price,
            "reason_codes": route.reason_codes if not complete else (),
        })
    missing_routes = defaultdict(int)
    for observed in snapshot.observed_routes.routes:
        key = (observed.sku, observed.origin_cluster_id,
               observed.destination_cluster_id)
        if key not in covered_route_keys:
            missing_routes[key] += observed.quantity
    for (sku, origin, destination), quantity in sorted(missing_routes.items()):
        by_sku[sku].append({
            "origin": origin, "destination": destination, "qty": quantity,
            "price": None, "cost": None, "profit": None, "margin": None,
            "roi": None, "logistics": None, "gap": None,
            "target_price": None, "reason_codes": ("NO_ROUTE_ECONOMICS",),
        })
    for sku in identity:
        by_sku.setdefault(sku, [])
    products = []
    for sku in sorted(by_sku):
        routes = by_sku[sku]
        article, name = identity.get(sku, ("", ""))
        unit = unit_by_sku.get(sku)
        summary = _aggregate(routes, margin, roi, goal)
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
                         "assumed_drr_rate": model_rate,
                         "planned_drr_rate": overrides.get(sku, planned_drr),
                         **summary, "groups": groups})
    weeks = snapshot.observed_routes.window.included_weeks
    period = ({"from": date.fromisocalendar(*min(weeks), 1),
               "to": date.fromisocalendar(*max(weeks), 7)} if weeks else None)
    return {"period": period, "evidence": "fulfilled_completed_weeks",
            "target_margin": margin, "target_roi": roi, "goal": goal,
            "planned_drr": planned_drr, "products": products,
            "modeled_drr": model_rate,
            "modeled_shortfall": (sum((p["modeled_shortfall"] for p in products
                                       if p["modeled_shortfall"] is not None), ZERO)
                                  if any(p["covered_qty"] for p in products) else None),
            "incomplete_sku_count": sum(p["partial"] or p["no_observations"] for p in products)}
