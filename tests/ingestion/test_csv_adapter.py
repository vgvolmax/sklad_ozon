import pytest
from backend.ingestion.csv_adapter import iter_csv_rows


def test_bom_comma_quotes_crlf_and_source_rows():
    result = iter_csv_rows('\ufeff SKU ,Название\r\n1,"Товар, один"\r\n'.encode())
    assert result.rows[0].source_row == 2
    assert result.rows[0].values == {"sku": "1", "название": "Товар, один"}
    assert result.diagnostics == ()


def test_semicolon_quotes_and_lf():
    result = iter_csv_rows('SKU;Склад\n2;"Казань; Восток"\n'.encode())
    assert result.rows[0].values["склад"] == "Казань; Восток"


@pytest.mark.parametrize(("data", "code"), [
    (b"", "MISSING_HEADER"),
    ("SKU; sku\n1;2\n".encode(), "DUPLICATE_HEADER"),
])
def test_invalid_headers_are_rejected(data, code):
    result = iter_csv_rows(data)
    assert result.rows == ()
    assert [d.code for d in result.diagnostics] == [code]


def test_multiline_records_keep_physical_start_rows_and_bad_width_is_rejected():
    result = iter_csv_rows('SKU,Комментарий\n1,"строка 1\nстрока 2"\n2,ok\n3,extra,value\n'.encode())
    assert [row.source_row for row in result.rows] == [2, 4]
    assert result.rows[0].values["комментарий"] == "строка 1\nстрока 2"
    assert [(d.code, d.row) for d in result.diagnostics] == [("MALFORMED_ROW", 5)]
