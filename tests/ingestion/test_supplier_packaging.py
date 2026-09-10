from datetime import datetime, timezone

import pytest

from backend.domain.contracts import ReportMeta
from backend.ingestion.normalization import normalize_seller_article_identity
from backend.ingestion.supplier_packaging import (
    import_supplier_packaging,
    normalize_supplier_article,
    parse_pack_multiple,
)
from tests.helpers.xlsx_fixtures import make_multisheet_xlsx

META = ReportMeta("unitka.xlsx", datetime.now(timezone.utc).isoformat())


@pytest.mark.parametrize(("value", "expected"), [
    ("40750", "40750"), (" 40750 ", "40750"), (40750, "40750"),
    (40750.0, "40750"), ("00123", "00123"), ("ABC-40750", "ABC-40750"),
])
def test_normalize_supplier_article(value, expected):
    assert normalize_supplier_article(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    (40750, "40750"), (40750.0, "40750"), (40750.5, "40750.5"),
    ("40750.0", "40750.0"), (" 40750 ", "40750"), ("00123", "00123"),
    (None, ""),
])
def test_source_aware_seller_article_identity(value, expected):
    assert normalize_seller_article_identity(value) == expected


@pytest.mark.parametrize("value", [40750.5, True, False, None, "", "   "])
def test_invalid_supplier_articles_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_supplier_article(value)


@pytest.mark.parametrize(("value", "expected"), [
    ("72/6", 6), ("36/6", 6), ("54/9", 9), ("100+/1", 1), ("72 / 6", 6),
])
def test_parse_pack_multiple(value, expected):
    assert parse_pack_multiple(value) == expected


@pytest.mark.parametrize("value", ["72/", "/6", "72/0", "72/-1", "72/1.5", "abc", "", None])
def test_invalid_pack_expressions_are_rejected(value):
    with pytest.raises(ValueError):
        parse_pack_multiple(value)


def test_import_collapses_identical_duplicates_and_blocks_conflicts_without_aborting_rows():
    data = make_multisheet_xlsx([
        ("Оглавление", ["КРАТНОСТЬ"], [[99]]),
        ("Прайс списком", ["КОД", "Упак"], [
            [40750.0, "72/6"], ["40750", "36/6"],
            ["OTHER", "72/6"], ["OTHER", "24/12"],
            [40750.5, "72/6"], ["BROKEN", "72/"],
        ]),
    ])
    result = import_supplier_packaging(data, META)
    by_article = {row.article: row for row in result.records}
    assert by_article["40750"].pack_multiple == 6
    assert by_article["OTHER"].pack_multiple is None
    assert by_article["OTHER"].reason_codes == ("CONFLICTING_PACK_MULTIPLICITY",)
    assert {d.code for d in result.diagnostics} >= {
        "INVALID_SUPPLIER_ARTICLE", "INVALID_PACK_MULTIPLICITY", "CONFLICTING_PACK_MULTIPLICITY",
    }
    assert next(d for d in result.diagnostics if d.code == "INVALID_SUPPLIER_ARTICLE").row == 6
