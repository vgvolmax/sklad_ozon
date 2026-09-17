"""One-shot A/B probe of the existing urllib and an isolated httpx transport."""

from __future__ import annotations

from dataclasses import dataclass
import ssl
import time
from typing import Callable, Protocol

import httpx

from .client import OzonClientError, OzonRequestPolicy
from .contracts import OzonCredentials
from .endpoints import CONNECTION_TEST_PATH, OZON_API_BASE

URLLIB_TIMEOUT = 10.0
# Matches the timeout profile used by the known-working
# WB_OZON_Yandex Ozon httpx integration.
HTTPX_REFERENCE_TIMEOUT = httpx.Timeout(
    90.0,
    connect=15.0,
    read=60.0,
    write=30.0,
    pool=15.0,
)


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
    outcome: str
    urllib: TransportProbeResult
    httpx: TransportProbeResult


class UrllibProbeClient(Protocol):
    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy,
                  timeout: float | None = None) -> dict: ...


HttpxClientFactory = Callable[..., httpx.Client]


def _elapsed(started: float, clock: Callable[[], float]) -> int:
    return max(0, round((clock() - started) * 1000))


def _request_id(headers: httpx.Headers) -> str | None:
    for name in ("x-o3-trace-id", "x-request-id"):
        value = headers.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _httpx_transport_kind(error: httpx.TransportError) -> str:
    if isinstance(error, httpx.ConnectTimeout): return "connect_timeout"
    if isinstance(error, httpx.ReadTimeout): return "read_timeout"
    if isinstance(error, httpx.WriteTimeout): return "write_timeout"
    if isinstance(error, httpx.PoolTimeout): return "pool_timeout"
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ssl.SSLError): return "tls"
        current = current.__cause__ or current.__context__
    if isinstance(error, httpx.ConnectError): return "connect_error"
    return "network"


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


def _probe_httpx(credentials: OzonCredentials, *, httpx_client_factory: HttpxClientFactory,
                 clock: Callable[[], float]) -> TransportProbeResult:
    started = clock()
    try:
        with httpx_client_factory(follow_redirects=False) as client:
            response = client.post(
                OZON_API_BASE + CONNECTION_TEST_PATH,
                headers={"Client-Id": credentials.client_id, "Api-Key": credentials.api_key,
                         "Content-Type": "application/json"},
                json={}, timeout=HTTPX_REFERENCE_TIMEOUT)
    except httpx.TransportError as error:
        return TransportProbeResult("httpx", False, "transport_error", _elapsed(started, clock),
                                    transport_kind=_httpx_transport_kind(error))
    status = "ok" if response.status_code < 400 else "http_error"
    return TransportProbeResult("httpx", True, status, _elapsed(started, clock),
                                http_status=response.status_code,
                                request_id=_request_id(response.headers))


def compare_transports(urllib_client: UrllibProbeClient, credentials: OzonCredentials, *,
                       httpx_client_factory: HttpxClientFactory = httpx.Client,
                       clock: Callable[[], float] = time.perf_counter) -> TransportComparison:
    """Run probes sequentially without a raw DNS/TLS preflight or fallback."""
    urllib_result = _probe_urllib(urllib_client, clock=clock)
    httpx_result = _probe_httpx(credentials, httpx_client_factory=httpx_client_factory, clock=clock)
    outcome = {(True, True): "both_reached_http", (False, True): "httpx_only_reached_http",
               (True, False): "urllib_only_reached_http",
               (False, False): "neither_reached_http"}[
                   (urllib_result.reached_http, httpx_result.reached_http)]
    return TransportComparison(CONNECTION_TEST_PATH, outcome, urllib_result, httpx_result)
