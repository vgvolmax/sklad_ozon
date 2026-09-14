"""Process-local HTTP security boundary for the loopback application."""

import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response


LOCAL_SESSION_HEADER = "X-Sklad-Ozon-Session"

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ALLOWED_BODY_MEDIA_TYPES = frozenset({"application/json", "multipart/form-data"})
_LOCAL_SESSION_TOKEN = secrets.token_urlsafe(32)


def current_local_session_token() -> str:
    """Return the in-memory token generated once for this Python process."""

    return _LOCAL_SESSION_TOKEN


def local_session_response() -> JSONResponse:
    """Build the same-origin, non-cacheable browser bootstrap response."""

    return JSONResponse(
        {"api_version": 1, "session_token": current_local_session_token()},
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "api_version": 1,
            "error": {"code": code, "message": message, "field": None},
        },
        status_code=status_code,
    )


def _parse_host(host_header: str | None) -> tuple[str, int | None] | None:
    if not host_header or any(character.isspace() for character in host_header):
        return None
    try:
        parsed = urlsplit("//" + host_header)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return hostname.lower(), port


def _same_origin(request: Request, request_host: tuple[str, int | None]) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    request_hostname, request_port = request_host
    expected_port = request_port or (443 if request.url.scheme == "https" else 80)
    actual_port = origin_port or (443 if parsed.scheme == "https" else 80)
    return (
        parsed.scheme == request.url.scheme
        and parsed.hostname.lower() == request_hostname
        and actual_port == expected_port
    )


def _request_has_body(request: Request) -> bool:
    transfer_encoding = request.headers.get("transfer-encoding")
    if transfer_encoding:
        return True
    content_length = request.headers.get("content-length")
    if content_length is None:
        return False
    try:
        return int(content_length) > 0
    except ValueError:
        return True


async def enforce_local_request_security(request: Request, call_next) -> Response:
    """Reject requests that are outside the local browser/API trust boundary."""

    request_host = _parse_host(request.headers.get("host"))
    if request_host is None or request_host[0] not in _ALLOWED_HOSTS:
        return _error(
            400,
            "INVALID_LOCAL_HOST",
            "Request host is not allowed for this local application.",
        )

    if request.method.upper() not in _UNSAFE_METHODS:
        return await call_next(request)

    if not _same_origin(request, request_host):
        return _error(
            403,
            "CROSS_ORIGIN_REQUEST_BLOCKED",
            "Cross-origin mutation is not allowed for this local application.",
        )

    received_token = request.headers.get(LOCAL_SESSION_HEADER)
    if received_token is None:
        return _error(
            403,
            "LOCAL_SESSION_REQUIRED",
            "A local application session is required for this request.",
        )
    if not secrets.compare_digest(received_token, current_local_session_token()):
        return _error(
            403,
            "LOCAL_SESSION_INVALID",
            "The local application session is no longer valid.",
        )

    if _request_has_body(request):
        media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
        if media_type not in _ALLOWED_BODY_MEDIA_TYPES:
            return _error(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                "Request body must use application/json or multipart/form-data.",
            )

    return await call_next(request)
