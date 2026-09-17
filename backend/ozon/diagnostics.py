"""Fast, public-safe preflight diagnostics for the fixed Ozon Seller API host."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import socket
import ssl
import threading
import time
from typing import Callable, Mapping, Protocol

from .client import BoundOzonClient, OzonClientError, OzonRequestPolicy
from .contracts import OzonErrorCode
from .endpoints import (
    CLUSTERS_V1_PATH,
    CLUSTERS_V2_PATH,
    CONNECTION_TEST_PATH,
    FBO_POSTINGS_PATH,
    FBO_STOCK_PATH,
    FBS_POSTINGS_PATH,
    FBS_STOCK_PATH,
    OZON_API_HOST,
    PLACEMENT_ZONE_PATH,
    PRODUCT_LIST_PATH,
    ROLES_PATH,
    SELLER_WAREHOUSES_PATH,
    SUPPLY_ORDER_BUNDLE_PATH,
    SUPPLY_ORDER_GET_PATH,
    SUPPLY_ORDER_LIST_PATH,
)


DNS_TIMEOUT = 5.0
TLS_TIMEOUT = 5.0
HTTP_TIMEOUT = 10.0
CHECK_NAMES = ("dns", "tls", "seller_info", "roles")


@dataclass(frozen=True, slots=True)
class OzonDiagnosticCheck:
    name: str
    status: str
    elapsed_ms: int | None = None
    code: str | None = None
    http_status: int | None = None
    request_id: str | None = None
    transport_kind: str | None = None
    permissions: Mapping[str, bool] | None = None
    expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class OzonConnectionDiagnostic:
    api_version: int
    status: str
    host: str
    elapsed_ms: int
    connection_valid: bool
    sync_ready: bool
    checks: tuple[OzonDiagnosticCheck, ...]


class DiagnosticClient(Protocol):
    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy,
                  timeout: float | None = None) -> dict: ...


Resolver = Callable[[str, float], object]
TlsConnector = Callable[[str, int, float], None]


def _elapsed(started: float, clock: Callable[[], float]) -> int:
    return max(0, round((clock() - started) * 1000))


def _system_resolver(host: str, timeout: float) -> object:
    """Bound getaddrinfo with a daemon worker; never expose resolver details."""
    result: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result.put((True, socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
        except Exception as exc:  # kept inside the probe and never serialized
            result.put((False, exc))

    threading.Thread(target=resolve, name="ozon-dns-probe", daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError from None
    if not ok:
        if isinstance(value, Exception):
            raise value
        raise OSError from None
    return value


def _system_tls_connector(host: str, port: int, timeout: float) -> None:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        raw.settimeout(timeout)
        with context.wrap_socket(raw, server_hostname=host):
            return


def diagnose_dns(*, resolver: Resolver = _system_resolver, host: str = OZON_API_HOST,
                 timeout: float = DNS_TIMEOUT,
                 clock: Callable[[], float] = time.perf_counter) -> OzonDiagnosticCheck:
    started = clock()
    try:
        resolver(host, timeout)
    except (TimeoutError, socket.timeout):
        return OzonDiagnosticCheck("dns", "failed", _elapsed(started, clock), "TIMEOUT",
                                   transport_kind="timeout")
    except Exception:
        return OzonDiagnosticCheck("dns", "failed", _elapsed(started, clock), "DNS_FAILED",
                                   transport_kind="dns")
    return OzonDiagnosticCheck("dns", "ok", _elapsed(started, clock))


def diagnose_tls(*, connector: TlsConnector = _system_tls_connector, host: str = OZON_API_HOST,
                 timeout: float = TLS_TIMEOUT,
                 clock: Callable[[], float] = time.perf_counter) -> OzonDiagnosticCheck:
    started = clock()
    try:
        connector(host, 443, timeout)
    except (TimeoutError, socket.timeout):
        return OzonDiagnosticCheck("tls", "failed", _elapsed(started, clock), "TIMEOUT",
                                   transport_kind="timeout")
    except ssl.SSLCertVerificationError:
        return OzonDiagnosticCheck("tls", "failed", _elapsed(started, clock),
                                   "TLS_CERTIFICATE_FAILED", transport_kind="tls_certificate")
    except ssl.SSLError:
        return OzonDiagnosticCheck("tls", "failed", _elapsed(started, clock),
                                   "TLS_HANDSHAKE_FAILED", transport_kind="tls_handshake")
    except (ConnectionError, OSError):
        return OzonDiagnosticCheck("tls", "failed", _elapsed(started, clock),
                                   "TCP_CONNECTION_FAILED", transport_kind="tcp_connection")
    except Exception:
        return OzonDiagnosticCheck("tls", "failed", _elapsed(started, clock),
                                   "TCP_CONNECTION_FAILED", transport_kind="network")
    return OzonDiagnosticCheck("tls", "ok", _elapsed(started, clock))


def _client_failure(name: str, exc: OzonClientError, elapsed_ms: int) -> OzonDiagnosticCheck:
    code = exc.code.value
    if exc.code is OzonErrorCode.PERMISSION_DENIED:
        code = "OZON_PERMISSION_MISSING"
    return OzonDiagnosticCheck(name, "failed", elapsed_ms, code, exc.status,
                               exc.request_id, exc.transport_kind)


def diagnose_seller_info(client: DiagnosticClient, *,
                         clock: Callable[[], float] = time.perf_counter) -> OzonDiagnosticCheck:
    started = clock()
    try:
        client.post_json(CONNECTION_TEST_PATH, {}, policy=OzonRequestPolicy(
            retry_safe=True, max_attempts=1), timeout=HTTP_TIMEOUT)
    except OzonClientError as exc:
        return _client_failure("seller_info", exc, _elapsed(started, clock))
    return OzonDiagnosticCheck("seller_info", "ok", _elapsed(started, clock))


# Current /v1/roles wire: top-level expires_at + roles[], with methods as
# endpoint-path strings.  Every endpoint used by the heavy sync must be present
# before the preflight may declare sync_ready.
_PERMISSION_METHODS = {
    "orders": frozenset({FBO_POSTINGS_PATH, FBS_POSTINGS_PATH}),
    "products": frozenset({
        PRODUCT_LIST_PATH, FBO_STOCK_PATH, FBS_STOCK_PATH, PLACEMENT_ZONE_PATH,
    }),
    "fbo_supply": frozenset({
        CLUSTERS_V2_PATH, CLUSTERS_V1_PATH, SUPPLY_ORDER_LIST_PATH,
        SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_BUNDLE_PATH,
    }),
    "warehouses": frozenset({SELLER_WAREHOUSES_PATH}),
}


def parse_roles(payload: object) -> tuple[dict[str, bool], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("roles"), list):
        raise ValueError("invalid roles response")

    expiry = payload.get("expires_at")
    if expiry is not None:
        if not isinstance(expiry, str) or not expiry.strip():
            raise ValueError("invalid expiry")
        expiry = expiry.strip()

    available: set[str] = set()
    for role in payload["roles"]:
        if not isinstance(role, dict):
            raise ValueError("invalid role")
        name = role.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("invalid role name")
        methods = role.get("methods")
        if not isinstance(methods, list):
            raise ValueError("invalid role methods")
        for method in methods:
            if not isinstance(method, str) or not method.strip():
                raise ValueError("invalid role method")
            available.add(method.strip())

    permissions = {name: methods.issubset(available)
                   for name, methods in _PERMISSION_METHODS.items()}
    return permissions, expiry


def diagnose_roles(client: DiagnosticClient, *,
                   clock: Callable[[], float] = time.perf_counter) -> OzonDiagnosticCheck:
    started = clock()
    try:
        payload = client.post_json(ROLES_PATH, {}, policy=OzonRequestPolicy(
            retry_safe=True, max_attempts=1), timeout=HTTP_TIMEOUT)
        permissions, expires_at = parse_roles(payload)
    except OzonClientError as exc:
        return _client_failure("roles", exc, _elapsed(started, clock))
    except (TypeError, ValueError):
        return OzonDiagnosticCheck("roles", "failed", _elapsed(started, clock),
                                   "OZON_ROLES_INVALID_RESPONSE")
    if not all(permissions.values()):
        return OzonDiagnosticCheck("roles", "failed", _elapsed(started, clock),
                                   "OZON_PERMISSION_MISSING", permissions=permissions,
                                   expires_at=expires_at)
    return OzonDiagnosticCheck("roles", "ok", _elapsed(started, clock),
                               permissions=permissions, expires_at=expires_at)


def diagnose_connection(
    client: BoundOzonClient, *, resolver: Resolver = _system_resolver,
    connector: TlsConnector = _system_tls_connector,
    clock: Callable[[], float] = time.perf_counter,
) -> OzonConnectionDiagnostic:
    started = clock()
    checks: list[OzonDiagnosticCheck] = []
    stages = (
        lambda: diagnose_dns(resolver=resolver, clock=clock),
        lambda: diagnose_tls(connector=connector, clock=clock),
        lambda: diagnose_seller_info(client, clock=clock),
        lambda: diagnose_roles(client, clock=clock),
    )
    for index, stage in enumerate(stages):
        check = stage()
        checks.append(check)
        if check.status == "failed":
            checks.extend(OzonDiagnosticCheck(name, "not_run")
                          for name in CHECK_NAMES[index + 1:])
            break
    seller_ok = checks[2].status == "ok"
    ready = checks[3].status == "ok"
    return OzonConnectionDiagnostic(1, "ok" if ready else "failed", OZON_API_HOST,
                                    _elapsed(started, clock), seller_ok, ready,
                                    tuple(checks))
