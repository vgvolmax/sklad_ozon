"""Causal orchestration for one immutable API source snapshot."""

from datetime import datetime, timezone
from uuid import uuid4

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle
from backend.ozon.adapters.catalog import fetch_clusters, fetch_seller_warehouses
from backend.ozon.adapters.inbound import fetch_inbound
from backend.ozon.adapters.orders import fetch_postings
from backend.ozon.adapters.placement_zones import fetch_placement_zones
from backend.ozon.adapters.products import fetch_product_skus
from backend.ozon.adapters.stocks import fetch_fbo_stock, fetch_seller_stock
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH
from backend.ozon.history import history_window, next_backfill, usable_completed_weeks
from backend.ozon.source_contracts import EndpointEvidence, OzonSourceSnapshot, SOURCE_TIMEZONE, source_business_date


def capability_matrix(snapshot: OzonSourceSnapshot, *, include_inbound: bool = True) -> dict[str, dict[str, object]]:
    evidence = {item.name: item for item in snapshot.endpoint_evidence}

    def cap(names, affected, required=True):
        names = (names,) if isinstance(names, str) else names
        complete = all(bool(evidence.get(name) and evidence[name].complete) for name in names)
        return {"complete": complete, "required": required, "affects": affected}

    return {
        "demand_flow": cap(("orders_fbo", "orders_fbs"), "demand_flow"),
        "cluster_identity": cap("clusters", "affected_evidence"),
        "seller_warehouse_selection": cap("seller_warehouses", "crossdock_selection", False),
        "need_fbo": cap("fbo_stock", "need"),
        "need_inbound": cap("inbound", "need", include_inbound),
        "operational_allocation": cap("seller_stock", "operational_allocation"),
        "ozon_comparison": {"complete": False, "required": False, "affects": "safe_comparison"},
        "shipment_compatibility": cap("placement_zones", "shipment_compatibility", False),
    }


def sync_ozon_source(client, *, credential_context_id: str | None = None,
                     progress_callback=None) -> OzonSourceSnapshot:
    now = datetime.now(timezone.utc)
    as_of = source_business_date(now)
    window = history_window(as_of)
    evidence: list[EndpointEvidence] = []
    diagnostics: list[ImportDiagnostic] = []

    def progress(stage):
        if progress_callback:
            progress_callback(stage)

    def run(name, function, default):
        progress(name)
        started = datetime.now(timezone.utc).isoformat()
        try:
            value = function()
            if name == "clusters":
                records, item_diagnostics = value.clusters, value.diagnostics
            else:
                records, item_diagnostics = value
            diagnostics.extend(item_diagnostics)
            complete = not any(item.severity == "error" for item in item_diagnostics)
            evidence.append(EndpointEvidence(name, started, len(records), complete, item_diagnostics))
            return value if name == "clusters" else records
        except Exception as exc:
            diagnostic = ImportDiagnostic(
                "error", f"OZON_{name.upper()}_FAILED",
                f"Ozon {name} evidence unavailable: {type(exc).__name__}")
            diagnostics.append(diagnostic)
            evidence.append(EndpointEvidence(name, started, 0, False, (diagnostic,)))
            return default

    def history_fetch(current_window):
        fbo = run("orders_fbo", lambda: fetch_postings(
            client, FBO_POSTINGS_PATH, current_window.history_from, current_window.history_to), ())
        fbs = run("orders_fbs", lambda: fetch_postings(
            client, FBS_POSTINGS_PATH, current_window.history_from, current_window.history_to), ())
        return tuple(fbo) + tuple(fbs)

    orders = history_fetch(window)
    while (all(item.complete for item in evidence[-2:]) and
           len(usable_completed_weeks(orders, as_of)) < 8):
        expanded = next_backfill(window)
        if expanded is None:
            break
        window = expanded
        # The full expanded window replaces, rather than merges, prior evidence.
        evidence[:] = [item for item in evidence if item.name not in {"orders_fbo", "orders_fbs"}]
        orders = history_fetch(window)

    clusters_result = run("clusters", lambda: fetch_clusters(client), None)
    clusters = clusters_result.clusters if clusters_result is not None else ()
    warehouse_to_macrolocal = clusters_result.warehouse_to_macrolocal if clusters_result is not None else {}
    seller_warehouses = run("seller_warehouses", lambda: fetch_seller_warehouses(client), ())
    cluster_by_id = {cluster.cluster_id: cluster.name for cluster in clusters}
    product_skus = run("products", lambda: (fetch_product_skus(client), ()), ())
    product_evidence = next(item for item in evidence if item.name == "products")
    if product_evidence.complete:
        fbo = run("fbo_stock", lambda: fetch_fbo_stock(client, product_skus), ())
    else:
        fbo = ()
        if not product_evidence.complete:
            diagnostic = ImportDiagnostic("error", "OZON_FBO_STOCK_FAILED", "FBO stock unavailable without complete SKU universe.")
            diagnostics.append(diagnostic)
            evidence.append(EndpointEvidence("fbo_stock", datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))
    seller_stock = run("seller_stock", lambda: fetch_seller_stock(client), ())
    inbound = run("inbound", lambda: fetch_inbound(client, cluster_by_id, warehouse_to_macrolocal), ())
    if product_evidence.complete:
        zones = run("placement_zones", lambda: fetch_placement_zones(client, product_skus), ())
    else:
        zones = ()
        diagnostic = ImportDiagnostic(
            "error", "OZON_PLACEMENT_ZONES_FAILED",
            "Placement-zone evidence unavailable because SKU universe is incomplete.")
        diagnostics.append(diagnostic)
        evidence.append(EndpointEvidence(
            "placement_zones", datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))

    # FBO is warehouse-grained while inbound is cluster-grained.  Preserve them
    # as independent evidence rows so downstream Need aggregation counts each
    # inbound quantity exactly once.
    availability = tuple(fbo) + tuple(inbound)
    progress("complete")
    return OzonSourceSnapshot(
        uuid4().hex, now.isoformat(), as_of, SOURCE_TIMEZONE, window.history_from,
        window.history_to, orders, availability, seller_stock, clusters,
        seller_warehouses, zones, tuple(evidence), tuple(diagnostics),
        credential_context_id)
