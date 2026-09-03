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


def _profile(flow: FulfillmentFlowCell, origin: str) -> tuple[RouteDistributionCell, ...]:
    return (RouteDistributionCell(
        flow.sku, origin, flow.destination_cluster_id, flow.quantity,
        flow.observation_count, Decimal("1"),
    ),)


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
    if product.sku != flow.sku:
        raise ValueError("product SKU must match flow SKU")
    if local_feasibility.sku != flow.sku:
        raise ValueError("feasibility SKU must match flow SKU")
    if local_feasibility.cluster_id != flow.destination_cluster_id:
        raise ValueError("feasibility cluster must match flow destination")
    if product.volume_liters is None:
        return RouteOpportunity(
            flow.sku, flow.origin_cluster_id, flow.destination_cluster_id,
            flow.quantity, flow.destination_share,
            None, None, None, None, None, None, None, None, None, None, None,
            product.price, None,
            False, ("CURRENT_ROUTE_INCOMPLETE", "CURRENT_ECONOMICS_INCOMPLETE"),
        )

    current_logistics = expected_logistics(
        _profile(flow, flow.origin_cluster_id), tariffs,
        LogisticsContext(flow.sku, flow.origin_cluster_id, product.volume_liters,
                         product.price, RouteProfileSource.OBSERVED),
    )
    current = calculate_unit_economics(
        product, flow.origin_cluster_id, current_logistics, settings
    )
    reasons = []
    if current_logistics.coverage_status is not LogisticsCoverageStatus.COMPLETE:
        reasons.append("CURRENT_ROUTE_INCOMPLETE")
    if not current.complete:
        reasons.append("CURRENT_ECONOMICS_INCOMPLETE")
    if current.realization is None or current.realization <= 0:
        reasons.append("MISSING_OR_ZERO_REALIZATION")
    current_ready = (
        not reasons and current.expected_logistics is not None
        and current.profit_per_unit is not None and current.margin_rate is not None
    )
    if not current_ready:
        return _empty(flow, current, reasons)

    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        current_pct = current.expected_logistics / current.realization
    if not local_feasibility.allowed or local_feasibility.max_supply_qty == 0:
        return _empty(flow, current, ("LOCAL_PLACEMENT_INFEASIBLE",), current_pct)

    destination = flow.destination_cluster_id
    local_logistics = expected_logistics(
        _profile(flow, destination), tariffs,
        LogisticsContext(flow.sku, destination, product.volume_liters,
                         product.price, RouteProfileSource.OBSERVED),
    )
    local = calculate_unit_economics(product, destination, local_logistics, settings)
    reasons = []
    if local_logistics.coverage_status is not LogisticsCoverageStatus.COMPLETE:
        reasons.append("LOCAL_ROUTE_INCOMPLETE")
    if not local.complete:
        reasons.append("LOCAL_ECONOMICS_INCOMPLETE")
    if local.realization is None or local.realization <= 0:
        reasons.append("MISSING_OR_ZERO_REALIZATION")
    local_ready = (
        not reasons and local.expected_logistics is not None
        and local.profit_per_unit is not None and local.margin_rate is not None
    )
    if not local_ready:
        return RouteOpportunity(
            flow.sku, flow.origin_cluster_id, destination, flow.quantity,
            flow.destination_share, current.expected_logistics, current_pct,
            current.profit_per_unit, current.margin_rate, None, None, None, None,
            None, None, None, current.price, current.realization,
            False, tuple(reasons),
        )

    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        local_pct = local.expected_logistics / local.realization
        margin_delta = (local.margin_rate - current.margin_rate) * Decimal("100")
        profit_delta = local.profit_per_unit - current.profit_per_unit
        opportunity = profit_delta * Decimal(flow.quantity)
    return RouteOpportunity(
        flow.sku, flow.origin_cluster_id, destination, flow.quantity,
        flow.destination_share, current.expected_logistics, current_pct,
        current.profit_per_unit, current.margin_rate, local.expected_logistics,
        local_pct, local.profit_per_unit, local.margin_rate, margin_delta,
        profit_delta, opportunity, current.price, current.realization, True, (),
    )
