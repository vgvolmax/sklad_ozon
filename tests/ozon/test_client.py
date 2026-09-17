import json
import logging
import socket
from threading import Event, Thread

import pytest

from backend.ozon.client import (
    MAX_VENDOR_MESSAGE_CHARS, OzonClient, OzonClientError, OzonRequestPolicy,
    TransportResponse,
)
from backend.ozon.contracts import OzonCredentialContext, OzonCredentials, OzonErrorCode
from backend.ozon.endpoints import OZON_API_BASE


class VaultStub:
    credentials = OzonCredentials("sensitive-client", "sensitive-api-key")
    context = OzonCredentialContext("context", credentials, 1)

    def capture_context(self):
        return self.context

    def is_context_active(self, context):
        return context is self.context


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
    client = OzonClient(VaultStub(), transport=FakeTransport([
        response(body=b"not-json", headers={"X-Request-ID": " response-trace "}),
    ]))
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is OzonErrorCode.INVALID_RESPONSE
    assert error.value.endpoint == "/v1/test"
    assert error.value.status == 200
    assert error.value.request_id == "response-trace"


def test_http_400_preserves_only_allowlisted_safe_evidence():
    body = b'''{
        "code": 3,
        "message": "sku or offer_id is required",
        "details": [{"debug": "MUST_NOT_SURVIVE"}]
    }'''
    client = OzonClient(VaultStub(), transport=FakeTransport([
        response(400, body, {"X-O3-Trace-Id": "trace-123"}),
    ]))

    with pytest.raises(OzonClientError) as error:
        client.post_json(
            "/v2/product/info/stocks-by-warehouse/fbs",
            {"limit": 1000},
            policy=OzonRequestPolicy(False),
        )

    assert error.value.code is OzonErrorCode.INVALID_REQUEST
    assert error.value.endpoint == "/v2/product/info/stocks-by-warehouse/fbs"
    assert error.value.status == 400
    assert error.value.vendor_code == "3"
    assert error.value.vendor_message == "sku or offer_id is required"
    assert error.value.request_id == "trace-123"
    assert not hasattr(error.value, "details")
    assert "MUST_NOT_SURVIVE" not in repr(error.value)
    assert "MUST_NOT_SURVIVE" not in str(error.value)


@pytest.mark.parametrize("status,expected", [
    (401, OzonErrorCode.AUTH_FAILED),
    (403, OzonErrorCode.PERMISSION_DENIED),
])
def test_unauthorized_and_forbidden_have_distinct_classifications(status, expected):
    transport = FakeTransport([response(status, b"{}")])
    client = OzonClient(VaultStub(), transport=transport)
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is expected
    assert error.value.status == status


def test_malformed_error_json_keeps_response_metadata():
    client = OzonClient(VaultStub(), transport=FakeTransport([
        response(400, b"not-json", {"x-O3-tRaCe-Id": "trace-x"}),
    ]))
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is OzonErrorCode.INVALID_REQUEST
    assert error.value.endpoint == "/v1/test"
    assert error.value.status == 400
    assert error.value.request_id == "trace-x"
    assert error.value.vendor_code is None
    assert error.value.vendor_message is None


def test_nested_vendor_error_fields_are_not_retained():
    client = OzonClient(VaultStub(), transport=FakeTransport([
        response(400, b'{"code":{"unexpected":1},"message":{"unexpected":2},"details":["raw"]}'),
    ]))
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.vendor_code is None
    assert error.value.vendor_message is None


def test_vendor_message_is_normalized_bounded_and_credentials_safe(caplog):
    raw_message = " \n sensitive-client\t sensitive-api-key " + ("x" * 500)
    body = json.dumps({"code": "BAD", "message": raw_message, "details": "raw-body-secret"}).encode()
    client = OzonClient(VaultStub(), transport=FakeTransport([response(400, body)]))
    with caplog.at_level(logging.DEBUG), pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))

    rendered = " ".join((str(error.value), repr(error.value), error.value.vendor_message or "",
                         *(record.getMessage() for record in caplog.records)))
    assert "sensitive-client" not in rendered
    assert "sensitive-api-key" not in rendered
    assert "raw-body-secret" not in rendered
    assert len(error.value.vendor_message) <= MAX_VENDOR_MESSAGE_CHARS
    assert "\n" not in error.value.vendor_message


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
        response(429, b'{"code":"TOO_MANY","message":"slow down"}',
                 {"Retry-After": "120", "X-O3-Trace-ID": "trace-budget"}), response(),
    ])
    sleeps = []
    client = OzonClient(VaultStub(), transport=transport, sleeper=sleeps.append)

    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(True, max_attempts=3))

    assert error.value.code is OzonErrorCode.RATE_LIMITED
    assert error.value.status == 429
    assert error.value.endpoint == "/v1/test"
    assert error.value.request_id == "trace-budget"
    assert error.value.vendor_code == "TOO_MANY"
    assert error.value.vendor_message == "slow down"
    assert len(transport.calls) == 1
    assert sleeps == []


def test_non_retry_safe_policy_makes_exactly_one_attempt():
    transport = FakeTransport([response(503), response()])
    client = OzonClient(VaultStub(), transport=transport)
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False, max_attempts=99))
    assert error.value.code is OzonErrorCode.UNAVAILABLE
    assert len(transport.calls) == 1


