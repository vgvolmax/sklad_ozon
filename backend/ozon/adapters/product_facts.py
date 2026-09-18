"""Normalize Ozon product price, FBO commission and package dimensions."""

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from backend.domain.contracts import ImportDiagnostic
from backend.ozon.adapters.products import ProductCatalogItem
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PRODUCT_ATTRIBUTES_PATH, PRODUCT_PRICES_PATH
from backend.ozon.source_contracts import OzonRecordQualityEvidence

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 1000


@dataclass(frozen=True, slots=True)
class ProductApiFacts:
    sku: str
    article: str
    product_id: int
    price: Decimal | None = None
    commission_rate: Decimal | None = None
    volume_liters: Decimal | None = None


def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def dimensions_to_liters(width, height, depth, unit):
    values = tuple(_decimal(value) for value in (width, height, depth))
    if any(value is None or value <= 0 for value in values):
        return None
    normalized = unit.strip().lower() if isinstance(unit, str) else ""
    divisor = {"mm": Decimal("1000000"), "cm": Decimal("1000")}.get(normalized)
    factor = Decimal("1")
    if normalized in {"in", "inch", "inches"}:
        divisor, factor = Decimal("1000000"), Decimal("25.4")
    if divisor is None:
        return None
    return values[0] * values[1] * values[2] * factor ** 3 / divisor


def _identity(raw, by_id):
    product_id = raw.get("product_id", raw.get("id")) if isinstance(raw, dict) else None
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        return None
    item = by_id.get(product_id)
    if item is None:
        return None
    offer = raw.get("offer_id")
    if offer is not None and (not isinstance(offer, str) or offer.strip() != item.offer_id):
        return None
    return item


def normalize_product_prices(response, catalog):
    items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list):
        raise ValueError("invalid product-prices response")
    by_id = {item.product_id: item for item in catalog}
    records, diagnostics, incomplete = [], [], set()
    rejected = 0
    for raw in items:
        item = _identity(raw, by_id)
        if item is None:
            rejected += 1
            diagnostics.append(ImportDiagnostic("warning", "PRODUCT_API_IDENTITY_UNRESOLVED", "Product price record could not be matched to the current catalog."))
            continue
        price_block = raw.get("price")
        commissions = raw.get("commissions")
        price = _decimal(price_block.get("price")) if isinstance(price_block, dict) else None
        currency = price_block.get("currency_code") if isinstance(price_block, dict) else None
        if currency != "RUB" or price is None or price <= 0:
            price = None
            diagnostics.append(ImportDiagnostic("warning", "PRODUCT_API_PRICE_MISSING", f"Valid RUB seller price is unavailable for SKU {item.sku}."))
        percent = _decimal(commissions.get("sales_percent_fbo")) if isinstance(commissions, dict) else None
        commission = percent / Decimal("100") if percent is not None and 0 <= percent <= 100 else None
        if commission is None:
            diagnostics.append(ImportDiagnostic("warning", "PRODUCT_API_COMMISSION_MISSING", f"Valid FBO commission is unavailable for SKU {item.sku}."))
        if price is None or commission is None:
            incomplete.add(item.sku)
        records.append(ProductApiFacts(item.sku, item.offer_id, item.product_id, price, commission))
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def normalize_product_attributes(response, catalog):
    result = response.get("result") if isinstance(response, dict) else None
    items = result if isinstance(result, list) else response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list):
        raise ValueError("invalid product-attributes response")
    by_id = {item.product_id: item for item in catalog}
    records, diagnostics, incomplete = [], [], set(); rejected = 0
    for raw in items:
        item = _identity(raw, by_id)
        if item is None:
            rejected += 1
            diagnostics.append(ImportDiagnostic("warning", "PRODUCT_API_IDENTITY_UNRESOLVED", "Product attributes record could not be matched to the current catalog."))
            continue
        volume = dimensions_to_liters(raw.get("width"), raw.get("height"), raw.get("depth"), raw.get("dimension_unit"))
        if volume is None:
            code = ("PRODUCT_API_DIMENSION_UNIT_UNSUPPORTED" if all(_decimal(raw.get(key)) is not None and _decimal(raw.get(key)) > 0 for key in ("width", "height", "depth")) else "PRODUCT_API_DIMENSIONS_MISSING")
            diagnostics.append(ImportDiagnostic("warning", code, f"Valid package dimensions are unavailable for SKU {item.sku}."))
            incomplete.add(item.sku)
        records.append(ProductApiFacts(item.sku, item.offer_id, item.product_id, volume_liters=volume))
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def _fetch_batches(client, path, catalog, normalizer, progress_callback=None):
    records, diagnostics, incomplete = [], [], set(); rejected = 0
    if progress_callback: progress_callback(current=0, total=len(catalog), unit="sku")
    for start in range(0, len(catalog), PAGE_SIZE):
        batch = catalog[start:start + PAGE_SIZE]
        payload = {"filter": {"product_id": [item.product_id for item in batch]}, "limit": PAGE_SIZE}
        page, page_diagnostics, quality = normalizer(client.post_json(path, payload, policy=READ), batch)
        records.extend(page); diagnostics.extend(page_diagnostics)
        rejected += quality.rejected_record_count; incomplete.update(quality.incomplete_skus)
        returned = {item.sku for item in page}
        for missing in (item.sku for item in batch if item.sku not in returned):
            incomplete.add(missing)
        if progress_callback: progress_callback(current=start + len(batch), total=len(catalog), unit="sku")
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def fetch_product_prices(client, catalog, progress_callback=None):
    return _fetch_batches(client, PRODUCT_PRICES_PATH, catalog, normalize_product_prices, progress_callback)


def fetch_product_attributes(client, catalog, progress_callback=None):
    return _fetch_batches(client, PRODUCT_ATTRIBUTES_PATH, catalog, normalize_product_attributes, progress_callback)


def merge_product_facts(catalog, prices, attributes):
    price_by_sku = {item.sku: item for item in prices}
    dimensions_by_sku = {item.sku: item for item in attributes}
    return tuple(replace(price_by_sku.get(item.sku, ProductApiFacts(item.sku, item.offer_id, item.product_id)),
                         volume_liters=getattr(dimensions_by_sku.get(item.sku), "volume_liters", None))
                 for item in catalog)
