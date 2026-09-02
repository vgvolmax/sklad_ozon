"""Pure application orchestration for one stateless analysis request."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from backend.analytics.demand import aggregate_demand, DemandResult
from backend.analytics.routes import build_route_profile, RouteProfile
from backend.analytics.stockout import detect_stockouts
from backend.analytics.distortion import detect_recommendation_distortion
from backend.analytics.clean_routes import build_clean_route_profile, CleanRouteResult
from backend.analytics.route_profiles import select_route_profile
from backend.economics import expected_logistics, LogisticsContext, RouteProfileSource, calculate_unit_economics
from backend.project import EconomicsSettings, OptimizerThresholds
from backend.supply import (WarehouseCapability, PlacementInput, PlacementSource, RouteConfidence,
                            compare_placements, optimize_allocations)

@dataclass(frozen=True, slots=True)
class AnalysisDiagnostic:
    severity: str; code: str; message: str; sku: str | None = None; cluster_id: str | None = None
    destination_cluster_id: str | None = None

@dataclass(frozen=True, slots=True)
class AnalysisSummary:
    sku_count: int
    placement_count: int
    ozon_recommended_qty: int
    allocated_qty: int
    objective_profit: Decimal


def build_analysis_summary(placements: tuple, allocations: tuple) -> AnalysisSummary:
    with localcontext(Context(prec=40, rounding=ROUND_HALF_EVEN)):
        objective_profit = sum(
            (result.objective_profit for result in allocations),
            start=Decimal("0"),
        )
    return AnalysisSummary(
        sku_count=len({placement.sku for placement in placements}),
        placement_count=len(placements),
        ozon_recommended_qty=sum(placement.ozon_recommended_qty for placement in placements),
        allocated_qty=sum(result.allocated_qty for result in allocations),
        objective_profit=objective_profit,
    )


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    demand: DemandResult; observed_routes: RouteProfile; clean_routes: CleanRouteResult
    stockouts: tuple; distortions: tuple; logistics: tuple; economics: tuple
    placements: tuple; allocations: tuple; summary: AnalysisSummary
    diagnostics: tuple[AnalysisDiagnostic, ...]

def analyze(availability, restrictions, orders, tariffs, products, *, as_of: date,
            economics_settings: EconomicsSettings, optimizer_thresholds: OptimizerThresholds,
            availability_fbs_authoritative: bool = False, operational_availability=None,
            progress_callback=None) -> AnalysisResult:
    def progress(stage, current=None, total=None):
        if progress_callback is not None:
            progress_callback(stage, current, total)

    progress("demand")
    demand = aggregate_demand(orders, as_of)
    progress("routes")
    observed = build_route_profile(orders, as_of)
    progress("distortions")
    stockouts = detect_stockouts(observed, availability)
    distortions = detect_recommendation_distortion(stockouts, observed)
    clean = build_clean_route_profile(observed, stockouts)
    diagnostics = []
    rec_values = {}
    conflicts = set()
    for record in availability:
        if record.recommended_quantity is None: continue
        key = (record.sku, record.cluster)
        if key in rec_values and rec_values[key] != record.recommended_quantity:
            conflicts.add(key); rec_values[key] = 0
        elif key not in conflicts: rec_values[key] = record.recommended_quantity
    for sku, cluster in sorted(conflicts):
        diagnostics.append(AnalysisDiagnostic("error", "CONFLICTING_OZON_RECOMMENDATION", "Conflicting cluster-level recommendations.", sku, cluster))
    if not rec_values:
        diagnostics.append(AnalysisDiagnostic("error", "MISSING_OZON_RECOMMENDATIONS", "Availability report contains no Ozon recommendations."))
    mappings = {}
    for record in availability:
        mappings.setdefault(record.warehouse, set()).add(record.cluster)
    bad_warehouses = {w for w, clusters in mappings.items() if len(clusters) > 1}
    for warehouse in sorted(bad_warehouses):
        diagnostics.append(AnalysisDiagnostic("error", "CONFLICTING_WAREHOUSE_CLUSTER", f"Warehouse {warehouse} maps to multiple clusters."))
    product_map = {p.sku:p for p in products}
    seller_stock_evidence = tuple(operational_availability) if operational_availability is not None else tuple(availability)
    fbs = {}
    for record in seller_stock_evidence:
        if getattr(record, "fbs_quantity", None) is not None: fbs.setdefault(record.sku, set()).add(record.fbs_quantity)
    positive_fbs = {sku: {value for value in values if value > 0} for sku, values in fbs.items()}
    conflicting_fbs = {sku for sku, values in positive_fbs.items() if len(values) > 1}
    for sku in sorted(conflicting_fbs):
        diagnostics.append(AnalysisDiagnostic("error", "CONFLICTING_FBS_AVAILABLE_STOCK", "Conflicting FBS seller stock values.", sku))
    skus = sorted({c.sku for c in demand.cells} | {r.sku for r in observed.routes} | {k[0] for k in rec_values})
    def grouped(items, key):
        result = defaultdict(list)
        for item in items:
            result[key(item)].append(item)
        return {group: tuple(values) for group, values in result.items()}
    demand_by_sku = grouped(demand.cells, lambda item: item.sku)
    observed_by_sku = grouped(observed.routes, lambda item: item.sku)
    observed_by_origin = grouped(clean.observed_routes, lambda item: (item.sku, item.origin_cluster_id))
    stockouts_by_sku = grouped(stockouts, lambda item: item.sku)
    distortions_by_sku = grouped(distortions, lambda item: item.sku)
    distortion_by_cluster = {}
    for item in distortions:
        distortion_by_cluster.setdefault((item.sku, item.recommended_cluster_id), item)
    restrictions_by_sku = grouped(restrictions, lambda item: item.sku)
    availability_by_sku = grouped(availability, lambda item: item.sku)
    recommendations_by_sku = grouped(
        tuple((sku, cluster, value) for (sku, cluster), value in rec_values.items()),
        lambda item: item[0],
    )
    logistics_results=[]; economics_results=[]; candidates=[]
    progress("logistics_economics", 0, len(skus))
    for sku_index, sku in enumerate(skus, 1):
        clusters = {c.destination_cluster_id for c in demand_by_sku.get(sku, ())}
        clusters |= {r.origin_cluster_id for r in observed_by_sku.get(sku, ())}
        clusters |= {item[1] for item in recommendations_by_sku.get(sku, ()) if item[2]>0}
        clusters |= {s.destination_cluster_id for s in stockouts_by_sku.get(sku, ())}
        clusters |= {s.recommended_cluster_id for s in distortions_by_sku.get(sku, ())}
        product=product_map.get(sku)
        if product is None:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_PRODUCT_ECONOMICS","Missing product economics.",sku))
            progress("logistics_economics", sku_index, len(skus)); continue
        if product.volume_liters is None:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_PRODUCT_VOLUME","Missing product volume.",sku))
            progress("logistics_economics", sku_index, len(skus)); continue
        for cluster in sorted(clusters):
            observed_profile=observed_by_origin.get((sku, cluster), ())
            selection=select_route_profile(sku, cluster, clean, observed)
            confidence=RouteConfidence(selection.confidence.value)
            log=expected_logistics(selection.profile, tariffs, LogisticsContext(sku,cluster,product.volume_liters,product.price,selection.source))
            econ=calculate_unit_economics(product,cluster,log,economics_settings)
            logistics_results.append(log); economics_results.append(econ)
            diagnostics.extend(
                AnalysisDiagnostic(item.severity, item.code, item.message, sku, cluster, item.destination_cluster_id)
                for item in log.diagnostics
            )
            if not econ.complete:
                diagnostics.extend(
                    AnalysisDiagnostic("error", blocker, f"Unit economics is blocked by {blocker}.", sku, cluster)
                    for blocker in econ.blockers
                )
            qty=0 if (sku,cluster) in conflicts else rec_values.get((sku,cluster),0)
            sources=[]
            if observed_profile: sources.append(PlacementSource.OBSERVED)
            sources.append(PlacementSource.RECOMMENDED if qty>0 else PlacementSource.COUNTERFACTUAL)
            distortion=distortion_by_cluster.get((sku, cluster))
            candidates.append(PlacementInput(sku,cluster,qty,tuple(sources),econ,distortion,confidence))
        progress("logistics_economics", sku_index, len(skus))
    candidates_by_sku = grouped(candidates, lambda item: item.sku)
    progress("placements", 0, len(skus))
    placements_list = []
    for sku_index, sku in enumerate(skus, 1):
        sku_restrictions = restrictions_by_sku.get(sku, ())
        mapped = tuple(WarehouseCapability(r.warehouse, r.cluster, r.max_supply_qty)
                       for r in sku_restrictions if getattr(r, "cluster", ""))
        if not mapped:
            mapped = tuple(WarehouseCapability(r.warehouse, r.cluster, None)
                           for r in sorted(availability_by_sku.get(sku, ()), key=lambda x:(x.warehouse,x.cluster))
                           if r.warehouse not in bad_warehouses)
        placements_list.extend(compare_placements(candidates_by_sku.get(sku, ()), sku_restrictions, tuple(dict.fromkeys(mapped))))
        progress("placements", sku_index, len(skus))
    placements=tuple(sorted(placements_list, key=lambda item: (item.sku, item.cluster_id)))
    placements_by_sku = grouped(placements, lambda item: item.sku)
    progress("optimizer", 0, len(skus))
    allocations=[]
    for sku_index, sku in enumerate(skus, 1):
        product=product_map.get(sku); group=placements_by_sku.get(sku, ())
        stock = ((next(iter(positive_fbs[sku])) if positive_fbs.get(sku) else 0) if sku in fbs and sku not in conflicting_fbs else
                 (product.available_qty if product and sku not in fbs and not availability_fbs_authoritative else None))
        if product and stock is not None and group:
            allocations.append(optimize_allocations(group, stock, optimizer_thresholds))
        elif product and sku not in conflicting_fbs:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_SELLER_AVAILABLE_STOCK","Missing seller available stock.",sku))
        progress("optimizer", sku_index, len(skus))
    allocations = tuple(allocations)
    summary = build_analysis_summary(placements, allocations)
    return AnalysisResult(demand,observed,clean,stockouts,distortions,tuple(logistics_results),tuple(economics_results),placements,allocations,summary,tuple(diagnostics))
