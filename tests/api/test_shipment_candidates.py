"""Provenance-bound local shipment candidate HTTP boundary."""

from dataclasses import replace
from decimal import Decimal

import backend.api as api_module
from backend.ozon.source_contracts import PlacementZoneEvidence, SellerWarehouse
from tests.api.test_analysis import CLIENT, _analysis_data, _api_parity_fixture, _parity_files


def _analyze_api_plan():
    base = _api_parity_fixture()
    source = replace(
        base,
        operational_seller_stock=tuple(replace(row, available_quantity=20, fbs_quantity=20)
                                       for row in base.operational_seller_stock),
        seller_warehouses=(SellerWarehouse(91, "Origin", None, True, None),),
        placement_zones=(PlacementZoneEvidence("SKU-1", ("SORTABLE",)),),
    )
    api_module.OZON_SOURCE_STORE.put(source)
    files = _parity_files()
    response = CLIENT.post("/api/analysis", files={
        key: files[key] for key in ("tariffs_file", "product_economics_file")},
        data=_analysis_data(source_mode="api", source_snapshot_id=source.source_snapshot_id),
    )
    assert response.status_code == 200, response.text
    payload = response.json()["snapshot"]
    # The legacy economics fixture intentionally has no supplier pack sheet; make
    # this API-boundary fixture operational without changing analytical math.
    stored = api_module.ANALYSIS_STORE.get(payload["snapshot_id"])
    line = replace(stored.shippable_plan.lines[0], analytical_qty=2,
                   rounded_target_qty=2, rounding_delta_qty=0,
                   allocation_priority_rank=1, pack_multiple=1,
                   shippable_qty=2, total_volume_l=Decimal("2"), reason_codes=())
    plan = replace(stored.shippable_plan, shippable_plan_id="sp-api-test", lines=(line,))
    api_module.ANALYSIS_STORE.put(replace(stored, shippable_plan=plan))
    payload["shippable_plan"] = api_module.wire(plan)
    return payload


def test_candidate_endpoint_uses_stored_plan_and_performs_no_network(monkeypatch):
    snapshot = _analyze_api_plan()
    monkeypatch.setattr(api_module.OZON_CLIENT, "post_json",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")))
    plan = snapshot["shippable_plan"]
    response = CLIENT.post("/api/shipment/candidates", json={
        "analysis_snapshot_id": snapshot["snapshot_id"],
        "shippable_plan_id": plan["shippable_plan_id"],
        "scenario": {
            "selected_cluster_ids": ["Москва"],
            "date_from": "2026-09-11", "date_to": "2026-09-12",
            "allowed_methods": ["direct"],
            "preferred_clusters_per_shipment": 1,
            "max_clusters_per_shipment": 1,
        },
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["candidates"]
    assert payload["candidates"][0]["method"] == "direct"
    serialized = response.text.casefold()
    assert not any(term in serialized for term in (
        "timeslot", "accepted_by_ozon", "booked", "confirmed", "supply_created"))


def test_candidate_endpoint_rejects_foreign_plan_identity():
    snapshot = _analyze_api_plan()
    response = CLIENT.post("/api/shipment/candidates", json={
        "analysis_snapshot_id": snapshot["snapshot_id"],
        "shippable_plan_id": "sp_frontend_forgery",
        "scenario": {},
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SHIPPABLE_PLAN_IDENTITY_MISMATCH"
