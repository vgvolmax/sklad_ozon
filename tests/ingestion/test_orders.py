import json
from dataclasses import asdict
from pathlib import Path
from backend.domain.contracts import OrderLifecycle, ReportMeta
from backend.ingestion.orders import import_orders

FIXTURE = Path(__file__).parents[1] / "fixtures/operational/orders_with_synthetic_pii.csv"
META = ReportMeta(source_name="orders.csv", imported_at="2026-08-21T10:00:00Z", period_start="2026-08-01", period_end="2026-08-20")
PII = ("Тест Покупатель", "Тестовая улица 1", "+70000000000", "buyer@example.invalid")


def test_direction_lifecycle_numbers_metadata_and_sources():
    result = import_orders(FIXTURE.read_bytes(), META)
    assert len(result.records) == 4
    first = result.records[0]
    assert first.origin_cluster == "Казань"
    assert first.destination_cluster == "Москва"
    assert first.quantity == 2 and first.seller_price == 1499.5
    assert [r.lifecycle for r in result.records] == [OrderLifecycle.FULFILLED, OrderLifecycle.IN_PROGRESS, OrderLifecycle.CANCELLED, OrderLifecycle.UNKNOWN]
    assert result.record_sources == (2, 3, 4, 5)
    assert result.meta is META
    assert next(d for d in result.diagnostics if d.code == "UNKNOWN_ORDER_STATUS").row == 5


def test_pii_and_raw_rows_never_cross_serialized_boundary():
    result = import_orders(FIXTURE.read_bytes(), META)
    serialized = json.dumps(asdict(result), ensure_ascii=False, default=str)
    for value in PII:
        assert value not in serialized
    assert "raw_row" not in serialized


def test_invalid_numbers_and_structural_headers():
    bad = import_orders("SKU;Количество;Цена продавца;Кластер отгрузки;Кластер доставки;Статус\n1;1,5;bad;Казань;Москва;Доставлен\n".encode(), META)
    assert bad.records == () and [d.code for d in bad.diagnostics] == ["INVALID_NUMBER"]
    missing = import_orders("SKU;Количество\n1;1\n".encode(), META)
    duplicate = import_orders("SKU; sku;Количество;Цена продавца;Кластер отгрузки;Кластер доставки;Статус\n1;2;1;1;К;М;Доставлен\n".encode(), META)
    assert "MISSING_REQUIRED_HEADER" in [d.code for d in missing.diagnostics]
    assert [d.code for d in duplicate.diagnostics] == ["DUPLICATE_HEADER"]


def test_non_finite_seller_price_is_rejected():
    data = "SKU;Количество;Цена продавца;Кластер отгрузки;Кластер доставки;Статус\n1;1;Infinity;Казань;Москва;Доставлен\n".encode()
    result = import_orders(data, META)
    assert result.records == ()
    assert [d.code for d in result.diagnostics] == ["INVALID_NUMBER"]


def test_real_shape_your_price_direction_and_pii_are_preserved_safely():
    data = ("SKU;Артикул;Количество;Статус;Ваша цена;Кластер отгрузки;Кластер доставки;Склад отгрузки;Принят в обработку;Имя покупателя;Телефон\n"
            "X;ART-X;2;Доставлен;999;Казань;Москва;КАЗАНЬ_РФЦ;2026-07-01T10:00:00;SECRET;79990000000\n").encode()
    result = import_orders(data, META)
    record = result.records[0]
    assert (record.article, record.seller_price, record.origin_cluster, record.destination_cluster) == ("ART-X", 999.0, "Казань", "Москва")
    assert "SECRET" not in json.dumps(asdict(result), ensure_ascii=False, default=str)
