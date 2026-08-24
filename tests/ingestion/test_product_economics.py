from decimal import Decimal

from backend.domain.contracts import ReportMeta
from backend.ingestion.product_economics import import_product_economics
from tests.helpers.xlsx_fixtures import make_xlsx

META = ReportMeta("economics.xlsx", "2026-08-24T10:00:00Z")
HEADERS = ["SKU", "Артикул", "Себестоимость", "Доступный остаток", "Цена", "Комиссия", "Объём, л"]


def test_imports_typed_optional_economics_rates_metadata_and_sources():
    data = make_xlsx(headers=HEADERS, rows=[["100", "ART", "635,770", 12, 999.5, "41%", "2,5"], ["101", "", "", "", "", "0,41", ""]])
    result = import_product_economics(data, META)
    assert result.meta is META and result.record_sources == (2, 3)
    first = result.records[0]
    assert (first.sku, first.article, first.available_qty) == ("100", "ART", 12)
    assert (first.cost, first.price, first.commission_rate, first.volume_liters) == (Decimal("635.770"), Decimal("999.5"), Decimal("0.41"), Decimal("2.5"))
    assert result.records[1].cost is None and result.records[1].article == ""


def test_numeric_rate_is_fraction_and_ambiguous_whole_number_is_rejected():
    good = make_xlsx(headers=HEADERS, rows=[[1, "A", 1, 1, 1, 0.41, 1]])
    bad = make_xlsx(headers=HEADERS, rows=[[1, "A", 1, 1, 1, 41, 1]])
    assert import_product_economics(good, META).records[0].commission_rate == Decimal("0.41")
    assert [d.code for d in import_product_economics(bad, META).diagnostics] == ["INVALID_RATE"]


def test_rejects_malformed_negative_noninteger_and_nonfinite_values():
    rows = [["a", "", -1, 1, 1, .1, 1], ["b", "", 1, -1, 1, .1, 1], ["c", "", 1, 1.5, 1, .1, 1], ["d", "", "NaN", 1, 1, .1, 1], ["e", "", 1, 1, "Infinity", .1, 1], ["f", "", "oops", 1, 1, .1, 1]]
    result = import_product_economics(make_xlsx(headers=HEADERS, rows=rows), META)
    assert result.records == ()
    assert len(result.diagnostics) == 6
