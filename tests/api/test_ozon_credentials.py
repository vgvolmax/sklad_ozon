from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import backend.api as api
from backend.main import app
from backend.ozon.contracts import OzonCredentials
from backend.ozon.vault import CredentialVault


CLIENT_ID = "client-credential-secret"
API_KEY = "api-key-never-returned"
PASSWORD = "vault-password-never-returned"


class FakeOzonClient:
    def __init__(self):
        self.calls = []

    def post_json(self, path, payload, *, policy):
        self.calls.append((path, payload, policy))
        return {"seller_name": "safe"}

    def bind_context(self, _context):
        return self


@pytest.fixture
def local_api(tmp_path, monkeypatch):
    vault = CredentialVault(tmp_path / "ozon-credentials.json")
    client = FakeOzonClient()
    monkeypatch.setattr(api, "OZON_VAULT", vault)
    monkeypatch.setattr(api, "OZON_CLIENT", client)
    return TestClient(app), vault, client


def assert_no_secrets(response):
    rendered = response.text
    assert CLIENT_ID not in rendered
    assert API_KEY not in rendered
    assert PASSWORD not in rendered


def setup(client):
    return client.post("/api/ozon/credentials/setup", json={
        "client_id": CLIENT_ID, "api_key": API_KEY,
        "password": PASSWORD, "password_confirmation": PASSWORD,
    })


def test_setup_status_lock_unlock_and_restart_state(local_api):
    client, vault, _ = local_api
    initial = client.get("/api/ozon/credentials/status")
    assert initial.json() == {"configured": False, "locked": True, "masked_client_id_suffix": None, "last_connection_check": None, "credential_context_id": None}

    configured = setup(client)
    assert configured.status_code == 200
    assert configured.json()["configured"] is True
    assert configured.json()["locked"] is False
    assert configured.json()["masked_client_id_suffix"] == "…cret"
    assert configured.json()["last_connection_check"] is None
    assert len(configured.json()["credential_context_id"]) == 64
    assert_no_secrets(configured)

    locked = client.post("/api/ozon/credentials/lock")
    assert locked.json()["locked"] is True
    restarted = CredentialVault(vault._path)
    assert restarted.status().configured and restarted.status().locked

    unlocked = client.post("/api/ozon/credentials/unlock", json={"password": PASSWORD})
    assert unlocked.status_code == 200 and unlocked.json()["locked"] is False
    assert_no_secrets(unlocked)


def test_setup_rejects_confirmation_mismatch_without_writing(local_api):
    client, vault, _ = local_api
    response = client.post("/api/ozon/credentials/setup", json={
        "client_id": CLIENT_ID, "api_key": API_KEY,
        "password": PASSWORD, "password_confirmation": "different",
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PASSWORD_CONFIRMATION_MISMATCH"
    assert not vault.status().configured
    assert_no_secrets(response)


def test_setup_rejects_whitespace_only_password_without_writing(local_api):
    client, vault, _ = local_api
    response = client.post("/api/ozon/credentials/setup", json={
        "client_id": CLIENT_ID, "api_key": API_KEY,
        "password": "   ", "password_confirmation": "   ",
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_FIELD"
    assert not vault.status().configured


def test_wrong_password_returns_safe_normalized_error(local_api):
    client, _, _ = local_api
    setup(client)
    client.post("/api/ozon/credentials/lock")
    response = client.post("/api/ozon/credentials/unlock", json={"password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "OZON_AUTH_FAILED"
    assert_no_secrets(response)


def test_unlock_rejects_whitespace_only_password_before_cryptography(local_api, monkeypatch):
    client, vault, _ = local_api
    setup(client)
    client.post("/api/ozon/credentials/lock")
    derive_calls = []

    def record_derive(*args):
        derive_calls.append(args)
        raise AssertionError("cryptography must not run for blank input")

    monkeypatch.setattr(vault, "_derive_key", record_derive)
    response = client.post("/api/ozon/credentials/unlock", json={"password": "\t\n"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_FIELD"
    assert derive_calls == []


def test_locked_connection_test_never_calls_transport(local_api):
    client, _, ozon_client = local_api
    setup(client)
    client.post("/api/ozon/credentials/lock")
    response = client.post("/api/ozon/connection/test")
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "OZON_VAULT_LOCKED"
    assert ozon_client.calls == []
    assert_no_secrets(response)


def test_successful_connection_test_updates_only_safe_timestamp(local_api):
    client, vault, ozon_client = local_api
    setup(client)
    response = client.post("/api/ozon/connection/test")
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["locked"] is False
    assert response.json()["last_connection_check"].endswith("+00:00")
    assert len(ozon_client.calls) == 1
    assert vault.require_credentials() == OzonCredentials(CLIENT_ID, API_KEY)
    assert set(response.json()) == {"configured", "locked", "masked_client_id_suffix", "last_connection_check", "credential_context_id"}
    assert_no_secrets(response)


def test_setup_replacement_invalidates_old_api_source_and_shipment_plan(local_api, monkeypatch):
    from tests.ozon.test_source_store import snap

    client, _, _ = local_api
    api.OZON_SOURCE_STORE.put(snap("old-source"))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE, "clear", lambda: setattr(
        test_setup_replacement_invalidates_old_api_source_and_shipment_plan, "plan_cleared", True))

    response = setup(client)

    assert response.status_code == 200
    assert api.OZON_SOURCE_STORE.get("old-source") is None
    assert getattr(test_setup_replacement_invalidates_old_api_source_and_shipment_plan, "plan_cleared", False)
