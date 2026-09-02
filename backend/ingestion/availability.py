"""Availability report importer."""

from dataclasses import dataclass, replace
import re
from backend.domain.contracts import ImportResult, ReportMeta
from ._common import _diag, parse_non_negative_number, read_source_rows, read_xlsx_tables
from .normalization import normalize_cluster_label, normalize_text

_HEADERS = {"sku": "sku", "склад": "warehouse", "кластер": "cluster", "доступно": "available_quantity"}
_RECOMMENDATION_HEADERS = {"рекомендуемая поставка", "рекомендуемая поставка по fbo"}
_RECOMMENDATION_HORIZON = re.compile(r"(?:на|за)\s+(\d+)\s+дн", re.IGNORECASE)
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
    product_name: str = ""
    days_without_stock: int | None = None
    inbound_quantity: int | None = None


def import_availability(data: bytes, report_context: ReportMeta) -> ImportResult[AvailabilityRecord]:
    # Operational XLSX headers may be shifted. Scan them in the first and only
    # workbook open instead of first assuming row one and reopening on fallback.
    source = (read_xlsx_tables(data, lambda h: _REQUIRED <= set(h) or ({"sku", "кластер", "артикул"} <= set(h) and
                               any("рекомендуемая поставка" in x for x in h)), read_only=True)
              if data.startswith(b"PK") else read_source_rows(data))
    diagnostics = list(source.diagnostics)
    recommendation_headers = {
        key for _, row in source.rows[:1] for key in row if "рекомендуемая поставка" in key
    }
    horizons = {
        int(match.group(1)) for header in recommendation_headers
        if (match := _RECOMMENDATION_HORIZON.search(header))
    }
    horizon = next(iter(horizons)) if len(horizons) == 1 else None
    if len(horizons) > 1:
        diagnostics.append(_diag(
            "CONFLICTING_RECOMMENDATION_HORIZON",
            "Recommendation columns declare conflicting horizons.",
            field="recommendation_horizon_days",
        ))
    if horizon != report_context.recommendation_horizon_days:
        report_context = replace(report_context, recommendation_horizon_days=horizon)
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
            days_without_stock = optional_int("дней без остатка за 28 дней")
            inbound = optional_int("товары в пути на склад озон, шт")
        except ValueError:
            fields = (
                ("fbo_quantity", "остаток fbo, шт"), ("fbs_quantity", "остаток fbs, шт"),
                ("days_without_stock", "дней без остатка за 28 дней"),
                ("inbound_quantity", "товары в пути на склад озон, шт"),
            )
            invalid_field = next((field for field, key in fields if row.get(key) not in (None, "") and _invalid_optional_int(row.get(key))), "operational_quantity")
            diagnostics.append(_diag("INVALID_NUMBER", "Operational evidence must be a non-negative integer.", row=row_number, field=invalid_field)); continue
        records.append(AvailabilityRecord(sku, warehouse, cluster, quantity, recommendation,
                                          normalize_text(row.get("артикул")), fbo, fbs,
                                          normalize_text(row.get("название товара")), days_without_stock, inbound)); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))


def _invalid_optional_int(value: object) -> bool:
    try:
        parsed = parse_non_negative_number(value)
        return not parsed.is_integer()
    except ValueError:
        return True
