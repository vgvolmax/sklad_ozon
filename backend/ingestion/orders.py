"""Directional Ozon orders importer with a strict canonical-field whitelist."""

from backend.domain.contracts import ImportResult, OrderRecord, ReportMeta
from ._common import _diag, parse_non_negative_number, read_source_rows
from .lifecycle import classify_order_lifecycle
from .normalization import normalize_cluster_label, normalize_text

_REQUIRED = {"sku", "количество", "цена продавца", "кластер отгрузки", "кластер доставки", "статус"}


def import_orders(data: bytes, report_context: ReportMeta) -> ImportResult[OrderRecord]:
    source = read_source_rows(data); diagnostics = list(source.diagnostics)
    missing = _REQUIRED - source.rows[0][1].keys() if source.rows else (_REQUIRED if not diagnostics else set())
    if missing:
        diagnostics.append(_diag("MISSING_REQUIRED_HEADER", f"Missing order headers: {', '.join(sorted(missing))}"))
        return ImportResult((), tuple(diagnostics), report_context)
    records, sources = [], []
    for row_number, row in source.rows:
        try:
            quantity_number = parse_non_negative_number(row["количество"])
            if not quantity_number.is_integer():
                raise ValueError
            price = parse_non_negative_number(row["цена продавца"])
            sku = normalize_text(row["sku"])
            origin = normalize_cluster_label(row["кластер отгрузки"])
            destination = normalize_cluster_label(row["кластер доставки"])
            if not sku or not origin or not destination:
                raise KeyError
        except ValueError:
            diagnostics.append(_diag("INVALID_NUMBER", "Order quantity and seller price must be valid non-negative numbers.", row=row_number)); continue
        except KeyError:
            diagnostics.append(_diag("MALFORMED_ROW", "Required order value is blank.", row=row_number)); continue
        raw_status = normalize_text(row["статус"])
        lifecycle, lifecycle_diagnostic = classify_order_lifecycle(raw_status)
        if lifecycle_diagnostic:
            diagnostics.append(type(lifecycle_diagnostic)(
                lifecycle_diagnostic.severity, lifecycle_diagnostic.code,
                lifecycle_diagnostic.message, row_number, lifecycle_diagnostic.field,
            ))
        # Deliberately construct only the canonical OrderRecord whitelist. Any
        # buyer, address, phone, email, or other source columns are discarded.
        records.append(OrderRecord(
            sku=sku, quantity=int(quantity_number), origin_cluster=origin,
            destination_cluster=destination, lifecycle=lifecycle,
            accepted_at=normalize_text(row.get("принят в обработку")), raw_status=raw_status,
            article=normalize_text(row.get("артикул продавца")),
            product_name=normalize_text(row.get("название товара")), seller_price=price,
            origin_warehouse=normalize_text(row.get("склад отгрузки")) or None,
        )); sources.append(row_number)
    return ImportResult(tuple(records), tuple(diagnostics), report_context, tuple(sources))
