"""Supplier-owned article and pack-multiplicity workbook evidence."""

from dataclasses import dataclass
from io import BytesIO
from math import isfinite
import re

from openpyxl import load_workbook

from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag
from .normalization import normalize_header, normalize_text

_SHEET = "Прайс списком"
_ARTICLE_HEADER = "код"
_PACK_HEADER = "упак"
_PACK_PATTERN = re.compile(r"^\s*[^/\s][^/]*/\s*([1-9]\d*)\s*$")


@dataclass(frozen=True, slots=True)
class PackMultiplicityEvidence:
    article: str
    pack_multiple: int | None
    source_row: int | None
    source_value: str | None
    reason_codes: tuple[str, ...]


def normalize_supplier_article(value: object) -> str:
    """Normalize real numeric spreadsheet cells without coercing string identity."""
    if isinstance(value, bool) or value is None:
        raise ValueError("supplier article is invalid")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not isfinite(value) or not value.is_integer():
            raise ValueError("supplier article is invalid")
        return str(int(value))
    if isinstance(value, str):
        article = value.strip()
        if article:
            return article
    raise ValueError("supplier article is invalid")


def parse_pack_multiple(value: object) -> int:
    """Return the positive integer on the right of a valid packaging slash."""
    if value is None or isinstance(value, bool):
        raise ValueError("pack multiplicity is invalid")
    match = _PACK_PATTERN.fullmatch(str(value))
    if match is None:
        raise ValueError("pack multiplicity is invalid")
    return int(match.group(1))


def import_supplier_packaging(data: bytes, report_context: ReportMeta, *, workbook=None) -> ImportResult[PackMultiplicityEvidence]:
    if not data.startswith(b"PK"):
        return ImportResult((), (_diag("SUPPLIER_PACKAGING_SHEET_NOT_FOUND", "Supplier packaging requires the Unitka XLSX workbook."),), report_context)
    owns_workbook = workbook is None
    if owns_workbook:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    try:
        if _SHEET not in workbook.sheetnames:
            return ImportResult((), (_diag("SUPPLIER_PACKAGING_SHEET_NOT_FOUND", f"Worksheet {_SHEET!r} is missing."),), report_context)
        worksheet = workbook[_SHEET]
        binding = None
        header_row = None
        for row_number, values in enumerate(worksheet.iter_rows(max_row=30, values_only=True), 1):
            headers = [normalize_header(value) for value in values]
            if _ARTICLE_HEADER in headers and _PACK_HEADER in headers:
                binding = (headers.index(_ARTICLE_HEADER), headers.index(_PACK_HEADER))
                header_row = row_number
                break
        if binding is None or header_row is None:
            return ImportResult((), (_diag("MISSING_SUPPLIER_PACKAGING_HEADERS", "Прайс списком must contain КОД and Упак."),), report_context)

        diagnostics = []
        observations: dict[str, list[tuple[int | None, int, str]]] = {}
        invalid_by_article: dict[str, tuple[int, str | None]] = {}
        for row_number, values in enumerate(worksheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
            article_value = values[binding[0]] if binding[0] < len(values) else None
            pack_value = values[binding[1]] if binding[1] < len(values) else None
            if article_value is None and pack_value is None:
                continue
            try:
                article = normalize_supplier_article(article_value)
            except ValueError:
                diagnostics.append(_diag("INVALID_SUPPLIER_ARTICLE", "Supplier article is blank or not integer-like.", row=row_number, field="КОД"))
                continue
            source_value = None if pack_value is None else str(pack_value).strip()
            try:
                multiple = parse_pack_multiple(pack_value)
            except ValueError:
                diagnostics.append(_diag("INVALID_PACK_MULTIPLICITY", "Упак must end in '/' followed by a positive integer.", row=row_number, field="Упак"))
                invalid_by_article.setdefault(article, (row_number, source_value))
                continue
            observations.setdefault(article, []).append((multiple, row_number, source_value or ""))

        records = []
        for article in sorted(set(observations) | set(invalid_by_article)):
            rows = observations.get(article, [])
            multiples = {item[0] for item in rows}
            if len(multiples) > 1:
                records.append(PackMultiplicityEvidence(article, None, min(item[1] for item in rows), None, ("CONFLICTING_PACK_MULTIPLICITY",)))
                diagnostics.append(_diag("CONFLICTING_PACK_MULTIPLICITY", f"Article {article!r} has conflicting pack multiples.", field="Упак"))
            elif rows:
                multiple, source_row, source_value = rows[0]
                records.append(PackMultiplicityEvidence(article, multiple, source_row, source_value, ()))
            else:
                source_row, source_value = invalid_by_article[article]
                records.append(PackMultiplicityEvidence(article, None, source_row, source_value, ("INVALID_PACK_MULTIPLICITY",)))
        return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(record.source_row for record in records))
    finally:
        if owns_workbook:
            workbook.close()
