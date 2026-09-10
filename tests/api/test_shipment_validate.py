"""HTTP validation boundary regressions build on the PR-C analysis fixture."""

import backend.api as api_module
from backend.ozon.contracts import OzonCredentials
from tests.api.test_analysis import CLIENT
from tests.api.test_shipment_candidates import _analyze_api_plan


def _scenario():
    return {"selected_cluster_ids":["Москва"],"date_from":"2026-09-11",
            "date_to":"2026-09-12","allowed_methods":["direct"],
            "preferred_clusters_per_shipment":1,"max_clusters_per_shipment":1}


def test_validate_reconstructs_candidate_and_rejects_authoritative_rows(monkeypatch):
    snapshot=_analyze_api_plan(); plan=snapshot["shippable_plan"]
    candidates=CLIENT.post("/api/shipment/candidates",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],"shippable_plan_id":plan["shippable_plan_id"],
        "scenario":_scenario()}).json()["candidates"]
    monkeypatch.setattr(api_module.OZON_VAULT,"require_credentials",lambda:OzonCredentials("client","key"))
    response=CLIENT.post("/api/shipment/validate",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],"shippable_plan_id":plan["shippable_plan_id"],
        "scenario":_scenario(),"candidate_ids":[candidates[0]["candidate_id"]],
        "quantities":[999999]})
    assert response.status_code==400
    assert response.json()["error"]["code"]=="UNSUPPORTED_FIELD"


def test_files_source_is_rejected_before_network(monkeypatch):
    # Existing FILES fixture is deliberately produced by the canonical analysis helper.
    from tests.api.test_analysis import _post_analysis
    snapshot=_post_analysis().json()["snapshot"]
    called=False
    def network(*args,**kwargs):
        nonlocal called; called=True; raise AssertionError
    monkeypatch.setattr(api_module.OZON_CLIENT,"post_json",network)
    response=CLIENT.post("/api/shipment/validate",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_scenario(),"candidate_ids":["cs_unknown"]})
    assert response.status_code==409
    assert response.json()["error"]["code"]=="LIVE_VALIDATION_REQUIRES_API_SOURCE"
    assert called is False
