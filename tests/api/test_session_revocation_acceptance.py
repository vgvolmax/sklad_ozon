"""Acceptance coverage for vault-session revocation at live API commit boundaries."""

from dataclasses import replace
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.handoff import HandoffPoint
from tests.api.test_shipment_candidates import _analyze_api_plan
from tests.api.test_shipment_plan import FakeValidation, _candidate, _request
from tests.ozon.test_source_store import snap


CLIENT = TestClient(app)


def _lock_request():
    return TestClient(app).post("/api/ozon/credentials/lock")


def _race_lock_against_blocked_commit(monkeypatch, target, attribute, request_call):
    """Start Lock while a live-result commit owns the shared commit guard."""
    entered = Event()
    release = Event()
    original = getattr(target, attribute)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "timed out waiting to release live commit"
        return original(*args, **kwargs)

    monkeypatch.setattr(target, attribute, blocked)
    responses = {}

    request_thread = Thread(
        target=lambda: responses.setdefault("request", request_call()),
        daemon=True,
    )
    request_thread.start()
    assert entered.wait(5), "live request never reached final commit"

    lock_started = Event()
    lock_done = Event()

    def run_lock():
        lock_started.set()
        responses["lock"] = _lock_request()
        lock_done.set()

    lock_thread = Thread(target=run_lock, daemon=True)
    lock_thread.start()
    assert lock_started.wait(5), "lock request thread never started"

    lock_finished_before_release = lock_done.wait(1)
    release.set()
    request_thread.join(5)
    lock_thread.join(5)
    assert not request_thread.is_alive() and not lock_thread.is_alive()
    return responses, lock_finished_before_release


def test_connection_check_lock_before_final_commit_does_not_stamp_timestamp(monkeypatch):
    class LockingBoundClient:
        def post_json(self, *_args, **_kwargs):
            api_module.OZON_VAULT.lock()
            return {"ok": True}

    monkeypatch.setattr(
        api_module.OZON_CLIENT,
        "bind_context",
        lambda _context: LockingBoundClient(),
    )

    response = CLIENT.post("/api/ozon/connection/test")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.OZON_VAULT.status().last_connection_check is None


def test_sync_lock_before_final_commit_preserves_previous_healthy_source(monkeypatch):
    context_id = api_module.OZON_VAULT.credential_context_id()
    previous = replace(snap("source-before-lock"), credential_context_id=context_id)
    incoming = replace(snap("source-after-lock"), credential_context_id=context_id)
    api_module.OZON_SOURCE_STORE.put(previous)

    def locking_sync(_client, *, credential_context_id):
        assert credential_context_id == context_id
        api_module.OZON_VAULT.lock()
        return incoming

    monkeypatch.setattr(api_module, "sync_ozon_source", locking_sync)

    response = CLIENT.post("/api/ozon/sync")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.OZON_SOURCE_STORE.get("source-after-lock") is None
    assert api_module.OZON_SOURCE_STORE.get("source-before-lock") == previous
    assert api_module.OZON_SOURCE_STORE.last_healthy() == previous


def test_handoff_lock_before_final_commit_does_not_store_results(monkeypatch):
    point = HandoffPoint(991, "Revoked point", None, "PVZ", "CREATE_TYPE_CROSSDOCK")

    def locking_search(_client, _query, _supply_types):
        api_module.OZON_VAULT.lock()
        return (point,)

    monkeypatch.setattr(api_module, "search_handoff_points", locking_search)

    response = CLIENT.post("/api/ozon/handoff/search", json={
        "query": "Москва",
        "supply_types": ["pvz_crossdock"],
    })

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.HANDOFF_STORE.get(point.warehouse_id) is None


@pytest.mark.parametrize("endpoint", ["validate", "plan"])
def test_shipment_live_result_is_rejected_when_validation_revokes_session(monkeypatch, endpoint):
    snapshot = _analyze_api_plan()
    candidate_id = _candidate(snapshot)

    class LockingValidation(FakeValidation):
        def validate(self, candidates, scenario, **kwargs):
            result = super().validate(candidates, scenario, **kwargs)
            api_module.OZON_VAULT.lock()
            return result

    api_module.SHIPMENT_PLAN_STORE.clear()
    monkeypatch.setattr(api_module, "DRAFT_VALIDATION_SERVICE", LockingValidation())

    response = CLIENT.post(f"/api/shipment/{endpoint}", json=_request(snapshot, candidate_id))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert "options" not in response.json()
    assert len(api_module.SHIPMENT_PLAN_STORE) == 0


def test_lock_waits_for_live_commit_that_already_owns_commit_guard(monkeypatch):
    context_id = api_module.OZON_VAULT.credential_context_id()
    source = replace(snap("source-committed-before-lock"), credential_context_id=context_id)
    monkeypatch.setattr(
        api_module,
        "sync_ozon_source",
        lambda _client, *, credential_context_id: source,
    )

    responses, lock_finished_early = _race_lock_against_blocked_commit(
        monkeypatch,
        api_module.OZON_SOURCE_STORE,
        "put",
        lambda: TestClient(app).post("/api/ozon/sync"),
    )

    assert lock_finished_early is False
    assert responses["request"].status_code == 200
    assert responses["lock"].status_code == 200
    assert responses["lock"].json()["locked"] is True
    assert api_module.OZON_SOURCE_STORE.get("source-committed-before-lock") is not None


def test_lock_that_wins_before_live_commit_rejects_old_sync_result(monkeypatch):
    context_id = api_module.OZON_VAULT.credential_context_id()
    source = replace(snap("source-lock-wins"), credential_context_id=context_id)
    entered = Event()
    release = Event()

    def blocked_sync(_client, *, credential_context_id):
        assert credential_context_id == context_id
        entered.set()
        assert release.wait(5), "timed out waiting to release sync"
        return source

    monkeypatch.setattr(api_module, "sync_ozon_source", blocked_sync)
    responses = {}
    request_thread = Thread(
        target=lambda: responses.setdefault(
            "request", TestClient(app).post("/api/ozon/sync")
        ),
        daemon=True,
    )
    request_thread.start()
    assert entered.wait(5), "sync never reached pre-commit pause"

    locked = _lock_request()
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    release.set()
    request_thread.join(5)
    assert not request_thread.is_alive()

    response = responses["request"]
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OZON_CREDENTIAL_CONTEXT_CHANGED"
    assert api_module.OZON_SOURCE_STORE.get("source-lock-wins") is None
