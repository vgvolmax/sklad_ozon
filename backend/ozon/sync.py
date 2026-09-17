"""Causal orchestration for one immutable API source snapshot."""

from datetime import datetime, timezone
import inspect
from uuid import uuid4

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle
from backend.ozon.client import OzonClientError
from backend.ozon.adapters.catalog import fetch_clusters, fetch_seller_warehouses
from backend.ozon.adapters.inbound import fetch_inbound
from backend.ozon.adapters.orders import fetch_postings
from backend.ozon.adapters.placement_zones import fetch_placement_zones
from backend.ozon.adapters.products import fetch_product_skus
from backend.ozon.adapters.stocks import fetch_fbo_stock, fetch_seller_stock
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH
from backend.ozon.history import history_window, next_backfill, usable_completed_weeks
from backend.ozon.source_contracts import (
    EndpointEvidence, OzonApiErrorEvidence, OzonRecordQualityEvidence,
    OzonSourceSnapshot, SOURCE_TIMEZONE,
    source_business_date,
)

SYNC_STAGES = (
    ("orders_fbo", "Заказы FBO", "Получение истории заказов"),
    ("orders_fbs", "Заказы FBS", "Получение истории заказов"),
    ("clusters", "Кластеры", "Получение каталога кластеров"),
    ("seller_warehouses", "Склады отправления продавца", "Получение складов"),
    ("products", "Каталог SKU", "Получение каталога товаров"),
    ("fbo_stock", "FBO остатки", "Получение остатков FBO"),
    ("seller_stock", "Остаток продавца", "Получение остатков продавца"),
    ("inbound", "Поставки в пути", "Поиск заявок"),
    ("placement_zones", "Зоны размещения", "Получение зон размещения"),
)
_STAGE_BY_NAME = {
    name: (index, label, detail)
    for index, (name, label, detail) in enumerate(SYNC_STAGES, 1)
}


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
    highest_stage_index = 0
    stage_progress: dict[str, dict[str, object]] = {}

    def progress(stage, *, detail=None, current=None, total=None, unit=None,
                 completed=False):
        nonlocal highest_stage_index
        if not progress_callback:
            return
        index, label, default_detail = _STAGE_BY_NAME[stage]
        # History backfill revisits FBO before FBS. Do not make the user-facing
        # pipeline move backwards; the initial pass already exposed both stages.
        if index < highest_stage_index:
            return
        highest_stage_index = index
        previous = stage_progress.setdefault(stage, {})
        for key, value in (("detail", detail), ("current", current),
                           ("total", total), ("unit", unit)):
            if value is not None:
                previous[key] = value
        event = {"type": "progress", "stage": stage, "stage_index": index,
                 "stage_count": len(SYNC_STAGES), "label": label,
                 "detail": previous.get("detail", default_detail),
                 "current": previous.get("current"), "total": previous.get("total"),
                 "unit": previous.get("unit"), "completed": completed}
        progress_callback(event)

    def call_with_progress(function, *args, stage):
        callback = lambda **values: progress(stage, **values)
        try:
            supports_progress = "progress_callback" in inspect.signature(function).parameters
        except (TypeError, ValueError):
            supports_progress = False
        return function(*args, progress_callback=callback) if supports_progress else function(*args)

    def run(name, function, default):
        progress(name)
        started = datetime.now(timezone.utc).isoformat()
        try:
            value = function()
            record_quality = None
            if name == "clusters":
                records, item_diagnostics = value.clusters, value.diagnostics
            elif name in {"orders_fbo", "orders_fbs", "inbound", "fbo_stock", "seller_stock", "placement_zones"}:
                if len(value) == 3:
                    records, item_diagnostics, record_quality = value
                else:  # Compatibility for injected legacy adapter doubles.
                    records, item_diagnostics = value
                    record_quality = OzonRecordQualityEvidence()
            else:
                records, item_diagnostics = value
            diagnostics.extend(item_diagnostics)
            complete = not any(item.severity == "error" for item in item_diagnostics)
            evidence.append(EndpointEvidence(
                name, started, len(records), complete, item_diagnostics,
                record_quality=record_quality))
            progress(name, completed=True)
            return value if name == "clusters" else records
        except OzonClientError as exc:
            diagnostic = ImportDiagnostic(
                "error", f"OZON_{name.upper()}_FAILED",
                f"Ozon {name} request failed: {exc.code.value}.")
            diagnostics.append(diagnostic)
            api_error = OzonApiErrorEvidence(
                code=exc.code.value,
                endpoint=exc.endpoint,
                http_status=exc.status,
                vendor_code=exc.vendor_code,
                vendor_message=exc.vendor_message,
                request_id=exc.request_id,
                transport_kind=exc.transport_kind,
                attempts=exc.attempts,
                elapsed_ms=exc.elapsed_ms,
            )
            evidence.append(EndpointEvidence(
                name, started, 0, False, (diagnostic,), api_error,
            ))
            progress(name, completed=True)
            return default
        except Exception as exc:
            diagnostic = ImportDiagnostic(
                "error", f"OZON_{name.upper()}_FAILED",
                f"Ozon {name} evidence unavailable: {type(exc).__name__}")
            diagnostics.append(diagnostic)
            evidence.append(EndpointEvidence(name, started, 0, False, (diagnostic,)))
            progress(name, completed=True)
            return default

    def history_fetch(current_window):
        fbo = run("orders_fbo", lambda: call_with_progress(
            fetch_postings, client, FBO_POSTINGS_PATH, current_window.history_from,
            current_window.history_to, stage="orders_fbo"), ())
        fbs = run("orders_fbs", lambda: call_with_progress(
            fetch_postings, client, FBS_POSTINGS_PATH, current_window.history_from,
            current_window.history_to, stage="orders_fbs"), ())
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
    cluster_by_warehouse = {
        str(warehouse_id): cluster_by_id[macrolocal_id]
        for warehouse_id, macrolocal_id in warehouse_to_macrolocal.items()
        if macrolocal_id in cluster_by_id
    }
    product_skus = run("products", lambda: (
        call_with_progress(fetch_product_skus, client, stage="products"), ()), ())
    product_evidence = next(item for item in evidence if item.name == "products")
    if product_evidence.complete:
        fbo = run(
            "fbo_stock",
            lambda: call_with_progress(fetch_fbo_stock, client, product_skus,
                                       cluster_by_warehouse, stage="fbo_stock"),
            (),
        )
    else:
        fbo = ()
        if not product_evidence.complete:
            diagnostic = ImportDiagnostic("error", "OZON_FBO_STOCK_FAILED", "FBO stock unavailable without complete SKU universe.")
            diagnostics.append(diagnostic)
            evidence.append(EndpointEvidence("fbo_stock", datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))
            progress("fbo_stock", completed=True)
    if product_evidence.complete:
        seller_stock = run("seller_stock", lambda: call_with_progress(
            fetch_seller_stock, client, product_skus, stage="seller_stock"), ())
    else:
        seller_stock = ()
        diagnostic = ImportDiagnostic(
            "error", "OZON_SELLER_STOCK_FAILED",
            "Seller stock unavailable without complete SKU universe.")
        diagnostics.append(diagnostic)
        evidence.append(EndpointEvidence(
            "seller_stock", datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))
        progress("seller_stock", completed=True)
    inbound = run("inbound", lambda: call_with_progress(
        fetch_inbound, client, cluster_by_id, warehouse_to_macrolocal,
        stage="inbound"), ())
    if product_evidence.complete:
        zones = run("placement_zones", lambda: call_with_progress(
            fetch_placement_zones, client, product_skus, stage="placement_zones"), ())
    else:
        zones = ()
        diagnostic = ImportDiagnostic(
            "error", "OZON_PLACEMENT_ZONES_FAILED",
            "Placement-zone evidence unavailable because SKU universe is incomplete.")
        diagnostics.append(diagnostic)
        evidence.append(EndpointEvidence(
            "placement_zones", datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))
        progress("placement_zones", completed=True)

    # FBO is warehouse-grained while inbound is cluster-grained.  Preserve them
    # as independent evidence rows so downstream Need aggregation counts each
    # inbound quantity exactly once.
    availability = tuple(fbo) + tuple(inbound)
    return OzonSourceSnapshot(
        uuid4().hex, now.isoformat(), as_of, SOURCE_TIMEZONE, window.history_from,
        window.history_to, orders, availability, seller_stock, clusters,
        seller_warehouses, zones, tuple(evidence), tuple(diagnostics),
        credential_context_id)
