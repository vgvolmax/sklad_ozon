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
from .endpoints import CONNECTION_TEST_PATH, OZON_API_HOST, ROLES_PATH


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


# The documented RoleAPI response is result[] -> roles[] -> methods[].  We only
# recognize explicit method availability and fail closed on every other shape.
_PERMISSION_METHODS = {
    "orders": frozenset({"/v3/posting/fbo/list", "/v4/posting/fbs/list"}),
    "products": frozenset({"/v3/product/list"}),
    "fbo_supply": frozenset({"/v3/supply-order/list", "/v3/supply-order/get"}),
    "warehouses": frozenset({"/v1/warehouse/fbo/seller/list"}),
}


def parse_roles(payload: object) -> tuple[dict[str, bool], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
        raise ValueError("invalid roles response")
    available: set[str] = set()
    expiries: set[str] = set()
    for group in payload["result"]:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str) \
                or not isinstance(group.get("roles"), list):
            raise ValueError("invalid role group")
        for role in group["roles"]:
            if not isinstance(role, dict) or not isinstance(role.get("name"), str) \
                    or not isinstance(role.get("methods"), list):
                raise ValueError("invalid role")
            expiry = role.get("expires_at")
            if expiry is not None:
                if not isinstance(expiry, str) or not expiry.strip():
                    raise ValueError("invalid expiry")
                expiries.add(expiry)
            for method in role["methods"]:
                if not isinstance(method, dict) or not isinstance(method.get("name"), str) \
                        or type(method.get("is_available")) is not bool:
                    raise ValueError("invalid role method")
                if method["is_available"]:
                    name = method["name"].strip()
                    if name.startswith("POST "):
                        name = name[5:].strip()
                    available.add(name)
    permissions = {name: methods.issubset(available)
                   for name, methods in _PERMISSION_METHODS.items()}
    return permissions, min(expiries) if expiries else None


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
