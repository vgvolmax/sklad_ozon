"""Current FBO and operational seller-stock adapters."""

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_STOCK_PATH, FBS_STOCK_PATH

READ = OzonRequestPolicy(retry_safe=True)


def _fbo_items(response: dict) -> list:
    items = response.get("items")
    if isinstance(items, list):
        return items
    result = response.get("result")
    return result.get("items", []) if isinstance(result, dict) else []


def normalize_fbo_stock(response: dict, cluster_by_warehouse: dict[str, str] | None = None):
    cluster_by_warehouse = cluster_by_warehouse or {}
    records = []
    diagnostics = []
    for raw in _fbo_items(response):
        sku = str(raw.get("sku", "")).strip()
        warehouse = str(raw.get("warehouse_name", "")).strip()
        cluster = str(raw.get("cluster_name") or cluster_by_warehouse.get(str(raw.get("warehouse_id", "")), "")).strip()
        quantity = raw.get("available_stock_count")
        if not sku or not cluster or isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity < 0 or int(quantity) != quantity:
            diagnostics.append(ImportDiagnostic("error", "INVALID_FBO_STOCK", "Invalid FBO stock evidence"))
            continue
        records.append(AvailabilityRecord(sku, warehouse or cluster, cluster, float(quantity), None,
                                          str(raw.get("offer_id", "")).strip(), int(quantity), None,
                                          str(raw.get("name", "")).strip()))
    return tuple(records), tuple(diagnostics)


def normalize_fbs_stock(response: dict):
    """Keep every top-level products[] warehouse observation separate."""
    records = []
    diagnostics = []
    products = response.get("products", [])
    for raw in products if isinstance(products, list) else ():
        sku = str(raw.get("sku", "")).strip()
        warehouse = str(raw.get("warehouse_name") or raw.get("warehouse_id") or "").strip()
        available = raw.get("free_stock")
        if not sku or isinstance(available, bool) or not isinstance(available, (int, float)) or int(available) != available or available < 0:
            diagnostics.append(ImportDiagnostic("error", "INVALID_FBS_STOCK", "Invalid seller-stock evidence"))
            continue
        available = int(available)
        records.append(AvailabilityRecord(sku, warehouse or "seller", "", float(available), None,
                                          str(raw.get("offer_id", "")).strip(), None, available,
                                          str(raw.get("name", "")).strip()))
    return tuple(records), tuple(diagnostics)


def fetch_fbo_stock(client: OzonClient, skus: tuple[str, ...],
                    cluster_by_warehouse: dict[str, str] | None = None):
    records = []
    diagnostics = []
    for start in range(0, len(skus), 100):
        response = client.post_json(FBO_STOCK_PATH, {"skus": list(skus[start:start + 100])}, policy=READ)
        page, page_diagnostics = normalize_fbo_stock(response, cluster_by_warehouse)
        records.extend(page)
        diagnostics.extend(page_diagnostics)
    return tuple(records), tuple(diagnostics)


def fetch_seller_stock(client: OzonClient):
    records = []
    diagnostics = []
    cursor = ""
    seen = {cursor}
    while True:
        payload = {"limit": 1000}
        if cursor:
            payload["cursor"] = cursor
        response = client.post_json(FBS_STOCK_PATH, payload, policy=READ)
        page, page_diagnostics = normalize_fbs_stock(response)
        records.extend(page)
        diagnostics.extend(page_diagnostics)
        next_cursor = str(response.get("cursor") or "")
        has_next = bool(response.get("has_next"))
        if not has_next:
            break
        if not next_cursor or next_cursor in seen:
            raise ValueError("non-progressing seller-stock cursor")
        seen.add(next_cursor)
        cursor = next_cursor
    return tuple(records), tuple(diagnostics)
