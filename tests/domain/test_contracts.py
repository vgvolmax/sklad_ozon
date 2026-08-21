from dataclasses import asdict, fields

import pytest

from backend.domain.contracts import (
    ImportDiagnostic, ImportResult, OrderLifecycle, OrderRecord, ReportMeta,
)


def test_foundation_contracts_are_typed_and_serializable():
    meta = ReportMeta(source_name="orders.csv", imported_at="2026-08-21T00:00:00Z")
    diagnostic = ImportDiagnostic("error", "BAD_ROW", "Bad row", row=4, field="sku")
    result = ImportResult(records=(), diagnostics=(diagnostic,), meta=meta)
    assert asdict(result)["diagnostics"][0]["code"] == "BAD_ROW"
    assert [item.value for item in OrderLifecycle] == [
        "fulfilled", "in_progress", "cancelled", "unknown",
    ]


def test_order_record_whitelist_excludes_pii_and_raw_rows():
    names = {field.name for field in fields(OrderRecord)}
    forbidden = {"buyer_name", "customer_name", "address", "phone", "email",
                 "inn", "kpp", "payment_info", "raw_row"}
    assert names.isdisjoint(forbidden)
    with pytest.raises(TypeError):
        OrderRecord(sku="1", quantity=1, origin_cluster="Kazan",
                    destination_cluster="Moscow", buyer_name="PII")
