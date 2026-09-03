"""Pure assembly of the immutable Product Completion business snapshot."""

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from uuid import uuid4

from backend.analytics.flows import aggregate_clean_flows, aggregate_observed_flows
from backend.domain.signals import SignalConfidence
from .contracts import (AnalysisSnapshot, DecisionRow, DecisionSummary, DiagnosticView,
                        FlowEconomicsAggregate, FlowLinkView, FlowView, FlowViewAggregates, RouteSkuBreakdown)
from .explanations import explain_decision

_CTX = Context(prec=40, rounding=ROUND_HALF_EVEN)


def first_nonblank(*values) -> str:
    """Return the first meaningful identity value, never a blank override."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _route_aggregate(opportunities, observed_components=()):
    """Fail closed, then aggregate a destination's routes by observed units."""
    if not opportunities:
        return None, None, False
    complete = all(
        item.complete
        and item.margin_delta_pp is not None
        and item.observed_profit_opportunity_rub is not None
        for item in opportunities
    )
    if observed_components:
        observed = defaultdict(int)
        for item in observed_components:
            observed[item.origin_cluster_id] += item.quantity
        modeled = {item.origin_cluster_id: item.observed_qty for item in opportunities}
        complete = complete and modeled == dict(observed)
    if not complete:
        return None, None, False
    quantity = sum(item.observed_qty for item in opportunities)
    if quantity <= 0:
        return None, None, False
    with localcontext(_CTX):
        margin = sum(
            (item.margin_delta_pp * Decimal(item.observed_qty) for item in opportunities),
            Decimal("0"),
        ) / Decimal(quantity)
        rubles = sum(
            (item.observed_profit_opportunity_rub for item in opportunities),
            Decimal("0"),
        )
    return margin, rubles, True


def _is_incomplete_row(row, placement, *, route_required, route_complete):
    return (
        not row.need.complete
        or row.safe_plan_qty is None
        or row.calculated_plan_qty is None
        or placement is None
        or not placement.economics.complete
        or not placement.feasibility.allowed
        or (route_required and not route_complete)
    )


def _signal_status_codes(key, stockout_signals, distortion_signals):
    """Project already-computed signal identities into a decision-row status."""
    codes = set()
    if key in {(item.sku, item.destination_cluster_id) for item in stockout_signals}:
        codes.add("PROBABLE_STOCKOUT")
    if key in {(item.sku, item.recommended_cluster_id) for item in distortion_signals}:
        codes.add("RECOMMENDATION_DISTORTION")
    return codes


def _flow_economics(rows, opportunities):
    """Aggregate calculated per-unit economics with selected evidence quantities."""
    quantity = sum(row.quantity for row in rows)
    pairs = [(row, opportunities.get((row.sku, row.origin_cluster_id,
                                      row.destination_cluster_id))) for row in rows]
    reasons = tuple(sorted({code for _, item in pairs if item
                            for code in item.reason_codes}))
    complete = bool(pairs) and quantity > 0 and all(
        item is not None and item.complete
        and item.route_cost_rub is not None
        and item.realization_per_unit is not None
        and item.price_per_unit is not None
        and item.current_profit_per_unit is not None
        and item.local_route_cost_rub is not None
        and item.local_profit_per_unit is not None
        and item.profit_delta_per_unit is not None
        for _, item in pairs)
    if not complete:
        return FlowEconomicsAggregate(
            quantity, None, None, None, None, None, None, None, None, None,
            False, reasons or ("ROUTE_ECONOMICS_INCOMPLETE",))
    with localcontext(_CTX):
        q = Decimal(quantity)
        route_total = sum((item.route_cost_rub * Decimal(row.quantity)
                           for row, item in pairs), Decimal("0"))
        realization_total = sum((item.realization_per_unit * Decimal(row.quantity)
                                 for row, item in pairs), Decimal("0"))
        price_total = sum((item.price_per_unit * Decimal(row.quantity)
                           for row, item in pairs), Decimal("0"))
        current_profit = sum((item.current_profit_per_unit * Decimal(row.quantity)
                              for row, item in pairs), Decimal("0"))
        local_route_total = sum((item.local_route_cost_rub * Decimal(row.quantity)
                                 for row, item in pairs), Decimal("0"))
        local_profit = sum((item.local_profit_per_unit * Decimal(row.quantity)
                            for row, item in pairs), Decimal("0"))
        opportunity = sum((item.profit_delta_per_unit * Decimal(row.quantity)
                           for row, item in pairs), Decimal("0"))
        if realization_total <= 0 or price_total <= 0:
            return FlowEconomicsAggregate(
                quantity, None, None, None, None, None, None, None, None, None,
                False, ("MISSING_OR_ZERO_REALIZATION",))
        current_margin = current_profit / price_total
        local_margin = local_profit / price_total
        return FlowEconomicsAggregate(
            quantity, route_total / q, route_total / realization_total,
            current_margin, local_route_total / q,
            local_route_total / realization_total, local_margin,
            (local_margin - current_margin) * Decimal("100"), opportunity / q,
            opportunity, True, ())


