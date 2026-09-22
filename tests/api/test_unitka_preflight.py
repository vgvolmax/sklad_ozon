"""Pure Unitka preflight API regressions."""

import hashlib

import backend.api as api_module
from backend.main import app
from starlette.testclient import TestClient

from tests.helpers.xlsx_fixtures import make_real_unitka


CLIENT = TestClient(app)


def test_valid_unitka_preflight_uses_full_bundle_without_mutation(monkeypatch):
    data = make_real_unitka(pack_rows=[[40750.0, "72/6"]])
    monkeypatch.setattr(api_module, "save_project_atomic",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("project mutated")))
    cleared = []
    original_clear = api_module.ANALYSIS_STORE.clear
    monkeypatch.setattr(api_module.ANALYSIS_STORE, "clear", lambda: cleared.append(True))

    response = CLIENT.post("/api/import/unitka/validate",
                           files={"file": ("unitka.xlsx", data)})

    assert response.status_code == 200
    assert cleared == []
    monkeypatch.setattr(api_module.ANALYSIS_STORE, "clear", original_clear)
    payload = response.json()
    assert payload["valid"] is True
    assert payload["product_count"] > 0
    assert payload["tariff_count"] > 0
    assert payload["pack_count"] == 1
    assert payload["error_count"] == 0
    assert payload["content_sha256"] == hashlib.sha256(data).hexdigest()


def test_malformed_unitka_preflight_returns_stable_field_error():
    response = CLIENT.post("/api/import/unitka/validate",
                           files={"file": ("broken.xlsx", b"not an xlsx")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_UNITKA_FILE"
    assert response.json()["error"]["field"] == "unitka_file"


def test_unitka_preflight_error_diagnostics_make_file_invalid():
    # The workbook opens, while the shared importers report its missing schema.
    data = make_real_unitka(product_rows=[], tariff_rows=[], pack_rows=[])
    response = CLIENT.post("/api/import/unitka/validate",
                           files={"file": ("empty-unitka.xlsx", data)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is (payload["error_count"] == 0)
