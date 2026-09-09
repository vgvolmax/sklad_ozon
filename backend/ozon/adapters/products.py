"""Backend-only enumeration of the current Ozon SKU universe."""

from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import PRODUCT_LIST_PATH

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 1000


def fetch_product_skus(client: OzonClient) -> tuple[str, ...]:
    skus: list[str] = []
    seen_skus: set[str] = set()
    last_id = ""
    seen_cursors = {last_id}
    while True:
        payload = {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": PAGE_SIZE}
        response = client.post_json(PRODUCT_LIST_PATH, payload, policy=READ)
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("items", []), list):
            raise ValueError("invalid product-list response")
        for item in result.get("items", []):
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku", "")).strip()
            if sku and sku not in seen_skus:
                seen_skus.add(sku)
                skus.append(sku)
        next_id = str(result.get("last_id") or "").strip()
        if not next_id:
            break
        if next_id in seen_cursors:
            raise ValueError("non-progressing product-list cursor")
        seen_cursors.add(next_id)
        last_id = next_id
    return tuple(skus)
