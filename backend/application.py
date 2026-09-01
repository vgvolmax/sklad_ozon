"""Pure application orchestration for one stateless analysis request."""
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from backend.analytics.demand import aggregate_demand, DemandResult
from backend.analytics.routes import build_route_profile, RouteProfile
from backend.analytics.stockout import detect_stockouts
from backend.analytics.distortion import detect_recommendation_distortion
from backend.analytics.clean_routes import build_clean_route_profile, CleanRouteResult
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
            availability_fbs_authoritative: bool = False) -> AnalysisResult:
    demand = aggregate_demand(orders, as_of)
    observed = build_route_profile(orders, as_of)
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
    fbs = {}
    for record in availability:
        if getattr(record, "fbs_quantity", None) is not None: fbs.setdefault(record.sku, set()).add(record.fbs_quantity)
    positive_fbs = {sku: {value for value in values if value > 0} for sku, values in fbs.items()}
    conflicting_fbs = {sku for sku, values in positive_fbs.items() if len(values) > 1}
    for sku in sorted(conflicting_fbs):
        diagnostics.append(AnalysisDiagnostic("error", "CONFLICTING_FBS_AVAILABLE_STOCK", "Conflicting FBS seller stock values.", sku))
    skus = sorted({c.sku for c in demand.cells} | {r.sku for r in observed.routes} | {k[0] for k in rec_values})
    logistics_results=[]; economics_results=[]; candidates=[]
    for sku in skus:
        clusters = {c.destination_cluster_id for c in demand.cells if c.sku==sku}
        clusters |= {r.origin_cluster_id for r in observed.routes if r.sku==sku}
        clusters |= {k[1] for k,v in rec_values.items() if k[0]==sku and v>0}
        clusters |= {s.destination_cluster_id for s in stockouts if s.sku==sku}
        clusters |= {s.recommended_cluster_id for s in distortions if s.sku==sku}
        product=product_map.get(sku)
        if product is None:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_PRODUCT_ECONOMICS","Missing product economics.",sku)); continue
        if product.volume_liters is None:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_PRODUCT_VOLUME","Missing product volume.",sku)); continue
        for cluster in sorted(clusters):
            clean_profile=tuple(r for r in clean.clean_routes if r.sku==sku and r.origin_cluster_id==cluster)
            observed_profile=tuple(r for r in clean.observed_routes if r.sku==sku and r.origin_cluster_id==cluster)
            profile=clean_profile or observed_profile
            source=RouteProfileSource.CLEAN if clean_profile else RouteProfileSource.OBSERVED
            confidence=RouteConfidence.MEDIUM if clean_profile else RouteConfidence.LOW
            log=expected_logistics(profile, tariffs, LogisticsContext(sku,cluster,product.volume_liters,product.price,source))
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
            distortion=next((d for d in distortions if d.sku==sku and d.recommended_cluster_id==cluster),None)
            candidates.append(PlacementInput(sku,cluster,qty,tuple(sources),econ,distortion,confidence))
    placements_list = []
    for sku in skus:
        sku_restrictions = tuple(r for r in restrictions if r.sku == sku)
        mapped = tuple(WarehouseCapability(r.warehouse, r.cluster, r.max_supply_qty)
                       for r in sku_restrictions if getattr(r, "cluster", ""))
        if not mapped:
            mapped = tuple(WarehouseCapability(r.warehouse, r.cluster, None)
                           for r in sorted(availability, key=lambda x:(x.warehouse,x.cluster))
                           if r.sku == sku and r.warehouse not in bad_warehouses)
        placements_list.extend(compare_placements((c for c in candidates if c.sku == sku), sku_restrictions, tuple(dict.fromkeys(mapped))))
    placements=tuple(sorted(placements_list, key=lambda item: (item.sku, item.cluster_id)))
    allocations=[]
    for sku in skus:
        product=product_map.get(sku); group=tuple(p for p in placements if p.sku==sku)
        stock = ((next(iter(positive_fbs[sku])) if positive_fbs.get(sku) else 0) if sku in fbs and sku not in conflicting_fbs else
                 (product.available_qty if product and sku not in fbs and not availability_fbs_authoritative else None))
        if product and stock is not None and group:
            allocations.append(optimize_allocations(group, stock, optimizer_thresholds))
        elif product and sku not in conflicting_fbs:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_SELLER_AVAILABLE_STOCK","Missing seller available stock.",sku))
    allocations = tuple(allocations)
    summary = build_analysis_summary(placements, allocations)
    return AnalysisResult(demand,observed,clean,stockouts,distortions,tuple(logistics_results),tuple(economics_results),placements,allocations,summary,tuple(diagnostics))
