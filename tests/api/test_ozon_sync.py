from datetime import date, timedelta

from backend.domain.contracts import OrderLifecycle, OrderRecord
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_STOCK_PATH
from backend.ozon.adapters.catalog import ClusterCatalogResult
from backend.ozon.source_contracts import Cluster, SellerWarehouse
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
        monkeypatch.setattr(module, "fetch_fbo_stock", lambda _client, _skus: (_ for _ in ()).throw(RuntimeError("fbo")))
    else:
        monkeypatch.setattr(module, "fetch_fbo_stock", lambda _client, _skus: ((), ()))
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: ("OLD",))
    monkeypatch.setattr(module, "fetch_seller_stock", lambda _client: (
        (AvailabilityRecord("OLD", "Seller", "", 3, fbs_quantity=3),), ()))
    monkeypatch.setattr(module, "fetch_inbound", lambda _client, _clusters, _mapping: ((), ()))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda _client, _skus: ((), ()))


def test_registry_and_capability_matrix_excludes_handoff():
    assert FBS_STOCK_PATH.startswith("/v2/")
    matrix = capability_matrix(snap("x"))
    assert "handoff" not in matrix and matrix["ozon_comparison"]["complete"] is False


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
    monkeypatch.setattr(module, "fetch_placement_zones", lambda *_args: dependent_calls.append("zones"))

    source = sync_ozon_source(object())

    assert dependent_calls == []
    assert capability_matrix(source)["need_fbo"]["complete"] is False
    assert capability_matrix(source)["shipment_compatibility"]["complete"] is False


def test_known_empty_product_universe_allows_complete_empty_dependencies(monkeypatch):
    import backend.ozon.sync as module
    monkeypatch.setattr(module, "fetch_postings", lambda _client, path, start, end: (
        _orders(end, 8) if path == FBO_POSTINGS_PATH else (), ()))
    _patch_non_history(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "fetch_product_skus", lambda _client: ())
    monkeypatch.setattr(module, "fetch_fbo_stock", lambda _client, skus: (calls.append(("fbo", skus)) or (), ()))
    monkeypatch.setattr(module, "fetch_placement_zones", lambda _client, skus: (calls.append(("zones", skus)) or (), ()))

    source = sync_ozon_source(object())

    assert calls == [("fbo", ()), ("zones", ())]
    assert capability_matrix(source)["need_fbo"]["complete"] is True
    assert capability_matrix(source)["shipment_compatibility"]["complete"] is True
