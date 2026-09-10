"""Offline regressions for the trusted shipment-plan HTTP boundary."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

import backend.api as api_module
from backend.ozon.contracts import OzonCredentials
from backend.ozon.draft_contracts import ValidatedShipmentOption, ValidationState
from tests.api.test_analysis import CLIENT, _post_analysis
from tests.api.test_shipment_candidates import _analyze_api_plan


def _scenario():
    return {"selected_cluster_ids":["Москва"],"date_from":"2026-09-11",
            "date_to":"2026-09-12","allowed_methods":["direct"],
            "preferred_clusters_per_shipment":1,"max_clusters_per_shipment":1}


class FakeValidation:
    def __init__(self, state=ValidationState.ACCEPTED, foreign=False):
        self.state=state; self.foreign=foreign; self.calls=[]
    def validate(self,candidates,scenario,**kwargs):
        self.calls.append(candidates)
        return tuple(ValidatedShipmentOption(
            "cs_invented" if self.foreign else candidate.candidate_id,1,self.state,
            candidate.method,candidate.seller_warehouse_id,candidate.handoff_point_id,
            candidate.assignments if self.state is ValidationState.ACCEPTED else (),(),(),None,(),
            datetime.now(timezone.utc).isoformat(),()) for candidate in candidates)


def _request(snapshot, candidate_id):
    return {"analysis_snapshot_id":snapshot["snapshot_id"],
            "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
            "scenario":_scenario(),"candidate_ids":[candidate_id]}


def _candidate(snapshot):
    response=CLIENT.post("/api/shipment/candidates",json={
        "analysis_snapshot_id":snapshot["snapshot_id"],
        "shippable_plan_id":snapshot["shippable_plan"]["shippable_plan_id"],
        "scenario":_scenario()})
    return response.json()["candidates"][0]["candidate_id"]


def test_plan_happy_path_uses_reconstructed_candidate_and_stores_plan(monkeypatch):
    snapshot=_analyze_api_plan(); candidate_id=_candidate(snapshot); fake=FakeValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    monkeypatch.setattr(api_module.OZON_VAULT,"require_credentials",lambda:OzonCredentials("client","key"))
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,candidate_id))
    assert response.status_code==200,response.text
    payload=response.json(); plan=payload["shipment_plan"]
    assert payload["api_version"]==1
    assert plan["shipment_plan_id"].startswith("sp_")
    assert plan["scenario_fingerprint"].startswith("ss_")
    assert plan["ranked_options"][0]["option_id"]==candidate_id
    assert fake.calls[0][0].candidate_id==candidate_id
    assert api_module.SHIPMENT_PLAN_STORE.get(plan["shipment_plan_id"]) is not None


@pytest.mark.parametrize("field",["accepted_assignments","validated_options","timeslots","quantity"])
def test_plan_rejects_client_validation_evidence(field):
    response=CLIENT.post("/api/shipment/plan",json={field:[] if field!="quantity" else 999})
    assert response.status_code==400
    assert response.json()["error"]["code"]=="UNSUPPORTED_FIELD"


def test_plan_unknown_candidate_fails_before_validation(monkeypatch):
    snapshot=_analyze_api_plan(); fake=FakeValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,"cs_invented"))
    assert response.status_code==409
    assert response.json()["error"]["code"]=="CANDIDATE_PROVENANCE_MISMATCH"
    assert fake.calls==[]


def test_plan_files_source_fails_before_validation(monkeypatch):
    snapshot=_post_analysis().json()["snapshot"]; fake=FakeValidation()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,"cs_invented"))
    assert response.status_code==409
    assert response.json()["error"]["code"]=="LIVE_VALIDATION_REQUIRES_API_SOURCE"
    assert fake.calls==[]


def test_plan_all_failed_is_successful_empty_plan(monkeypatch):
    snapshot=_analyze_api_plan(); candidate_id=_candidate(snapshot); fake=FakeValidation(ValidationState.REJECTED)
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    monkeypatch.setattr(api_module.OZON_VAULT,"require_credentials",lambda:OzonCredentials("client","key"))
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,candidate_id))
    assert response.status_code==200,response.text
    assert response.json()["shipment_plan"]["ranked_options"]==[]
    assert response.json()["shipment_plan"]["unavailable_options"]


def test_plan_validation_identity_mismatch_does_not_store(monkeypatch):
    snapshot=_analyze_api_plan(); candidate_id=_candidate(snapshot); fake=FakeValidation(foreign=True)
    api_module.SHIPMENT_PLAN_STORE.clear()
    monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    monkeypatch.setattr(api_module.OZON_VAULT,"require_credentials",lambda:OzonCredentials("client","key"))
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,candidate_id))
    assert response.status_code==502
    assert response.json()["error"]["code"]=="VALIDATION_RESULT_IDENTITY_MISMATCH"
    assert len(api_module.SHIPMENT_PLAN_STORE)==0


@pytest.mark.parametrize("mutation,code",[
    ("plan_source","SOURCE_PROVENANCE_MISMATCH"),
    ("analysis_date","SOURCE_PROVENANCE_MISMATCH"),
    ("plan_date","SOURCE_PROVENANCE_MISMATCH"),
    ("missing_source","OZON_SOURCE_SNAPSHOT_NOT_FOUND"),
])
def test_plan_source_mismatches_fail_before_validation(monkeypatch,mutation,code):
    snapshot=_analyze_api_plan(); stored=api_module.ANALYSIS_STORE.get(snapshot["snapshot_id"]); fake=FakeValidation()
    if mutation=="plan_source": stored=replace(stored,shippable_plan=replace(stored.shippable_plan,source_snapshot_id="os_foreign"))
    elif mutation=="analysis_date": stored=replace(stored,analysis_as_of=stored.analysis_as_of.replace(day=stored.analysis_as_of.day-1))
    elif mutation=="plan_date": stored=replace(stored,shippable_plan=replace(stored.shippable_plan,analysis_as_of=stored.analysis_as_of.replace(day=stored.analysis_as_of.day-1)))
    else: stored=replace(stored,source_snapshot_id="os_missing",shippable_plan=replace(stored.shippable_plan,source_snapshot_id="os_missing"))
    api_module.ANALYSIS_STORE.put(stored); monkeypatch.setattr(api_module,"DRAFT_VALIDATION_SERVICE",fake)
    response=CLIENT.post("/api/shipment/plan",json=_request(snapshot,"cs_invented"))
    assert response.status_code==409 and response.json()["error"]["code"]==code
    assert fake.calls==[]
