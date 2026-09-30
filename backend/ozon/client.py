"""Synchronous fixed-host Ozon Seller API JSON client."""

from __future__ import annotations

from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import json
import logging
import math
import socket
import ssl
import time
from threading import Lock
from typing import Callable, Mapping, Protocol
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import OzonCredentialContext, OzonCredentials, OzonErrorCode
from .endpoints import FBO_STOCK_PATH, OZON_API_BASE
from .vault import CredentialVault


logger = logging.getLogger(__name__)
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_SERVER_RETRY_AFTER_SECONDS = 60.0
# Conservative application pacing, not an assertion of Ozon's account quota.
_REQUEST_INTERVAL_SECONDS = 1.1
_STOCK_INTERVAL_SECONDS = 6.0
MAX_VENDOR_MESSAGE_CHARS = 300


@dataclass(frozen=True, slots=True)
class OzonRequestPolicy:
    retry_safe: bool
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if type(self.retry_safe) is not bool:
            raise ValueError("retry_safe must be a bool")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(self, request: Request, timeout: float) -> TransportResponse: ...


class OzonClientError(Exception):
    def __init__(
        self,
        code: OzonErrorCode,
        message: str,
        *,
        endpoint: str | None = None,
        status: int | None = None,
        vendor_code: str | None = None,
        vendor_message: str | None = None,
        request_id: str | None = None,
        transport_kind: str | None = None,
        attempts: int | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        self.code = code
        self.endpoint = endpoint
        self.status = status
        self.vendor_code = vendor_code
        self.vendor_message = vendor_message
        self.request_id = request_id
        self.transport_kind = transport_kind
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        super().__init__(message)


def urllib_transport(request: Request, timeout: float) -> TransportResponse:
    try:
        with urlopen(request, timeout=timeout) as response:
            return TransportResponse(response.status, dict(response.headers.items()), response.read())
    except HTTPError as error:
        return TransportResponse(error.code, dict(error.headers.items()), error.read())


class OzonClient:
    def __init__(
        self,
        vault: CredentialVault,
        *,
        transport: Transport = urllib_transport,
        timeout: float = 15.0,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if isinstance(timeout, bool) or not 0 < timeout < 60:
            raise ValueError("timeout must be finite and between 0 and 60 seconds")
        self._vault = vault
        self._transport = transport
        self._timeout = float(timeout)
        self._sleep = sleeper
        self._clock = clock
        self._wall_clock = wall_clock
        self._request_lock = Lock()
        self._next_request = 0.0
        self._next_stock_request = 0.0
        self._cooldown_until = 0.0
        self._cooldown_error: OzonClientError | None = None

    def post_json(
        self, path: str, payload: dict, *, policy: OzonRequestPolicy,
        timeout: float | None = None,
    ) -> dict:
        return self._post_json(path, payload, policy=policy,
                               context=self._vault.capture_context(), timeout=timeout)

    def bind_context(self, context: OzonCredentialContext) -> "BoundOzonClient":
        return BoundOzonClient(self, context)

    def _post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy,
                   context: OzonCredentialContext, timeout: float | None = None) -> dict:
        self._validate_path(path)
        request_timeout = self._timeout if timeout is None else float(timeout)
        if isinstance(timeout, bool) or not 0 < request_timeout < 60:
            raise ValueError("timeout must be finite and between 0 and 60 seconds")
        credentials = context.credentials
        request = Request(
            OZON_API_BASE + path,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Client-Id": credentials.client_id,
                "Api-Key": credentials.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        attempts = policy.max_attempts if policy.retry_safe else 1
        operation_started = time.perf_counter()
        for attempt in range(1, attempts + 1):
            self._assert_context_active(context, path)
            try:
                response = self._send(request, request_timeout, path, context, attempt)
            except OzonClientError:
                raise
            except Exception as exc:
                self._assert_context_active(context, path)
                logger.warning("Ozon request transport failure path=%s attempt=%d", path, attempt)
                if policy.retry_safe and attempt < attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise OzonClientError(
                    OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", endpoint=path,
                    transport_kind=self._transport_kind(exc), attempts=attempt,
                    elapsed_ms=round((time.perf_counter() - operation_started) * 1000),
                ) from None
            self._assert_context_active(context, path)
            if response.status in _TRANSIENT_STATUSES and policy.retry_safe and attempt < attempts:
                self._sleep(self._retry_delay(
                    response, attempt, endpoint=path, credentials=credentials,
                ))
                continue
            if response.status >= 400:
                raise self._http_error(response, endpoint=path, credentials=credentials)
            try:
                decoded = json.loads(response.body)
                if not isinstance(decoded, dict):
                    raise ValueError
                self._assert_context_active(context, path)
                return decoded
            except (UnicodeError, json.JSONDecodeError, ValueError):
                raise OzonClientError(
                    OzonErrorCode.INVALID_RESPONSE,
                    "Ozon API returned invalid JSON",
                    endpoint=path,
                    status=response.status,
                    request_id=self._request_id(response),
                ) from None
        raise OzonClientError(
            OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", endpoint=path,
        )

    def _assert_context_active(self, context: OzonCredentialContext, path: str) -> None:
        if not self._vault.is_context_active(context):
            raise OzonClientError(
                OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED,
                "Ozon credential context changed",
                endpoint=path,
            )


    @staticmethod
    def _validate_path(path: str) -> None:
        if not isinstance(path, str):
            raise ValueError("Expected a relative Ozon API path")
        parsed = urlsplit(path)
        if (not path.startswith("/") or path.startswith("//") or parsed.scheme or parsed.netloc
                or parsed.query or parsed.fragment or ".." in parsed.path.split("/")):
            raise ValueError("Expected a relative Ozon API path")

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.5 * (2 ** (attempt - 1)), 5.0)

    @staticmethod
    def _transport_kind(error: Exception) -> str:
        """Return a small, stable classification without retaining exception text."""
        cause = error.reason if isinstance(error, URLError) else error
        if isinstance(cause, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(cause, ConnectionResetError):
            return "connection_reset"
        if isinstance(cause, socket.gaierror):
            return "dns"
        if isinstance(cause, ssl.SSLError):
            return "tls"
        if isinstance(cause, (ConnectionError, ConnectionRefusedError, BrokenPipeError)):
            return "connection"
        if isinstance(error, (URLError, OSError)):
            return "network"
        return "unknown_transport"

    def _retry_delay(
        self,
        response: TransportResponse,
        attempt: int,
        *,
        endpoint: str,
        credentials: OzonCredentials,
    ) -> float:
        value = self._retry_after(response)
        if value is not None and value > _MAX_SERVER_RETRY_AFTER_SECONDS:
            error = self._http_error(response, endpoint=endpoint, credentials=credentials)
            raise OzonClientError(
                OzonErrorCode.RATE_LIMITED,
                "Ozon API rate limit exceeds the client wait budget",
                endpoint=error.endpoint, status=error.status,
                vendor_code=error.vendor_code, vendor_message=error.vendor_message,
                request_id=error.request_id,
            )
        fallback = min(60.0, 10.0 * 2 ** (attempt - 1)) if response.status == 429 else self._backoff(attempt)
        return max(value or 0.0, fallback)

    def _retry_after(self, response: TransportResponse) -> float | None:
        header = next((value for key, value in response.headers.items()
                       if key.lower() == "retry-after"), None)
        if header is None:
            return None
        try:
            value = float(header)
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(header)
                if parsed.tzinfo is None:
                    return None
                value = parsed.timestamp() - self._wall_clock()
            except (TypeError, ValueError, OverflowError):
                return None
        return max(0.0, value) if math.isfinite(value) else None

    def _send(self, request, timeout, path, context, attempt):
        # Shared by all bound clients. Serialize admission and response cooldown
        # so concurrent sync/search callers cannot bypass a just-received 429.
        with self._request_lock:
            self._assert_context_active(context, path)
            now = self._clock()
            if self._cooldown_until - now > _MAX_SERVER_RETRY_AFTER_SECONDS:
                raise self._cooldown_error
            allowed = max(self._next_request, self._cooldown_until,
                          self._next_stock_request if path == FBO_STOCK_PATH else 0.0)
            if allowed > now:
                self._sleep(allowed - now)
            self._assert_context_active(context, path)
            started = self._clock()
            self._next_request = started + _REQUEST_INTERVAL_SECONDS
            if path == FBO_STOCK_PATH:
                self._next_stock_request = started + _STOCK_INTERVAL_SECONDS
            response = self._transport(request, timeout)
            if response.status == 429:
                delay = max(self._retry_after(response) or 0.0,
                            min(60.0, 10.0 * 2 ** (attempt - 1)))
                self._cooldown_until = max(self._cooldown_until, self._clock() + delay)
                self._cooldown_error = self._http_error(
                    response, endpoint=path, credentials=context.credentials)
            return response

    def _http_error(
        self,
        response: TransportResponse,
        *,
        endpoint: str,
        credentials: OzonCredentials,
    ) -> OzonClientError:
        status = response.status
        vendor_code, vendor_message = self._vendor_error(response.body, credentials)
        common = {
            "endpoint": endpoint,
            "status": status,
            "vendor_code": vendor_code,
            "vendor_message": vendor_message,
            "request_id": self._request_id(response),
        }
        if status == 401:
            return OzonClientError(OzonErrorCode.AUTH_FAILED, "Ozon API rejected credentials", **common)
        if status == 403:
            return OzonClientError(
                OzonErrorCode.PERMISSION_DENIED, "Ozon API denied access to endpoint", **common,
            )
        if status == 400:
            return OzonClientError(
                OzonErrorCode.INVALID_REQUEST, "Ozon API rejected the request", **common,
            )
        if status == 429:
            return OzonClientError(OzonErrorCode.RATE_LIMITED, "Ozon API rate limit reached", **common)
        if status >= 500:
            return OzonClientError(OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", **common)
        return OzonClientError(OzonErrorCode.INVALID_RESPONSE, "Ozon API returned an invalid response", **common)

    @staticmethod
    def _request_id(response: TransportResponse) -> str | None:
        headers = {key.lower(): value for key, value in response.headers.items()}
        for name in ("x-o3-trace-id", "x-request-id"):
            value = headers.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _vendor_error(
        body: bytes, credentials: OzonCredentials,
    ) -> tuple[str | None, str | None]:
        try:
            decoded = json.loads(body)
        except (UnicodeError, json.JSONDecodeError, TypeError):
            return None, None
        if not isinstance(decoded, dict):
            return None, None
        raw_code = decoded.get("code")
        vendor_code = str(raw_code) if type(raw_code) in {str, int} else None
        raw_message = decoded.get("message")
        if not isinstance(raw_message, str):
            return vendor_code, None
        normalized = "".join(
            " " if character.isspace() or unicodedata.category(character).startswith("C") else character
            for character in raw_message
        )
        normalized = " ".join(normalized.split())
        for secret in sorted(
            (credentials.client_id, credentials.api_key), key=len, reverse=True,
        ):
            normalized = normalized.replace(secret, "[REDACTED]")
        return vendor_code, normalized[:MAX_VENDOR_MESSAGE_CHARS]


@dataclass(frozen=True, slots=True)
class BoundOzonClient:
    _client: OzonClient
    _context: OzonCredentialContext = field(repr=False)

    @property
    def context_id(self) -> str:
        return self._context.context_id

    def post_json(
        self, path: str, payload: dict, *, policy: OzonRequestPolicy,
        timeout: float | None = None,
    ) -> dict:
        return self._client._post_json(path, payload, policy=policy,
                                       context=self._context, timeout=timeout)
