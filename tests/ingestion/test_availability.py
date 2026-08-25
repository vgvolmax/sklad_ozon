from backend.domain.contracts import ReportMeta
from backend.ingestion.availability import import_availability
from tests.helpers.xlsx_fixtures import make_xlsx

META = ReportMeta(source_name="availability.xlsx", imported_at="2026-08-21T10:00:00Z", report_generated_at="2026-08-20")
_ROWS = [
    ["1001", "Склад Казань", "Казань", 12],
    ["1002", "Склад Москва", "Москва", 0],
    ["1003", "Склад Омск", "Омск", "1,5"],
    ["bad1", "W", "C", -1],
    ["bad2", "W", "C", "нет"],
]


def availability_xlsx() -> bytes:
    return make_xlsx(
        headers=["SKU", "Склад", "Кластер", "Доступно"],
        rows=_ROWS,
        malformed_dimension=True,
    )


def test_imports_all_malformed_dimension_rows_with_metadata_and_sources():
    result = import_availability(availability_xlsx(), META)
    assert len(result.records) == 3
    assert result.record_sources == (2, 3, 4)
    assert result.meta is META
    assert result.records[0].sku == "1001"
    assert result.records[0].warehouse == "Склад Казань"
    assert result.records[0].cluster == "Казань"
    assert result.records[0].available_quantity == 12
    assert "WORKSHEET_DIMENSION_REPAIRED" in [d.code for d in result.diagnostics]


def test_rejects_negative_and_malformed_numbers_with_source_rows():
    result = import_availability(availability_xlsx(), META)
    assert [r.sku for r in result.records] == ["1001", "1002", "1003"]
    invalid = [d for d in result.diagnostics if d.code == "INVALID_NUMBER"]
    assert [(d.row, d.field) for d in invalid] == [(5, "available_quantity"), (6, "available_quantity")]


def test_missing_and_duplicate_headers_are_structural_errors():
    missing = import_availability("SKU,Склад\n1,Казань\n".encode(), META)
    duplicate = import_availability("SKU, sku,Склад,Кластер,Доступно\n1,2,W,C,1\n".encode(), META)
    assert "MISSING_REQUIRED_HEADER" in [d.code for d in missing.diagnostics]
    assert [d.code for d in duplicate.diagnostics] == ["DUPLICATE_HEADER"]


def test_non_finite_quantity_is_rejected():
    result = import_availability("SKU,Склад,Кластер,Доступно\n1,W,C,NaN\n".encode(), META)
    assert result.records == ()
    assert [d.code for d in result.diagnostics] == ["INVALID_NUMBER"]

def test_optional_cluster_recommendation_aliases_and_validation():
    base = [["SKU", "Склад", "Кластер", "Доступно", "Рекомендуемая поставка"],
            ["1", "W1", "Москва", 99, 10], ["2", "W2", "Казань", 1, -1],
            ["3", "W3", "Казань", 1, 1.5], ["4", "W4", "Казань", 1, "bad"]]
    result = import_availability(make_xlsx(headers=base[0], rows=base[1:]), META)
    assert result.records[0].recommended_quantity == 10
    assert len([d for d in result.diagnostics if d.field == "recommended_quantity"]) == 3


def test_fbo_recommendation_alias():
    result = import_availability(make_xlsx(headers=["SKU","Склад","Кластер","Доступно","Рекомендуемая поставка по FBO"], rows=[["1","W","Москва",2,7]]), META)
    assert result.records[0].recommended_quantity == 7
