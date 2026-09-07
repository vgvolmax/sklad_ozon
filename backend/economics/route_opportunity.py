"""Modeled economics of an observed fulfillment route and local alternative."""

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from backend.analytics.clean_routes import RouteDistributionCell
from backend.analytics.flows import FulfillmentFlowCell
from backend.domain.contracts import ImportResult, ProductEconomicsInput, TariffRow
from backend.project import EconomicsSettings
from backend.supply.contracts import SupplyFeasibility

from .tariffs import (LogisticsContext, LogisticsCoverageStatus,
                      RouteProfileSource, expected_logistics)
from .unit import calculate_unit_economics


@dataclass(frozen=True, slots=True)
class RouteOpportunity:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    observed_qty: int
    destination_share: Decimal
    route_cost_rub: Decimal | None
    route_cost_pct_of_realization: Decimal | None
    current_profit_per_unit: Decimal | None
    current_margin_rate: Decimal | None
    local_route_cost_rub: Decimal | None
    local_route_cost_pct_of_realization: Decimal | None
    local_profit_per_unit: Decimal | None
    local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None
    profit_delta_per_unit: Decimal | None
    observed_profit_opportunity_rub: Decimal | None
    price_per_unit: Decimal | None
    realization_per_unit: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteCounterfactual:
    sku: str
    origin_cluster_id: str
    destination_cluster_id: str
    route_cost_rub: Decimal | None
    route_cost_pct_of_realization: Decimal | None
    current_profit_per_unit: Decimal | None
    current_margin_rate: Decimal | None
    local_route_cost_rub: Decimal | None
    local_route_cost_pct_of_realization: Decimal | None
    local_profit_per_unit: Decimal | None
    local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None
    profit_delta_per_unit: Decimal | None
    price_per_unit: Decimal | None
    realization_per_unit: Decimal | None
    complete: bool
    reason_codes: tuple[str, ...]


def _profile(flow: FulfillmentFlowCell, origin: str) -> tuple[RouteDistributionCell, ...]:
    return (RouteDistributionCell(
        flow.sku, origin, flow.destination_cluster_id, flow.quantity,
        flow.observation_count, Decimal("1"),
    ),)


def _counterfactual_profile(sku: str, origin: str, destination: str):
    return (RouteDistributionCell(sku, origin, destination, 1, 1, Decimal("1")),)


