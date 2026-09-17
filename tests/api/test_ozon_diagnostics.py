from datetime import datetime, timezone

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.diagnostics import OzonConnectionDiagnostic, OzonDiagnosticCheck


CLIENT = TestClient(app)


def diagnostic(*, seller_ok: bool, ready: bool):
    return OzonConnectionDiagnostic(
        1, "ok" if ready else "failed", "api-seller.ozon.ru", 12,
        seller_ok, ready,
        (OzonDiagnosticCheck("dns", "ok", 1),
         OzonDiagnosticCheck("tls", "ok", 2),
         OzonDiagnosticCheck("seller_info", "ok" if seller_ok else "failed", 9,
                             None if seller_ok else "OZON_UNAVAILABLE",
                             transport_kind=None if seller_ok else "timeout"),
         OzonDiagnosticCheck("roles", "ok" if ready else "not_run",
                             1 if ready else None)),
    )


def test_diagnostic_endpoint_uses_active_context_and_returns_safe_wire(monkeypatch):
    seen = []
    monkeypatch.setattr(api_module, "diagnose_connection",
                        lambda bound: seen.append(bound.context_id) or diagnostic(seller_ok=True, ready=True))
    response = CLIENT.post("/api/ozon/connection/diagnose")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["connection_valid"] is True and body["sync_ready"] is True
    assert body["checks"][0] == {"name": "dns", "status": "ok", "elapsed_ms": 1,
                                  "code": None, "http_status": None, "request_id": None,
                                  "transport_kind": None, "permissions": None, "expires_at": None}
    assert seen == [api_module.OZON_VAULT.credential_context_id()]
    assert api_module.OZON_VAULT.status().last_connection_check is not None


def test_failed_seller_probe_does_not_stamp_connection_check(monkeypatch):
    monkeypatch.setattr(api_module, "diagnose_connection",
                        lambda _bound: diagnostic(seller_ok=False, ready=False))
    response = CLIENT.post("/api/ozon/connection/diagnose")
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert api_module.OZON_VAULT.status().last_connection_check is None


def test_roles_failure_still_stamps_authorized_connection(monkeypatch):
    monkeypatch.setattr(api_module, "diagnose_connection",
                        lambda _bound: diagnostic(seller_ok=True, ready=False))
    response = CLIENT.post("/api/ozon/connection/diagnose")
    assert response.json()["connection_valid"] is True
    assert response.json()["sync_ready"] is False
    assert api_module.OZON_VAULT.status().last_connection_check is not None
