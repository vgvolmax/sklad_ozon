"""Synchronous fixed-host Ozon Seller API JSON client."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import math
import time
from typing import Callable, Mapping, Protocol
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import OzonCredentialContext, OzonCredentials, OzonErrorCode
from .endpoints import OZON_API_BASE
from .vault import CredentialVault


logger = logging.getLogger(__name__)
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_SERVER_RETRY_AFTER_SECONDS = 60.0
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
    ) -> None:
        self.code = code
        self.endpoint = endpoint
        self.status = status
        self.vendor_code = vendor_code
        self.vendor_message = vendor_message
        self.request_id = request_id
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
    ) -> None:
        if isinstance(timeout, bool) or not 0 < timeout < 60:
            raise ValueError("timeout must be finite and between 0 and 60 seconds")
        self._vault = vault
        self._transport = transport
        self._timeout = float(timeout)
        self._sleep = sleeper

    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy) -> dict:
        return self._post_json(path, payload, policy=policy,
                               credentials=self._vault.require_credentials())

    def bind_context(self, context: OzonCredentialContext) -> "BoundOzonClient":
        return BoundOzonClient(self, context)

    def _post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy,
                   credentials: OzonCredentials, context_id: str | None = None) -> dict:
        self._validate_path(path)
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
        for attempt in range(1, attempts + 1):
            if context_id is not None and self._vault.credential_context_id() != context_id:
                raise OzonClientError(
                    OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED,
                    "Ozon credential context changed",
                    endpoint=path,
                )
            try:
                response = self._transport(request, self._timeout)
            except Exception:
                logger.warning("Ozon request transport failure path=%s attempt=%d", path, attempt)
                if policy.retry_safe and attempt < attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise OzonClientError(
                    OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", endpoint=path,
                ) from None
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

    def _retry_delay(
        self,
        response: TransportResponse,
        attempt: int,
        *,
        endpoint: str,
        credentials: OzonCredentials,
    ) -> float:
        retry_after = next((value for key, value in response.headers.items() if key.lower() == "retry-after"), None)
        if retry_after is not None:
            try:
                value = float(retry_after)
                if math.isfinite(value) and 0 <= value <= _MAX_SERVER_RETRY_AFTER_SECONDS:
                    return value
                if math.isfinite(value) and value > _MAX_SERVER_RETRY_AFTER_SECONDS:
                    error = self._http_error(
                        response, endpoint=endpoint, credentials=credentials,
                    )
                    raise OzonClientError(
                        OzonErrorCode.RATE_LIMITED,
                        "Ozon API rate limit exceeds the client wait budget",
                        endpoint=error.endpoint,
                        status=error.status,
                        vendor_code=error.vendor_code,
                        vendor_message=error.vendor_message,
                        request_id=error.request_id,
                    )
            except (TypeError, ValueError):
                pass
        return self._backoff(attempt)

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
        if status == 429:
            return OzonClientError(OzonErrorCode.RATE_LIMITED, "Ozon API rate limit reached", **common)
        if status >= 500:
            return OzonClientError(OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", **common)
        return OzonClientError(OzonErrorCode.INVALID_RESPONSE, "Ozon API rejected the request", **common)

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

    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy) -> dict:
        return self._client._post_json(path, payload, policy=policy,
                                       credentials=self._context.credentials,
                                       context_id=self._context.context_id)
