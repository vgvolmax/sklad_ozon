"""Availability report importer."""

from dataclasses import dataclass
from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag, parse_non_negative_number, read_source_rows, read_xlsx_tables
from .normalization import normalize_cluster_label, normalize_text

_HEADERS = {"sku": "sku", "склад": "warehouse", "кластер": "cluster", "доступно": "available_quantity"}
_RECOMMENDATION_HEADERS = {"рекомендуемая поставка", "рекомендуемая поставка по fbo"}
_REQUIRED = frozenset(_HEADERS)


@dataclass(frozen=True, slots=True)
class AvailabilityRecord:
    sku: str
    warehouse: str
    cluster: str
    available_quantity: float
    recommended_quantity: int | None = None
    article: str = ""
    fbo_quantity: int | None = None
    fbs_quantity: int | None = None


def import_availability(data: bytes, report_context: ReportMeta) -> ImportResult[AvailabilityRecord]:
    source = read_source_rows(data)
    if data.startswith(b"PK") and not (source.rows and _REQUIRED <= source.rows[0][1].keys()):
        source = read_xlsx_tables(data, lambda h: _REQUIRED <= set(h) or ({"sku", "кластер", "артикул"} <= set(h) and
                                 any("рекомендуемая поставка" in x for x in h)))
    diagnostics = list(source.diagnostics)
    if source.rows:
        keys = source.rows[0][1].keys()
        real = "артикул" in keys and any("рекомендуемая поставка" in key for key in keys)
        missing = set() if real else _REQUIRED - keys
    else:
        missing = _REQUIRED if not diagnostics else set()
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", f"Missing availability headers: {', '.join(sorted(missing))}"))
        return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, row in source.rows:
        try:
            quantity = parse_non_negative_number(row.get("доступно", row.get("остаток fbo, шт", 0)))
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Availability quantity must be a non-negative number.", row=row_number, field="available_quantity"))
            continue
        try:
            sku, warehouse = normalize_text(row["sku"]), normalize_text(row.get("склад")) or normalize_text(row["кластер"])
            cluster = normalize_cluster_label(row["кластер"])
            if not sku or not warehouse or not cluster:
                raise KeyError
            raw_recommendation = next((value for key, value in row.items() if "рекомендуемая поставка" in key), None)
            if raw_recommendation is None or (isinstance(raw_recommendation, str) and not raw_recommendation.strip()):
                recommendation = None
            else:
                parsed = parse_non_negative_number(raw_recommendation)
                if not parsed.is_integer():
                    raise ValueError
                recommendation = int(parsed)
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Recommendation quantity must be a non-negative integer.", row=row_number, field="recommended_quantity"))
            continue
        except KeyError:
            diagnostics.append(_diag("MALFORMED_ROW", "Required availability value is blank.", row=row_number))
            continue
        def optional_int(key):
            value = row.get(key)
            if value is None or str(value).strip() == "": return None
            parsed = parse_non_negative_number(value)
            if not parsed.is_integer(): raise ValueError
            return int(parsed)
        try:
            fbo, fbs = optional_int("остаток fbo, шт"), optional_int("остаток fbs, шт")
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Operational stock must be a non-negative integer.", row=row_number)); continue
        records.append(AvailabilityRecord(sku, warehouse, cluster, quantity, recommendation,
                                          normalize_text(row.get("артикул")), fbo, fbs)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
