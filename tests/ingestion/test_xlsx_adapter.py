from io import BytesIO
from datetime import datetime, timezone
from types import SimpleNamespace
from xml.etree import ElementTree
from zipfile import ZipFile

import openpyxl.writer.excel as excel_writer

from backend.ingestion.xlsx import iter_worksheet_rows
from tests.helpers.xlsx_fixtures import make_xlsx, worksheet_xml

_ROWS = [["1001"], ["1002"], ["1003"]]
_XML_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def test_malformed_dimension_returns_all_populated_rows_and_one_diagnostic():
    payload = make_xlsx(headers=["SKU"], rows=_ROWS, malformed_dimension=True)
    xml = worksheet_xml(payload)

    assert b'<dimension ref="A1"' in xml
    assert len(ElementTree.fromstring(xml).findall(".//main:row", _XML_NS)) == 4

    result = iter_worksheet_rows(BytesIO(payload), 0)
    assert [row.source_row for row in result.rows] == [1, 2, 3, 4]
    assert [row.values[0] for row in result.rows] == ["SKU", "1001", "1002", "1003"]
    assert [d.code for d in result.diagnostics] == ["WORKSHEET_DIMENSION_REPAIRED"]


def test_regular_workbook_needs_no_repair(monkeypatch):
    # openpyxl overwrites modified on save; cross a second boundary deliberately.
    moments = iter((datetime(2026, 9, 30, 11, 0, 0, tzinfo=timezone.utc),
                    datetime(2026, 9, 30, 11, 0, 1, tzinfo=timezone.utc)))

    class SaveClock:
        @staticmethod
        def now(tz=None):
            return next(moments)

    monkeypatch.setattr(excel_writer, "datetime", SimpleNamespace(datetime=SaveClock, timezone=timezone))
    payload = make_xlsx(headers=["SKU"], rows=_ROWS)
    assert payload == make_xlsx(headers=["SKU"], rows=_ROWS)
    with ZipFile(BytesIO(payload)) as archive:
        core_xml = archive.read("docProps/core.xml")
    namespaces = dict(namespace for _, namespace in ElementTree.iterparse(BytesIO(core_xml), events=("start-ns",)))
    core = ElementTree.fromstring(core_xml)
    for field in ("created", "modified"):
        node = core.find("{http://purl.org/dc/terms/}" + field)
        type_prefix = node.attrib["{http://www.w3.org/2001/XMLSchema-instance}type"].split(":")[0]
        assert namespaces[type_prefix] == "http://purl.org/dc/terms/"
    result = iter_worksheet_rows(BytesIO(payload), "Отчёт")
    assert len(result.rows) == 4
    assert result.diagnostics == ()


def test_real_one_cell_workbook_needs_no_repair_diagnostic():
    payload = make_xlsx(headers=["SKU"], rows=[])

    result = iter_worksheet_rows(BytesIO(payload), 0)

    assert [(row.source_row, row.values) for row in result.rows] == [(1, ("SKU",))]
    assert result.diagnostics == ()
