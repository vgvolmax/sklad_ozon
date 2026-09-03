from fastapi.testclient import TestClient

from backend.config import HOST, PORT
from backend.main import app


client = TestClient(app)


def test_exact_health_contract():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok", "service": "sklad_ozon", "api_version": 1,
    }


def test_committed_frontend_and_assets_are_served():
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert "Sklad Ozon" in index.text
    assert "План" in index.text
    assert client.get("/assets/js/core.js").status_code == 200
    assert client.get("/assets/js/components.js").status_code == 200
    assert client.get("/assets/js/app.js").status_code == 200
    assert client.get("/assets/css/app.css").status_code == 200


def test_loopback_configuration_is_exact():
    assert HOST == "127.0.0.1"
    assert PORT == 17843
