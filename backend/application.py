"""Pure application orchestration for one stateless analysis request."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from backend.analytics.demand import aggregate_demand, DemandResult
from backend.analytics.demand_estimate import estimate_destination_demand
from backend.analytics.routes import build_route_profile, RouteProfile
from backend.analytics.stockout import detect_stockouts
from backend.analytics.distortion import detect_recommendation_distortion
from backend.analytics.clean_routes import build_clean_route_profile, CleanRouteResult
from backend.analytics.flows import aggregate_observed_flows
from backend.analytics.route_profiles import select_route_profile
from backend.economics import (expected_logistics, LogisticsContext, RouteProfileSource,
                               calculate_unit_economics, calculate_route_opportunity)
from backend.project import EconomicsSettings, OptimizerThresholds
from backend.decision import ScenarioSettings, calculate_need
from backend.supply import (AllocationObjective, PlanFamily, WarehouseCapability, PlacementInput, PlacementSource, RouteConfidence,
                            compare_placements, optimize_allocations)

_DEFAULT_SCENARIO = ScenarioSettings(
    horizon_days=56,
    include_inbound=True,
    objective=AllocationObjective.MAX_PROFIT,
)

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
    placements: tuple; allocations: tuple; safe_allocations: tuple; summary: AnalysisSummary
    diagnostics: tuple[AnalysisDiagnostic, ...]
    demand_estimates: tuple = ()
    needs: tuple = ()
    route_economics: tuple = ()

def analyze(availability, restrictions, orders, tariffs, products, *, as_of: date,
            economics_settings: EconomicsSettings, optimizer_thresholds: OptimizerThresholds,
            availability_fbs_authoritative: bool = False, operational_availability=None,
            ozon_horizon_days: int | None = None,
            progress_callback=None,
            scenario_settings: ScenarioSettings = _DEFAULT_SCENARIO) -> AnalysisResult:
    if not isinstance(scenario_settings, ScenarioSettings):
        raise TypeError("scenario_settings must be ScenarioSettings")
    def progress(stage, current=None, total=None):
        if progress_callback is not None:
            progress_callback(stage, current, total)

    progress("demand")
    demand = aggregate_demand(orders, as_of)
    demand_estimates = estimate_destination_demand(demand)
    demand_estimates_by_identity = {
        (item.sku, item.destination_cluster_id): item for item in demand_estimates
    }
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
            conflicts.add(key); rec_values.pop(key, None)
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
    availability_by_identity = defaultdict(list)
    for record in availability:
        availability_by_identity[(record.sku, record.cluster)].append(record)

    def conservative_quantity(records, field):
        values = [getattr(record, field, None) for record in records]
        if not values or any(value is None for value in values):
            return None
        return sum(values)
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
    logistics_results=[]; economics_results=[]; candidates=[]; needs=[]
    progress("logistics_economics", 0, len(skus))
    for sku_index, sku in enumerate(skus, 1):
        clusters = {c.destination_cluster_id for c in demand_by_sku.get(sku, ())}
        clusters |= {r.destination_cluster_id for r in observed_by_sku.get(sku, ())}
        clusters |= {item[1] for item in recommendations_by_sku.get(sku, ()) if item[2] > 0}
        clusters |= {s.destination_cluster_id for s in stockouts_by_sku.get(sku, ())}
        clusters |= {s.recommended_cluster_id for s in distortions_by_sku.get(sku, ())}
        product=product_map.get(sku)
        # Need is an upstream quantity contract.  Build it before attempting
        # economics so missing product data can only block placement/allocation.
        sku_needs = []
        for cluster in sorted(clusters):
            operational = availability_by_identity.get((sku, cluster), ())
            estimate = demand_estimates_by_identity.get((sku, cluster))
            need = calculate_need(
                sku=sku,
                destination_cluster_id=cluster,
                weekly_rate=(estimate.current_weekly_rate if estimate is not None else None),
                horizon_days=scenario_settings.horizon_days,
                fbo_stock=conservative_quantity(operational, "fbo_quantity"),
                inbound_qty=conservative_quantity(operational, "inbound_quantity"),
                include_inbound=scenario_settings.include_inbound,
                ozon_recommended_qty=rec_values.get((sku, cluster)),
                ozon_horizon_days=ozon_horizon_days,
            )
            needs.append(need)
            sku_needs.append(need)
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
            recommendation = rec_values.get((sku,cluster))
            qty = recommendation if recommendation is not None else 0
            need = next(item for item in sku_needs if item.destination_cluster_id == cluster)
            sources=[]
            if observed_profile: sources.append(PlacementSource.OBSERVED)
            sources.append(PlacementSource.RECOMMENDED if recommendation is not None else PlacementSource.COUNTERFACTUAL)
            distortion=distortion_by_cluster.get((sku, cluster))
            candidates.append(PlacementInput(
                sku, cluster, qty, tuple(sources), econ, distortion, confidence,
                need.calculated_need_qty,
            ))
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
    allocations=[]; safe_allocations=[]
    for sku_index, sku in enumerate(skus, 1):
        product=product_map.get(sku); group=placements_by_sku.get(sku, ())
        stock = ((next(iter(positive_fbs[sku])) if positive_fbs.get(sku) else 0) if sku in fbs and sku not in conflicting_fbs else
                 (product.available_qty if product and sku not in fbs and not availability_fbs_authoritative else None))
        if product and stock is not None and group:
            # Safe is not calculable without the external Ozon ceiling.  The
            # Calculated family remains independent from that evidence.
            recommendations = {
                item.destination_cluster_id: item.ozon_recommended_qty
                for item in needs if item.sku == sku
            }
            safe_group = tuple(
                item for item in group
                if recommendations.get(item.cluster_id) is not None
            )
            if safe_group:
                safe_allocations.append(optimize_allocations(
                    safe_group, stock, optimizer_thresholds,
                    plan_family=PlanFamily.SAFE,
                    objective=scenario_settings.objective,
                ))
            allocations.append(optimize_allocations(
                group, stock, optimizer_thresholds,
                plan_family=PlanFamily.CALCULATED,
                objective=scenario_settings.objective,
            ))
        elif product and sku not in conflicting_fbs:
            diagnostics.append(AnalysisDiagnostic("error","MISSING_SELLER_AVAILABLE_STOCK","Missing seller available stock.",sku))
        progress("optimizer", sku_index, len(skus))
    allocations = tuple(allocations)
    safe_allocations = tuple(safe_allocations)
    feasibility={(p.sku,p.cluster_id):p.feasibility for p in placements}
    route_opportunities=[]
    for flow in aggregate_observed_flows(observed):
        product=product_map.get(flow.sku); local=feasibility.get((flow.sku,flow.destination_cluster_id))
        if product is not None and local is not None:
            route_opportunities.append(calculate_route_opportunity(flow,product,tariffs,economics_settings,local))
    summary = build_analysis_summary(placements, allocations)
    identities = [(item.sku, item.destination_cluster_id) for item in needs]
    if len(identities) != len(set(identities)):
        raise AssertionError("duplicate NeedComparison for SKU and destination")
    return AnalysisResult(
        demand, observed, clean, stockouts, distortions, tuple(logistics_results),
        tuple(economics_results), placements, allocations, safe_allocations, summary,
        tuple(diagnostics), tuple(demand_estimates), tuple(needs), tuple(route_opportunities),
    )
