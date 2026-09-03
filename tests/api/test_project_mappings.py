from dataclasses import replace
from decimal import Decimal

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.domain.contracts import ProductEconomicsInput
from backend.main import app
from backend.project import Project, load_project, save_project_atomic


def test_mapping_get_put_round_trip_without_touching_real_project(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    monkeypatch.setattr(api_module, "PROJECT_PATH", path)
    client = TestClient(app)

    assert client.get("/api/project/mappings").json() == {"api_version": 1, "mappings": {}}
    assert not path.exists()
    response = client.put("/api/project/mappings", json={" Москва РФЦ ": " Москва "})

    assert response.status_code == 200
    assert response.json() == {"api_version": 1, "mappings": {"Москва РФЦ": "Москва"}}
    assert client.get("/api/project/mappings").json() == response.json()


def test_mapping_update_preserves_other_project_fields(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    project = Project(
        product_economics=(ProductEconomicsInput(
            "SKU", "ART", Decimal("10"), 7, Decimal("100"),
            Decimal("0.1"), Decimal("1"),
        ),),
        seller_available_stock={"SKU": 7},
    )
    save_project_atomic(path, project)
    monkeypatch.setattr(api_module, "PROJECT_PATH", path)

    response = TestClient(app).put("/api/project/mappings", json={"Alias": "Москва"})

    assert response.status_code == 200
    saved = load_project(path)
    assert saved == replace(project, manual_cluster_mappings={"Alias": "Москва"})


def test_mapping_put_rejects_invalid_shapes(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "PROJECT_PATH", tmp_path / "project.json")
    client = TestClient(app)

    for payload in (["a", "b"], {"A": ""}, {"A": 1}):
        response = client.put("/api/project/mappings", json=payload)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_MAPPINGS"
