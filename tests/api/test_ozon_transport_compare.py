from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app
from backend.ozon.transport_compare import (
    DnsTopology,
    RuntimeFingerprint,
    TransportComparison,
    TransportProbeResult,
)
from backend.ozon.vault import CredentialVault


CLIENT = TestClient(app)


def test_endpoint_uses_active_context_and_safe_wire(monkeypatch):
    seen = []
    comparison = TransportComparison(
        endpoint="/v1/seller/info",
        runtime=RuntimeFingerprint("3.13.14", "CPython", "64bit", "0.28.1", "windows"),
        dns=DnsTopology(2, 2, 0, ("ipv4", "ipv4")),
        urllib=TransportProbeResult("urllib", False, "transport_error", 10_001,
                                    transport_kind="timeout"),
        httpx_sync=TransportProbeResult("httpx_sync", False, "transport_error", 15_002,
                                       transport_kind="connect_timeout"),
        httpx_async=TransportProbeResult("httpx_async", True, "ok", 250, http_status=200,
                                        request_id="safe-id"),
        outcome="async_only_reached_http",
    )

    async def compare(bound, credentials):
        seen.append((bound.context_id, credentials))
        return comparison

    monkeypatch.setattr(api_module, "compare_transports", compare)
    response = CLIENT.post("/api/ozon/connection/transport-compare")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"endpoint", "runtime", "dns", "urllib", "httpx_sync", "httpx_async", "outcome"}
    assert body["runtime"] == {"python": "3.13.14", "implementation": "CPython", "architecture": "64bit", "httpx": "0.28.1", "os": "windows"}
    assert body["dns"] == {"candidate_count": 2, "ipv4_count": 2, "ipv6_count": 0,
                           "families_in_order": ["ipv4", "ipv4"]}
    assert body["httpx_async"]["request_id"] == "safe-id"
    rendered = response.text
    assert "client-secret" not in rendered and "key-secret" not in rendered
    assert seen[0][0] == api_module.OZON_VAULT.credential_context_id()


def test_missing_credentials_do_not_start_network_probes(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "OZON_VAULT", CredentialVault(tmp_path / "missing.json"))
    called = False

    async def compare(*args):
        nonlocal called
        called = True

    monkeypatch.setattr(api_module, "compare_transports", compare)
    response = CLIENT.post("/api/ozon/connection/transport-compare")
    assert response.status_code == 423
    assert called is False
