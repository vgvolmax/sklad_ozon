import subprocess
import sys
from unittest.mock import Mock

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.main import app


LOCAL_HOST = {"Host": "127.0.0.1:17843"}
CLIENT = TestClient(app)


def error_code(response):
    return response.json()["error"]["code"]


def session_token():
    response = CLIENT.get("/api/local-session", headers=LOCAL_HOST)
    assert response.status_code == 200
    return response.json()["session_token"]


def authorized_headers(**headers):
    return {**LOCAL_HOST, "X-Sklad-Ozon-Session": session_token(), **headers}


def test_hostile_host_is_rejected_before_local_token_disclosure():
    response = CLIENT.get("/api/local-session", headers={"Host": "attacker.example"})

    assert response.status_code == 400
    assert error_code(response) == "INVALID_LOCAL_HOST"
    assert "session_token" not in response.text


def test_hostile_host_is_rejected_before_mutation_validation():
    response = CLIENT.post(
        "/api/ozon/credentials/lock", headers={"Host": "attacker.example"}
    )

    assert response.status_code == 400
    assert error_code(response) == "INVALID_LOCAL_HOST"


def test_local_session_token_is_random_for_each_python_process():
    command = [
        sys.executable,
        "-c",
        "from backend.security import current_local_session_token; "
        "print(current_local_session_token())",
    ]

    first = subprocess.check_output(command, text=True).strip()
    second = subprocess.check_output(command, text=True).strip()

    assert first
    assert second
    assert first != second


def test_local_session_bootstrap_is_non_cacheable_and_not_cors_enabled():
    response = CLIENT.get("/api/local-session", headers=LOCAL_HOST)

    assert response.status_code == 200
    assert isinstance(response.json()["session_token"], str)
    assert response.json()["session_token"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert "Access-Control-Allow-Origin" not in response.headers


def test_bodyless_mutation_requires_session_before_route_execution(monkeypatch):
    lock = Mock()
    monkeypatch.setattr(api_module.OZON_VAULT, "lock", lock)

    response = CLIENT.post("/api/ozon/credentials/lock", headers=LOCAL_HOST)

    assert response.status_code == 403
    assert error_code(response) == "LOCAL_SESSION_REQUIRED"
    lock.assert_not_called()


def test_sync_without_session_does_not_reach_side_effect(monkeypatch):
    sync = Mock()
    monkeypatch.setattr(api_module, "sync_ozon_source", sync)

    response = CLIENT.post("/api/ozon/sync", headers=LOCAL_HOST)

    assert response.status_code == 403
    assert error_code(response) == "LOCAL_SESSION_REQUIRED"
    sync.assert_not_called()


def test_wrong_session_is_rejected():
    response = CLIENT.post(
        "/api/ozon/credentials/lock",
        headers={**LOCAL_HOST, "X-Sklad-Ozon-Session": "wrong"},
    )

    assert response.status_code == 403
    assert error_code(response) == "LOCAL_SESSION_INVALID"


def test_correct_session_allows_bodyless_mutation():
    response = CLIENT.post(
        "/api/ozon/credentials/lock", headers=authorized_headers()
    )

    assert response.status_code == 200


def test_foreign_origin_is_rejected_even_with_correct_session():
    response = CLIENT.post(
        "/api/ozon/credentials/lock",
        headers=authorized_headers(Origin="https://evil.example"),
    )

    assert response.status_code == 403
    assert error_code(response) == "CROSS_ORIGIN_REQUEST_BLOCKED"


def test_same_origin_is_allowed_and_loopback_alias_is_not_interchangeable():
    allowed = CLIENT.post(
        "/api/ozon/credentials/lock",
        headers=authorized_headers(Origin="http://127.0.0.1:17843"),
    )
    blocked = CLIENT.post(
        "/api/ozon/credentials/lock",
        headers=authorized_headers(Origin="http://localhost:17843"),
    )

    assert allowed.status_code == 200
    assert blocked.status_code == 403
    assert error_code(blocked) == "CROSS_ORIGIN_REQUEST_BLOCKED"


def test_unsafe_body_rejects_plain_text_and_urlencoded_before_json_handler():
    headers = authorized_headers()
    plain = CLIENT.post(
        "/api/ozon/credentials/unlock",
        headers={**headers, "Content-Type": "text/plain"},
        content='{"password":"x"}',
    )
    urlencoded = CLIENT.post(
        "/api/ozon/credentials/unlock",
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        content="password=x",
    )

    assert plain.status_code == 415
    assert error_code(plain) == "UNSUPPORTED_MEDIA_TYPE"
    assert urlencoded.status_code == 415
    assert error_code(urlencoded) == "UNSUPPORTED_MEDIA_TYPE"


def test_json_and_real_multipart_pass_the_security_boundary():
    json_response = CLIENT.post(
        "/api/ozon/credentials/unlock",
        headers=authorized_headers(),
        json={"password": "x"},
    )
    multipart_response = CLIENT.post(
        "/api/analysis",
        headers=authorized_headers(),
        files={"unrelated": ("data.csv", b"x")},
    )

    assert json_response.status_code != 415
    assert multipart_response.status_code not in {403, 415}


def test_cross_origin_multipart_without_session_is_blocked_before_analysis(monkeypatch):
    prepare = Mock()
    monkeypatch.setattr(api_module, "prepare_analysis", prepare)

    response = CLIENT.post(
        "/api/analysis",
        headers={**LOCAL_HOST, "Origin": "https://evil.example"},
        files={"file": ("data.csv", b"x")},
    )

    assert response.status_code == 403
    assert error_code(response) == "CROSS_ORIGIN_REQUEST_BLOCKED"
    prepare.assert_not_called()


def test_health_and_static_assets_remain_available_without_session():
    health = CLIENT.get("/api/health", headers=LOCAL_HOST)
    assets = [
        CLIENT.get(path, headers=LOCAL_HOST)
        for path in ("/", "/assets/js/core.js", "/assets/js/app.js", "/assets/css/app.css")
    ]

    assert health.json() == {
        "status": "ok",
        "service": "sklad_ozon",
        "api_version": 1,
    }
    assert all(response.status_code == 200 for response in assets)


def test_cross_origin_preflight_does_not_receive_cors_permission():
    response = CLIENT.options(
        "/api/ozon/sync",
        headers={
            **LOCAL_HOST,
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Sklad-Ozon-Session",
        },
    )

    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Headers" not in response.headers
    assert "Access-Control-Allow-Methods" not in response.headers
