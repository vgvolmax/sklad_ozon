"""Warehouse restriction report importer."""

from dataclasses import dataclass
from enum import Enum
from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag, read_source_rows, read_xlsx_tables
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
    cluster: str = ""
    max_supply_qty: int | None = None


def import_restrictions(data: bytes, report_context: ReportMeta) -> ImportResult[RestrictionRecord]:
    source = (read_xlsx_tables(data, lambda h: _REQUIRED <= set(h) or {"sku","кластер","склад","возможно ли поставить товар","максимальный размер поставки"} <= set(h), all_sheets=True, read_only=True)
              if data.startswith(b"PK") else read_source_rows(data)); diagnostics = list(source.diagnostics)
    real = bool(source.rows and "возможно ли поставить товар" in source.rows[0][1])
    if real:
        source = type(source)(tuple((n,{**r,"статус":r.get("возможно ли поставить товар")}) for n,r in source.rows),source.diagnostics)
    missing = _REQUIRED - source.rows[0][1].keys() if source.rows else (_REQUIRED if not diagnostics else set())
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", f"Missing restriction headers: {', '.join(sorted(missing))}"))
        return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, row in source.rows:
        sku, warehouse, raw = normalize_text(row.get("sku")), normalize_text(row.get("склад")), normalize_text(row.get("статус"))
        if not sku or not warehouse or not raw:
            diagnostics.append(_diag("MALFORMED_ROW", "Required restriction value is blank.", row=row_number)); continue
        state = {"да":RestrictionState.ALLOWED,"нет":RestrictionState.PROHIBITED,**_STATE_MAP}.get(raw.casefold(), RestrictionState.UNKNOWN)
        if state is RestrictionState.UNKNOWN:
            diagnostics.append(_diag("UNKNOWN_RESTRICTION_VALUE", f"Unknown restriction value: {raw!r}", row=row_number, field="state", severity="warning"))
        maximum = row.get("максимальный размер поставки")
        max_qty = None
        maximum_text = normalize_text(maximum).casefold()
        if state is RestrictionState.PROHIBITED and maximum_text in {"", "-"}:
            max_qty = None
        elif maximum not in (None, "") and maximum_text != "без ограничений":
            try:
                value=float(maximum); max_qty=int(value)
                if value != max_qty or max_qty < 0: raise ValueError
            except (ValueError,TypeError):
                diagnostics.append(_diag("INVALID_MAX_SUPPLY_QTY","Maximum supply quantity is invalid.",row=row_number)); continue
        records.append(RestrictionRecord(sku, warehouse, state, normalize_text(row.get("причина")), raw, normalize_text(row.get("кластер")), max_qty)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
