import json
from pathlib import Path
import socket
import ssl

import pytest

from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.diagnostics import (
    diagnose_connection, diagnose_dns, diagnose_roles, diagnose_seller_info,
    diagnose_tls, parse_roles,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "ozon" / "roles_v1_full.json"
REQUIRED_SYNC_METHODS = (
    "/v3/posting/fbo/list",
    "/v4/posting/fbs/list",
    "/v2/cluster/list",
    "/v1/cluster/list",
    "/v1/warehouse/fbo/seller/list",
    "/v3/product/list",
    "/v1/analytics/stocks",
    "/v2/product/info/stocks-by-warehouse/fbs",
    "/v3/supply-order/list",
    "/v3/supply-order/get",
    "/v1/supply-order/bundle",
    "/v1/product/placement-zone/info",
)


class Client:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post_json(self, path, payload, *, policy, timeout=None):
        self.calls.append((path, policy.max_attempts, timeout))
        if self.error:
            raise self.error
        return self.responses.pop(0)


def full_roles():
    return json.loads(FIXTURE.read_text())


def test_dns_success_timeout_and_error_are_normalized():
    assert diagnose_dns(resolver=lambda _h, _t: [(1,)]).status == "ok"
    timeout = diagnose_dns(resolver=lambda *_: (_ for _ in ()).throw(TimeoutError("secret")))
    failed = diagnose_dns(resolver=lambda *_: (_ for _ in ()).throw(socket.gaierror("secret")))
    assert (timeout.code, timeout.transport_kind) == ("TIMEOUT", "timeout")
    assert (failed.code, failed.transport_kind) == ("DNS_FAILED", "dns")
    assert "secret" not in repr(timeout) + repr(failed)


def test_tls_success_and_failure_classes_are_normalized():
    assert diagnose_tls(connector=lambda *_: None).status == "ok"
    cases = [
        (socket.timeout("secret"), "TIMEOUT", "timeout"),
        (ssl.SSLError("secret"), "TLS_HANDSHAKE_FAILED", "tls_handshake"),
        (ssl.SSLCertVerificationError("secret"), "TLS_CERTIFICATE_FAILED", "tls_certificate"),
        (ConnectionRefusedError("secret"), "TCP_CONNECTION_FAILED", "tcp_connection"),
    ]
    for exc, code, kind in cases:
        result = diagnose_tls(connector=lambda *_, exc=exc: (_ for _ in ()).throw(exc))
        assert (result.code, result.transport_kind) == (code, kind)
        assert "secret" not in repr(result)


@pytest.mark.parametrize("code,status,expected", [
    (None, None, ("ok", None)),
    (OzonErrorCode.AUTH_FAILED, 401, ("failed", "OZON_AUTH_FAILED")),
    (OzonErrorCode.PERMISSION_DENIED, 403, ("failed", "OZON_PERMISSION_MISSING")),
    (OzonErrorCode.RATE_LIMITED, 429, ("failed", "OZON_RATE_LIMITED")),
    (OzonErrorCode.UNAVAILABLE, 503, ("failed", "OZON_UNAVAILABLE")),
    (OzonErrorCode.INVALID_RESPONSE, 200, ("failed", "OZON_INVALID_RESPONSE")),
])
def test_seller_info_normalizes_http_and_invalid_json(code, status, expected):
    error = None if code is None else OzonClientError(code, "safe", status=status,
                                                       transport_kind="timeout" if code is OzonErrorCode.UNAVAILABLE else None)
    result = diagnose_seller_info(Client([{}], error))
    assert (result.status, result.code) == expected


def test_seller_info_uses_one_attempt_and_short_timeout():
    client = Client([{}])
    diagnose_seller_info(client)
    assert client.calls == [("/v1/seller/info", 1, 10.0)]


def test_roles_current_wire_full_and_expiry():
    payload = full_roles()
    assert payload["roles"][0]["methods"] == list(REQUIRED_SYNC_METHODS)
    result = diagnose_roles(Client([payload]))
    assert result.status == "ok" and all(result.permissions.values())
    assert result.expires_at == "2027-12-31T23:59:59Z"


@pytest.mark.parametrize("method", REQUIRED_SYNC_METHODS)
def test_roles_requires_every_endpoint_used_by_heavy_sync(method):
    payload = full_roles()
    payload["roles"][0]["methods"].remove(method)
    result = diagnose_roles(Client([payload]))
    assert result.code == "OZON_PERMISSION_MISSING"
    assert result.status == "failed"


def test_roles_empty_and_malformed_fail_closed():
    permissions, expiry = parse_roles({"roles": []})
    assert not any(permissions.values()) and expiry is None

    malformed = (
        {"unexpected": []},
        {"roles": [{"name": "x", "methods": [{}]}]},
        {"roles": [{"name": "x", "methods": "bad"}]},
        {"result": [{"name": "legacy-invented-shape", "roles": []}]},
    )
    for payload in malformed:
        assert diagnose_roles(Client([payload])).code == "OZON_ROLES_INVALID_RESPONSE"


def test_roles_expiry_is_optional_but_must_be_a_nonblank_string_when_present():
    payload = full_roles()
    del payload["expires_at"]
    assert diagnose_roles(Client([payload])).expires_at is None

    for invalid in ("", 123, [], {}):
        payload = full_roles()
        payload["expires_at"] = invalid
        assert diagnose_roles(Client([payload])).code == "OZON_ROLES_INVALID_RESPONSE"


def test_fail_fast_marks_later_checks_not_run():
    client = Client([{}])
    result = diagnose_connection(client, resolver=lambda *_: (_ for _ in ()).throw(socket.gaierror()),
                                 connector=lambda *_: pytest.fail("TLS ran"))
    assert [x.status for x in result.checks] == ["failed", "not_run", "not_run", "not_run"]
    assert client.calls == [] and result.connection_valid is False and result.sync_ready is False


def test_successful_preflight_is_ready():
    result = diagnose_connection(Client([{}, full_roles()]), resolver=lambda *_: (), connector=lambda *_: None)
    assert result.status == "ok" and result.connection_valid is True and result.sync_ready is True
