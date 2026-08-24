"""Deterministic stdlib CSV adapter for comma and semicolon reports."""

import csv
import io
from dataclasses import dataclass

from backend.domain.contracts import ImportDiagnostic
from .normalization import normalize_header


@dataclass(frozen=True, slots=True)
class CsvRow:
    source_row: int
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class CsvRows:
    rows: tuple[CsvRow, ...]
    diagnostics: tuple[ImportDiagnostic, ...]


def iter_csv_rows(data: bytes, encoding: str = "utf-8-sig") -> CsvRows:
    text = data.decode(encoding)
    if not text.strip():
        return CsvRows((), (_diagnostic("MISSING_HEADER", "CSV header is missing."),))
    first_line = text.splitlines()[0]
    try:
        delimiter = csv.Sniffer().sniff(first_line, delimiters=",;").delimiter
    except csv.Error:
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    raw_headers = next(reader, [])
    headers = [normalize_header(value) for value in raw_headers]
    if not headers or not any(headers):
        return CsvRows((), (_diagnostic("MISSING_HEADER", "CSV header is missing."),))
    duplicates = sorted({header for header in headers if header and headers.count(header) > 1})
    if duplicates:
        return CsvRows((), (_diagnostic("DUPLICATE_HEADER", f"Duplicate normalized header: {duplicates[0]}", field=duplicates[0]),))
    rows = []
    diagnostics = []
    previous_line = reader.line_num
    for values in reader:
        source_row = previous_line + 1
        previous_line = reader.line_num
        if not any(value.strip() for value in values):
            continue
        if len(values) != len(headers):
            diagnostics.append(ImportDiagnostic(
                severity="error", code="MALFORMED_ROW",
                message="CSV row width does not match its header.", row=source_row,
            ))
            continue
        rows.append(CsvRow(source_row, dict(zip(headers, values, strict=True))))
    return CsvRows(tuple(rows), tuple(diagnostics))


def _diagnostic(code: str, message: str, field: str | None = None) -> ImportDiagnostic:
    return ImportDiagnostic(severity="error", code=code, message=message, field=field)
