"""Backend-only enumeration of the current Ozon product universe."""

from dataclasses import dataclass

from backend.ozon.adapters.wire import nonnegative_int, optional_text, positive_int, sku as parse_sku
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PRODUCT_LIST_PATH

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 1000


@dataclass(frozen=True, slots=True)
class ProductCatalogItem:
    sku: str
    product_id: int
    offer_id: str


def fetch_product_catalog(client: OzonClient, progress_callback=None) -> tuple[ProductCatalogItem, ...]:
    products: list[ProductCatalogItem] = []
    seen_skus: set[str] = set()
    fetched = 0
    cursor = ""
    seen_cursors = {cursor}
    expected_total = None
    while True:
        response = client.post_json(PRODUCT_LIST_PATH, {
            "filter": {"visibility": "ALL"}, "last_id": cursor, "limit": PAGE_SIZE,
        }, policy=READ)
        result = response.get("result")
        if not isinstance(result, dict) or "items" not in result or not isinstance(result["items"], list):
            raise ValueError("invalid product-list response")
        items = result["items"]
        total = nonnegative_int(result.get("total"), "product-list total")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("changing product-list total")
        if not items and fetched < total:
            raise ValueError("non-progressing product-list page")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid product-list SKU evidence")
            try:
                normalized = parse_sku(item.get("sku"))
                product_id = positive_int(item.get("product_id", item.get("id")), "product ID")
                offer_id = optional_text(item.get("offer_id"), "offer ID")
                if offer_id is None:
                    raise ValueError("missing offer ID")
            except ValueError as exc:
                raise ValueError("invalid product-list identity evidence") from exc
            if normalized not in seen_skus:
                seen_skus.add(normalized); products.append(ProductCatalogItem(normalized, product_id, offer_id))
        fetched += len(items)
        if progress_callback:
            progress_callback(current=len(products), total=total, unit="sku")
        if fetched > total:
            raise ValueError("product-list item count exceeds total")
        if fetched == total:
            return tuple(products)
        next_cursor = result.get("last_id")
        if not isinstance(next_cursor, str) or not next_cursor.strip():
            raise ValueError("missing product-list continuation cursor")
        next_cursor = next_cursor.strip()
        if next_cursor in seen_cursors:
            raise ValueError("non-progressing product-list cursor")
        seen_cursors.add(next_cursor); cursor = next_cursor


def fetch_product_skus(client: OzonClient, progress_callback=None) -> tuple[str, ...]:
    """Compatibility helper for callers that only need the SKU universe."""
    skus, seen, fetched, cursor, cursors, expected = [], set(), 0, "", {""}, None
    while True:
        response = client.post_json(PRODUCT_LIST_PATH, {
            "filter": {"visibility": "ALL"}, "last_id": cursor, "limit": PAGE_SIZE,
        }, policy=READ)
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise ValueError("invalid product-list response")
        items = result["items"]
        total = nonnegative_int(result.get("total"), "product-list total")
        expected = total if expected is None else expected
        if total != expected: raise ValueError("changing product-list total")
        if not items and fetched < total: raise ValueError("non-progressing product-list page")
        for item in items:
            if not isinstance(item, dict): raise ValueError("invalid product-list SKU evidence")
            try: normalized = parse_sku(item.get("sku"))
            except ValueError as exc: raise ValueError("invalid product-list SKU evidence") from exc
            if normalized not in seen: seen.add(normalized); skus.append(normalized)
        fetched += len(items)
        if progress_callback: progress_callback(current=len(skus), total=total, unit="sku")
        if fetched > total: raise ValueError("product-list item count exceeds total")
        if fetched == total: return tuple(skus)
        next_cursor = result.get("last_id")
        if not isinstance(next_cursor, str) or not next_cursor.strip(): raise ValueError("missing product-list continuation cursor")
        next_cursor = next_cursor.strip()
        if next_cursor in cursors: raise ValueError("non-progressing product-list cursor")
        cursors.add(next_cursor); cursor = next_cursor
