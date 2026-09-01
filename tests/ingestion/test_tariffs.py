from decimal import Decimal

from backend.domain.contracts import ReportMeta
from backend.ingestion.tariffs import import_tariffs
from tests.helpers.xlsx_fixtures import make_multisheet_xlsx, make_real_unitka, make_xlsx

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


def test_real_unitka_selects_only_fbo_and_builds_half_open_volume_tiers():
    result = import_tariffs(make_real_unitka(tariff_rows=[
        (0, "0-0,200 л", "Москва", "Москва", 18, 69),
        (0.201, "0,201-0,4 л", "Москва", "Москва", 19, 70),
        (800.001, "От 800,001 л", "Москва", "Москва", 20, 71),
    ]), META)
    assert [r.logistics_fee for r in result.records] == [Decimal("18"), Decimal("69"), Decimal("19"), Decimal("70"), Decimal("20"), Decimal("71")]
    assert {r.logistics_fee for r in result.records}.isdisjoint({Decimal("118"), Decimal("169"), Decimal("5"), Decimal("15")})
    lows = [r for r in result.records if r.max_price == Decimal("300")]
    assert [(r.min_volume_liters, r.max_volume_liters) for r in lows] == [
        (Decimal("0"), Decimal("0.201")), (Decimal("0.201"), Decimal("800.001")),
        (Decimal("800.001"), None)]


def test_economics_and_reference_fbo_values_do_not_count_as_tariff_sections():
    result = import_tariffs(make_real_unitka(
        economics_scheme_fbo=True,
        extra_fbo_data_sheets=2,
    ), META)

    assert [record.logistics_fee for record in result.records] == [Decimal("18"), Decimal("69")]
    assert result.diagnostics == ()
    assert {record.logistics_fee for record in result.records}.isdisjoint(
        {Decimal("118"), Decimal("169"), Decimal("5"), Decimal("15")}
    )


def test_stray_fbo_without_tariff_structure_is_not_a_unitka_section():
    result = import_tariffs(make_multisheet_xlsx([
        ("Справочник", ["Схема работы"], [["FBO"]]),
    ]), META)

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["TARIFF_SHEET_NOT_FOUND"]


def test_multiple_structural_fbo_sections_are_ambiguous():
    result = import_tariffs(make_real_unitka(duplicate_tariff_section=True), META)

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["AMBIGUOUS_TARIFF_SHEETS"]


def test_markerless_unitka_headers_do_not_use_worksheet_wide_fallback():
    result = import_tariffs(make_xlsx(
        headers=["Кластер поставки", "Кластер доставки", "Для товаров до 300 руб.",
                 "Для товаров свыше 300 руб."],
        rows=[["Москва", "Москва", 18, 69]],
    ), META)

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["TARIFF_SHEET_NOT_FOUND"]


def test_fbo_marker_with_incomplete_block_fails_closed_without_fbs_or_base_fallback():
    result = import_tariffs(make_real_unitka(fbo_complete=False), META)

    assert result.records == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["UNSUPPORTED_UNITKA_TARIFF_LAYOUT"]
    assert {record.logistics_fee for record in result.records}.isdisjoint(
        {Decimal("118"), Decimal("169"), Decimal("5"), Decimal("15")}
    )


def test_legacy_single_table_without_fbo_marker_remains_supported():
    result = import_tariffs(
        make_xlsx(headers=HEADERS, rows=[["Москва", "Москва", 0, "", "", "", 49]]),
        META,
    )

    assert [record.logistics_fee for record in result.records] == [Decimal("49")]
    assert result.diagnostics == ()
