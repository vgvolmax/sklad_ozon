"""Deterministic, sanitized XLSX payloads generated only for tests."""

from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook

_WORKSHEET_XML = "xl/worksheets/sheet1.xml"
_FIXED_TIMESTAMP = (2026, 8, 20, 0, 0, 0)


def make_xlsx(*, headers: list[object], rows: list[list[object]], malformed_dimension: bool = False) -> bytes:
    """Build a one-sheet workbook, optionally corrupting only its declared range."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Отчёт"
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    fixed_time = datetime(2026, 8, 20, tzinfo=timezone.utc)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time

    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    payload = stream.getvalue()
    if malformed_dimension:
        payload = _replace_dimension_with_a1(payload)
    return _normalize_zip_metadata(payload)


def make_multisheet_xlsx(sheets: list[tuple[str, list[object], list[list[object]]]]) -> bytes:
    """Build a deterministic workbook with explicitly named worksheets."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, headers, rows in sheets:
        worksheet = workbook.create_sheet(name)
        worksheet.append(headers)
        for row in rows:
            worksheet.append(row)
    fixed_time = datetime(2026, 8, 20, tzinfo=timezone.utc)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return _normalize_zip_metadata(stream.getvalue())


def worksheet_xml(payload: bytes) -> bytes:
    """Expose worksheet XML so tests can independently prove fixture shape."""
    with ZipFile(BytesIO(payload)) as archive:
        return archive.read(_WORKSHEET_XML)


def _replace_dimension_with_a1(payload: bytes) -> bytes:
    source = BytesIO(payload)
    target = BytesIO()
    with ZipFile(source) as archive, ZipFile(target, "w", ZIP_DEFLATED) as rebuilt:
        for name in archive.namelist():
            content = archive.read(name)
            if name == _WORKSHEET_XML:
                start = content.index(b"<dimension ")
                end = content.index(b"/>", start) + 2
                content = content[:start] + b'<dimension ref="A1"/>' + content[end:]
            rebuilt.writestr(name, content)
    return target.getvalue()


def _normalize_zip_metadata(payload: bytes) -> bytes:
    target = BytesIO()
    with ZipFile(BytesIO(payload)) as archive, ZipFile(target, "w", ZIP_DEFLATED) as rebuilt:
        for name in sorted(archive.namelist()):
            info = ZipInfo(name, _FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = archive.getinfo(name).external_attr
            rebuilt.writestr(info, archive.read(name))
    return target.getvalue()
