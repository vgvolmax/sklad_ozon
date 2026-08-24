"""Availability report importer."""

from dataclasses import dataclass
from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag, parse_non_negative_number, read_source_rows
from .normalization import normalize_cluster_label, normalize_text

_HEADERS = {"sku": "sku", "склад": "warehouse", "кластер": "cluster", "доступно": "available_quantity"}
_REQUIRED = frozenset(_HEADERS)


@dataclass(frozen=True, slots=True)
class AvailabilityRecord:
    sku: str
    warehouse: str
    cluster: str
    available_quantity: float


def import_availability(data: bytes, report_context: ReportMeta) -> ImportResult[AvailabilityRecord]:
    source = read_source_rows(data)
    diagnostics = list(source.diagnostics)
    if source.rows:
        missing = _REQUIRED - source.rows[0][1].keys()
    else:
        missing = _REQUIRED if not diagnostics else set()
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", f"Missing availability headers: {', '.join(sorted(missing))}"))
        return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, row in source.rows:
        try:
            quantity = parse_non_negative_number(row["доступно"])
            sku, warehouse = normalize_text(row["sku"]), normalize_text(row["склад"])
            cluster = normalize_cluster_label(row["кластер"])
            if not sku or not warehouse or not cluster:
                raise KeyError
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Availability quantity must be a non-negative number.", row=row_number, field="available_quantity"))
            continue
        except KeyError:
            diagnostics.append(_diag("MALFORMED_ROW", "Required availability value is blank.", row=row_number))
            continue
        records.append(AvailabilityRecord(sku, warehouse, cluster, quantity)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
