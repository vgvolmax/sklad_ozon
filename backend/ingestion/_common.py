"""Small shared row/header utilities for operational importers."""

from dataclasses import dataclass
from io import BytesIO
from math import isfinite

from backend.domain.contracts import ImportDiagnostic
from .csv_adapter import iter_csv_rows
from .normalization import normalize_header


@dataclass(frozen=True, slots=True)
class SourceRows:
    rows: tuple[tuple[int, dict[str, object]], ...]
    diagnostics: tuple[ImportDiagnostic, ...]


def read_source_rows(data: bytes) -> SourceRows:
    if data.startswith(b"PK"):
        from .xlsx import iter_worksheet_rows
        adapted = iter_worksheet_rows(BytesIO(data), 0)
        if not adapted.rows:
            return SourceRows((), adapted.diagnostics + (_diag("MISSING_HEADER", "Worksheet header is missing."),))
        headers = [normalize_header(v) for v in adapted.rows[0].values]
        duplicate = next((h for h in headers if h and headers.count(h) > 1), None)
        if duplicate:
            return SourceRows((), adapted.diagnostics + (_diag("DUPLICATE_HEADER", f"Duplicate normalized header: {duplicate}", field=duplicate),))
        rows = tuple((row.source_row, dict(zip(headers, row.values, strict=False))) for row in adapted.rows[1:])
        return SourceRows(rows, adapted.diagnostics)
    adapted = iter_csv_rows(data)
    return SourceRows(tuple((row.source_row, row.values) for row in adapted.rows), adapted.diagnostics)


def parse_non_negative_number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        number = float(str(value).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    if not isfinite(number) or number < 0:
        raise ValueError
    return number


def _diag(code: str, message: str, *, row=None, field=None, severity="error"):
    return ImportDiagnostic(severity=severity, code=code, message=message, row=row, field=field)
