"""Cross-request acceptance regressions for Ozon credential-context provenance."""

from dataclasses import replace

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.contracts import OzonCredentials
from backend.ozon.handoff import HandoffPoint
from tests.api.conftest import TEST_VAULT_PASSWORD
from tests.api.test_shipment_candidates import _analyze_api_plan
from tests.api.test_shipment_export import _stored_plan
from tests.api.test_shipment_plan import FakeValidation, _candidate, _request
from tests.ozon.test_source_store import snap


CLIENT = TestClient(app)


def _replace_credentials(client_id="client-b", api_key="key-b", password="password-b"):
    api_module.OZON_VAULT.setup(OzonCredentials(client_id, api_key), password)


def test_sync_context_switch_does_not_persist_old_source(monkeypatch):
    old_context = api_module.OZON_VAULT.credential_context_id()
    source = replace(snap("source-from-a"), credential_context_id=old_context)

    def switching_sync(_client, *, credential_context_id):
        assert credential_context_id == old_context
        _replace_credentials()
        return source

    monkeypatch.setattr(api_module, "sync_ozon_source", switching_sync)

    response = CLIENT.post("/api/ozon/sync")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.OZON_SOURCE_STORE.get("source-from-a") is None


def test_handoff_context_switch_does_not_persist_old_search_results(monkeypatch):
    point = HandoffPoint(777, "Old account point", None, "PVZ", "CREATE_TYPE_CROSSDOCK")

    def switching_search(_client, _query, _supply_types):
        _replace_credentials()
        return (point,)

    monkeypatch.setattr(api_module, "search_handoff_points", switching_search)

    response = CLIENT.post("/api/ozon/handoff/search", json={
        "query": "Москва",
        "supply_types": ["pvz_crossdock"],
    })

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.HANDOFF_STORE.get(point.warehouse_id) is None


def test_plan_context_switch_during_validation_does_not_store_shipment_plan(monkeypatch):
    snapshot = _analyze_api_plan()
    candidate_id = _candidate(snapshot)

    class SwitchingValidation(FakeValidation):
        def validate(self, candidates, scenario, **kwargs):
            result = super().validate(candidates, scenario, **kwargs)
            _replace_credentials()
            return result

    api_module.SHIPMENT_PLAN_STORE.clear()
    monkeypatch.setattr(api_module, "DRAFT_VALIDATION_SERVICE", SwitchingValidation())

    response = CLIENT.post("/api/shipment/plan", json=_request(snapshot, candidate_id))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert len(api_module.SHIPMENT_PLAN_STORE) == 0


def test_credentials_replacement_makes_existing_shipment_plan_unexportable():
    _stored_plan()

    setup = CLIENT.post("/api/ozon/credentials/setup", json={
        "client_id": "client-b",
        "api_key": "key-b",
        "password": "password-b",
        "password_confirmation": "password-b",
    })
    assert setup.status_code == 200

    response = CLIENT.post("/api/shipment/export", json={
        "shipment_plan_id": "sp_export",
        "option_id": "cs_export",
    })

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SHIPMENT_PLAN_NOT_FOUND"


def test_lock_unlock_preserves_current_source_context():
    context_id = api_module.OZON_VAULT.credential_context_id()
    source = replace(snap("source-a"), credential_context_id=context_id)
    api_module.OZON_SOURCE_STORE.put(source)

    locked = CLIENT.post("/api/ozon/credentials/lock")
    assert locked.status_code == 200
    assert api_module.OZON_SOURCE_STORE.get("source-a") is not None

    unlocked = CLIENT.post("/api/ozon/credentials/unlock", json={
        "password": TEST_VAULT_PASSWORD,
    })
    assert unlocked.status_code == 200
    assert api_module.OZON_SOURCE_STORE.get("source-a") is not None

    status = CLIENT.get("/api/ozon/source/source-a/status")
    assert status.status_code == 200
