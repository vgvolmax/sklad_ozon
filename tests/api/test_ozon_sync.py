from dataclasses import asdict, replace
from datetime import date, timedelta

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.main import app
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_STOCK_PATH, PRODUCT_LIST_PATH
from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.adapters.catalog import ClusterCatalogResult
from backend.ozon.source_contracts import (
    Cluster, OzonRecordQualityEvidence, SellerWarehouse,
)
from backend.ozon.sync import capability_matrix, sync_ozon_source
from tests.ozon.test_source_store import snap


def _orders(as_of: date, weeks: int, *, include_new=False):
    week_start = as_of - timedelta(days=as_of.weekday())
    result = [OrderRecord("OLD", 1, "Москва", "Москва", OrderLifecycle.FULFILLED,
                          (week_start - timedelta(weeks=index)).isoformat())
              for index in range(1, weeks + 1)]
    if include_new:
        result.append(OrderRecord("NEW", 1, "Москва", "Москва", OrderLifecycle.FULFILLED,
                                  (week_start - timedelta(weeks=1)).isoformat()))
    return tuple(result)


def _patch_non_history(monkeypatch, *, fbo_failure=False, cluster_failure=False):
    import backend.ozon.sync as module

    def clusters(_client):
        if cluster_failure:
            raise RuntimeError("cluster unavailable")
        return ClusterCatalogResult((Cluster(10, "Москва"),), {501: 10}, ())

    monkeypatch.setattr(module, "fetch_clusters", clusters)
    monkeypatch.setattr(module, "fetch_seller_warehouses", lambda _client: (
        (SellerWarehouse(1, "Seller", None, True, False),), ()))
    if fbo_failure:
        monkeypatch.setattr(module, "fetch_fbo_stock", lambda *_args: (_ for _ in ()).throw(RuntimeError("fbo")))
    else:
        monkeypatch.setattr(module, "fetch_fbo_stock", lambda *_args: ((), ()))
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: ("OLD",))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client, _skus: (
        (AvailabilityRecord("OLD", "Seller", "", 3, fbs_quantity=3),), ()))
    monkeypatch.setattr(module, "fetch_inbound", lambda _client, _clusters, _mapping: ((), ()))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda *_args: ((), ()))


def test_registry_and_capability_matrix_excludes_handoff():
    assert FBS_STOCK_PATH.startswith("/v2/")
    matrix = capability_matrix(snap("x"))
    assert "handoff" not in matrix and matrix["ozon_comparison"]["complete"] is False


def test_sync_snapshot_carries_captured_credential_context(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda *_args: ((), ()))
    _patch_non_history(monkeypatch)

    source = sync_ozon_source(object(), credential_context_id="opaque-context-a")

    assert source.credential_context_id == "opaque-context-a"


def test_initial_twelve_window_with_eight_usable_weeks_fetches_once(monkeypatch):
    import backend.ozon.sync as module
    calls = []
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        calls.append((path, start)) or (_orders(end, 8) if path == FBO_POSTINGS_PATH else ()), ()))
    _patch_non_history(monkeypatch)
    sync_ozon_source(object())
    assert len(calls) == 2


def test_source_wide_six_weeks_backfills_four_then_stops_at_eight(monkeypatch):
    import backend.ozon.sync as module
    windows = []
    def postings(_client, path, start, end):
        if start not in windows:
            windows.append(start)
        weeks = 6 if len(windows) == 1 else 8
        return (_orders(end, weeks) if path == FBO_POSTINGS_PATH else ()), ()
    monkeypatch.setattr(module, "fetch_postings", postings)
    _patch_non_history(monkeypatch)
    source = sync_ozon_source(object())
    assert len(windows) == 2
    assert (source.history_to - source.history_from).days >= 16 * 7


