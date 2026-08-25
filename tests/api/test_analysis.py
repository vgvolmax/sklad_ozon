"""End-to-end Task 17 API regressions over the real ASGI application."""

from dataclasses import dataclass
from decimal import Decimal, getcontext
from enum import Enum
import json
from pathlib import Path

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.api import MAX_UPLOAD_BYTES, wire
from backend.main import app
from tests.helpers.xlsx_fixtures import make_xlsx


CLIENT = TestClient(app)
AVAILABILITY_HEADERS = ["SKU", "Склад", "Кластер", "Доступно", "Рекомендуемая поставка"]
TARIFF_HEADERS = ["Кластер отгрузки", "Кластер доставки", "Объём от", "Объём до", "Цена от", "Цена до", "Логистика"]
PRODUCT_HEADERS = ["SKU", "Артикул", "Себестоимость", "Доступный остаток", "Цена", "Комиссия", "Объём, л"]
PII_MARKERS = ("PII_BUYER_12345", "PII_PHONE_12345", "PII_EMAIL_12345", "PII_ADDRESS_12345")


class Example(Enum):
    VALUE = "value"


@dataclass(frozen=True)
class Payload:
    amount: Decimal
    state: Example
    values: tuple[int, ...]


def _orders(origin="Москва", destination="Москва", *, pii=False):
    headers = ["SKU", "Количество", "Цена продавца", "Кластер отгрузки", "Кластер доставки", "Статус", "Принят в обработку"]
    values = ["SKU-1", 1, 1000, origin, destination, "Доставлен", "2026-07-01T10:00:00"]
    if pii:
        headers += ["Имя покупателя", "Телефон", "Email", "Адрес"]
        values += list(PII_MARKERS)
    return (";".join(map(str, headers)) + "\n" + ";".join(map(str, values)) + "\n").encode()


def _analysis_files(*, recommendations=(10,), available_stock=20, origin="Москва", destination="Москва", tariff=True, pii=False):
    availability_rows = [["SKU-1", f"W{i + 1}", origin, 999, recommendation] for i, recommendation in enumerate(recommendations)]
    restrictions = "SKU;Склад;Статус;Причина\n" + "".join(
        f"SKU-1;W{i + 1};Разрешено;\n" for i in range(len(recommendations))
    )
    tariff_rows = [[origin, destination, 0, "", "", "", 50]] if tariff else [["Другой", destination, 0, "", "", "", 50]]
    return {
        "availability_file": ("availability.xlsx", make_xlsx(headers=AVAILABILITY_HEADERS, rows=availability_rows)),
        "restrictions_file": ("restrictions.csv", restrictions.encode()),
        "orders_file": ("orders.csv", _orders(origin, destination, pii=pii)),
        "tariffs_file": ("tariffs.xlsx", make_xlsx(headers=TARIFF_HEADERS, rows=tariff_rows)),
        "product_economics_file": ("products.xlsx", make_xlsx(headers=PRODUCT_HEADERS, rows=[["SKU-1", "ART-1", 100, available_stock, 1000, "10%", 1]])),
    }


def _analysis_data(**overrides):
    values = {
        "as_of": "2026-08-25", "acquiring_rate": "0.01", "advertising_rate": "0.01",
        "buyout_rate": "1", "fixed_fbo_fee": "0", "tax_system": "usn_income",
        "income_tax_rate": "0.06", "vat_rate": "0", "co_invest_rate": "0",
        "min_profit_per_unit": "0", "min_margin_rate": "0", "min_roi": "0",
    }
    values.update(overrides)
    return values


def _post_analysis(*, files=None, data=None, **fixture_overrides):
    return CLIENT.post("/api/analysis", files=files or _analysis_files(**fixture_overrides), data=data or _analysis_data())


def _allocation(payload, cluster):
    return next(decision["allocation_qty"] for result in payload["allocations"] for decision in result["decisions"] if decision["cluster_id"] == cluster)


def _placement(payload, cluster):
    return next(item for item in payload["placements"] if item["cluster_id"] == cluster)


def test_wire_serializer_preserves_decimal_and_contract_types():
    assert wire(Payload(Decimal("10.250"), Example.VALUE, (1, 2))) == {"amount": "10.25", "state": "value", "values": [1, 2]}
    assert [wire(Decimal(value)) for value in ("1000", "1E+3", "0.000", "-0.000")] == ["1000", "1000", "0", "0"]


def test_wire_decimal_is_exact_and_independent_of_global_precision():
    value = Decimal("1.123456789012345678901234567890123456789")
    context = getcontext()
    original_precision = context.prec
    try:
        context.prec = 10
        assert wire(value) == "1.123456789012345678901234567890123456789"
        assert context.prec == 10
    finally:
        context.prec = original_precision


def test_happy_path_uses_recommendation_not_availability():
    response = _post_analysis(recommendations=(3,), available_stock=5)
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == 1 and payload["complete"] is True
    assert {"api_version", "complete", "as_of", "metadata", "demand", "observed_routes", "clean_routes", "stockout_signals", "distortion_signals", "logistics", "economics", "placements", "allocations", "coverage", "diagnostics"} <= payload.keys()
    assert _placement(payload, "Москва")["ozon_recommended_qty"] == 3
    assert _allocation(payload, "Москва") == 3


