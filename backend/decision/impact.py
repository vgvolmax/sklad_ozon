"""Bounded, deterministic presentation assembly for stockout impact."""

from collections import defaultdict
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from backend.economics.stockout_impact import aggregate_impacts
from .contracts import (DestinationDailyPoint, DestinationDailySeries,
    DestinationImpactSummary, EpisodeDonorBreakdown, EpisodeSkuBreakdown,
    ImpactEconomicsView, RouteImpactView, StockoutEpisodeView,
    StockoutImpactPresentation)

ECONOMICS_BASIS_TEXT = "Оценка по текущим тарифам и настройкам на фактическом объёме периода."
_CTX = Context(prec=40, rounding=ROUND_HALF_EVEN)


def _economics(value):
    return ImpactEconomicsView(value.quantity, value.current_route_cost_rub_per_unit,
        value.local_route_cost_rub_per_unit, value.extra_logistics_rub,
        value.weighted_current_margin_rate, value.weighted_local_margin_rate,
        value.margin_delta_pp, value.profit_delta_per_unit,
        value.profit_loss_or_opportunity_rub, value.complete, value.reason_codes)


def build_stockout_impact_presentation(locality, episode_impacts,
                                       product_identities=None):
    identities = product_identities or {}
    def identity(sku): return identities.get(sku, ("", ""))
    episode_views = []
    for episode in episode_impacts:
        article, name = identity(episode.sku)
        donors = []
        for route in episode.routes:
            route_view = RouteImpactView(route.sku, article, name,
                route.origin_cluster_id, route.destination_cluster_id, route.quantity,
                route.current_route_cost_rub_per_unit, route.local_route_cost_rub_per_unit,
                route.extra_logistics_rub, route.current_margin_rate,
                route.local_margin_rate, route.margin_delta_pp,
                route.profit_delta_per_unit, route.profit_loss_or_opportunity_rub,
                route.complete, route.reason_codes)
            with localcontext(_CTX):
                share = Decimal(route.quantity) / Decimal(episode.external_quantity)
            donors.append(EpisodeDonorBreakdown(route.origin_cluster_id,
                route.destination_cluster_id, route.quantity, share,
                _economics(aggregate_impacts((route,))), (route_view,)))
        donors.sort(key=lambda x: (-x.quantity, x.origin_cluster_id))
        episode_views.append(StockoutEpisodeView(
            episode.episode_id, episode.sku, article, name,
            episode.destination_cluster_id, episode.start_date, episode.end_date,
            episode.confidence, episode.evidence_scope, episode.destination_demand_qty,
            episode.fulfilled_quantity, episode.local_quantity, episode.external_quantity,
            episode.local_share, episode.external_share, episode.baseline_local_share,
            episode.local_share_during, len(donors), _economics(episode.economics),
            tuple(donors), episode.evidence_reason_codes))
    episode_views.sort(key=lambda x: (x.destination_cluster_id, x.start_date,
                                      x.end_date, x.sku))

    episode_index = defaultdict(list)
    for episode in episode_impacts:
        for day in episode.affected_dates:
            episode_index[(episode.destination_cluster_id, day)].append(episode)
    daily = defaultdict(lambda: [0, 0, 0])
    for point in locality:
        values = daily[(point.destination_cluster_id, point.day)]
        values[0] += point.destination_demand_qty
        values[1] += point.local_fulfilled_qty
        values[2] += point.external_fulfilled_qty
    series = []
    for destination in sorted({key[0] for key in daily}):
        points = []
        for (dest, day), (demand, local, external) in sorted(daily.items()):
            if dest != destination: continue
            fulfilled = local + external
            episodes = episode_index.get((dest, day), ())
            with localcontext(_CTX):
                local_share = Decimal(local) / Decimal(fulfilled) if fulfilled else None
                external_share = Decimal(external) / Decimal(fulfilled) if fulfilled else None
            points.append(DestinationDailyPoint(day, demand, fulfilled, local, external,
                local_share, external_share,
                len({episode.sku for episode in episodes}),
                tuple(sorted(episode.episode_id for episode in episodes))))
        series.append(DestinationDailySeries(destination, tuple(points)))

    summaries = []
    for item in series:
        episodes = [e for e in episode_impacts
                    if e.destination_cluster_id == item.destination_cluster_id]
        routes = tuple(route for episode in episodes for route in episode.routes)
        episode_external = sum(e.external_quantity for e in episodes)
        sku_rows = []
        for sku in sorted({e.sku for e in episodes}):
            selected = [e for e in episodes if e.sku == sku]
            sku_routes = tuple(route for episode in selected for route in episode.routes)
            quantity = sum(e.external_quantity for e in selected)
            article, name = identity(sku)
            with localcontext(_CTX):
                share = (Decimal(quantity) / Decimal(episode_external)
                         if episode_external else None)
            sku_rows.append(EpisodeSkuBreakdown(sku, article, name, len(selected),
                quantity, share, _economics(aggregate_impacts(sku_routes))))
        demand = sum(p.destination_demand_qty for p in item.points)
        local = sum(p.local_fulfilled_qty for p in item.points)
        external = sum(p.external_fulfilled_qty for p in item.points)
        fulfilled = local + external
        with localcontext(_CTX):
            local_share = Decimal(local) / Decimal(fulfilled) if fulfilled else None
            external_share = Decimal(external) / Decimal(fulfilled) if fulfilled else None
        summaries.append(DestinationImpactSummary(item.destination_cluster_id,
            item.points[0].day, item.points[-1].day, demand, fulfilled, local, external,
            local_share, external_share, len(episodes), len({e.sku for e in episodes}),
            episode_external, _economics(aggregate_impacts(routes)), tuple(sku_rows)))
    return StockoutImpactPresentation(ECONOMICS_BASIS_TEXT, tuple(summaries),
                                      tuple(series), tuple(episode_views))
