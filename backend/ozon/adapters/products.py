"""Backend-only enumeration of the current Ozon SKU universe."""

from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PRODUCT_LIST_PATH

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 1000


def fetch_product_skus(client: OzonClient) -> tuple[str, ...]:
    skus: list[str] = []
    seen_skus: set[str] = set()
    fetched_item_count = 0
    last_id = ""
    seen_cursors = {last_id}
    while True:
        payload = {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": PAGE_SIZE}
        response = client.post_json(PRODUCT_LIST_PATH, payload, policy=READ)
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("items", []), list):
            raise ValueError("invalid product-list response")
        items = result.get("items", [])
        total = result.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValueError("invalid product-list total")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("invalid product-list SKU evidence")
            raw_sku = item.get("sku")
            if isinstance(raw_sku, bool) or not isinstance(raw_sku, (int, str)):
                raise ValueError("invalid product-list SKU evidence")
            sku = str(raw_sku).strip()
            if not sku:
                raise ValueError("invalid product-list SKU evidence")
            if sku not in seen_skus:
                seen_skus.add(sku)
                skus.append(sku)
        fetched_item_count += len(items)
        if fetched_item_count >= total:
            break
        next_id = str(result.get("last_id") or "").strip()
        if not next_id:
            raise ValueError("missing product-list continuation cursor")
        if next_id in seen_cursors:
            raise ValueError("non-progressing product-list cursor")
        seen_cursors.add(next_id)
        last_id = next_id
    return tuple(skus)
