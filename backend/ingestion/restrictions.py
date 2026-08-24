"""Warehouse restriction report importer."""

from dataclasses import dataclass
from enum import Enum
from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag, read_source_rows
from .normalization import normalize_text


class RestrictionState(str, Enum):
    ALLOWED = "allowed"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


_STATE_MAP = {"разрешено": RestrictionState.ALLOWED, "запрещено": RestrictionState.PROHIBITED}
_REQUIRED = {"sku", "склад", "статус"}


@dataclass(frozen=True, slots=True)
class RestrictionRecord:
    sku: str
    warehouse: str
    state: RestrictionState
    reason: str
    source_value: str


def import_restrictions(data: bytes, report_context: ReportMeta) -> ImportResult[RestrictionRecord]:
    source = read_source_rows(data); diagnostics = list(source.diagnostics)
    missing = _REQUIRED - source.rows[0][1].keys() if source.rows else (_REQUIRED if not diagnostics else set())
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", f"Missing restriction headers: {', '.join(sorted(missing))}"))
        return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, row in source.rows:
        sku, warehouse, raw = normalize_text(row.get("sku")), normalize_text(row.get("склад")), normalize_text(row.get("статус"))
        if not sku or not warehouse or not raw:
            diagnostics.append(_diag("MALFORMED_ROW", "Required restriction value is blank.", row=row_number)); continue
        state = _STATE_MAP.get(raw.casefold(), RestrictionState.UNKNOWN)
        if state is RestrictionState.UNKNOWN:
            diagnostics.append(_diag("UNKNOWN_RESTRICTION_VALUE", f"Unknown restriction value: {raw!r}", row=row_number, field="state", severity="warning"))
        records.append(RestrictionRecord(sku, warehouse, state, normalize_text(row.get("причина")), raw)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
