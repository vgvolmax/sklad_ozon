from backend.domain.contracts import ReportMeta
from backend.ingestion.restrictions import RestrictionState, import_restrictions
from tests.helpers.xlsx_fixtures import make_xlsx

META = ReportMeta(source_name="restrictions.xlsx", imported_at="2026-08-21T10:00:00Z", report_generated_at="2026-08-20")


def restrictions_xlsx() -> bytes:
    return make_xlsx(
        headers=["SKU", "Склад", "Статус", "Причина"],
        rows=[
            ["1001", "Склад Казань", "Разрешено", ""],
            ["1002", "Склад Москва", "Запрещено", "Ограничение склада"],
            ["1003", "Склад Омск", "На проверке", "Новый источник"],
        ],
    )


def test_explicit_states_unknown_diagnostic_sources_and_metadata():
    result = import_restrictions(restrictions_xlsx(), META)
    assert [r.state for r in result.records] == [RestrictionState.ALLOWED, RestrictionState.PROHIBITED, RestrictionState.UNKNOWN]
    assert result.record_sources == (2, 3, 4)
    assert result.meta is META
    unknown = next(d for d in result.diagnostics if d.code == "UNKNOWN_RESTRICTION_VALUE")
    assert unknown.row == 4 and "На проверке" in unknown.message
    assert result.records[2].source_value == "На проверке"


def test_malformed_rows_and_structural_headers():
    malformed = import_restrictions("SKU;Склад;Статус\n;W;Разрешено\n".encode(), META)
    assert [d.code for d in malformed.diagnostics] == ["MALFORMED_ROW"]
    missing = import_restrictions("SKU;Склад\n1;W\n".encode(), META)
    duplicate = import_restrictions("SKU; sku;Склад;Статус\n1;2;W;Разрешено\n".encode(), META)
    assert "MISSING_REQUIRED_HEADER" in [d.code for d in missing.diagnostics]
    assert [d.code for d in duplicate.diagnostics] == ["DUPLICATE_HEADER"]
