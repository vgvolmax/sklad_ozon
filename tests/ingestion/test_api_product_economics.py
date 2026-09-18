from decimal import Decimal

from backend.domain.contracts import ProductEconomicsInput
from backend.ingestion.api_product_economics import merge_api_product_economics
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.adapters.product_facts import ProductApiFacts


def product(*, volume=None):
    return ProductEconomicsInput("SKU-1", "UNITKA-ART", Decimal("100"), 999,
                                 Decimal("500"), Decimal("0.20"), volume)


def facts(*, volume=Decimal("0.35")):
    return ProductApiFacts("SKU-1", "API-ART", 101, Decimal("550"), Decimal("0.41"), volume)


def test_api_facts_and_seller_stock_are_authoritative_for_canonical_product():
    merged, diagnostics = merge_api_product_economics(
        (product(),), (facts(),),
        (AvailabilityRecord("SKU-1", "Seller", "", 24, fbs_quantity=24),),
    )

    assert merged == (ProductEconomicsInput(
        "SKU-1", "API-ART", Decimal("100"), 24, Decimal("550"),
        Decimal("0.41"), Decimal("0.35")),)
    assert {item.code for item in diagnostics} == {
        "API_UNITKA_PRICE_MISMATCH", "API_UNITKA_COMMISSION_MISMATCH",
    }


def test_missing_api_volume_falls_back_with_explicit_diagnostic():
    merged, diagnostics = merge_api_product_economics(
        (product(volume=Decimal("0.12")),), (facts(volume=None),), ())

    assert merged[0].volume_liters == Decimal("0.12")
    assert merged[0].available_qty is None
    assert "PRODUCT_VOLUME_FALLBACK_TO_UNITKA" in {item.code for item in diagnostics}


def test_small_decimal_volume_rounding_difference_is_not_a_mismatch():
    _, diagnostics = merge_api_product_economics(
        (product(volume=Decimal("0.3505")),), (facts(),), ())

    assert "API_UNITKA_VOLUME_MISMATCH" not in {item.code for item in diagnostics}
