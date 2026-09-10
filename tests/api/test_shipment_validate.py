"""HTTP validation boundary regressions build on the PR-C analysis fixture."""

import pytest
import backend.api as api_module
from backend.ozon.contracts import OzonCredentials,OzonErrorCode
from backend.ozon.vault import OzonVaultError
from tests.api.test_analysis import CLIENT
from tests.api.test_shipment_candidates import _analyze_api_plan


def _scenario():
    return {"selected_cluster_ids":["Москва"],"date_from":"2026-09-11",
            "date_to":"2026-09-12","allowed_methods":["direct"],
            "preferred_clusters_per_shipment":1,"max_clusters_per_shipment":1}


class RecordingValidation:
    def __init__(self): self.calls=[]
    def validate(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        raise AssertionError("live validation must not be called")


def _crossdock_scenario(*,warehouse_id,point_id):
    return {"selected_cluster_ids":["Москва"],"date_from":"2026-09-11",
            "date_to":"2026-09-12","allowed_methods":["pvz_crossdock"],
            "preferred_clusters_per_shipment":1,"max_clusters_per_shipment":1,
            "seller_warehouse_id":warehouse_id,"selected_handoff_point_ids":[point_id]}


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


@pytest.mark.parametrize("endpoint",["validate","plan"])
def test_crossdock_invalid_seller_warehouse_has_shared_guard_semantics(monkeypatch,endpoint):
    snapshot=_analyze_api_plan(); fake=RecordingValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    response=CLIENT.post(f"/api/shipment/{endpoint}",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_crossdock_scenario(warehouse_id=999,point_id=987654),
        "candidate_ids":["cs_not_reached"]})
    assert response.status_code==409
    assert response.json()["error"]["code"]=="SELLER_WAREHOUSE_INVALID"
    assert fake.calls==[]


@pytest.mark.parametrize("endpoint",["validate","plan"])
def test_crossdock_unresolved_handoff_has_shared_guard_semantics(monkeypatch,endpoint):
    snapshot=_analyze_api_plan(); fake=RecordingValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    response=CLIENT.post(f"/api/shipment/{endpoint}",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_crossdock_scenario(warehouse_id=91,point_id=987654),
        "candidate_ids":["cs_not_reached"]})
    assert response.status_code==409
    assert response.json()["error"]["code"]=="HANDOFF_POINT_UNRESOLVED"
    assert fake.calls==[]


@pytest.mark.parametrize("endpoint",["validate","plan"])
def test_locked_vault_has_shared_guard_semantics(monkeypatch,endpoint):
    snapshot=_analyze_api_plan()
    candidates=CLIENT.post("/api/shipment/candidates",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_scenario()}).json()["candidates"]
    fake=RecordingValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    monkeypatch.setattr(api_module.OZON_VAULT,"require_credentials",
        lambda:(_ for _ in ()).throw(OzonVaultError(OzonErrorCode.LOCKED,"locked")))
    response=CLIENT.post(f"/api/shipment/{endpoint}",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_scenario(),"candidate_ids":[candidates[0]["candidate_id"]]})
    assert response.status_code==423
    assert response.json()["error"]["code"]=="OZON_VAULT_LOCKED"
    assert fake.calls==[]
