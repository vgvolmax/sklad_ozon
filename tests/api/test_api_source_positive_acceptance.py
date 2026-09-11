"""Focused acceptance for API-first analytical feasibility before live Ozon validation."""

from dataclasses import replace

import backend.api as api_module
from backend.ozon.source_contracts import PlacementZoneEvidence
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture
from tests.helpers.xlsx_fixtures import make_real_unitka


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