def calculate_route_counterfactual(
    sku: str,
    origin_cluster_id: str,
    destination_cluster_id: str,
    product: ProductEconomicsInput | None,
    tariffs: ImportResult[TariffRow],
    settings: EconomicsSettings,
    local_feasibility: SupplyFeasibility | None,
) -> RouteCounterfactual:
    """Calculate the quantity-independent current-route/local identity."""
    if product is None:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            None, None, None, None, None, None, None, None, None, None, None,
            None, False, ("MISSING_PRODUCT_ECONOMICS",))
    if product.sku != sku:
        raise ValueError("product SKU must match route SKU")
    if product.volume_liters is None:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            None, None, None, None, None, None, None, None, None, None,
            product.price, None, False, ("MISSING_PRODUCT_VOLUME",))
    current_logistics = expected_logistics(
        _counterfactual_profile(sku, origin_cluster_id, destination_cluster_id), tariffs,
        LogisticsContext(sku, origin_cluster_id, product.volume_liters, product.price,
                         RouteProfileSource.OBSERVED))
    current = calculate_unit_economics(product, origin_cluster_id, current_logistics, settings)
    reasons = []
    if current_logistics.coverage_status is not LogisticsCoverageStatus.COMPLETE:
        reasons.append("CURRENT_ROUTE_INCOMPLETE")
    if not current.complete:
        reasons.append("CURRENT_ECONOMICS_INCOMPLETE")
    if current.realization is None or current.realization <= 0:
        reasons.append("MISSING_OR_ZERO_REALIZATION")
    current_ready = not reasons and all(value is not None for value in
        (current.expected_logistics, current.profit_per_unit, current.margin_rate))
    current_pct = None
    if current_ready:
        with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
            current_pct = current.expected_logistics / current.realization
    if not current_ready:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            current.expected_logistics, None, current.profit_per_unit, current.margin_rate,
            None, None, None, None, None, None, current.price, current.realization,
            False, tuple(reasons))
    if local_feasibility is None:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            current.expected_logistics, current_pct, current.profit_per_unit,
            current.margin_rate, None, None, None, None, None, None, current.price,
            current.realization, False, ("LOCAL_FEASIBILITY_MISSING",))
    if local_feasibility.sku != sku or local_feasibility.cluster_id != destination_cluster_id:
        raise ValueError("feasibility identity must match route destination")
    if not local_feasibility.allowed or local_feasibility.max_supply_qty == 0:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            current.expected_logistics, current_pct, current.profit_per_unit,
            current.margin_rate, None, None, None, None, None, None, current.price,
            current.realization, False, ("LOCAL_PLACEMENT_INFEASIBLE",))
    local_logistics = expected_logistics(
        _counterfactual_profile(sku, destination_cluster_id, destination_cluster_id), tariffs,
        LogisticsContext(sku, destination_cluster_id, product.volume_liters, product.price,
                         RouteProfileSource.OBSERVED))
    local = calculate_unit_economics(product, destination_cluster_id, local_logistics, settings)
    reasons = []
    if local_logistics.coverage_status is not LogisticsCoverageStatus.COMPLETE:
        reasons.append("LOCAL_ROUTE_INCOMPLETE")
    if not local.complete:
        reasons.append("LOCAL_ECONOMICS_INCOMPLETE")
    if local.realization is None or local.realization <= 0:
        reasons.append("MISSING_OR_ZERO_REALIZATION")
    if reasons:
        return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
            current.expected_logistics, current_pct, current.profit_per_unit,
            current.margin_rate, None, None, None, None, None, None, current.price,
            current.realization, False, tuple(reasons))
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        local_pct = local.expected_logistics / local.realization
        margin_delta = (local.margin_rate - current.margin_rate) * Decimal("100")
        profit_delta = local.profit_per_unit - current.profit_per_unit
    return RouteCounterfactual(sku, origin_cluster_id, destination_cluster_id,
        current.expected_logistics, current_pct, current.profit_per_unit,
        current.margin_rate, local.expected_logistics, local_pct,
        local.profit_per_unit, local.margin_rate, margin_delta, profit_delta,
        current.price, current.realization, True, ())


def _empty(flow, current, reasons, current_pct=None):
    route_cost = current.expected_logistics
    return RouteOpportunity(
        flow.sku, flow.origin_cluster_id, flow.destination_cluster_id,
        flow.quantity, flow.destination_share, route_cost, current_pct,
        current.profit_per_unit, current.margin_rate,
        None, None, None, None, None, None, None,
        current.price, current.realization, False, tuple(reasons),
    )


def calculate_route_opportunity(
    flow: FulfillmentFlowCell,
    product: ProductEconomicsInput,
    tariffs: ImportResult[TariffRow],
    settings: EconomicsSettings,
    local_feasibility: SupplyFeasibility,
) -> RouteOpportunity:
    counterfactual = calculate_route_counterfactual(
        flow.sku, flow.origin_cluster_id, flow.destination_cluster_id,
        product, tariffs, settings, local_feasibility)
    opportunity = (counterfactual.profit_delta_per_unit * Decimal(flow.quantity)
                   if counterfactual.profit_delta_per_unit is not None else None)
    return RouteOpportunity(
        flow.sku, flow.origin_cluster_id, flow.destination_cluster_id, flow.quantity,
        flow.destination_share, counterfactual.route_cost_rub,
        counterfactual.route_cost_pct_of_realization,
        counterfactual.current_profit_per_unit, counterfactual.current_margin_rate,
        counterfactual.local_route_cost_rub,
        counterfactual.local_route_cost_pct_of_realization,
        counterfactual.local_profit_per_unit, counterfactual.local_margin_rate,
        counterfactual.margin_delta_pp, counterfactual.profit_delta_per_unit,
        opportunity, counterfactual.price_per_unit,
        counterfactual.realization_per_unit, counterfactual.complete,
        counterfactual.reason_codes,
    )
