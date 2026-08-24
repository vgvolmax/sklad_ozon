from decimal import Decimal

from backend.domain.contracts import ReportMeta
from backend.ingestion.tariffs import import_tariffs
from tests.helpers.xlsx_fixtures import make_multisheet_xlsx, make_xlsx

META = ReportMeta("rates.xlsx", "2026-08-24T10:00:00Z", report_generated_at="2026-08-23")
HEADERS = ["Кластер отгрузки", "Кластер доставки", "Объём от", "Объём до", "Цена от", "Цена до", "Логистика"]


def test_tariff_only_workbook_parses_decimal_intervals_metadata_and_sources():
    data = make_xlsx(headers=HEADERS, rows=[["Казань", "Москва", "0,5", 2.5, "100", "635,77", "49,9"]])
    result = import_tariffs(data, META)
    assert result.meta is META
    assert result.record_sources == (2,)
    assert result.records[0].origin_cluster_id == "Казань"
    assert result.records[0].destination_cluster_id == "Москва"
    assert (result.records[0].min_volume_liters, result.records[0].max_volume_liters) == (Decimal("0.5"), Decimal("2.5"))
    assert (result.records[0].min_price, result.records[0].max_price, result.records[0].logistics_fee) == (Decimal("100"), Decimal("635.77"), Decimal("49.9"))


def test_detects_tariff_sheet_by_signature_among_unrelated_named_sheets():
    data = make_multisheet_xlsx([
        ("Расчёты", ["SKU", "Прибыль"], [[1, 2]]),
        ("Логистика с 28 августа 2026г.", HEADERS, [["Казань", "Москва", 0, "", "", "", 50]]),
    ])
    assert len(import_tariffs(data, META).records) == 1


def test_invalid_intervals_negative_fee_and_blank_clusters_are_diagnosed():
    data = make_xlsx(headers=HEADERS, rows=[
        ["A", "B", 2, 1, "", "", 1], ["A", "B", 0, "", 20, 10, 1],
        ["A", "B", 0, "", "", "", -1], ["", "B", 0, "", "", "", 1],
    ])
    result = import_tariffs(data, META)
    assert result.records == ()
    assert [d.code for d in result.diagnostics] == ["INVALID_VOLUME_INTERVAL", "INVALID_PRICE_INTERVAL", "INVALID_NUMBER", "MALFORMED_ROW"]


def test_no_matching_or_multiple_matching_sheets_is_explicit():
    none = make_multisheet_xlsx([("Other", ["SKU"], [[1]])])
    ambiguous = make_multisheet_xlsx([("A", HEADERS, [["A", "B", 0, "", "", "", 1]]), ("B", HEADERS, [["A", "B", 0, "", "", "", 1]])])
    assert [d.code for d in import_tariffs(none, META).diagnostics] == ["TARIFF_SHEET_NOT_FOUND"]
    assert [d.code for d in import_tariffs(ambiguous, META).diagnostics] == ["AMBIGUOUS_TARIFF_SHEETS"]
