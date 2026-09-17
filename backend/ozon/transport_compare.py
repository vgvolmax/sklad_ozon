"""One-shot A/B/C probe of production, sync-httpx, and async-httpx transports."""

from __future__ import annotations

from dataclasses import dataclass
import platform
import socket
import ssl
import time
from typing import Callable, Protocol

import httpx

from .client import OzonClientError, OzonRequestPolicy
from .contracts import OzonCredentials
from .endpoints import CONNECTION_TEST_PATH, OZON_API_BASE

OZON_HOST = "api-seller.ozon.ru"
URLLIB_TIMEOUT = 10.0
# Exact profile used by the known-working WB_OZON_Yandex httpx integration.
HTTPX_REFERENCE_TIMEOUT = httpx.Timeout(
    90.0,
    connect=15.0,
    read=60.0,
    write=30.0,
    pool=15.0,
)


@dataclass(frozen=True, slots=True)
class RuntimeFingerprint:
    python: str
    implementation: str
    architecture: str
    httpx: str
    os: str


@dataclass(frozen=True, slots=True)
class DnsTopology:
    candidate_count: int
    ipv4_count: int
    ipv6_count: int
    families_in_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransportProbeResult:
    transport: str
    reached_http: bool
    status: str
    elapsed_ms: int
    http_status: int | None = None
    request_id: str | None = None
    transport_kind: str | None = None


@dataclass(frozen=True, slots=True)
class TransportComparison:
    endpoint: str
    runtime: RuntimeFingerprint
    dns: DnsTopology
    urllib: TransportProbeResult
    httpx_sync: TransportProbeResult
    httpx_async: TransportProbeResult
    outcome: str


class UrllibProbeClient(Protocol):
    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy,
                  timeout: float | None = None) -> dict: ...


HttpxClientFactory = Callable[..., httpx.Client]
HttpxAsyncClientFactory = Callable[..., httpx.AsyncClient]
DnsResolver = Callable[..., list[tuple]]


def _elapsed(started: float, clock: Callable[[], float]) -> int:
    return max(0, round((clock() - started) * 1000))


