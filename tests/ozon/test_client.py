import json
import logging

import pytest

from backend.ozon.client import (
    OzonClient, OzonClientError, OzonRequestPolicy, TransportResponse,
)
from backend.ozon.contracts import OzonCredentials, OzonErrorCode
from backend.ozon.endpoints import OZON_API_BASE


class VaultStub:
    credentials = OzonCredentials("sensitive-client", "sensitive-api-key")

    def require_credentials(self):
        return self.credentials


class FakeTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response(status=200, body=b'{"result":"ok"}', headers=None):
    return TransportResponse(status, headers or {}, body)


def test_post_json_uses_fixed_host_credentials_json_and_finite_timeout():
    transport = FakeTransport([response()])
    client = OzonClient(VaultStub(), transport=transport, timeout=7.5)
    assert client.post_json("/v1/test", {"hello": "world"}, policy=OzonRequestPolicy(False)) == {"result": "ok"}
    request, timeout = transport.calls[0]
    assert request.full_url == OZON_API_BASE + "/v1/test"
    assert request.method == "POST" and json.loads(request.data) == {"hello": "world"}
    assert request.get_header("Client-id") == "sensitive-client"
    assert request.get_header("Api-key") == "sensitive-api-key"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 7.5 and 0 < timeout < 60


@pytest.mark.parametrize("path", [
    "https://evil.example/test", "//evil.example/test", "test", "/../test",
    "/v1/test?api_key=secret", "/v1/test#fragment",
])
def test_arbitrary_or_invalid_paths_are_rejected_without_transport(path):
    transport = FakeTransport([])
    with pytest.raises(ValueError, match="relative Ozon API path"):
        OzonClient(VaultStub(), transport=transport).post_json(path, {}, policy=OzonRequestPolicy(False))
    assert transport.calls == []


def test_malformed_json_is_normalized():
    client = OzonClient(VaultStub(), transport=FakeTransport([response(body=b"not-json")]))
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is OzonErrorCode.INVALID_RESPONSE


def test_retry_safe_is_bounded_and_respects_numeric_retry_after():
    transport = FakeTransport([
        response(429, b"{}", {"Retry-After": "2"}), response(503, b"{}"), response(),
    ])
    sleeps = []
    client = OzonClient(VaultStub(), transport=transport, sleeper=sleeps.append)
    result = client.post_json("/v1/test", {}, policy=OzonRequestPolicy(True, max_attempts=3))
    assert result == {"result": "ok"}
    assert len(transport.calls) == 3
    assert sleeps == [2.0, 1.0]


def test_retry_after_above_wait_budget_stops_without_early_retry():
    transport = FakeTransport([
        response(429, b"{}", {"Retry-After": "120"}), response(),
    ])
    sleeps = []
    client = OzonClient(VaultStub(), transport=transport, sleeper=sleeps.append)

    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(True, max_attempts=3))

    assert error.value.code is OzonErrorCode.RATE_LIMITED
    assert len(transport.calls) == 1
    assert sleeps == []


def test_non_retry_safe_policy_makes_exactly_one_attempt():
    transport = FakeTransport([response(503), response()])
    client = OzonClient(VaultStub(), transport=transport)
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False, max_attempts=99))
    assert error.value.code is OzonErrorCode.UNAVAILABLE
    assert len(transport.calls) == 1


def test_errors_and_logs_do_not_expose_credentials(caplog):
    transport = FakeTransport([RuntimeError("sensitive-client sensitive-api-key")])
    client = OzonClient(VaultStub(), transport=transport)
    with caplog.at_level(logging.DEBUG), pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    rendered = str(error.value) + " " + " ".join(record.getMessage() for record in caplog.records)
    assert "sensitive-client" not in rendered
    assert "sensitive-api-key" not in rendered
    assert error.value.code is OzonErrorCode.UNAVAILABLE


@pytest.mark.parametrize("max_attempts", [0, -1, 1.5, True])
def test_request_policy_rejects_non_positive_or_non_integer_attempts(max_attempts):
    with pytest.raises(ValueError, match="positive integer"):
        OzonRequestPolicy(True, max_attempts=max_attempts)


@pytest.mark.parametrize("retry_safe", [1, "yes"])
def test_request_policy_requires_boolean_retry_safe(retry_safe):
    with pytest.raises(ValueError, match="retry_safe must be a bool"):
        OzonRequestPolicy(retry_safe)


@pytest.mark.parametrize("policy", [
    OzonRequestPolicy(True),
    OzonRequestPolicy(False, 1),
    OzonRequestPolicy(True, 3),
])
def test_request_policy_accepts_valid_values(policy):
    assert isinstance(policy.retry_safe, bool)
    assert type(policy.max_attempts) is int


def test_client_timeout_is_validated():
    with pytest.raises(ValueError):
        OzonClient(VaultStub(), timeout=0)


def test_bound_client_rejects_changed_context_before_transport(tmp_path):
    from backend.ozon.vault import CredentialVault

    vault = CredentialVault(tmp_path / "vault.json")
    vault.setup(OzonCredentials("account-a", "key-a"), "password")
    context = vault.capture_context()
    transport = FakeTransport([response()])
    bound = OzonClient(vault, transport=transport).bind_context(context)
    vault.setup(OzonCredentials("account-b", "key-b"), "password")

    with pytest.raises(OzonClientError) as error:
        bound.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))

    assert error.value.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED
    assert transport.calls == []