def test_seller_stock_not_ozon_availability_is_hard_limit():
    payload = _post_analysis(recommendations=(10,), available_stock=2).json()
    assert _allocation(payload, "Москва") == 2


def test_origin_destination_direction_is_preserved():
    payload = _post_analysis(origin="Казань", destination="Москва").json()
    assert {cell["destination_cluster_id"] for cell in payload["demand"]["cells"]} == {"Москва"}
    route = payload["observed_routes"]["routes"][0]
    assert (route["origin_cluster_id"], route["destination_cluster_id"]) == ("Казань", "Москва")


def test_counterfactual_zero_stays_visible_and_unallocated():
    payload = _post_analysis(recommendations=(0,)).json()
    assert _placement(payload, "Москва")["ozon_recommended_qty"] == 0
    assert _allocation(payload, "Москва") == 0


def test_duplicate_cluster_recommendations_are_not_summed():
    payload = _post_analysis(recommendations=(10, 10)).json()
    assert _placement(payload, "Москва")["ozon_recommended_qty"] == 10


def test_conflicting_cluster_recommendations_fail_closed():
    payload = _post_analysis(recommendations=(10, 20)).json()
    assert payload["complete"] is False
    assert "CONFLICTING_OZON_RECOMMENDATION" in {item["code"] for item in payload["diagnostics"]}
    assert _placement(payload, "Москва")["ozon_recommended_qty"] == 0
    assert _allocation(payload, "Москва") == 0


def test_missing_tariff_keeps_incomplete_rows_and_causes_visible():
    response = _post_analysis(tariff=False)
    assert response.status_code == 200
    payload = response.json()
    assert payload["complete"] is False and payload["placements"]
    assert payload["logistics"][0]["coverage_status"] != "complete"
    assert payload["logistics"][0]["expected_fee"] is None
    assert payload["economics"][0]["complete"] is False
    assert _allocation(payload, "Москва") == 0
    assert {"MISSING_TARIFF", "INCOMPLETE_LOGISTICS_COVERAGE"} <= {item["code"] for item in payload["diagnostics"]}


def test_pii_is_discarded_from_entire_analysis_response():
    payload = _post_analysis(pii=True).json()
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    assert not any(marker.casefold() in serialized for marker in PII_MARKERS)
    assert not any(field in serialized for field in ('"buyer_name"', '"phone"', '"email"', '"address"', '"raw_row"'))


def test_real_availability_import_endpoint():
    data = make_xlsx(headers=AVAILABILITY_HEADERS, rows=[["SKU-1", "W1", "Москва", 999, 3]])
    response = CLIENT.post("/api/import/availability", files={"file": ("availability.xlsx", data)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == 1 and payload["kind"] == "availability"
    assert payload["records"][0]["recommended_quantity"] == 3
    assert {"records", "diagnostics", "meta", "record_sources"} <= payload.keys()


def test_upload_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(api_module, "MAX_UPLOAD_BYTES", 4)
    response = CLIENT.post("/api/import/availability", files={"file": ("tiny.csv", b"12345")})
    assert response.status_code == 413
    assert response.json()["error"] | {} == {"code": "UPLOAD_TOO_LARGE", "message": "File exceeds 64 MiB.", "field": "file"}


def test_missing_field_and_invalid_date_are_controlled_errors():
    missing = CLIENT.post("/api/analysis", data=_analysis_data())
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "MISSING_FIELD"
    invalid = _post_analysis(data=_analysis_data(as_of="not-a-date"))
    assert invalid.status_code == 400 and invalid.json()["error"] | {} == {"code": "INVALID_DATE", "message": "Expected YYYY-MM-DD.", "field": "as_of"}


def test_economics_setting_domains_return_400():
    for field, value in (("acquiring_rate", "2"), ("buyout_rate", "0"), ("fixed_fbo_fee", "-1")):
        response = _post_analysis(data=_analysis_data(**{field: value}))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_SETTING"
        assert response.json()["error"]["field"] == field
    nonfinite = _post_analysis(data=_analysis_data(acquiring_rate="NaN"))
    assert nonfinite.status_code == 400 and nonfinite.json()["error"]["code"] == "INVALID_DECIMAL"


def test_negative_optimizer_threshold_is_accepted_by_transport():
    response = _post_analysis(data=_analysis_data(min_profit_per_unit="-100"))
    assert response.status_code == 200 and response.json()["complete"] is True


def test_upload_limit_and_thin_frontend_contract():
    assert MAX_UPLOAD_BYTES == 64 * 1024 * 1024
    source = Path("frontend/assets/js/app.js").read_text(encoding="utf-8")
    assert "fetch(" in source and "FormData" in source and "/api/" in source
    assert not any(token in source for token in ("calculate_unit_economics", "expected_logistics", "SheetJS", "FileReader", "ArrayBuffer", "JSZip"))
