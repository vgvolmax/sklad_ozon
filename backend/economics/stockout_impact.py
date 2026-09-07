"""Exact-quantity modeled financial impact for PR2 stockout episodes."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from backend.analytics.daily import DailyFulfillmentResult
from backend.analytics.stockout_episodes import DailyLocalityPoint, StockoutEpisode
from backend.domain.contracts import ImportResult, ProductEconomicsInput, TariffRow
from backend.project import EconomicsSettings
from backend.supply.contracts import SupplyFeasibility

from .route_opportunity import RouteCounterfactual, calculate_route_counterfactual

_CTX = Context(prec=40, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class RouteQuantityImpact:
    sku: str; origin_cluster_id: str; destination_cluster_id: str; quantity: int
    current_route_cost_rub_per_unit: Decimal | None
    local_route_cost_rub_per_unit: Decimal | None
    extra_logistics_rub: Decimal | None
    current_profit_per_unit: Decimal | None; local_profit_per_unit: Decimal | None
    current_margin_rate: Decimal | None; local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None; profit_delta_per_unit: Decimal | None
    profit_loss_or_opportunity_rub: Decimal | None
    price_per_unit: Decimal | None; realization_per_unit: Decimal | None
    complete: bool; reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteDayQuantityImpact:
    """Backend-only impact preserving one factual fulfillment cell's identity."""

    sku: str
    day: date
    origin_cluster_id: str
    destination_cluster_id: str
    quantity: int
    impact: RouteQuantityImpact


@dataclass(frozen=True, slots=True)
class ImpactEconomicsAggregate:
    quantity: int
    current_route_cost_rub_per_unit: Decimal | None
    local_route_cost_rub_per_unit: Decimal | None
    extra_logistics_rub: Decimal | None
    weighted_current_margin_rate: Decimal | None
    weighted_local_margin_rate: Decimal | None
    margin_delta_pp: Decimal | None
    profit_delta_per_unit: Decimal | None
    profit_loss_or_opportunity_rub: Decimal | None
    complete: bool; reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StockoutEpisodeImpact:
    episode_id: str; sku: str; destination_cluster_id: str
    start_date: date; end_date: date; affected_dates: tuple[date, ...]
    evidence_scope: object; confidence: object
    destination_demand_qty: int; fulfilled_quantity: int
    local_quantity: int; external_quantity: int
    local_share: Decimal | None; external_share: Decimal | None
    baseline_local_share: Decimal; local_share_during: Decimal
    evidence_reason_codes: tuple[str, ...]
    economics: ImpactEconomicsAggregate
    routes: tuple[RouteQuantityImpact, ...]
    route_day_impacts: tuple[RouteDayQuantityImpact, ...]


def deduplicate_route_day_impacts(
    episodes: tuple[StockoutEpisodeImpact, ...] | list[StockoutEpisodeImpact],
) -> tuple[RouteDayQuantityImpact, ...]:
    """Return the deterministic union of factual route-day evidence.

    Evidence-scoped episode views are intentionally not additive. Rolled-up
    destination/SKU totals use this union keyed without episode or scope.
    """
    unique: dict[tuple[str, str, date, str], RouteDayQuantityImpact] = {}
    for episode in episodes:
        for component in episode.route_day_impacts:
            key = (component.sku, component.destination_cluster_id,
                   component.day, component.origin_cluster_id)
            previous = unique.get(key)
            if previous is not None and previous != component:
                raise ValueError(
                    "conflicting stockout factual route-day evidence: "
                    f"sku={key[0]!r}, destination={key[1]!r}, "
                    f"day={key[2].isoformat()}, origin={key[3]!r}"
                )
            unique[key] = component
    return tuple(unique[key] for key in sorted(unique))


def apply_route_quantity(counterfactual: RouteCounterfactual, quantity: int) -> RouteQuantityImpact:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("quantity must be a positive int")
    extra = profit = None
    if counterfactual.complete:
        with localcontext(_CTX):
            extra = ((counterfactual.route_cost_rub - counterfactual.local_route_cost_rub)
                     * Decimal(quantity))
            profit = counterfactual.profit_delta_per_unit * Decimal(quantity)
    return RouteQuantityImpact(
        counterfactual.sku, counterfactual.origin_cluster_id,
        counterfactual.destination_cluster_id, quantity,
        counterfactual.route_cost_rub, counterfactual.local_route_cost_rub, extra,
        counterfactual.current_profit_per_unit, counterfactual.local_profit_per_unit,
        counterfactual.current_margin_rate, counterfactual.local_margin_rate,
        counterfactual.margin_delta_pp, counterfactual.profit_delta_per_unit, profit,
        counterfactual.price_per_unit, counterfactual.realization_per_unit,
        counterfactual.complete, counterfactual.reason_codes)