def test_localized_order_quality_does_not_stop_backfill(monkeypatch):
    import backend.ozon.sync as module
    windows = []

    def postings(_client, path, start, end):
        if start not in windows:
            windows.append(start)
        weeks = 6 if len(windows) == 1 else 8
        records = _orders(end, weeks) if path == FBO_POSTINGS_PATH else ()
        quality = (OzonRecordQualityEvidence(1, ("SKU-B",))
                   if path == FBO_POSTINGS_PATH else OzonRecordQualityEvidence())
        diagnostics = ((ImportDiagnostic(
            "warning", "UNRESOLVED_DESTINATION_CLUSTER", "Scoped row gap."),)
                       if path == FBO_POSTINGS_PATH else ())
        return records, diagnostics, quality

    monkeypatch.setattr(module, "fetch_postings", postings)
    _patch_non_history(monkeypatch)
    source = sync_ozon_source(object())
    order_evidence = next(item for item in source.endpoint_evidence
                          if item.name == "orders_fbo")
    assert len(windows) == 2
    assert order_evidence.complete is True
    assert order_evidence.record_quality == OzonRecordQualityEvidence(1, ("SKU-B",))
    assert capability_matrix(source)["demand_flow"]["complete"] is True


def test_missing_postings_marks_order_endpoints_globally_incomplete(monkeypatch):
    class CorruptedOrdersClient:
        def post_json(self, *_args, **_kwargs):
            return {"result": {}}

    _patch_non_history(monkeypatch)
    source = sync_ozon_source(CorruptedOrdersClient())
    order_evidence = {
        item.name: item for item in source.endpoint_evidence
        if item.name in {"orders_fbo", "orders_fbs"}
    }

    assert order_evidence["orders_fbo"].complete is False
    assert order_evidence["orders_fbs"].complete is False
    prepared = api_module._api_prepared_inputs(source)
    assert prepared.source_coverage.demand_complete_for("SKU-A") is False
    assert prepared.source_coverage.demand_complete_for("SKU-B") is False


def test_localized_inbound_quality_is_preserved_without_global_failure(monkeypatch):
    import backend.ozon.sync as module

    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    warning = ImportDiagnostic(
        "warning", "REPORT_REJECTED_SUPPLY_STATE", "Scoped inbound gap.")
    monkeypatch.setattr(module, "fetch_inbound", lambda *_args: (
        (), (warning,), OzonRecordQualityEvidence(1, ("SKU-B",))))

    source = sync_ozon_source(object())
    inbound_evidence = next(
        item for item in source.endpoint_evidence if item.name == "inbound")
    assert inbound_evidence.complete is True
    assert inbound_evidence.record_quality == OzonRecordQualityEvidence(
        1, ("SKU-B",))
    assert capability_matrix(source)["need_inbound"]["complete"] is True


def test_missing_supply_bundle_items_makes_inbound_globally_incomplete(monkeypatch):
    import backend.ozon.sync as module

    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    error = ImportDiagnostic(
        "error", "MISSING_SUPPLY_BUNDLE_ITEMS",
        "Supply order 7 has no bundle item evidence.")
    monkeypatch.setattr(module, "fetch_inbound", lambda *_args: (
        (), (error,), OzonRecordQualityEvidence()))

    source = sync_ozon_source(object())
    inbound = next(
        item for item in source.endpoint_evidence if item.name == "inbound")

    assert inbound.complete is False
    assert inbound.record_quality == OzonRecordQualityEvidence()
    assert capability_matrix(source)["need_inbound"]["complete"] is False


def test_global_order_error_stops_backfill(monkeypatch):
    import backend.ozon.sync as module
    calls = []

    def postings(_client, path, start, end):
        calls.append((path, start))
        diagnostic = ImportDiagnostic(
            "error", "NON_PROGRESSING_POSTINGS_CURSOR", "Cursor did not progress.")
        return (), (diagnostic,), OzonRecordQualityEvidence()

    monkeypatch.setattr(module, "fetch_postings", postings)
    _patch_non_history(monkeypatch)
    source = sync_ozon_source(object())
    assert len(calls) == 2
    assert capability_matrix(source)["demand_flow"]["complete"] is False


def test_backfill_never_exceeds_fifty_two_weeks(monkeypatch):
    import backend.ozon.sync as module
    calls = []
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (calls.append(start) or (), ()))
    _patch_non_history(monkeypatch)
    source = sync_ozon_source(object())
    assert (source.history_to - source.history_from).days <= 53 * 7
    assert len(set(calls)) == 11


def test_one_new_sku_does_not_trigger_per_sku_backfill(monkeypatch):
    import backend.ozon.sync as module
    calls = []
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        calls.append(path) or (_orders(end, 8, include_new=True) if path == FBO_POSTINGS_PATH else ()), ()))
    _patch_non_history(monkeypatch)
    sync_ozon_source(object())
    assert len(calls) == 2


