"""Pure arbitrary-horizon need and original-Ozon-value comparison."""

from decimal import Decimal, ROUND_CEILING

from .contracts import HorizonComparability, NeedComparison


def _validate_horizon(horizon_days: int) -> None:
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int):
        raise TypeError("horizon_days must be an int")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")


def forecast_horizon(weekly_rate: Decimal, horizon_days: int) -> Decimal:
    _validate_horizon(horizon_days)
    if not isinstance(weekly_rate, Decimal):
        raise TypeError("weekly_rate must be a Decimal")
    return weekly_rate * Decimal(horizon_days) / Decimal(7)


def _comparability(recommendation: int | None, ozon_days: int | None,
                   own_days: int) -> HorizonComparability:
    if recommendation is None:
        return HorizonComparability.OZON_RECOMMENDATION_MISSING
    if ozon_days is None:
        return HorizonComparability.OZON_HORIZON_UNKNOWN
    if ozon_days == own_days:
        return HorizonComparability.SAME_HORIZON
    return HorizonComparability.DIFFERENT_HORIZON


def calculate_need(
    *, sku: str, destination_cluster_id: str, weekly_rate: Decimal | None,
    horizon_days: int, fbo_stock: int | None, inbound_qty: int | None,
    include_inbound: bool, ozon_recommended_qty: int | None,
    ozon_horizon_days: int | None,
) -> NeedComparison:
    _validate_horizon(horizon_days)
    if not isinstance(include_inbound, bool):
        raise TypeError("include_inbound must be a bool")

    blockers = []
    if weekly_rate is None:
        forecast = None
        blockers.append("MISSING_DEMAND_ESTIMATE")
    else:
        forecast = forecast_horizon(weekly_rate, horizon_days)
    if fbo_stock is None:
        blockers.append("MISSING_FBO_STOCK")
    if include_inbound and inbound_qty is None:
        blockers.append("MISSING_INBOUND_QTY")

    need = None
    if not blockers:
        raw_need = forecast - Decimal(fbo_stock)
        if include_inbound:
            raw_need -= Decimal(inbound_qty)
        need = max(0, int(raw_need.to_integral_value(rounding=ROUND_CEILING)))

    delta = None if need is None or ozon_recommended_qty is None else need - ozon_recommended_qty
    delta_pct = None
    if delta is not None and ozon_recommended_qty > 0:
        delta_pct = Decimal(delta) / Decimal(ozon_recommended_qty)

    return NeedComparison(
        sku=sku, destination_cluster_id=destination_cluster_id,
        current_weekly_rate=weekly_rate, horizon_days=horizon_days,
        raw_demand_forecast=forecast, current_fbo_stock=fbo_stock,
        inbound_qty=inbound_qty, inbound_included=include_inbound,
        calculated_need_qty=need, ozon_recommended_qty=ozon_recommended_qty,
        ozon_horizon_days=ozon_horizon_days, delta_qty=delta,
        delta_pct=delta_pct,
        comparability=_comparability(ozon_recommended_qty, ozon_horizon_days, horizon_days),
        complete=need is not None, blocker_codes=tuple(blockers),
    )
