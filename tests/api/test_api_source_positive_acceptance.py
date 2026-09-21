"""Focused acceptance for API-first analytical feasibility before live Ozon validation."""

from dataclasses import replace

import backend.api as api_module
import backend.ozon.sync as sync_module
from backend.ozon.adapters.catalog import ClusterCatalogResult
from backend.ozon.endpoints import FBS_STOCK_PATH
from backend.ozon.source_contracts import Cluster, PlacementZoneEvidence
from backend.ozon.sync import sync_ozon_source
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture, _parity_files
from tests.helpers.xlsx_fixtures import make_real_unitka, make_xlsx


def _clean_api_source():
    base = _api_parity_fixture()
    return replace(
        base,
        source_snapshot_id="positive-api",
        operational_seller_stock=tuple(
            replace(row, available_quantity=99, fbs_quantity=99)
            for row in base.operational_seller_stock
        ),
        placement_zones=(PlacementZoneEvidence("SKU-1", ("SORTABLE",)),),
    )


def _seller_stock_wire_source(monkeypatch, seller_response):
    base = _api_parity_fixture()
    sku_b_orders = tuple(
        replace(row, sku="SKU-B", article="ART-B") for row in base.orders)
    fbo = base.availability + tuple(
        replace(row, sku="SKU-B", article="ART-B") for row in base.availability)
    monkeypatch.setattr(sync_module, "next_backfill", lambda _window: None)
    monkeypatch.setattr(sync_module, "fetch_postings", lambda *_args: (
        base.orders + sku_b_orders, ()))
    monkeypatch.setattr(sync_module, "fetch_clusters", lambda _client: ClusterCatalogResult(
        (Cluster(10, "Москва"),), {501: 10}, ()))
    monkeypatch.setattr(sync_module, "fetch_seller_warehouses", lambda _client: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_product_skus", lambda _client: ("SKU-1", "SKU-B"))
    monkeypatch.setattr(sync_module, "fetch_fbo_stock", lambda *_args: (fbo, ()))
    monkeypatch.setattr(sync_module, "fetch_inbound", lambda *_args: ((), ()))
    monkeypatch.setattr(sync_module, "fetch_placement_zones", lambda *_args: ((), ()))

    class Client:
        def post_json(self, path, _payload, **_kwargs):
            assert path == FBS_STOCK_PATH
            return seller_response

    return sync_ozon_source(Client())


def _analyze_two_sku_wire_source(source):
    api_module.OZON_SOURCE_STORE.put(source)
    base_files = _parity_files()
    products = make_xlsx(
        headers=["SKU", "Артикул", "Себестоимость", "Доступный остаток", "Цена", "Комиссия", "Объём, л"],
        rows=[
            ["SKU-1", "ART-1", 100, 99, 1000, "10%", 1],
            ["SKU-B", "ART-B", 100, 99, 1000, "10%", 1],
        ],
    )
    response = CLIENT.post("/api/analysis", files={
        "tariffs_file": base_files["tariffs_file"],
        "product_economics_file": ("products.xlsx", products),
    }, data=_analysis_data(
        source_mode="api", source_snapshot_id=source.source_snapshot_id,
        as_of=source.source_as_of.isoformat(),
    ))
    assert response.status_code == 200, response.text
    return response.json()


def test_scoped_seller_stock_wire_corruption_blocks_only_affected_optimizer_sku(monkeypatch):
    source = _seller_stock_wire_source(monkeypatch, {"products": [
        {"sku": "SKU-1", "warehouse_id": 1, "free_stock": 10},
        {"sku": "SKU-B", "warehouse_id": 1, "free_stock": None},
    ], "has_next": False})
    evidence = next(item for item in source.endpoint_evidence if item.name == "seller_stock")
    payload = _analyze_two_sku_wire_source(source)

    assert evidence.complete is True
    assert evidence.record_quality.incomplete_skus == ("SKU-B",)
    assert evidence.record_quality.rejected_record_count == 1
    assert {row["sku"] for row in payload["allocations"]} == {"SKU-1"}
    diagnostics = {(item.get("sku"), item["code"]) for item in payload["diagnostics"]}
    assert ("SKU-B", "MISSING_SELLER_AVAILABLE_STOCK") in diagnostics


def test_global_seller_stock_wire_corruption_blocks_partial_and_unitka_fallback(monkeypatch):
    source = _seller_stock_wire_source(monkeypatch, {"products": None})
    evidence = next(item for item in source.endpoint_evidence if item.name == "seller_stock")
    payload = _analyze_two_sku_wire_source(source)

    assert evidence.complete is False
    assert payload["allocations"] == []
    missing = {
        item.get("sku") for item in payload["diagnostics"]
        if item["code"] == "MISSING_SELLER_AVAILABLE_STOCK"
    }
    assert missing == {"SKU-1", "SKU-B"}


def test_api_source_reaches_positive_calculated_shippable_and_candidate_before_live_validation():
    source = _clean_api_source()
    api_module.OZON_SOURCE_STORE.put(source)
    unitka = make_real_unitka(
        product_rows=[["ART-1", "Product", 100, 1000, "10%", 1]],
        tariff_rows=[(0, "0-0,200 л", "Москва", "Москва", 18, 69)],
        pack_rows=[["ART-1", "36/6"]],
        economics_scheme_fbo=True,
    )

    response = CLIENT.post(
        "/api/analysis",
        files={"unitka_file": ("unitka.xlsx", unitka)},
        data=_analysis_data(
            source_mode="api", source_snapshot_id=source.source_snapshot_id,
        ),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    snapshot = payload["snapshot"]
    decision = next(
        row for row in snapshot["decision_rows"]
        if row["sku"] == "SKU-1" and row["destination_cluster_id"] == "Москва"
    )
    placement = next(
        row for row in payload["placements"]
        if row["sku"] == "SKU-1" and row["cluster_id"] == "Москва"
    )
    line = next(
        row for row in snapshot["shippable_plan"]["lines"]
        if row["sku"] == "SKU-1" and row["destination_cluster_id"] == "Москва"
    )

    assert decision["need"]["calculated_need_qty"] > 0
    assert decision["calculated_plan_qty"] > 0
    assert placement["feasibility"]["physical_state"] == "unknown_pending_live_validation"
    assert placement["feasibility"]["allowed"] is None
    assert placement["feasibility"]["max_supply_qty"] is None
    assert "PHYSICAL_CAPACITY_PENDING_OZON_VALIDATION" in decision["status_codes"]
    assert any("не подтверждена Ozon" in text for text in decision["explanations"])
    assert line["analytical_qty"] == decision["calculated_plan_qty"]
    assert line["pack_multiple"] == 6
    assert line["shippable_qty"] > 0

    candidate_response = CLIENT.post(
        "/api/shipment/candidates",
        json={
            "analysis_snapshot_id": snapshot["snapshot_id"],
            "shippable_plan_id": snapshot["shippable_plan"]["shippable_plan_id"],
            "working_plan_id": CLIENT.post("/api/working-plan", json={"analysis_snapshot_id": snapshot["snapshot_id"], "shippable_plan_id": snapshot["shippable_plan"]["shippable_plan_id"]}).json()["working_plan"]["working_plan_id"],
            "scenario": {
                "selected_cluster_ids": ["Москва"],
                "date_from": "2026-09-11",
                "date_to": "2026-09-12",
                "allowed_methods": ["direct"],
                "preferred_clusters_per_shipment": 1,
                "max_clusters_per_shipment": 1,
            },
        },
    )
    assert candidate_response.status_code == 200, candidate_response.text
    candidates = candidate_response.json()["candidates"]
    assert candidates
    assert candidates[0]["method"] == "direct"


def test_api_product_facts_feed_economics_and_plan_instead_of_unitka_values():
    from decimal import Decimal
    from backend.ozon.adapters.product_facts import ProductApiFacts

    base = _api_parity_fixture()
    source = replace(
        base,
        source_snapshot_id="api-product-facts",
        operational_seller_stock=(replace(base.operational_seller_stock[0],
                                          available_quantity=24, fbs_quantity=24),),
        product_facts=(ProductApiFacts(
            "SKU-1", "ART-1", 101, Decimal("550"), Decimal("0.41"),
            Decimal("0.35")),),
    )
    api_module.OZON_SOURCE_STORE.put(source)
    unitka = make_real_unitka(
        product_rows=[["ART-1", "Product", 100, 500, "20%", None]],
        tariff_rows=[(0, "0-0,500 л", "Москва", "Москва", 18, 69)],
        pack_rows=[["ART-1", "36/6"]],
        economics_scheme_fbo=True,
    )

    response = CLIENT.post("/api/analysis", files={"unitka_file": ("unitka.xlsx", unitka)},
                           data=_analysis_data(source_mode="api",
                                               source_snapshot_id=source.source_snapshot_id))
    assert response.status_code == 200, response.text
    payload = response.json()
    economics = next(item for item in payload["economics"] if item["sku"] == "SKU-1")
    assert economics["price"] == "550"
    assert economics["commission"] == "225.5"
    assert economics["cost"] == "100"
    line = next(item for item in payload["snapshot"]["shippable_plan"]["lines"]
                if item["sku"] == "SKU-1")
    assert line["unit_volume_l"] == "0.35"
    assert line["resolved_seller_stock"] == 24
