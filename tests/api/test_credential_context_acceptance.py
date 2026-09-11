"""Cross-request acceptance regressions for Ozon credential-context provenance."""

from dataclasses import replace
from threading import Event, Thread

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.contracts import OzonCredentials
from backend.ozon.handoff import HandoffPoint
from backend.ozon.source_contracts import PlacementZoneEvidence, SellerWarehouse
from tests.api.conftest import TEST_VAULT_PASSWORD
from tests.api.test_analysis import _analysis_data, _api_parity_fixture, _parity_files
from tests.api.test_shipment_candidates import _analyze_api_plan
from tests.api.test_shipment_export import _stored_plan
from tests.api.test_shipment_plan import FakeValidation, _candidate, _request
from tests.ozon.test_source_store import snap


CLIENT = TestClient(app)


def _replace_credentials(client_id="client-b", api_key="key-b", password="password-b"):
    api_module.OZON_VAULT.setup(OzonCredentials(client_id, api_key), password)


def _setup_request():
    return TestClient(app).post("/api/ozon/credentials/setup", json={
        "client_id": "client-b",
        "api_key": "key-b",
        "password": "password-b",
        "password_confirmation": "password-b",
    })


def _race_setup_against_blocked_commit(monkeypatch, target, attribute, request_call):
    """Run setup while an old-context request is paused inside its final commit."""
    entered = Event()
    release = Event()
    original = getattr(target, attribute)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "timed out waiting to release old-context commit"
        return original(*args, **kwargs)

    monkeypatch.setattr(target, attribute, blocked)
    responses = {}

    request_thread = Thread(
        target=lambda: responses.setdefault("request", request_call()),
        daemon=True,
    )
    request_thread.start()
    assert entered.wait(5), "old-context request never reached final commit"

    setup_done = Event()

    def run_setup():
        responses["setup"] = _setup_request()
        setup_done.set()

    setup_thread = Thread(target=run_setup, daemon=True)
    setup_thread.start()

    # Without a shared commit guard, setup completes and clears state before the
    # blocked old-context write resumes. With the guard, setup must wait.
    setup_finished_before_release = setup_done.wait(1)
    release.set()
    request_thread.join(5)
    setup_thread.join(5)
    assert not request_thread.is_alive() and not setup_thread.is_alive()
    return responses, setup_finished_before_release


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


def test_sync_setup_is_atomic_with_final_source_commit(monkeypatch):
    context_id = api_module.OZON_VAULT.credential_context_id()
    source = replace(snap("source-race"), credential_context_id=context_id)
    monkeypatch.setattr(
        api_module,
        "sync_ozon_source",
        lambda _client, *, credential_context_id: source,
    )

    responses, setup_finished_early = _race_setup_against_blocked_commit(
        monkeypatch,
        api_module.OZON_SOURCE_STORE,
        "put",
        lambda: TestClient(app).post("/api/ozon/sync"),
    )

    assert setup_finished_early is False
    assert responses["request"].status_code == 200
    assert responses["setup"].status_code == 200
    assert api_module.OZON_SOURCE_STORE.get("source-race") is None


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


def test_handoff_setup_is_atomic_with_final_store_commit(monkeypatch):
    point = HandoffPoint(778, "Race point", None, "PVZ", "CREATE_TYPE_CROSSDOCK")
    monkeypatch.setattr(
        api_module,
        "search_handoff_points",
        lambda _client, _query, _supply_types: (point,),
    )

    responses, setup_finished_early = _race_setup_against_blocked_commit(
        monkeypatch,
        api_module.HANDOFF_STORE,
        "put_all",
        lambda: TestClient(app).post("/api/ozon/handoff/search", json={
            "query": "Москва",
            "supply_types": ["pvz_crossdock"],
        }),
    )

    assert setup_finished_early is False
    assert responses["request"].status_code == 200
    assert responses["setup"].status_code == 200
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


def test_plan_setup_is_atomic_with_final_plan_commit(monkeypatch):
    snapshot = _analyze_api_plan()
    candidate_id = _candidate(snapshot)
    monkeypatch.setattr(api_module, "DRAFT_VALIDATION_SERVICE", FakeValidation())

    responses, setup_finished_early = _race_setup_against_blocked_commit(
        monkeypatch,
        api_module.SHIPMENT_PLAN_STORE,
        "put",
        lambda: TestClient(app).post(
            "/api/shipment/plan",
            json=_request(snapshot, candidate_id),
        ),
    )

    assert setup_finished_early is False
    assert responses["request"].status_code == 200
    assert responses["setup"].status_code == 200
    assert len(api_module.SHIPMENT_PLAN_STORE) == 0


def test_api_analysis_setup_is_atomic_with_final_analysis_commit(monkeypatch):
    base = _api_parity_fixture()
    source = replace(
        base,
        operational_seller_stock=tuple(
            replace(row, available_quantity=20, fbs_quantity=20)
            for row in base.operational_seller_stock
        ),
        seller_warehouses=(SellerWarehouse(91, "Origin", None, True, None),),
        placement_zones=(PlacementZoneEvidence("SKU-1", ("SORTABLE",)),),
    )
    api_module.OZON_SOURCE_STORE.put(source)
    files = _parity_files()

    responses, setup_finished_early = _race_setup_against_blocked_commit(
        monkeypatch,
        api_module.ANALYSIS_STORE,
        "put",
        lambda: TestClient(app).post(
            "/api/analysis",
            files={key: files[key] for key in ("tariffs_file", "product_economics_file")},
            data=_analysis_data(source_mode="api", source_snapshot_id=source.source_snapshot_id),
        ),
    )

    assert setup_finished_early is False
    assert responses["request"].status_code == 200, responses["request"].text
    assert responses["setup"].status_code == 200
    snapshot_id = responses["request"].json()["snapshot"]["snapshot_id"]
    assert api_module.ANALYSIS_STORE.get(snapshot_id) is None


def test_connection_check_cannot_stamp_replaced_context(monkeypatch):
    class SuccessfulBoundClient:
        def post_json(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(
        api_module.OZON_CLIENT,
        "bind_context",
        lambda _context: SuccessfulBoundClient(),
    )

    responses, setup_finished_early = _race_setup_against_blocked_commit(
        monkeypatch,
        api_module.OZON_VAULT,
        "record_connection_check",
        lambda: TestClient(app).post("/api/ozon/connection/test"),
    )

    assert setup_finished_early is False
    assert responses["request"].status_code == 200
    assert responses["setup"].status_code == 200
    assert api_module.OZON_VAULT.status().last_connection_check is None


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