def _request_id(headers: httpx.Headers) -> str | None:
    for name in ("x-o3-trace-id", "x-request-id"):
        value = headers.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _httpx_transport_kind(error: httpx.TransportError) -> str:
    if isinstance(error, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(error, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(error, httpx.WriteTimeout):
        return "write_timeout"
    if isinstance(error, httpx.PoolTimeout):
        return "pool_timeout"
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return "tls"
        current = current.__cause__ or current.__context__
    if isinstance(error, httpx.ConnectError):
        return "connect_error"
    return "network"


def _runtime_fingerprint() -> RuntimeFingerprint:
    return RuntimeFingerprint(
        python=platform.python_version(),
        implementation=platform.python_implementation(),
        architecture=platform.architecture()[0],
        httpx=httpx.__version__,
        os=platform.system().lower(),
    )


def _dns_topology(resolver: DnsResolver) -> DnsTopology:
    try:
        candidates = resolver(OZON_HOST, 443, type=socket.SOCK_STREAM)
    except OSError:
        candidates = []
    seen: set[tuple[int, str]] = set()
    families: list[str] = []
    ipv4_count = 0
    ipv6_count = 0
    for family, _socktype, _proto, _canonname, sockaddr in candidates:
        label = {socket.AF_INET: "ipv4", socket.AF_INET6: "ipv6"}.get(family)
        if label is None or not sockaddr:
            continue
        identity = (family, str(sockaddr[0]))
        if identity in seen:
            continue
        seen.add(identity)
        families.append(label)
        if family == socket.AF_INET:
            ipv4_count += 1
        else:
            ipv6_count += 1
    return DnsTopology(len(seen), ipv4_count, ipv6_count, tuple(families))


def _probe_urllib(client: UrllibProbeClient, *, clock: Callable[[], float]) -> TransportProbeResult:
    started = clock()
    try:
        client.post_json(CONNECTION_TEST_PATH, {}, policy=OzonRequestPolicy(
            retry_safe=True, max_attempts=1), timeout=URLLIB_TIMEOUT)
    except OzonClientError as error:
        elapsed_ms = _elapsed(started, clock)
        if error.status is not None:
            status = "ok" if error.status < 400 else "http_error"
            return TransportProbeResult("urllib", True, status, elapsed_ms,
                                        http_status=error.status, request_id=error.request_id)
        return TransportProbeResult("urllib", False, "transport_error", elapsed_ms,
                                    transport_kind=error.transport_kind or "network")
    return TransportProbeResult("urllib", True, "ok", _elapsed(started, clock), http_status=200)


def _probe_httpx_sync(credentials: OzonCredentials, *, httpx_client_factory: HttpxClientFactory,
                      clock: Callable[[], float]) -> TransportProbeResult:
    started = clock()
    try:
        with httpx_client_factory(follow_redirects=False) as client:
            response = client.post(
                OZON_API_BASE + CONNECTION_TEST_PATH,
                headers=_headers(credentials), json={}, timeout=HTTPX_REFERENCE_TIMEOUT)
    except httpx.TransportError as error:
        return TransportProbeResult("httpx_sync", False, "transport_error",
                                    _elapsed(started, clock),
                                    transport_kind=_httpx_transport_kind(error))
    return _http_response("httpx_sync", response, _elapsed(started, clock))


async def _probe_httpx_async(
    credentials: OzonCredentials, *, httpx_async_client_factory: HttpxAsyncClientFactory,
    clock: Callable[[], float],
) -> TransportProbeResult:
    started = clock()
    try:
        async with httpx_async_client_factory(
            timeout=HTTPX_REFERENCE_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                OZON_API_BASE + CONNECTION_TEST_PATH,
                headers=_headers(credentials), json={},
            )
    except httpx.TransportError as error:
        return TransportProbeResult("httpx_async", False, "transport_error",
                                    _elapsed(started, clock),
                                    transport_kind=_httpx_transport_kind(error))
    return _http_response("httpx_async", response, _elapsed(started, clock))


def _headers(credentials: OzonCredentials) -> dict[str, str]:
    return {"Client-Id": credentials.client_id, "Api-Key": credentials.api_key,
            "Content-Type": "application/json"}


def _http_response(transport: str, response: httpx.Response,
                   elapsed_ms: int) -> TransportProbeResult:
    status = "ok" if response.status_code < 400 else "http_error"
    return TransportProbeResult(transport, True, status, elapsed_ms,
                                http_status=response.status_code,
                                request_id=_request_id(response.headers))


def _outcome(urllib: bool, sync: bool, async_: bool) -> str:
    if urllib and sync and async_:
        return "all_reached_http"
    if not urllib and not sync and not async_:
        return "none_reached_http"
    if not urllib and not sync and async_:
        return "async_only_reached_http"
    if urllib and not sync and not async_:
        return "urllib_only_reached_http"
    return "mixed"


async def compare_transports(
    urllib_client: UrllibProbeClient,
    credentials: OzonCredentials,
    *,
    httpx_client_factory: HttpxClientFactory = httpx.Client,
    httpx_async_client_factory: HttpxAsyncClientFactory = httpx.AsyncClient,
    dns_resolver: DnsResolver = socket.getaddrinfo,
    clock: Callable[[], float] = time.perf_counter,
) -> TransportComparison:
    """Run three real requests sequentially, with no preflight or fallback."""
    runtime = _runtime_fingerprint()
    dns = _dns_topology(dns_resolver)
    urllib_result = _probe_urllib(urllib_client, clock=clock)
    sync_result = _probe_httpx_sync(
        credentials, httpx_client_factory=httpx_client_factory, clock=clock)
    async_result = await _probe_httpx_async(
        credentials, httpx_async_client_factory=httpx_async_client_factory, clock=clock)
    outcome = _outcome(urllib_result.reached_http, sync_result.reached_http,
                       async_result.reached_http)
    return TransportComparison(
        CONNECTION_TEST_PATH, runtime, dns, urllib_result, sync_result, async_result, outcome)
