from backend.ozon.adapters.orders import normalize_fbs_posting


def _posting():
    return {
        "posting_number": "FBS-PRICE-1",
        "status": "delivered",
        "in_process_at": "2026-09-15T10:00:00Z",
        "financial_data": {"cluster_from": "", "cluster_to": "Москва"},
        "products": [{"sku": "SKU-1", "quantity": 1}],
    }


def test_missing_optional_price_keeps_demand_record_without_warning():
    records, diagnostics, quality = normalize_fbs_posting(_posting())

    assert len(records) == 1
    assert records[0].seller_price == 0.0
    assert diagnostics == ()
    assert quality.rejected_record_count == 0
    assert quality.incomplete_skus == ()


def test_present_malformed_price_warns_without_losing_demand_record():
    posting = _posting()
    posting["products"][0]["price"] = {"currency": "RUB"}

    records, diagnostics, quality = normalize_fbs_posting(posting)

    assert len(records) == 1
    assert records[0].seller_price == 0.0
    assert [(item.code, item.severity, item.field) for item in diagnostics] == [
        ("INVALID_ORDER_PRICE", "warning", "price")
    ]
    assert quality.rejected_record_count == 0
    assert quality.incomplete_skus == ()