def test_fbo_and_seller_stock_failures_are_isolated(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch, fbo_failure=True)
    matrix = capability_matrix(sync_ozon_source(object()))
    assert matrix["need_fbo"]["complete"] is False
    assert matrix["operational_allocation"]["complete"] is True


def test_sync_preserves_structured_ozon_api_error_evidence(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client, _skus: (_ for _ in ()).throw(
        OzonClientError(
            OzonErrorCode.PERMISSION_DENIED,
            "Ozon API denied access to endpoint",
            endpoint=FBS_STOCK_PATH,
            status=403,
            vendor_code="PERMISSION_DENIED",
            vendor_message="Access denied",
            request_id="trace-403",
        )))

    source = sync_ozon_source(object())
    evidence = next(item for item in source.endpoint_evidence if item.name == "seller_stock")

    assert evidence.complete is False
    assert evidence.record_count == 0
    assert evidence.api_error.code == "OZON_PERMISSION_DENIED"
    assert evidence.api_error.endpoint == FBS_STOCK_PATH
    assert evidence.api_error.http_status == 403
    assert evidence.api_error.vendor_code == "PERMISSION_DENIED"
    assert evidence.api_error.vendor_message == "Access denied"
    assert evidence.api_error.request_id == "trace-403"
    assert capability_matrix(source)["operational_allocation"]["complete"] is False
    serialized = repr(asdict(evidence))
    assert "Client-Id" not in serialized
    assert "Api-Key" not in serialized
    assert "details" not in serialized


def test_sync_preserves_only_normalized_transport_evidence(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    monkeypatch.setattr(module, "fetch_seller_stock", lambda *_args: (_ for _ in ()).throw(
        OzonClientError(OzonErrorCode.UNAVAILABLE, "safe", endpoint=FBS_STOCK_PATH,
                        transport_kind="timeout", attempts=3, elapsed_ms=46001)))

    source = sync_ozon_source(object())
    error = next(item.api_error for item in source.endpoint_evidence
                 if item.name == "seller_stock")
    assert (error.transport_kind, error.attempts, error.elapsed_ms) == (
        "timeout", 3, 46001)
    assert "sensitive" not in repr(asdict(source))


def test_generic_sync_exception_has_no_ozon_api_error(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client, _skus: (_ for _ in ()).throw(
        RuntimeError("boom")))

    source = sync_ozon_source(object())
    evidence = next(item for item in source.endpoint_evidence if item.name == "seller_stock")
    assert evidence.complete is False
    assert evidence.api_error is None


def test_cluster_and_seller_warehouse_failures_are_isolated(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch, cluster_failure=True)
    matrix = capability_matrix(sync_ozon_source(object()))
    assert matrix["cluster_identity"]["complete"] is False
    assert matrix["seller_warehouse_selection"]["complete"] is True


def test_optional_capability_failure_is_not_reported_complete():
    source = snap("x")
    source = source.__class__(
        source.source_snapshot_id, source.synced_at_utc, source.source_as_of, source.source_timezone,
        source.history_from, source.history_to, source.orders, source.availability,
        source.operational_seller_stock, source.clusters, source.seller_warehouses,
        source.placement_zones,
        tuple(item for item in source.endpoint_evidence if item.name != "seller_warehouses"),
        source.diagnostics)
    capability = capability_matrix(source)["seller_warehouse_selection"]
    assert capability == {"complete": False, "required": False, "affects": "crossdock_selection"}


def test_product_list_failure_makes_fbo_stock_incomplete(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: (_ for _ in ()).throw(RuntimeError("products")))
    source = sync_ozon_source(object())
    assert capability_matrix(source)["need_fbo"]["complete"] is False
    assert not any(item.name == "fbo_stock" and item.complete for item in source.endpoint_evidence)


def test_product_list_failure_skips_dependent_stock_and_placement(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    dependent_calls = []
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: (_ for _ in ()).throw(RuntimeError("products")))
    monkeypatch.setattr(module, "fetch_fbo_stock", lambda *_args: dependent_calls.append("fbo"))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda *_args: dependent_calls.append("seller"))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda *_args: dependent_calls.append("zones"))

    source = sync_ozon_source(object())

    assert dependent_calls == []
    assert capability_matrix(source)["need_fbo"]["complete"] is False
    assert capability_matrix(source)["operational_allocation"]["complete"] is False
    assert capability_matrix(source)["shipment_compatibility"]["complete"] is False
    evidence = {item.name: item for item in source.endpoint_evidence}
    assert evidence["products"].complete is False
    assert evidence["seller_stock"].complete is False
    assert evidence["seller_stock"].diagnostics[0].code == "OZON_SELLER_STOCK_FAILED"


