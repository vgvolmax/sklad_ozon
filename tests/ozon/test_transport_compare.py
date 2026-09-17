import httpx

from backend.ozon.client import OzonClientError
from backend.ozon.contracts import OzonCredentials, OzonErrorCode
from backend.ozon.transport_compare import compare_transports


class UrllibProbe:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def post_json(self, path, payload, *, policy, timeout=None):
        self.calls.append((path, payload, policy, timeout))
        if self.error:
            raise self.error
        return {"ok": True}


def httpx_transport(status=200, *, error=None):
    calls = []

    def handler(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, headers={"x-request-id": "req-safe"}, json={})

    return lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs), calls


def failure(kind="timeout", status=None):
    return OzonClientError(
        OzonErrorCode.UNAVAILABLE, "safe", status=status,
        request_id="urllib-request", transport_kind=kind,
    )


def run(urllib_error=None, http_status=200, http_error=None):
    urllib = UrllibProbe(urllib_error)
    factory, calls = httpx_transport(http_status, error=http_error)
    result = compare_transports(
        urllib, OzonCredentials("client-secret", "key-secret"),
        httpx_client_factory=factory,
    )
    return result, urllib, calls


def test_urllib_timeout_and_httpx_200():
    result, _, _ = run(failure())
    assert result.outcome == "httpx_only_reached_http"
    assert not result.urllib.reached_http and result.urllib.transport_kind == "timeout"
    assert result.httpx.reached_http and result.httpx.http_status == 200


def test_both_200_reach_http():
    result, _, _ = run()
    assert result.outcome == "both_reached_http"


def test_urllib_200_httpx_timeout():
    request = httpx.Request("POST", "https://api-seller.ozon.ru/v1/seller/info")
    result, _, _ = run(http_error=httpx.ReadTimeout("private raw details", request=request))
    assert result.outcome == "urllib_only_reached_http"
    assert result.httpx.status == "transport_error"
    assert result.httpx.transport_kind == "read_timeout"


def test_both_transport_failures_do_not_reach_http():
    request = httpx.Request("POST", "https://api-seller.ozon.ru/v1/seller/info")
    result, _, _ = run(failure(), http_error=httpx.ConnectTimeout("secret", request=request))
    assert result.outcome == "neither_reached_http"
    assert result.httpx.transport_kind == "connect_timeout"


def test_http_errors_count_as_reached_http():
    for status in (401, 403, 500):
        result, _, _ = run(failure(status=401), http_status=status)
        assert result.outcome == "both_reached_http"
        assert result.httpx.reached_http is True
        assert result.httpx.http_status == status
        assert result.httpx.status == "http_error"


def test_both_transports_send_same_post_and_empty_json():
    result, urllib, calls = run()
    path, payload, policy, timeout = urllib.calls[0]
    assert path == result.endpoint == "/v1/seller/info"
    assert payload == {} and policy.max_attempts == 1 and timeout == 10.0
    request = calls[0]
    assert request.method == "POST"
    assert request.url.host == "api-seller.ozon.ru" and request.url.path == path
    assert request.content == b"{}"
    assert request.headers["Client-Id"] == "client-secret"
    assert request.headers["Api-Key"] == "key-secret"
    assert request.headers["Content-Type"] == "application/json"


def test_response_has_no_raw_exception_or_credentials():
    request = httpx.Request("POST", "https://api-seller.ozon.ru/v1/seller/info")
    result, _, _ = run(failure(), http_error=httpx.ConnectError(
        "client-secret key-secret raw exception", request=request))
    rendered = repr(result)
    assert result.httpx.transport_kind == "connect_error"
    assert "client-secret" not in rendered and "key-secret" not in rendered
    assert "raw exception" not in rendered
