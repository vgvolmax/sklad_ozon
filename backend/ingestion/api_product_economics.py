"""Canonical API-mode merge of Ozon facts with Unitka-owned product inputs."""

from dataclasses import replace
from decimal import Decimal

from backend.domain.contracts import ImportDiagnostic, ProductEconomicsInput

VOLUME_TOLERANCE_LITERS = Decimal("0.001")


def _stock_by_sku(rows):
    grouped = {}
    for row in rows:
        value = getattr(row, "fbs_quantity", None)
        if value is not None:
            grouped.setdefault(row.sku, []).append(value)
    result = {}
    for sku, values in grouped.items():
        positives = {value for value in values if value > 0}
        if len(positives) == 1:
            result[sku] = next(iter(positives))
        elif not positives and values:
            result[sku] = 0
    return result


def merge_api_product_economics(unitka_products, product_facts, seller_stock):
    """Use valid API facts first while retaining Unitka as an explicit fallback."""
    facts = {item.sku: item for item in product_facts}
    stock = _stock_by_sku(seller_stock)
    merged, diagnostics = [], []
    for unitka in unitka_products:
        fact = facts.get(unitka.sku)
        values = {}
        for field, missing_code, fallback_code, mismatch_code, tolerance in (
            ("price", "PRODUCT_API_PRICE_MISSING", "PRODUCT_PRICE_FALLBACK_TO_UNITKA", "API_UNITKA_PRICE_MISMATCH", Decimal("0")),
            ("commission_rate", "PRODUCT_API_COMMISSION_MISSING", "PRODUCT_COMMISSION_FALLBACK_TO_UNITKA", "API_UNITKA_COMMISSION_MISMATCH", Decimal("0")),
            ("volume_liters", "PRODUCT_API_DIMENSIONS_MISSING", "PRODUCT_VOLUME_FALLBACK_TO_UNITKA", "API_UNITKA_VOLUME_MISMATCH", VOLUME_TOLERANCE_LITERS),
        ):
            api_value = getattr(fact, field, None)
            file_value = getattr(unitka, field)
            if api_value is None:
                values[field] = file_value
                diagnostics.append(ImportDiagnostic("warning", fallback_code if file_value is not None else missing_code,
                                                    f"Ozon {field} evidence is unavailable for SKU {unitka.sku}; Unitka fallback was used." if file_value is not None else f"Ozon {field} evidence is unavailable for SKU {unitka.sku}."))
            else:
                values[field] = api_value
                if file_value is not None and abs(api_value - file_value) > tolerance:
                    diagnostics.append(ImportDiagnostic("warning", mismatch_code, f"Ozon and Unitka {field} values differ for SKU {unitka.sku}; Ozon is authoritative."))
        merged.append(ProductEconomicsInput(
            unitka.sku,
            fact.article if fact is not None and fact.article else unitka.article,
            unitka.cost,
            stock.get(unitka.sku),
            values["price"], values["commission_rate"], values["volume_liters"],
        ))
    return tuple(merged), tuple(diagnostics)
