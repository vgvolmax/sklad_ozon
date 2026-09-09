"""Canonical orchestration for one immutable API source snapshot."""

from datetime import datetime, timezone
from uuid import uuid4

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.adapters.catalog import fetch_catalogs
from backend.ozon.adapters.inbound import fetch_inbound
from backend.ozon.adapters.orders import fetch_orders
from backend.ozon.adapters.placement_zones import fetch_placement_zones
from backend.ozon.adapters.stocks import fetch_stocks
from backend.ozon.history import history_window
from backend.ozon.source_contracts import (EndpointEvidence, OzonSourceSnapshot,
    SOURCE_TIMEZONE, source_business_date)
from dataclasses import replace


def capability_matrix(snapshot: OzonSourceSnapshot, *, include_inbound: bool = True) -> dict[str, dict[str, object]]:
    evidence = {item.name:item for item in snapshot.endpoint_evidence}
    def cap(name, affected, required=True):
        item=evidence.get(name); complete=bool(item and item.complete)
        return {"complete":complete or not required,"required":required,"affects":affected}
    return {
        "demand_flow":cap("orders","demand_flow"),
        "cluster_identity":cap("catalogs","affected_evidence"),
        "need_fbo":cap("fbo_stock","need"),
        "need_inbound":cap("inbound","need",include_inbound),
        "operational_allocation":cap("seller_stock","operational_allocation"),
        "ozon_comparison":{"complete":False,"required":False,"affects":"safe_comparison"},
        "shipment_compatibility":cap("placement_zones","shipment_compatibility"),
    }


def sync_ozon_source(client, *, progress_callback=None) -> OzonSourceSnapshot:
    now = datetime.now(timezone.utc)
    as_of = source_business_date(now)
    window = history_window(as_of)
    evidence=[]; diagnostics=[]
    def progress(stage):
        if progress_callback: progress_callback(stage)
    def run(name, function, default):
        progress(name)
        started=datetime.now(timezone.utc).isoformat()
        try:
            value=function()
            count=sum(len(part) for part in value if isinstance(part,tuple)) if isinstance(value,tuple) else len(value)
            evidence.append(EndpointEvidence(name,started,count,True,()))
            return value
        except Exception as exc:
            diagnostic=ImportDiagnostic("error",f"OZON_{name.upper()}_FAILED",f"Ozon {name} evidence unavailable: {type(exc).__name__}")
            diagnostics.append(diagnostic); evidence.append(EndpointEvidence(name,started,0,False,(diagnostic,)))
            return default
    orders, order_diags = run("orders",lambda:fetch_orders(client,window.history_from,window.history_to),((),()))
    diagnostics.extend(order_diags)
    clusters,seller_warehouses,catalog_diags=run("catalogs",lambda:fetch_catalogs(client),((),(),()))
    diagnostics.extend(catalog_diags)
    fbo,seller_stock,stock_diags=run("stocks",lambda:fetch_stocks(client),((),(),()))
    diagnostics.extend(stock_diags)
    # Split stock capability evidence because its consequences are intentionally distinct.
    stock_ev=evidence.pop(); evidence.extend((
        EndpointEvidence("fbo_stock",stock_ev.fetched_at_utc,len(fbo),stock_ev.complete,stock_ev.diagnostics),
        EndpointEvidence("seller_stock",stock_ev.fetched_at_utc,len(seller_stock),stock_ev.complete,stock_ev.diagnostics)))
    inbound,inbound_diags=run("inbound",lambda:fetch_inbound(client),((),()))
    diagnostics.extend(inbound_diags)
    skus=tuple(dict.fromkeys([x.sku for x in orders]+[x.sku for x in fbo]+[x.sku for x in seller_stock]))
    zones,zone_diags=run("placement_zones",lambda:fetch_placement_zones(client,skus),((),()))
    diagnostics.extend(zone_diags)
    inbound_by_key={(row.sku,row.cluster):row.inbound_quantity for row in inbound}
    availability=tuple(replace(row,inbound_quantity=inbound_by_key.get((row.sku,row.cluster))) for row in fbo)
    known={(row.sku,row.cluster) for row in availability}
    availability += tuple(row for row in inbound if (row.sku,row.cluster) not in known)
    progress("complete")
    return OzonSourceSnapshot(uuid4().hex,now.isoformat(),as_of,SOURCE_TIMEZONE,
        window.history_from,window.history_to,orders,availability,seller_stock,
        clusters,seller_warehouses,zones,tuple(evidence),tuple(diagnostics))
