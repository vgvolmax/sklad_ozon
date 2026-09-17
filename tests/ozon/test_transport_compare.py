import json
import socket

import httpx
import pytest

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


def sync_transport(status=200, *, error=None):
    calls, clients = [], []

    def handler(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, headers={"x-request-id": "sync-id"}, json={})

    def factory(**kwargs):
        clients.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory, calls, clients


def async_transport(status=200, *, error=None):
    calls, clients = [], []

    async def handler(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(status, headers={"x-o3-trace-id": "async-id"}, json={})

    def factory(**kwargs):
        clients.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory, calls, clients


def failure(kind="timeout", status=None):
    return OzonClientError(
        OzonErrorCode.UNAVAILABLE, "safe", status=status,
        request_id="urllib-request", transport_kind=kind,
    )


async def run(urllib_error=None, sync_status=200, async_status=200,
              sync_error=None, async_error=None, dns_resolver=None):
    urllib = UrllibProbe(urllib_error)
    sync_factory, sync_calls, sync_clients = sync_transport(sync_status, error=sync_error)
    async_factory, async_calls, async_clients = async_transport(async_status, error=async_error)
    result = await compare_transports(
        urllib, OzonCredentials("client-secret", "key-secret"),
        httpx_client_factory=sync_factory,
        httpx_async_client_factory=async_factory,
        dns_resolver=dns_resolver or (lambda *args, **kwargs: []),
    )
    return result, urllib, sync_calls, async_calls, sync_clients, async_clients


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("urllib_error", "sync_error", "async_error", "expected"),
    [
        (failure(), httpx.ConnectTimeout("sync"), None, "async_only_reached_http"),
        (None, None, None, "all_reached_http"),
        (failure(), httpx.ConnectTimeout("sync"), httpx.ReadTimeout("async"), "none_reached_http"),
        (failure(), None, httpx.ReadTimeout("async"), "mixed"),
    ],
)
async def test_outcomes(urllib_error, sync_error, async_error, expected):
    result, *_ = await run(urllib_error, sync_error=sync_error, async_error=async_error)
    assert result.outcome == expected


@pytest.mark.anyio
async def test_all_http_responses_count_as_reached_http():
    result, *_ = await run(failure(status=401), sync_status=403, async_status=500)
    assert result.outcome == "all_reached_http"
    assert result.urllib.reached_http and result.urllib.http_status == 401
    assert result.httpx_sync.reached_http and result.httpx_sync.http_status == 403
    assert result.httpx_async.reached_http and result.httpx_async.http_status == 500


@pytest.mark.anyio
async def test_all_transports_send_same_post_headers_and_empty_json():
    result, urllib, sync_calls, async_calls, sync_clients, async_clients = await run()
    path, payload, policy, timeout = urllib.calls[0]
    assert path == result.endpoint == "/v1/seller/info"
    assert payload == {} and policy.max_attempts == 1 and timeout == 10.0
    for request in (*sync_calls, *async_calls):
        assert request.method == "POST"
        assert request.url == httpx.URL("https://api-seller.ozon.ru/v1/seller/info")
        assert request.content == b"{}"
        assert request.headers["Client-Id"] == "client-secret"
        assert request.headers["Api-Key"] == "key-secret"
        assert request.headers["Content-Type"] == "application/json"
    assert async_clients[0]["follow_redirects"] is True
    timeout = async_clients[0]["timeout"]
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (15.0, 60.0, 30.0, 15.0)


@pytest.mark.anyio
async def test_async_timeout_kinds_and_no_raw_exception_or_credentials():
    result, *_ = await run(
        failure(), sync_error=httpx.ConnectTimeout("client-secret"),
        async_error=httpx.ReadTimeout("key-secret raw exception"),
    )
    assert result.httpx_sync.transport_kind == "connect_timeout"
    assert result.httpx_async.transport_kind == "read_timeout"
    rendered = repr(result)
    assert "client-secret" not in rendered and "key-secret" not in rendered
    assert "raw exception" not in rendered


@pytest.mark.anyio
async def test_dns_topology_deduplicates_family_and_address_without_serializing_ips():
    entries = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.0.2.1", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.2", 443)),
    ]
    seen = []

    def resolver(*args, **kwargs):
        seen.append((args, kwargs))
        return entries

    result, *_ = await run(dns_resolver=resolver)
    assert seen == [(('api-seller.ozon.ru', 443), {'type': socket.SOCK_STREAM})]
    assert result.dns.candidate_count == 3
    assert result.dns.ipv4_count == 2 and result.dns.ipv6_count == 1
    assert result.dns.families_in_order == ("ipv4", "ipv6", "ipv4")
    serialized = json.dumps(result.dns.__dict__ if hasattr(result.dns, "__dict__") else repr(result.dns))
    assert "192.0.2" not in serialized and "2001:db8" not in serialized


@pytest.mark.anyio
async def test_runtime_fingerprint_is_bounded_and_has_no_executable_path():
    result, *_ = await run()
    assert result.runtime.python
    assert result.runtime.implementation
    assert result.runtime.architecture
    assert result.runtime.httpx == httpx.__version__
    rendered = repr(result.runtime)
    assert "executable" not in rendered.lower()
    assert "/" not in rendered and "\\" not in rendered
