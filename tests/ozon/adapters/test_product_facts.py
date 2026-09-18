from decimal import Decimal

from backend.ozon.adapters.product_facts import (
    dimensions_to_liters, normalize_product_attributes, normalize_product_prices,
)
from backend.ozon.adapters.products import ProductCatalogItem

CATALOG = (
    ProductCatalogItem("SKU-1", 101, "ART-1"),
    ProductCatalogItem("SKU-2", 102, "ART-2"),
)


def test_price_and_zero_commission_are_normalized_from_exact_fields():
    records, diagnostics, quality = normalize_product_prices({"items": [{
        "product_id": 101, "offer_id": "ART-1",
        "price": {"price": "550", "currency_code": "RUB", "marketing_price": "1"},
        "commissions": {"sales_percent_fbo": 0, "acquiring": 99},
        "volume_weight": 777,
    }]}, CATALOG)

    assert records[0].price == Decimal("550")
    assert records[0].commission_rate == Decimal("0")
    assert records[0].volume_liters is None
    assert diagnostics == ()
    assert quality.incomplete_skus == ()


def test_non_rub_price_and_invalid_commission_fail_closed_per_sku():
    records, diagnostics, quality = normalize_product_prices({"items": [
        {"product_id": 101, "price": {"price": "550", "currency_code": "USD"},
         "commissions": {"sales_percent_fbo": 101}},
        {"product_id": 102, "price": {"price": "600", "currency_code": "RUB"},
         "commissions": {"sales_percent_fbo": 41}},
    ]}, CATALOG)

    assert records[0].price is None and records[0].commission_rate is None
    assert records[1].price == Decimal("600") and records[1].commission_rate == Decimal("0.41")
    assert quality.incomplete_skus == ("SKU-1",)
    assert {item.code for item in diagnostics} == {"PRODUCT_API_PRICE_MISSING", "PRODUCT_API_COMMISSION_MISSING"}


def test_dimensions_use_decimal_physical_volume_and_never_volume_weight():
    records, _, _ = normalize_product_attributes({"result": [{
        "id": 101, "offer_id": "ART-1", "width": 100, "height": 50,
        "depth": 20, "dimension_unit": "mm", "volume_weight": 500,
    }]}, CATALOG)

    assert records[0].volume_liters == Decimal("0.1")
    assert dimensions_to_liters("10", "5", "2", "cm") == Decimal("0.1")
    assert dimensions_to_liters("1", "1", "1", "in") == Decimal("0.016387064")


def test_bad_dimensions_are_scoped_and_never_fabricated_as_zero():
    records, diagnostics, quality = normalize_product_attributes({"result": [
        {"id": 101, "width": 1, "height": 2, "depth": 3, "dimension_unit": "parsec"},
        {"id": 102, "width": 0, "height": 2, "depth": 3, "dimension_unit": "mm"},
    ]}, CATALOG)

    assert [item.volume_liters for item in records] == [None, None]
    assert quality.incomplete_skus == ("SKU-1", "SKU-2")
    assert [item.code for item in diagnostics] == [
        "PRODUCT_API_DIMENSION_UNIT_UNSUPPORTED", "PRODUCT_API_DIMENSIONS_MISSING",
    ]
