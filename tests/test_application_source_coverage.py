from decimal import Decimal

import backend.api as api_module
import backend.ozon.sync as sync_module
from backend.application import aggregate_api_need_availability
from backend.decision.need import calculate_need
from backend.domain.contracts import AnalysisSourceCoverage
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.adapters.catalog import ClusterCatalogResult
from backend.ozon.endpoints import (
    FBO_POSTINGS_PATH,
    SUPPLY_ORDER_BUNDLE_PATH,
    SUPPLY_ORDER_GET_PATH,
    SUPPLY_ORDER_LIST_PATH,
)
from backend.ozon.source_contracts import Cluster, SellerWarehouse
from backend.ozon.sync import sync_ozon_source


def coverage(*, fbo=True, inbound=True):
    return AnalysisSourceCoverage(True, True, fbo, inbound)


def test_demand_completeness_can_be_scoped_to_sku():
    scoped = AnalysisSourceCoverage(
        True, True, True, True, demand_incomplete_skus=("SKU-B",))
    assert scoped.demand_complete is True
    assert scoped.demand_complete_for("SKU-A") is True
    assert scoped.demand_complete_for("SKU-B") is False

    globally_failed = AnalysisSourceCoverage(
        False, True, True, True, demand_incomplete_skus=("SKU-B",))
    assert globally_failed.demand_complete_for("SKU-A") is False
    assert globally_failed.demand_complete_for("SKU-B") is False


def test_inbound_completeness_can_be_scoped_to_sku():
    scoped = AnalysisSourceCoverage(
        True, True, True, True, inbound_incomplete_skus=("SKU-B",))
    assert scoped.inbound_complete_for("SKU-A") is True
    assert scoped.inbound_complete_for("SKU-B") is False

    globally_failed = AnalysisSourceCoverage(
        True, True, True, False, inbound_incomplete_skus=("SKU-B",))
    assert globally_failed.inbound_complete_for("SKU-A") is False
    assert globally_failed.inbound_complete_for("SKU-B") is False


def row(warehouse, fbo_quantity=None, inbound_quantity=None):
    return AvailabilityRecord(
        "SKU", warehouse, "Москва", 0, None,
        fbo_quantity=fbo_quantity, inbound_quantity=inbound_quantity)


def test_cluster_inbound_is_counted_once_for_one_two_and_three_fbo_warehouses():
    for fbo_quantities in ((10,), (5, 5), (2, 3, 5)):
        records = tuple(row(f"W{index}", quantity) for index, quantity in enumerate(fbo_quantities))
        records += (row("Москва", inbound_quantity=3),)
        assert aggregate_api_need_availability(records, coverage(), sku="SKU") == (10, 3)


def test_complete_empty_inbound_is_zero_but_incomplete_empty_inbound_is_unknown():
    records = (row("W", 10),)
    assert aggregate_api_need_availability(records, coverage(inbound=True), sku="SKU") == (10, 0)
    assert aggregate_api_need_availability(records, coverage(inbound=False), sku="SKU") == (10, None)


def test_incomplete_empty_fbo_is_unknown_not_zero():
    assert aggregate_api_need_availability((), coverage(fbo=False), sku="SKU") == (None, 0)


def test_partial_rows_do_not_make_an_incomplete_endpoint_complete():
    records = (row("W", 10), row("Москва", inbound_quantity=4))
    assert aggregate_api_need_availability(records, coverage(fbo=False), sku="SKU") == (None, 4)
    assert aggregate_api_need_availability(records, coverage(inbound=False), sku="SKU") == (10, None)


def test_scoped_inbound_gap_overrides_partial_numeric_observation():
    records = (row("W", 10), row("Москва", inbound_quantity=4))
    scoped = AnalysisSourceCoverage(
        True, True, True, True, inbound_incomplete_skus=("SKU-A",))
    assert aggregate_api_need_availability(records, scoped, sku="SKU-A") == (10, None)
    assert aggregate_api_need_availability(records, scoped, sku="SKU-B") == (10, 4)


