"""Pure assembly of the immutable Product Completion business snapshot."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from uuid import uuid4

from backend.analytics.flows import aggregate_clean_flows, aggregate_observed_flows
from backend.domain.signals import SignalConfidence
from .contracts import (AnalysisSnapshot, DecisionRow, DecisionSummary, DiagnosticView,
                        FlowLinkView, FlowView, FlowViewAggregates, RouteSkuBreakdown)
from .explanations import explain_decision

_CTX = Context(prec=40, rounding=ROUND_HALF_EVEN)


def _views(flows, products, opportunities, product_identities=None):
    product_map = {p.sku: p for p in products}
    product_identities = product_identities or {}
    opp = {(x.sku, x.origin_cluster_id, x.destination_cluster_id): x for x in opportunities}
    destination_totals = defaultdict(int)
    for f in flows: destination_totals[f.destination_cluster_id] += f.quantity

    def build(mode, key, selected):
        route_groups = defaultdict(list)
        for f in selected: route_groups[(f.origin_cluster_id, f.destination_cluster_id)].append(f)
        total = sum(f.quantity for f in selected)
        links = []
        with localcontext(_CTX):
            for (origin, destination), rows in sorted(route_groups.items()):
                qty = sum(x.quantity for x in rows)
                breakdown=[]
                for f in sorted(rows, key=lambda x:x.sku):
                    p=product_map.get(f.sku); o=opp.get((f.sku,origin,destination))
                    article,name=product_identities.get(f.sku,(getattr(p,"article","") or "",getattr(p,"product_name","") or ""))
                    breakdown.append(RouteSkuBreakdown(
                        f.sku, article, name,
                        f.quantity, Decimal(f.quantity)/Decimal(qty),
                        Decimal(f.quantity)/Decimal(destination_totals[destination]),
                        None if o is None else o.margin_delta_pp,
                        None if o is None else o.observed_profit_opportunity_rub))
                os=[opp.get((f.sku,origin,destination)) for f in rows]
                complete=bool(os) and all(o is not None and o.complete for o in os)
                reasons=tuple(sorted({c for o in os if o for c in o.reason_codes}))
                margins=[o.margin_delta_pp for o in os if o and o.margin_delta_pp is not None]
                rubles=[o.observed_profit_opportunity_rub for o in os if o and o.observed_profit_opportunity_rub is not None]
                links.append(FlowLinkView(origin,destination,qty,
                    Decimal(qty)/Decimal(destination_totals[destination]),
                    sum(margins,Decimal("0"))/Decimal(len(margins)) if margins else None,
                    sum(rubles,Decimal("0")) if rubles else None,complete,reasons,tuple(breakdown)))
            local=sum(f.quantity for f in selected if f.origin_cluster_id==f.destination_cluster_id)
            external=total-local
            return FlowView(mode,key,total,Decimal(local)/Decimal(total) if total else None,
                Decimal(external)/Decimal(total) if total else None,
                len({f.origin_cluster_id for f in selected if f.origin_cluster_id!=f.destination_cluster_id}),tuple(links))
    result=[]
    for mode, attr in (("destination","destination_cluster_id"),("origin","origin_cluster_id"),("sku","sku")):
        for key in sorted({getattr(f,attr) for f in flows}):
            result.append(build(mode,key,[f for f in flows if getattr(f,attr)==key]))
    return tuple(result)


def assemble_snapshot(*, scenario, report_meta, input_statuses, demand_estimates,
                      needs, observed_routes, clean_routes, stockout_signals,
                      distortion_signals, route_economics, unit_economics,
                      placements, safe_allocations, calculated_allocations,
                      products, diagnostics, freshness_warnings=(), product_identities=None):
    demand={(x.sku,x.destination_cluster_id):x for x in demand_estimates}
    placement={(x.sku,x.cluster_id):x for x in placements}
    safe={(d.sku,d.cluster_id):d for r in safe_allocations for d in r.decisions}
    calculated={(d.sku,d.cluster_id):d for r in calculated_allocations for d in r.decisions}
    opportunity=defaultdict(list)
    for o in route_economics: opportunity[(o.sku,o.destination_cluster_id)].append(o)
    distortion={(x.sku,x.recommended_cluster_id) for x in distortion_signals}
    products_by_sku={p.sku:p for p in products}
    product_identities = product_identities or {}
    rows=[]
    for need in sorted(needs,key=lambda x:(x.sku,x.destination_cluster_id)):
        key=(need.sku,need.destination_cluster_id); p=products_by_sku.get(need.sku); place=placement.get(key)
        s=safe.get(key); c=calculated.get(key); opportunities=opportunity.get(key,[])
        status=tuple(sorted(set(need.blocker_codes + (() if place is None else place.status_codes))))
        margins=[o.margin_delta_pp for o in opportunities if o.margin_delta_pp is not None]
        rubles=[o.observed_profit_opportunity_rub for o in opportunities if o.observed_profit_opportunity_rub is not None]
        article,name=product_identities.get(need.sku,(getattr(p,"article","") or "",""))
        rows.append(DecisionRow(need.sku,article,name,need.destination_cluster_id,
            demand.get(key),need,0 if s is None else s.allocation_qty,0 if c is None else c.allocation_qty,
            need.current_fbo_stock,need.inbound_qty,
            _external_share(observed_routes,key),
            max(margins) if margins else None,sum(rubles,Decimal("0")) if rubles else None,
            None if c is None else c.expected_profit,
            SignalConfidence.LOW if demand.get(key) is None else demand[key].confidence,status,
            explain_decision(need=need,status_codes=status,
                demand_codes=() if demand.get(key) is None else demand[key].explanation_codes,
                distorted=key in distortion,
                route_incomplete=any(not o.complete for o in opportunities))))
    with localcontext(_CTX): profit=sum((x.objective_profit for x in calculated_allocations),Decimal("0"))
    summary=DecisionSummary(len({r.sku for r in rows}),len(rows),
        sum(r.need.ozon_recommended_qty for r in rows if r.need.ozon_recommended_qty is not None),
        sum(r.need.calculated_need_qty for r in rows if r.need.calculated_need_qty is not None),
        sum(r.safe_plan_qty for r in rows),sum(r.calculated_plan_qty for r in rows),profit,
        sum(r.need.ozon_recommended_qty is not None and r.need.calculated_need_qty is not None and r.need.ozon_recommended_qty!=r.need.calculated_need_qty for r in rows),
        sum(not r.need.complete for r in rows))
    observed_flows=aggregate_observed_flows(observed_routes); clean_flows=aggregate_clean_flows(clean_routes)
    return AnalysisSnapshot(uuid4().hex,datetime.now(timezone.utc).isoformat(),dict(report_meta),tuple(freshness_warnings),scenario,
        dict(input_statuses),summary,tuple(rows),tuple(sorted(demand_estimates,key=lambda x:(x.sku,x.destination_cluster_id))),
        observed_routes,clean_routes,tuple(stockout_signals),tuple(distortion_signals),tuple(route_economics),
        tuple(unit_economics),tuple(safe_allocations),tuple(calculated_allocations),
        FlowViewAggregates(_views(observed_flows,products,route_economics,product_identities),_views(clean_flows,products,route_economics,product_identities)),
        tuple(sorted(diagnostics,key=lambda x:(x.sku or "",x.cluster_id or "",x.code,x.message))))


def _external_share(observed, key):
    rows=[r for r in observed.routes if (r.sku,r.destination_cluster_id)==key]
    total=sum(r.quantity for r in rows)
    if not total:return None
    external=sum(r.quantity for r in rows if r.origin_cluster_id!=r.destination_cluster_id)
    with localcontext(_CTX): return Decimal(external)/Decimal(total)