def _observed_flow_opportunity(rows, opportunities):
    """Aggregate the immutable observed audit value for a displayed link."""
    items = [opportunities.get((row.sku, row.origin_cluster_id,
                                row.destination_cluster_id)) for row in rows]
    if not items or any(
        item is None or not item.complete
        or item.observed_profit_opportunity_rub is None
        for item in items
    ):
        return None
    with localcontext(_CTX):
        return sum(
            (item.observed_profit_opportunity_rub for item in items),
            Decimal("0"),
        )


def _views(flows, products, opportunities, product_identities=None,
           *, evidence_source="observed"):
    product_map = {p.sku: p for p in products}
    product_identities = product_identities or {}
    opp = {(x.sku, x.origin_cluster_id, x.destination_cluster_id): x
           for x in opportunities}
    destination_totals = defaultdict(int)
    for flow in flows:
        destination_totals[flow.destination_cluster_id] += flow.quantity

    def build(mode, key, selected):
        route_groups = defaultdict(list)
        for flow in selected:
            route_groups[(flow.origin_cluster_id,
                          flow.destination_cluster_id)].append(flow)
        total = sum(flow.quantity for flow in selected)
        links = []
        with localcontext(_CTX):
            for (origin, destination), rows in sorted(route_groups.items()):
                quantity = sum(row.quantity for row in rows)
                economics = _flow_economics(rows, opp)
                observed_opportunity = _observed_flow_opportunity(rows, opp)
                breakdown = []
                for flow in sorted(rows, key=lambda item: item.sku):
                    product = product_map.get(flow.sku)
                    opportunity = opp.get((flow.sku, origin, destination))
                    identity = product_identities.get(flow.sku, ("", ""))
                    article = first_nonblank(identity[0], getattr(product, "article", ""))
                    name = first_nonblank(identity[1], getattr(product, "product_name", ""))
                    breakdown.append(RouteSkuBreakdown(
                        flow.sku, article, name, flow.quantity,
                        Decimal(flow.quantity) / Decimal(quantity),
                        Decimal(flow.quantity) / Decimal(destination_totals[destination]),
                        None if opportunity is None else opportunity.margin_delta_pp,
                        None if opportunity is None
                        else opportunity.observed_profit_opportunity_rub,
                        None if opportunity is None or opportunity.profit_delta_per_unit is None
                        else opportunity.profit_delta_per_unit * Decimal(flow.quantity)))
                links.append(FlowLinkView(
                    origin, destination, quantity,
                    Decimal(quantity) / Decimal(destination_totals[destination]),
                    economics.margin_delta_pp, observed_opportunity,
                    economics.complete, economics.reason_codes, tuple(breakdown),
                    economics))
            local = sum(flow.quantity for flow in selected
                        if flow.origin_cluster_id == flow.destination_cluster_id)
            external_rows = [flow for flow in selected
                             if flow.origin_cluster_id != flow.destination_cluster_id]
            external = total - local
            external_economics = (_flow_economics(external_rows, opp)
                                  if mode == "destination" and external_rows else None)
            return FlowView(
                mode, key, evidence_source, total,
                Decimal(local) / Decimal(total) if total else None,
                Decimal(external) / Decimal(total) if total else None,
                len({flow.origin_cluster_id for flow in external_rows}),
                external_economics, tuple(links))

    result = []
    for mode, attribute in (("destination", "destination_cluster_id"),
                            ("origin", "origin_cluster_id"), ("sku", "sku")):
        for key in sorted({getattr(flow, attribute) for flow in flows}):
            result.append(build(mode, key, [flow for flow in flows
                                           if getattr(flow, attribute) == key]))
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
    diagnostics_by_key = defaultdict(set)
    for item in diagnostics:
        if item.sku is not None:
            diagnostics_by_key[(item.sku, item.destination_cluster_id or item.cluster_id)].add(item.code)
            if item.destination_cluster_id is None and item.cluster_id is None:
                diagnostics_by_key[(item.sku, None)].add(item.code)
    rows=[]
    for need in sorted(needs,key=lambda x:(x.sku,x.destination_cluster_id)):
        key=(need.sku,need.destination_cluster_id); p=products_by_sku.get(need.sku); place=placement.get(key)
        s=safe.get(key); c=calculated.get(key); opportunities=opportunity.get(key,[])
        observed_components = [r for r in observed_routes.routes
                               if (r.sku, r.destination_cluster_id) == key]
        route_margin, route_rubles, route_complete = _route_aggregate(
            opportunities, observed_components)
        route_required = bool(observed_components)
        codes = set(need.blocker_codes + (() if place is None else place.status_codes))
        if s is not None:
            codes.update(s.reason_codes)
        if c is not None:
            codes.update(c.reason_codes)
        codes.update(diagnostics_by_key.get(key, ()))
        codes.update(diagnostics_by_key.get((need.sku, None), ()))
        if s is None: codes.add("SAFE_PLAN_UNAVAILABLE")
        if c is None: codes.add("CALCULATED_PLAN_UNAVAILABLE")
        if route_required and not route_complete: codes.add("ROUTE_ECONOMICS_INCOMPLETE")
        codes.update(_signal_status_codes(key, stockout_signals, distortion_signals))
        status=tuple(sorted(codes))
        identity=product_identities.get(need.sku, ("", ""))
        article=first_nonblank(identity[0], getattr(p,"article", ""))
        name=first_nonblank(identity[1], getattr(p,"product_name", ""))
        row = DecisionRow(need.sku,article,name,need.destination_cluster_id,
            demand.get(key),need,None if s is None else s.allocation_qty,None if c is None else c.allocation_qty,
            need.current_fbo_stock,need.inbound_qty,
            _external_share(observed_routes,key),
            route_margin,route_rubles,
            None if c is None else c.expected_profit,
            SignalConfidence.LOW if demand.get(key) is None else demand[key].confidence,status,
            explain_decision(need=need,status_codes=status,
                safe_reason_codes=() if s is None else s.reason_codes,
                demand_codes=() if demand.get(key) is None else demand[key].explanation_codes,
                distorted=key in distortion,
                route_incomplete=route_required and not route_complete))
        rows.append(row)
    with localcontext(_CTX): profit=sum((x.objective_profit for x in calculated_allocations),Decimal("0"))
    summary=DecisionSummary(len({r.sku for r in rows}),len(rows),
        sum(r.need.ozon_recommended_qty for r in rows if r.need.ozon_recommended_qty is not None),
        sum(r.need.calculated_need_qty for r in rows if r.need.calculated_need_qty is not None),
        sum(r.safe_plan_qty for r in rows if r.safe_plan_qty is not None),
        sum(r.calculated_plan_qty for r in rows if r.calculated_plan_qty is not None),profit,
        sum(r.need.ozon_recommended_qty is not None and r.need.calculated_need_qty is not None and r.need.ozon_recommended_qty!=r.need.calculated_need_qty for r in rows),
        sum(_is_incomplete_row(
            r, placement.get((r.sku, r.destination_cluster_id)),
            route_required=bool([item for item in observed_routes.routes if
                                 (item.sku, item.destination_cluster_id) ==
                                 (r.sku, r.destination_cluster_id)]),
            route_complete="ROUTE_ECONOMICS_INCOMPLETE" not in r.status_codes,
        ) for r in rows))
    observed_flows=aggregate_observed_flows(observed_routes); clean_flows=aggregate_clean_flows(clean_routes)
    return AnalysisSnapshot(uuid4().hex,datetime.now(timezone.utc).isoformat(),dict(report_meta),tuple(freshness_warnings),scenario,
        dict(input_statuses),summary,tuple(rows),tuple(sorted(demand_estimates,key=lambda x:(x.sku,x.destination_cluster_id))),
        observed_routes,clean_routes,tuple(stockout_signals),tuple(distortion_signals),tuple(route_economics),
        tuple(unit_economics),tuple(safe_allocations),tuple(calculated_allocations),
        FlowViewAggregates(
            _views(observed_flows, products, route_economics, product_identities,
                   evidence_source="observed"),
            _views(clean_flows, products, route_economics, product_identities,
                   evidence_source="clean")),
        tuple(sorted(diagnostics,key=lambda x:(x.sku or "",x.cluster_id or "",
                                                x.destination_cluster_id or "",
                                                x.code,x.message))))


def _external_share(observed, key):
    rows=[r for r in observed.routes if (r.sku,r.destination_cluster_id)==key]
    total=sum(r.quantity for r in rows)
    if not total:return None
    external=sum(r.quantity for r in rows if r.origin_cluster_id!=r.destination_cluster_id)
    with localcontext(_CTX): return Decimal(external)/Decimal(total)