def _need(sku, source_coverage):
    return calculate_need(
        sku=sku,
        destination_cluster_id="Москва",
        weekly_rate=Decimal("7"),
        horizon_days=14,
        fbo_stock=3,
        inbound_qty=1,
        include_inbound=True,
        ozon_recommended_qty=10,
        ozon_horizon_days=14,
        demand_source_complete=source_coverage.demand_complete_for(sku),
    )


def test_scoped_order_corruption_blocks_only_affected_sku_need():
    source_coverage = AnalysisSourceCoverage(
        True, True, True, True, demand_incomplete_skus=("SKU-B",))

    assert _need("SKU-A", source_coverage).calculated_need_qty == 10
    assert _need("SKU-B", source_coverage).calculated_need_qty is None


def test_global_order_corruption_blocks_need_for_every_sku():
    source_coverage = AnalysisSourceCoverage(False, True, True, True)

    for sku in ("SKU-A", "SKU-B", "SKU-C"):
        need = _need(sku, source_coverage)
        assert need.calculated_need_qty is None
        assert "INCOMPLETE_DEMAND_SOURCE" in need.blocker_codes


def test_scoped_wire_corruption_propagates_adapter_snapshot_coverage_and_need(monkeypatch):
    class ScopedOrdersClient:
        def post_json(self, path, _payload, **_kwargs):
            if path == FBO_POSTINGS_PATH:
                return {"result": {
                    "postings": [{
                        "posting_number": "P-1",
                        "status": "delivered",
                        "in_process_at": "2026-09-01T10:00:00Z",
                        "financial_data": {"cluster_from": "Казань", "cluster_to": "Москва"},
                        "analytics_data": {"warehouse_name": "W-1"},
                        "products": [
                            {"sku": "SKU-A", "quantity": 2, "price": "100"},
                            {"sku": "SKU-B", "quantity": None, "price": "100"},
                        ],
                    }],
                    "has_next": False,
                    "cursor": "",
                }}
            return {"result": {"postings": [], "has_next": False, "cursor": ""}}

    monkeypatch.setattr(sync_module, "next_backfill", lambda _window: None)
    monkeypatch.setattr(sync_module, "fetch_clusters", lambda _client: ClusterCatalogResult(
        (Cluster(10, "Москва"),), {501: 10}, ()))
    monkeypatch.setattr(sync_module, "fetch_seller_warehouses", lambda _client: (
        (SellerWarehouse(1, "Seller", None, True, False),), ()))
    monkeypatch.setattr(sync_module, "fetch_product_skus", lambda _client: ("SKU-A", "SKU-B"))
    monkeypatch.setattr(sync_module, "fetch_fbo_stock", lambda _client, _skus: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_seller_stock", lambda _client, _skus: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_inbound", lambda _client, _clusters, _mapping: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_placement_zones", lambda _client, _skus: ((), ()))

    source = sync_ozon_source(ScopedOrdersClient())
    fbo_evidence = next(item for item in source.endpoint_evidence if item.name == "orders_fbo")
    prepared = api_module._api_prepared_inputs(source)

    assert [order.sku for order in source.orders] == ["SKU-A"]
    assert fbo_evidence.complete is True
    assert fbo_evidence.record_quality.incomplete_skus == ("SKU-B",)
    assert prepared.source_coverage.demand_complete_for("SKU-A") is True
    assert prepared.source_coverage.demand_complete_for("SKU-B") is False
    assert _need("SKU-A", prepared.source_coverage).calculated_need_qty == 10
    assert _need("SKU-B", prepared.source_coverage).calculated_need_qty is None


def _patch_inbound_acceptance_dependencies(monkeypatch):
    monkeypatch.setattr(sync_module, "next_backfill", lambda _window: None)
    monkeypatch.setattr(sync_module, "fetch_postings", lambda *_args: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_clusters", lambda _client: ClusterCatalogResult(
        (Cluster(10, "Москва"),), {501: 10}, ()))
    monkeypatch.setattr(sync_module, "fetch_seller_warehouses", lambda _client: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_product_skus", lambda _client: ("SKU-A", "SKU-B"))
    monkeypatch.setattr(sync_module, "fetch_fbo_stock", lambda _client, _skus: (
        (AvailabilityRecord("SKU-A", "W", "Москва", 0, None, fbo_quantity=3),
         AvailabilityRecord("SKU-B", "W", "Москва", 0, None, fbo_quantity=3)), ()))
    monkeypatch.setattr(sync_module, "fetch_seller_stock", lambda *_args: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_placement_zones", lambda *_args: ((), ()))


def _calculated_need_from_source(source, sku, *, include_inbound=True):
    prepared = api_module._api_prepared_inputs(source)
    fbo, inbound = aggregate_api_need_availability(
        source.availability, prepared.source_coverage, sku=sku)
    return prepared.source_coverage, inbound, calculate_need(
        sku=sku, destination_cluster_id="Москва", weekly_rate=Decimal("7"),
        horizon_days=14, fbo_stock=fbo, inbound_qty=inbound,
        include_inbound=include_inbound, ozon_recommended_qty=None,
        ozon_horizon_days=None, demand_source_complete=True)


def test_scoped_inbound_wire_corruption_blocks_only_affected_sku_need(monkeypatch):
    _patch_inbound_acceptance_dependencies(monkeypatch)

    class Client:
        def post_json(self, path, _payload, **_kwargs):
            if path == SUPPLY_ORDER_LIST_PATH:
                return {"order_ids": [7]}
            if path == SUPPLY_ORDER_GET_PATH:
                return {"orders": [{"order_id": 7, "supplies": [{
                    "state": "IN_TRANSIT", "macrolocal_cluster_id": 10,
                    "bundle_id": "bundle",
                }]}]}
            if path == SUPPLY_ORDER_BUNDLE_PATH:
                return {"items": [
                    {"sku": "SKU-A", "quantity": 2},
                    {"sku": "SKU-B", "quantity": None},
                ], "has_next": False, "total_count": 2}
            raise AssertionError(path)

    source = sync_ozon_source(Client())
    inbound_evidence = next(
        item for item in source.endpoint_evidence if item.name == "inbound")
    coverage_a, inbound_a, need_a = _calculated_need_from_source(source, "SKU-A")
    coverage_b, inbound_b, need_b = _calculated_need_from_source(source, "SKU-B")

    assert inbound_evidence.complete is True
    assert inbound_evidence.record_quality.incomplete_skus == ("SKU-B",)
    assert coverage_a.inbound_complete_for("SKU-A") is True
    assert inbound_a == 2 and need_a.calculated_need_qty is not None
    assert coverage_b.inbound_complete_for("SKU-B") is False
    assert inbound_b is None and need_b.calculated_need_qty is None
    assert "MISSING_INBOUND_QTY" in need_b.blocker_codes


def test_global_inbound_wire_corruption_blocks_all_skus_but_not_disabled_inbound(monkeypatch):
    _patch_inbound_acceptance_dependencies(monkeypatch)

    class Client:
        def post_json(self, path, _payload, **_kwargs):
            if path == SUPPLY_ORDER_LIST_PATH:
                return {"order_ids": None}
            raise AssertionError(path)

    source = sync_ozon_source(Client())
    inbound_evidence = next(
        item for item in source.endpoint_evidence if item.name == "inbound")
    assert inbound_evidence.complete is False

    for sku in ("SKU-A", "SKU-B"):
        source_coverage, inbound, need = _calculated_need_from_source(source, sku)
        assert source_coverage.inbound_complete_for(sku) is False
        assert inbound is None and need.calculated_need_qty is None
        assert "MISSING_INBOUND_QTY" in need.blocker_codes
        _coverage, _inbound, without_inbound = _calculated_need_from_source(
            source, sku, include_inbound=False)
        assert without_inbound.calculated_need_qty is not None
        assert "MISSING_INBOUND_QTY" not in without_inbound.blocker_codes