def aggregate_impacts(components) -> ImpactEconomicsAggregate:
    components = tuple(components)
    quantity = sum(item.quantity for item in components)
    reasons = tuple(sorted({code for item in components if not item.complete
                            for code in item.reason_codes}))
    if not components or quantity <= 0 or any(not item.complete for item in components):
        return ImpactEconomicsAggregate(quantity, None, None, None, None, None,
                                        None, None, None, False,
                                        reasons or ("ROUTE_ECONOMICS_INCOMPLETE",))
    with localcontext(_CTX):
        q = Decimal(quantity)
        current_cost = sum((x.current_route_cost_rub_per_unit * Decimal(x.quantity)
                            for x in components), Decimal(0))
        local_cost = sum((x.local_route_cost_rub_per_unit * Decimal(x.quantity)
                          for x in components), Decimal(0))
        extra = sum((x.extra_logistics_rub for x in components), Decimal(0))
        price_basis = sum((x.price_per_unit * Decimal(x.quantity)
                           for x in components), Decimal(0))
        current_profit = sum((x.current_profit_per_unit * Decimal(x.quantity)
                              for x in components), Decimal(0))
        local_profit = sum((x.local_profit_per_unit * Decimal(x.quantity)
                            for x in components), Decimal(0))
        profit = sum((x.profit_loss_or_opportunity_rub for x in components), Decimal(0))
        if price_basis <= 0:
            return ImpactEconomicsAggregate(quantity, None, None, None, None, None,
                None, None, None, False, ("MISSING_OR_ZERO_REALIZATION",))
        current_margin = current_profit / price_basis
        local_margin = local_profit / price_basis
        return ImpactEconomicsAggregate(quantity, current_cost / q, local_cost / q,
            extra, current_margin, local_margin,
            (local_margin - current_margin) * Decimal(100), profit / q, profit, True, ())


def build_stockout_episode_impacts(
    episodes: tuple[StockoutEpisode, ...],
    fulfillment: DailyFulfillmentResult,
    locality: tuple[DailyLocalityPoint, ...],
    products: dict[str, ProductEconomicsInput],
    tariffs: ImportResult[TariffRow],
    settings: EconomicsSettings,
    feasibility: dict[tuple[str, str], SupplyFeasibility],
) -> tuple[StockoutEpisodeImpact, ...]:
    impacts = []
    for episode in episodes:
        dates = frozenset(episode.affected_dates)
        selected = [cell for cell in fulfillment.cells
                    if cell.sku == episode.sku
                    and cell.destination_cluster_id == episode.destination_cluster_id
                    and cell.day in dates]
        routes = defaultdict(int)
        local = 0
        route_day_impacts = []
        counterfactuals = {}
        for cell in selected:
            if cell.origin_cluster_id == cell.destination_cluster_id:
                local += cell.quantity
            else:
                routes[cell.origin_cluster_id] += cell.quantity
                route_key = (episode.sku, cell.origin_cluster_id,
                             episode.destination_cluster_id)
                counterfactual = counterfactuals.get(route_key)
                if counterfactual is None:
                    counterfactual = calculate_route_counterfactual(
                        episode.sku, cell.origin_cluster_id,
                        episode.destination_cluster_id, products.get(episode.sku),
                        tariffs, settings,
                        feasibility.get((episode.sku,
                                         episode.destination_cluster_id)))
                    counterfactuals[route_key] = counterfactual
                route_day_impacts.append(RouteDayQuantityImpact(
                    episode.sku, cell.day, cell.origin_cluster_id,
                    episode.destination_cluster_id, cell.quantity,
                    apply_route_quantity(counterfactual, cell.quantity)))
        route_impacts = []
        for origin, quantity in sorted(routes.items()):
            counterfactual = counterfactuals[
                (episode.sku, origin, episode.destination_cluster_id)]
            route_impacts.append(apply_route_quantity(counterfactual, quantity))
        external = sum(routes.values()); fulfilled = local + external
        demand = sum(point.destination_demand_qty for point in locality
                     if point.sku == episode.sku
                     and point.destination_cluster_id == episode.destination_cluster_id
                     and point.day in dates)
        with localcontext(_CTX):
            local_share = Decimal(local) / Decimal(fulfilled) if fulfilled else None
            external_share = Decimal(external) / Decimal(fulfilled) if fulfilled else None
        scope = getattr(episode.evidence_scope, "value", episode.evidence_scope)
        episode_id = (f"{episode.sku}::{episode.destination_cluster_id}::"
                      f"{episode.start_date.isoformat()}::{episode.end_date.isoformat()}::{scope}")
        impacts.append(StockoutEpisodeImpact(
            episode_id, episode.sku, episode.destination_cluster_id,
            episode.start_date, episode.end_date, episode.affected_dates,
            episode.evidence_scope, episode.confidence, demand, fulfilled, local, external,
            local_share, external_share, episode.baseline_local_share,
            episode.representative_local_share, episode.reason_codes,
            aggregate_impacts(route_impacts), tuple(route_impacts),
            tuple(sorted(route_day_impacts, key=lambda item: (
                item.sku, item.destination_cluster_id, item.day,
                item.origin_cluster_id)))))
    return tuple(impacts)
