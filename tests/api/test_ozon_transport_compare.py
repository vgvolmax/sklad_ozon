from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.transport_compare import TransportComparison, TransportProbeResult
from backend.ozon.vault import CredentialVault


CLIENT = TestClient(app)


def test_endpoint_uses_active_context_and_safe_wire(monkeypatch):
    seen = []
    comparison = TransportComparison(
        "/v1/seller/info", "httpx_only_reached_http",
        TransportProbeResult("urllib", False, "transport_error", 10_001,
                             transport_kind="timeout"),
        TransportProbeResult("httpx", True, "ok", 250, http_status=200,
                             request_id="safe-id"),
    )
    monkeypatch.setattr(api_module, "compare_transports", lambda bound, credentials:
                        seen.append((bound.context_id, credentials)) or comparison)
    response = CLIENT.post("/api/ozon/connection/transport-compare")
    assert response.status_code == 200
    assert response.json() == {
        "endpoint": "/v1/seller/info", "outcome": "httpx_only_reached_http",
        "urllib": {"transport": "urllib", "reached_http": False,
                   "status": "transport_error", "elapsed_ms": 10001,
                   "http_status": None, "request_id": None,
                   "transport_kind": "timeout"},
        "httpx": {"transport": "httpx", "reached_http": True, "status": "ok",
                  "elapsed_ms": 250, "http_status": 200,
                  "request_id": "safe-id", "transport_kind": None},
    }
    assert seen[0][0] == api_module.OZON_VAULT.credential_context_id()


def test_missing_credentials_do_not_start_network_probes(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "OZON_VAULT", CredentialVault(tmp_path / "missing.json"))
    called = False

    def compare(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(api_module, "compare_transports", compare)
    response = CLIENT.post("/api/ozon/connection/transport-compare")
    assert response.status_code == 423
    assert called is False
