"""Synchronous fixed-host Ozon Seller API JSON client."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import OzonErrorCode
from .endpoints import OZON_API_BASE
from .vault import CredentialVault


logger = logging.getLogger(__name__)
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class OzonRequestPolicy:
    retry_safe: bool
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(self, request: Request, timeout: float) -> TransportResponse: ...


class OzonClientError(Exception):
    def __init__(self, code: OzonErrorCode, message: str, *, status: int | None = None) -> None:
        self.code = code
        self.status = status
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
        self._validate_path(path)
        credentials = self._vault.require_credentials()
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
            try:
                response = self._transport(request, self._timeout)
            except Exception:
                logger.warning("Ozon request transport failure path=%s attempt=%d", path, attempt)
                if policy.retry_safe and attempt < attempts:
                    self._sleep(self._backoff(attempt))
                    continue
                raise OzonClientError(OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable") from None
            if response.status in _TRANSIENT_STATUSES and policy.retry_safe and attempt < attempts:
                self._sleep(self._retry_delay(response, attempt))
                continue
            if response.status >= 400:
                raise self._http_error(response.status)
            try:
                decoded = json.loads(response.body)
                if not isinstance(decoded, dict):
                    raise ValueError
                return decoded
            except (UnicodeError, json.JSONDecodeError, ValueError):
                raise OzonClientError(OzonErrorCode.INVALID_RESPONSE, "Ozon API returned invalid JSON") from None
        raise OzonClientError(OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable")

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

    def _retry_delay(self, response: TransportResponse, attempt: int) -> float:
        retry_after = next((value for key, value in response.headers.items() if key.lower() == "retry-after"), None)
        if retry_after is not None:
            try:
                value = float(retry_after)
                if 0 <= value <= 60:
                    return value
            except (TypeError, ValueError):
                pass
        return self._backoff(attempt)

    @staticmethod
    def _http_error(status: int) -> OzonClientError:
        if status in {401, 403}:
            return OzonClientError(OzonErrorCode.AUTH_FAILED, "Ozon API rejected credentials", status=status)
        if status == 429:
            return OzonClientError(OzonErrorCode.RATE_LIMITED, "Ozon API rate limit reached", status=status)
        if status >= 500:
            return OzonClientError(OzonErrorCode.UNAVAILABLE, "Ozon API is unavailable", status=status)
        return OzonClientError(OzonErrorCode.INVALID_RESPONSE, "Ozon API rejected the request", status=status)