def test_exhausted_retries_preserve_final_response_evidence():
    transport = FakeTransport([
        response(503, b"{}", {"X-O3-Trace-ID": "trace-first"}),
        response(503, b"{}", {"X-O3-Trace-ID": "trace-second"}),
        response(503, b"{}", {"X-O3-Trace-ID": "trace-third"}),
    ])
    client = OzonClient(VaultStub(), transport=transport, sleeper=lambda _delay: None)
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(True))
    assert len(transport.calls) == 3
    assert error.value.status == 503
    assert error.value.endpoint == "/v1/test"
    assert error.value.request_id == "trace-third"


def test_errors_and_logs_do_not_expose_credentials(caplog):
    transport = FakeTransport([RuntimeError("sensitive-client sensitive-api-key")])
    client = OzonClient(VaultStub(), transport=transport)
    with caplog.at_level(logging.DEBUG), pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    rendered = str(error.value) + " " + " ".join(record.getMessage() for record in caplog.records)
    assert "sensitive-client" not in rendered
    assert "sensitive-api-key" not in rendered
    assert error.value.code is OzonErrorCode.UNAVAILABLE
    assert error.value.endpoint == "/v1/test"
    assert error.value.status is None
    assert error.value.vendor_code is None
    assert error.value.vendor_message is None
    assert error.value.request_id is None


@pytest.mark.parametrize("failure,kind", [
    (TimeoutError("secret timeout detail"), "timeout"),
    (ConnectionResetError("secret reset detail"), "connection_reset"),
    (socket.gaierror("secret dns detail"), "dns"),
])
def test_transport_failures_have_safe_bounded_diagnostics(failure, kind):
    transport = FakeTransport([failure, failure, failure])
    client = OzonClient(VaultStub(), transport=transport, sleeper=lambda _delay: None)

    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(True))

    assert error.value.transport_kind == kind
    assert error.value.attempts == 3
    assert error.value.elapsed_ms is not None and error.value.elapsed_ms >= 0
    assert "secret" not in str(error.value)


def test_http_503_is_not_misclassified_as_transport_timeout():
    client = OzonClient(VaultStub(), transport=FakeTransport([
        response(503, b'{"code":"TEMP","message":"retry"}',
                 {"X-O3-Trace-ID": "trace-503"}),
    ]))
    with pytest.raises(OzonClientError) as error:
        client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.status == 503
    assert error.value.request_id == "trace-503"
    assert error.value.vendor_code == "TEMP"
    assert error.value.transport_kind is None


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
    assert error.value.endpoint == "/v1/test"
    assert transport.calls == []


def test_bound_client_rejects_lock_before_transport(tmp_path):
    from backend.ozon.vault import CredentialVault

    vault = CredentialVault(tmp_path / "vault.json")
    vault.setup(OzonCredentials("account-a", "key-a"), "password")
    transport = FakeTransport([response()])
    bound = OzonClient(vault, transport=transport).bind_context(vault.capture_context())
    vault.lock()

    with pytest.raises(OzonClientError) as error:
        bound.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED
    assert transport.calls == []


def test_old_bound_client_stays_revoked_after_unlock(tmp_path):
    from backend.ozon.vault import CredentialVault

    vault = CredentialVault(tmp_path / "vault.json")
    vault.setup(OzonCredentials("account-a", "key-a"), "password")
    transport = FakeTransport([response()])
    client = OzonClient(vault, transport=transport)
    old = client.bind_context(vault.capture_context())
    vault.lock()
    vault.unlock("password")

    with pytest.raises(OzonClientError) as error:
        old.post_json("/v1/test", {}, policy=OzonRequestPolicy(False))
    assert error.value.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED
    assert client.bind_context(vault.capture_context()).post_json(
        "/v1/test", {}, policy=OzonRequestPolicy(False)) == {"result": "ok"}


def test_lock_while_transport_is_in_flight_discards_response(tmp_path):
    from backend.ozon.vault import CredentialVault

    vault = CredentialVault(tmp_path / "vault.json")
    vault.setup(OzonCredentials("account-a", "key-a"), "password")
    entered, release = Event(), Event()

    def blocked_transport(request, timeout):
        entered.set()
        assert release.wait(2)
        return response()

    bound = OzonClient(vault, transport=blocked_transport).bind_context(vault.capture_context())
    outcomes = []
    thread = Thread(target=lambda: _capture_client_outcome(outcomes, bound))
    thread.start()
    assert entered.wait(2)
    vault.lock()
    release.set()
    thread.join(2)
    assert isinstance(outcomes[0], OzonClientError)
    assert outcomes[0].code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED


def _capture_client_outcome(outcomes, client):
    try:
        outcomes.append(client.post_json("/v1/test", {}, policy=OzonRequestPolicy(False)))
    except BaseException as exc:
        outcomes.append(exc)


@pytest.mark.parametrize("bound", [False, True])
def test_lock_during_retry_sleep_prevents_next_transport(bound, tmp_path):
    from backend.ozon.vault import CredentialVault

    vault = CredentialVault(tmp_path / "vault.json")
    vault.setup(OzonCredentials("account-a", "key-a"), "password")
    transport = FakeTransport([response(503), response()])
    client = OzonClient(vault, transport=transport, sleeper=lambda _delay: vault.lock())
    active = client.bind_context(vault.capture_context()) if bound else client

    with pytest.raises(OzonClientError) as error:
        active.post_json("/v1/test", {}, policy=OzonRequestPolicy(True))
    assert error.value.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED
    assert len(transport.calls) == 1
