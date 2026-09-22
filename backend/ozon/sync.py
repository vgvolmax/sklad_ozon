"""Causal orchestration for one immutable API source snapshot."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import inspect
from uuid import uuid4

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle
from backend.ozon.client import OzonClientError
from backend.ozon.adapters.catalog import fetch_clusters, fetch_seller_warehouses
from backend.ozon.adapters.inbound import fetch_inbound
from backend.ozon.adapters.orders import fetch_postings
from backend.ozon.adapters.placement_zones import fetch_placement_zones
from backend.ozon.adapters.products import ProductCatalogItem, fetch_product_catalog, fetch_product_skus
from backend.ozon.adapters.product_facts import (
    fetch_product_attributes, fetch_product_prices, merge_product_facts,
)
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
    ("product_prices", "Цены и комиссии", "Получение цен и комиссий"),
    ("product_attributes", "Габариты товаров", "Получение габаритов товаров"),
    ("fbo_stock", "FBO остатки", "Получение остатков FBO"),
    ("seller_stock", "Остаток продавца", "Получение остатков продавца"),
    ("inbound", "Поставки в пути", "Поиск заявок"),
    ("placement_zones", "Зоны размещения", "Получение зон размещения"),
)
CLUSTERS_TTL = timedelta(hours=24)
SELLER_WAREHOUSES_TTL = timedelta(hours=24)
PRODUCT_ATTRIBUTES_TTL = timedelta(days=7)
PLACEMENT_ZONES_TTL = timedelta(hours=24)
ORDER_REFRESH_OVERLAP_DAYS = 28


@dataclass(frozen=True, slots=True)
class OzonRefreshReport:
    requested_mode: str
    effective_mode: str
    base_source_snapshot_id: str | None
    refreshed_endpoints: tuple[str, ...]
    reused_endpoints: tuple[str, ...]
    failed_endpoints: tuple[str, ...]
    history_refresh_from: date | None
    activated: bool = True
_DEFAULT_FETCH_PRODUCT_SKUS = fetch_product_skus
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
        "product_parameters": cap(("products", "product_prices", "product_attributes"), "product_economics"),
        "ozon_comparison": {"complete": False, "required": False, "affects": "safe_comparison"},
        "shipment_compatibility": cap("placement_zones", "shipment_compatibility", False),
    }


def endpoint_quality(evidence: EndpointEvidence | None) -> int:
    """Rank completeness without treating volatile record counts as quality."""
    if evidence is None or not evidence.complete:
        return 0
    quality = evidence.record_quality
    if quality is not None and (quality.rejected_record_count > 0 or quality.incomplete_skus):
        return 1
    return 2


def source_refresh_regresses(base: OzonSourceSnapshot,
                             candidate: OzonSourceSnapshot) -> bool:
    """Return true when a candidate loses any previously established evidence."""
    candidate_evidence = _evidence_map(candidate)
    return any(
        endpoint_quality(candidate_evidence.get(name)) < endpoint_quality(old)
        for name, old in _evidence_map(base).items()
    )


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
            elif name in {"orders_fbo", "orders_fbs", "inbound", "fbo_stock", "seller_stock", "placement_zones", "product_prices", "product_attributes"}:
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

    def blocked_dependency(name, message):
        diagnostic = ImportDiagnostic(
            "error", f"OZON_{name.upper()}_FAILED", message)
        diagnostics.append(diagnostic)
        evidence.append(EndpointEvidence(
            name, datetime.now(timezone.utc).isoformat(), 0, False, (diagnostic,)))
        progress(name, completed=True)

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
    clusters_complete = next(item for item in evidence if item.name == "clusters").complete
    seller_warehouses = run("seller_warehouses", lambda: fetch_seller_warehouses(client), ())
    cluster_by_id = {cluster.cluster_id: cluster.name for cluster in clusters}
    cluster_by_warehouse = {
        str(warehouse_id): cluster_by_id[macrolocal_id]
        for warehouse_id, macrolocal_id in warehouse_to_macrolocal.items()
        if macrolocal_id in cluster_by_id
    }
    # The compatibility branch is only for injected legacy adapter doubles.
    # Production always performs the single identity-preserving catalog request.
    catalog_fetch = (lambda: tuple(ProductCatalogItem(sku, index, sku) for index, sku in enumerate(fetch_product_skus(client), 1))) if fetch_product_skus is not _DEFAULT_FETCH_PRODUCT_SKUS else (lambda: call_with_progress(fetch_product_catalog, client, stage="products"))
    catalog = run("products", lambda: (catalog_fetch(), ()), ())
    product_skus = tuple(item.sku for item in catalog)
    product_evidence = next(item for item in evidence if item.name == "products")
    if product_evidence.complete:
        prices = run("product_prices", lambda: call_with_progress(
            fetch_product_prices, client, catalog, stage="product_prices"), ())
        attributes = run("product_attributes", lambda: call_with_progress(
            fetch_product_attributes, client, catalog, stage="product_attributes"), ())
    else:
        prices = attributes = ()
        for name, message in (
            ("product_prices", "Product prices unavailable without complete product catalog."),
            ("product_attributes", "Product attributes unavailable without complete product catalog."),
        ):
            blocked_dependency(name, message)
    product_facts = merge_product_facts(catalog, prices, attributes)
    if product_evidence.complete and clusters_complete:
        fbo = run(
            "fbo_stock",
            lambda: call_with_progress(fetch_fbo_stock, client, product_skus,
                                       cluster_by_warehouse, stage="fbo_stock"),
            (),
        )
    else:
        fbo = ()
        message = ("FBO stock unavailable without complete SKU universe."
                   if not product_evidence.complete else
                   "FBO stock unavailable without complete cluster/warehouse mapping.")
        blocked_dependency("fbo_stock", message)
    if product_evidence.complete:
        seller_stock = run("seller_stock", lambda: call_with_progress(
            fetch_seller_stock, client, product_skus, stage="seller_stock"), ())
    else:
        seller_stock = ()
        blocked_dependency(
            "seller_stock", "Seller stock unavailable without complete SKU universe.")
    if clusters_complete:
        inbound = run("inbound", lambda: call_with_progress(
            fetch_inbound, client, cluster_by_id, warehouse_to_macrolocal,
            stage="inbound"), ())
    else:
        inbound = ()
        blocked_dependency(
            "inbound", "Inbound unavailable without complete cluster/warehouse mapping.")
    if product_evidence.complete:
        zones = run("placement_zones", lambda: call_with_progress(
            fetch_placement_zones, client, product_skus, stage="placement_zones"), ())
    else:
        zones = ()
        blocked_dependency(
            "placement_zones",
            "Placement-zone evidence unavailable because SKU universe is incomplete.")

    # FBO is warehouse-grained while inbound is cluster-grained.  Preserve them
    # as independent evidence rows so downstream Need aggregation counts each
    # inbound quantity exactly once.
    availability = tuple(fbo) + tuple(inbound)
    return OzonSourceSnapshot(
        uuid4().hex, now.isoformat(), as_of, SOURCE_TIMEZONE, window.history_from,
        window.history_to, orders, availability, seller_stock, clusters,
        seller_warehouses, zones, tuple(evidence), tuple(diagnostics),
        credential_context_id, product_facts,
        tuple(sorted(warehouse_to_macrolocal.items())))


def _evidence_map(snapshot):
    return {item.name: item for item in snapshot.endpoint_evidence}


def _fresh_complete(evidence, now, ttl):
    if evidence is None or not evidence.complete:
        return False
    try:
        fetched = datetime.fromisoformat(evidence.fetched_at_utc)
        if fetched.tzinfo is None:
            return False
    except (TypeError, ValueError):
        return False
    return now - fetched.astimezone(timezone.utc) <= ttl


def _catalog_identity(facts):
    return tuple(sorted((row.sku, row.product_id, row.article) for row in facts))


def _order_day(row):
    try:
        return date.fromisoformat(str(row.accepted_at)[:10])
    except ValueError:
        return date.min


def refresh_ozon_source(client, *, mode="smart", base_snapshot=None,
                        credential_context_id=None, progress_callback=None,
                        now=None):
    """Refresh a source, reusing only explicit fresh and complete evidence."""
    if mode not in {"smart", "full"}:
        raise ValueError("mode must be smart or full")
    requested = mode
    if mode == "full" or base_snapshot is None:
        snapshot = sync_ozon_source(client, credential_context_id=credential_context_id,
                                    progress_callback=progress_callback)
        failed = tuple(x.name for x in snapshot.endpoint_evidence if not x.complete)
        return snapshot, OzonRefreshReport(
            requested, "full", getattr(base_snapshot, "source_snapshot_id", None),
            tuple(x.name for x in snapshot.endpoint_evidence), (), failed, None)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    as_of = source_business_date(current)
    old_evidence = _evidence_map(base_snapshot)
    evidence = []
    diagnostics = []
    refreshed = []
    reused = []

    def progress(name, *, reused_stage=False, **values):
        if not progress_callback:
            return
        index, label, detail = _STAGE_BY_NAME[name]
        progress_callback({"type": "progress", "stage": name, "stage_index": index,
                           "stage_count": len(SYNC_STAGES), "label": label,
                           "detail": "Используем сохранённые данные" if reused_stage else values.get("detail", detail),
                           "current": values.get("current"), "total": values.get("total"),
                           "unit": values.get("unit"), "completed": values.get("completed", False),
                           "reused": reused_stage})

    def call(function, *args, stage):
        try:
            supports = "progress_callback" in inspect.signature(function).parameters
        except (TypeError, ValueError):
            supports = False
        callback = lambda **kw: progress(stage, **kw)
        return function(*args, progress_callback=callback) if supports else function(*args)

    def run(name, function, default):
        progress(name)
        started = current.isoformat()
        refreshed.append(name)
        try:
            value = function()
            quality = None
            if name == "clusters":
                records, item_diagnostics = value.clusters, value.diagnostics
            elif name in {"orders_fbo", "orders_fbs", "inbound", "fbo_stock", "seller_stock", "placement_zones", "product_prices", "product_attributes"}:
                if len(value) == 3:
                    records, item_diagnostics, quality = value
                else:
                    records, item_diagnostics = value
                    quality = OzonRecordQualityEvidence()
            else:
                records, item_diagnostics = value
            diagnostics.extend(item_diagnostics)
            complete = not any(x.severity == "error" for x in item_diagnostics)
            evidence.append(EndpointEvidence(name, started, len(records), complete,
                                             tuple(item_diagnostics), record_quality=quality))
            progress(name, completed=True)
            return value if name == "clusters" else tuple(records)
        except Exception as exc:
            diagnostic = ImportDiagnostic("error", f"OZON_{name.upper()}_FAILED",
                                          f"Ozon {name} evidence unavailable: {type(exc).__name__}")
            diagnostics.append(diagnostic)
            api_error = None
            if isinstance(exc, OzonClientError):
                api_error = OzonApiErrorEvidence(exc.code.value, exc.endpoint, exc.status,
                    exc.vendor_code, exc.vendor_message, exc.request_id, exc.transport_kind,
                    exc.attempts, exc.elapsed_ms)
            evidence.append(EndpointEvidence(name, started, 0, False, (diagnostic,), api_error))
            progress(name, completed=True)
            return default

    def reuse(name):
        reused.append(name)
        evidence.append(old_evidence[name])
        progress(name, reused_stage=True, completed=True)

    def blocked_dependency(name, message):
        diagnostic = ImportDiagnostic(
            "error", f"OZON_{name.upper()}_FAILED", message)
        diagnostics.append(diagnostic)
        evidence.append(EndpointEvidence(
            name, current.isoformat(), 0, False, (diagnostic,)))
        refreshed.append(name)
        progress(name, completed=True)

    delta_from = base_snapshot.history_to - timedelta(days=ORDER_REFRESH_OVERLAP_DAYS)
    fresh_orders = []
    channel_starts = {}
    for name, path, channel in (("orders_fbo", FBO_POSTINGS_PATH, "fbo"),
                                ("orders_fbs", FBS_POSTINGS_PATH, "fbs")):
        old = old_evidence.get(name)
        quality = old.record_quality if old else None
        unsafe = (old is None or not old.complete or
                  quality is not None and (quality.rejected_record_count > 0 or quality.incomplete_skus))
        start = base_snapshot.history_from if unsafe else delta_from
        channel_starts[channel] = start
        rows = run(name, lambda p=path, start=start: call(fetch_postings, client, p, start, as_of, stage=name), ())
        fresh_orders.extend(rows)
        if unsafe:
            # This channel is a complete replacement; the other channel may still use a delta.
            continue
    orders = tuple(row for row in base_snapshot.orders
                   if row.source_channel in channel_starts
                   and _order_day(row) < channel_starts[row.source_channel]) + tuple(fresh_orders)

    if _fresh_complete(old_evidence.get("clusters"), current, CLUSTERS_TTL):
        reuse("clusters")
        clusters = base_snapshot.clusters
        warehouse_to_macrolocal = dict(base_snapshot.warehouse_to_macrolocal)
    else:
        result = run("clusters", lambda: fetch_clusters(client), None)
        clusters = result.clusters if result else ()
        warehouse_to_macrolocal = result.warehouse_to_macrolocal if result else {}
    clusters_complete = next(item for item in evidence if item.name == "clusters").complete
    if _fresh_complete(old_evidence.get("seller_warehouses"), current, SELLER_WAREHOUSES_TTL):
        reuse("seller_warehouses"); seller_warehouses = base_snapshot.seller_warehouses
    else:
        seller_warehouses = run("seller_warehouses", lambda: fetch_seller_warehouses(client), ())

    catalog = run("products", lambda: (call(fetch_product_catalog, client, stage="products"), ()), ())
    product_skus = tuple(x.sku for x in catalog)
    product_evidence = next(item for item in evidence if item.name == "products")
    catalog_changed = _catalog_identity(base_snapshot.product_facts) != tuple(sorted((x.sku, x.product_id, x.offer_id) for x in catalog))
    if product_evidence.complete:
        prices = run("product_prices", lambda: call(fetch_product_prices, client, catalog, stage="product_prices"), ())
        reuse_attributes = (not catalog_changed and
                            _fresh_complete(old_evidence.get("product_attributes"), current, PRODUCT_ATTRIBUTES_TTL))
        if reuse_attributes:
            reuse("product_attributes")
            attributes = tuple(row for row in base_snapshot.product_facts if row.volume_liters is not None)
        else:
            attributes = run("product_attributes", lambda: call(fetch_product_attributes, client, catalog, stage="product_attributes"), ())
    else:
        prices = attributes = ()
        blocked_dependency("product_prices", "Product prices unavailable without complete product catalog.")
        blocked_dependency("product_attributes", "Product attributes unavailable without complete product catalog.")
    product_facts = merge_product_facts(catalog, prices, attributes)
    cluster_by_id = {row.cluster_id: row.name for row in clusters}
    cluster_by_warehouse = {str(k): cluster_by_id[v] for k, v in warehouse_to_macrolocal.items() if v in cluster_by_id}
    if product_evidence.complete and clusters_complete:
        fbo = run("fbo_stock", lambda: call(fetch_fbo_stock, client, product_skus, cluster_by_warehouse, stage="fbo_stock"), ())
    else:
        fbo = ()
        blocked_dependency("fbo_stock", "FBO stock unavailable without complete product and cluster/warehouse evidence.")
    if product_evidence.complete:
        seller_stock = run("seller_stock", lambda: call(fetch_seller_stock, client, product_skus, stage="seller_stock"), ())
    else:
        seller_stock = ()
        blocked_dependency("seller_stock", "Seller stock unavailable without complete product catalog.")
    if clusters_complete:
        inbound = run("inbound", lambda: call(fetch_inbound, client, cluster_by_id, warehouse_to_macrolocal, stage="inbound"), ())
    else:
        inbound = ()
        blocked_dependency("inbound", "Inbound unavailable without complete cluster/warehouse mapping.")
    reuse_zones = (not catalog_changed and
                   _fresh_complete(old_evidence.get("placement_zones"), current, PLACEMENT_ZONES_TTL))
    if not product_evidence.complete:
        zones = ()
        blocked_dependency("placement_zones", "Placement-zone evidence unavailable without complete product catalog.")
    elif reuse_zones:
        reuse("placement_zones"); zones = base_snapshot.placement_zones
    else:
        zones = run("placement_zones", lambda: call(fetch_placement_zones, client, product_skus, stage="placement_zones"), ())

    candidate = OzonSourceSnapshot(
        uuid4().hex, current.isoformat(), as_of, SOURCE_TIMEZONE,
        base_snapshot.history_from, as_of, orders, tuple(fbo) + tuple(inbound),
        seller_stock, clusters, seller_warehouses, zones, tuple(evidence),
        tuple(diagnostics), credential_context_id, product_facts,
        tuple(sorted(warehouse_to_macrolocal.items())))
    failed = tuple(x.name for x in evidence if not x.complete)
    return candidate, OzonRefreshReport(requested, "smart", base_snapshot.source_snapshot_id,
        tuple(refreshed), tuple(reused), failed, delta_from)
