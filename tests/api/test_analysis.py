"""End-to-end Task 17 API regressions over the real ASGI application."""

from dataclasses import dataclass
from decimal import Decimal, getcontext
from enum import Enum
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.application import AnalysisSummary, build_analysis_summary
from backend.api import MAX_UPLOAD_BYTES, wire
from backend.main import app
from tests.helpers.xlsx_fixtures import make_multisheet_xlsx, make_real_unitka, make_xlsx


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


def _two_sku_analysis_files():
    return {
        "availability_file": ("availability.xlsx", make_xlsx(headers=AVAILABILITY_HEADERS, rows=[
            ["SKU-1", "W1", "Москва", 999, 3], ["SKU-2", "W2", "Москва", 999, 4],
        ])),
        "restrictions_file": ("restrictions.csv", "SKU;Склад;Статус;Причина\nSKU-1;W1;Разрешено;\nSKU-2;W2;Разрешено;\n".encode()),
        "orders_file": ("orders.csv", _orders() + _orders().decode().splitlines()[1].replace("SKU-1", "SKU-2").encode() + b"\n"),
        "tariffs_file": ("tariffs.xlsx", make_xlsx(headers=TARIFF_HEADERS, rows=[["Москва", "Москва", 0, "", "", "", 50]])),
        "product_economics_file": ("products.xlsx", make_xlsx(headers=PRODUCT_HEADERS, rows=[
            ["SKU-1", "ART-1", 100, 3, 1000, "10%", 1], ["SKU-2", "ART-2", 200, 4, 1200, "10%", 1],
        ])),
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


def _real_four_files(fbs_a=(0, 0, 84, 0), *, include_second=True, obsolete=False,
                     fbo_complete=True, product_available_qty=None):
    availability_headers = ["SKU", "Артикул", "Название товара", "Рекомендуемая поставка, шт на 56 дней",
                            "Рекомендация", "Кластер", "Схема продаж", "Дней без остатка за 28 дней",
                            "Доля локальных продаж", "Среднесуточные продажи, руб. за 28дн", "Признак товара",
                            "До конца остатка FBO, дн", "До конца остатка FBS, дн", "Остаток FBO, шт",
                            "Остаток FBS, шт", "Товары в пути на склад озон, шт", "Среднесуточные продажи, шт. за 28дн"]
    clusters = ("Новосибирск", "Ростов", "Москва", "Уфа")
    availability_rows = [["SKU-A", "ART-A", "Товар A", 10 if cluster == "Москва" else 0, "", cluster, "FBO", 0, 1, 1, "", 1, 1, 2, fbs, 0, 1]
                         for cluster, fbs in zip(clusters, fbs_a)]
    if include_second:
        availability_rows.append(["SKU-B", "ART-B", "Товар B", 10, "", "Москва", "FBO", 0, 1, 1, "", 1, 1, 2, 20, 0, 1])
    availability = make_xlsx(headers=[None], rows=[[None], [None], [None], [None], availability_headers, *availability_rows])
    restriction_headers = ["Артикул", "SKU", "Название товара", "Рекомендуемая поставка на 56 дней", "Кластер", "Склад",
                           "Возможно ли поставить товар", "Зона размещения", "Ошибки в карточке товара",
                           "Склад оборудован под хранение товара", "Статус ликвидности: Без продаж, ограничен", "Максимальный размер поставки"]
    restriction_rows = [["ART-A", "SKU-A", "A", 10, "Москва", "МОСКВА_РФЦ", "Да", "", "", "", "", 3],
                        ["ART-A", "SKU-A", "A", 10, "Москва", "МОСКВА_ЗАПРЕТ", "Нет", "", "", "", "", "-"]]
    if include_second: restriction_rows.insert(1, ["ART-B", "SKU-B", "B", 10, "Москва", "МОСКВА_РФЦ", "Да", "", "", "", "", 7])
    restrictions = make_multisheet_xlsx([("Справка", ["meta"], [["x"]]),
        ("Ограничения", [None], [[None], restriction_headers, *restriction_rows])])
    order_header = "SKU;Артикул;Количество;Статус;Ваша цена;Кластер отгрузки;Кластер доставки;Склад отгрузки;Принят в обработку;Имя покупателя\n"
    orders = order_header + "SKU-A;ART-A;1;Доставлен;1000;Москва;Москва;МОСКВА_РФЦ;2026-07-01T10:00:00;PII_REAL_SHAPE\n"
    if include_second: orders += "SKU-B;ART-B;1;Доставлен;1000;Москва;Москва;МОСКВА_РФЦ;2026-07-01T10:00:00;PII_REAL_SHAPE\n"
    product_rows = [["ART-A", "A", 100, 1000, "10%", 1]]
    if include_second: product_rows.append(["ART-B", "B", 100, 1000, "10%", 1])
    if obsolete: product_rows.append(["OLD-ARTICLE", "Старый", 100, 1000, "10%", 1])
    unitka = make_real_unitka(product_rows=product_rows, fbo_complete=fbo_complete,
                              economics_scheme_fbo=True,
                              product_available_qty=product_available_qty)
    return {"availability_file": ("availability.xlsx", availability),
            "restrictions_file": ("restrictions.xlsx", restrictions),
            "orders_file": ("orders.csv", orders.encode()), "unitka_file": ("Юнитка OZON.xlsx", unitka)}


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


def test_analysis_summary_contract_and_reconciliation():
    payload = _post_analysis(recommendations=(3,), available_stock=5).json()
    summary = payload["summary"]
    assert set(summary) == {"sku_count", "placement_count", "ozon_recommended_qty", "allocated_qty", "objective_profit"}
    assert isinstance(summary["objective_profit"], str)
    assert summary["sku_count"] == len({item["sku"] for item in payload["placements"]})
    assert summary["placement_count"] == len(payload["placements"])
    assert summary["ozon_recommended_qty"] == sum(item["ozon_recommended_qty"] for item in payload["placements"])
    assert summary["allocated_qty"] == sum(item["allocated_qty"] for item in payload["allocations"])


def test_multi_sku_summary_has_one_exact_objective_profit_total():
    payload = _post_analysis(files=_two_sku_analysis_files()).json()
    profits = [Decimal(item["objective_profit"]) for item in payload["allocations"]]
    assert len(profits) == 2 and all(profit > 0 for profit in profits)
    assert Decimal(payload["summary"]["objective_profit"]) == profits[0] + profits[1]
    assert "," not in payload["summary"]["objective_profit"]


def test_summary_uses_local_canonical_decimal_context_without_mutating_global_context():
    context = getcontext()
    original_precision, original_rounding = context.prec, context.rounding
    try:
        context.prec = 5
        placements = (SimpleNamespace(sku="A", ozon_recommended_qty=2), SimpleNamespace(sku="B", ozon_recommended_qty=3))
        allocations = (
            SimpleNamespace(allocated_qty=2, objective_profit=Decimal("1.12345678901234567890123456789")),
            SimpleNamespace(allocated_qty=3, objective_profit=Decimal("2.98765432109876543210987654321")),
        )
        assert build_analysis_summary(placements, allocations) == AnalysisSummary(2, 2, 5, 5, Decimal("4.11111111011111111101111111110"))
        assert (context.prec, context.rounding) == (5, original_rounding)
    finally:
        context.prec, context.rounding = original_precision, original_rounding


def test_empty_analysis_summary_has_no_null_fields():
    assert build_analysis_summary((), ()) == AnalysisSummary(0, 0, 0, 0, Decimal("0"))


def test_analysis_exposes_all_successful_import_statuses():
    payload = _post_analysis().json()
    statuses = payload["input_statuses"]
    assert set(statuses) == {"availability_file", "restrictions_file", "orders_file", "tariffs_file", "product_economics_file"}
    assert all(status["ok"] is True and status["record_count"] > 0 and isinstance(status["diagnostics"], list) for status in statuses.values())


def test_analysis_import_error_is_visible_in_file_status_without_short_circuiting_response():
    files = _analysis_files()
    files["availability_file"] = ("availability.xlsx", make_xlsx(headers=AVAILABILITY_HEADERS, rows=[["SKU-1", "W1", "Москва", -1, 3]]))
    response = _post_analysis(files=files)
    assert response.status_code == 200
    status = response.json()["input_statuses"]["availability_file"]
    assert status["ok"] is False
    assert any(item["severity"] == "error" for item in status["diagnostics"])


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


def test_real_four_file_mode_fbo_fbs_article_and_sku_specific_caps():
    response = _post_analysis(files=_real_four_files(obsolete=True))
    assert response.status_code == 200
    payload = response.json()
    assert set(payload["input_statuses"]) == {"availability_file", "restrictions_file", "orders_file", "unitka_file"}
    assert payload["input_statuses"]["unitka_file"]["ok"] is True
    assert payload["complete"] is True
    assert not {"MISSING_REQUIRED_HEADER", "HEADER_ROW_NOT_FOUND", "TARIFF_SHEET_NOT_FOUND"} & {d["code"] for d in payload["diagnostics"]}
    assert {(p["sku"], p["ozon_recommended_qty"], p["feasibility"]["max_supply_qty"]) for p in payload["placements"]} == {
        ("SKU-A", 10, 3), ("SKU-B", 10, 7)}
    sku_a = next(p for p in payload["placements"] if p["sku"] == "SKU-A")
    assert sku_a["feasibility"]["eligible_warehouses"] == ["МОСКВА_РФЦ"]
    assert "PROHIBITED_WAREHOUSE_PRESENT" in sku_a["feasibility"]["reasons"]
    assert {a["sku"]: a["allocated_qty"] for a in payload["allocations"]} == {"SKU-A": 3, "SKU-B": 7}
    assert "INVALID_MAX_SUPPLY_QTY" not in {d["code"] for d in payload["diagnostics"]}
    assert {item["expected_fee"] for item in payload["logistics"]} == {"69"}
    assert "PII_REAL_SHAPE" not in json.dumps(payload, ensure_ascii=False)
    obsolete = next(d for d in payload["diagnostics"] if d["code"] == "MISSING_ARTICLE_TO_SKU")
    assert obsolete["severity"] == "warning"


def test_fbs_stock_resolution_zero_positive_all_zero_and_conflict():
    unique = _post_analysis(files=_real_four_files((0, 0, 84, 0), include_second=False)).json()
    assert unique["allocations"][0]["available_stock"] == 84
    assert "CONFLICTING_FBS_AVAILABLE_STOCK" not in {d["code"] for d in unique["diagnostics"]}
    duplicate = _post_analysis(files=_real_four_files((84, 0, 84), include_second=False)).json()
    assert duplicate["allocations"][0]["available_stock"] == 84
    zeros = _post_analysis(files=_real_four_files((0, 0, 0), include_second=False)).json()
    assert zeros["allocations"][0]["available_stock"] == 0
    assert "MISSING_SELLER_AVAILABLE_STOCK" not in {d["code"] for d in zeros["diagnostics"]}
    conflict = _post_analysis(files=_real_four_files((0, 84, 120), include_second=False)).json()
    assert conflict["allocations"] == []
    assert "CONFLICTING_FBS_AVAILABLE_STOCK" in {d["code"] for d in conflict["diagnostics"]}


def test_all_null_fbs_is_missing_seller_stock():
    payload = _post_analysis(files=_real_four_files(
        (None, None), include_second=False, product_available_qty=99,
    )).json()
    assert payload["allocations"] == []
    assert "MISSING_SELLER_AVAILABLE_STOCK" in {d["code"] for d in payload["diagnostics"]}


def test_unitka_status_combines_valid_economics_with_invalid_fbo_tariffs():
    response = _post_analysis(files=_real_four_files(include_second=False, fbo_complete=False))

    assert response.status_code == 200
    status = response.json()["input_statuses"]["unitka_file"]
    assert status["ok"] is False
    assert "UNSUPPORTED_UNITKA_TARIFF_LAYOUT" in {item["code"] for item in status["diagnostics"]}


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
    assert all(f"data.summary.{field}" in source for field in ("sku_count", "placement_count", "ozon_recommended_qty", "allocated_qty", "objective_profit"))
    assert "objective_profit).join" not in source
    assert "Number(data.summary.objective_profit" not in source
    assert "parseFloat(data.summary.objective_profit" not in source
    assert "data.input_statuses" in source
    assert all(label in source for label in ("Выбран", "Проверено", "Есть ошибки"))


def test_analysis_stream_emits_ordered_progress_and_equivalent_result_without_pii():
    files = _analysis_files(pii=True)
    ordinary = CLIENT.post('/api/analysis', files=files, data=_analysis_data()).json()
    streamed = CLIENT.post('/api/analysis/stream', files=_analysis_files(pii=True), data=_analysis_data())
    assert streamed.status_code == 200
    assert streamed.headers['content-type'].startswith('application/x-ndjson')
    events = [json.loads(line) for line in streamed.text.splitlines()]
    progress = [event for event in events if event['type'] == 'progress']
    results = [event for event in events if event['type'] == 'result']
    assert progress and len(results) == 1
    assert [event['stage_index'] for event in progress] == sorted(event['stage_index'] for event in progress)
    assert len({event['request_id'] for event in events}) == 1
    assert results[0]['data'] == ordinary
    assert not any(marker in streamed.text for marker in PII_MARKERS)


def test_analysis_stream_returns_controlled_error_event(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('SECRET TRACEBACK VALUE')
    monkeypatch.setattr(api_module, 'run_analysis_pipeline', fail)
    response = CLIENT.post('/api/analysis/stream', files=_analysis_files(), data=_analysis_data())
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == 'error'
    assert events[-1]['error']['code'] == 'ANALYSIS_FAILED'
    assert 'SECRET' not in response.text