def test_known_empty_product_universe_allows_complete_empty_dependencies(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: ())
    monkeypatch.setattr(module, "fetch_fbo_stock", lambda _client, skus, mapping: (
        calls.append(("fbo", skus, mapping)) or (), ()))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client, skus: (calls.append(("seller", skus)) or (), ()))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda _client, skus: (calls.append(("zones", skus)) or (), ()))

    source = sync_ozon_source(object())

    assert calls == [("fbo", (), {"501": "Москва"}), ("seller", ()), ("zones", ())]
    assert capability_matrix(source)["need_fbo"]["complete"] is True
    assert capability_matrix(source)["operational_allocation"]["complete"] is True
    assert capability_matrix(source)["shipment_compatibility"]["complete"] is True


def test_seller_stock_receives_canonical_product_universe(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: ("OLD", "NEW"))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client, skus: (calls.append(skus) or (), ()))

    sync_ozon_source(object())

    assert calls == [("OLD", "NEW")]


def test_malformed_product_list_sku_blocks_dependent_capabilities(monkeypatch):
    import backend.ozon.sync as module
    from backend.ozon.adapters.products import fetch_product_skus

    class Client:
        def post_json(self, path, payload, **_kwargs):
            assert path == PRODUCT_LIST_PATH
            return {"result": {"items": [{}], "total": 1, "last_id": "terminal"}}

    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    dependent_calls = []
    monkeypatch.setattr(module, "fetch_product_skus", fetch_product_skus)
    monkeypatch.setattr(module, "fetch_fbo_stock", lambda *_args: dependent_calls.append("fbo"))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda *_args: dependent_calls.append("seller"))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda *_args: dependent_calls.append("zones"))

    source = sync_ozon_source(Client())
    evidence = {item.name: item for item in source.endpoint_evidence}

    assert dependent_calls == []
    assert evidence["products"].complete is False
    assert evidence["fbo_stock"].complete is False
    assert evidence["seller_stock"].complete is False
    assert evidence["placement_zones"].complete is False
    assert capability_matrix(source)["need_fbo"]["complete"] is False
    assert capability_matrix(source)["operational_allocation"]["complete"] is False
    assert capability_matrix(source)["shipment_compatibility"]["complete"] is False


def test_partial_sync_response_does_not_evict_or_mask_last_healthy_source(monkeypatch):
    context_id = api_module.OZON_VAULT.credential_context_id()
    healthy = replace(snap("healthy-source"), credential_context_id=context_id)
    api_module.OZON_SOURCE_STORE.put(healthy)
    attempts = iter(range(1, 5))

    def partial_sync(_client, *, credential_context_id):
        number = next(attempts)
        diagnostic = ImportDiagnostic(
            "error",
            "OZON_FBO_STOCK_FAILED",
            "Ozon fbo_stock evidence unavailable: RuntimeError",
        )
        return replace(
            snap(f"partial-source-{number}", healthy=False),
            diagnostics=(diagnostic,),
            credential_context_id=credential_context_id,
        )

    monkeypatch.setattr(api_module, "sync_ozon_source", partial_sync)
    client = TestClient(app)
    responses = [client.post("/api/ozon/sync") for _ in range(4)]

    assert all(response.status_code == 200 for response in responses)
    latest = responses[-1].json()
    assert latest["source"]["source_snapshot_id"] == "partial-source-4"
    assert latest["source"]["endpoint_evidence"][0]["complete"] is False
    assert latest["source"]["diagnostics"][0]["code"] == "OZON_FBO_STOCK_FAILED"
    assert api_module.OZON_SOURCE_STORE.get("healthy-source") is not None
    assert api_module.OZON_SOURCE_STORE.last_healthy() == healthy
    assert len(api_module.OZON_SOURCE_STORE) == 3
