"""Current FBO and operational seller-stock adapters."""

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_STOCK_PATH, FBS_STOCK_PATH

READ = OzonRequestPolicy(retry_safe=True)


def _result_items(response: dict) -> list:
    result = response.get("result", response)
    if isinstance(result, dict):
        return result.get("rows") or result.get("items") or result.get("stocks") or []
    return result if isinstance(result, list) else []


def normalize_fbo_stock(response: dict, cluster_by_warehouse: dict[str, str] | None = None):
    cluster_by_warehouse = cluster_by_warehouse or {}
    records = []
    diagnostics = []
    for raw in _result_items(response):
        sku = str(raw.get("sku", raw.get("product_id", ""))).strip()
        warehouse = str(raw.get("warehouse_name", raw.get("warehouse", ""))).strip()
        cluster = str(raw.get("cluster_name", raw.get("cluster", cluster_by_warehouse.get(warehouse, "")))).strip()
        quantity = raw.get("available_stock_count", raw.get("free_to_sell_amount", raw.get("quantity")))
        if not sku or not cluster or isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity < 0 or int(quantity) != quantity:
            diagnostics.append(ImportDiagnostic("error", "INVALID_FBO_STOCK", "Invalid FBO stock evidence"))
            continue
        records.append(AvailabilityRecord(sku, warehouse or cluster, cluster, float(quantity), None,
                                          str(raw.get("offer_id", "")).strip(), int(quantity), None,
                                          str(raw.get("item_name", raw.get("name", ""))).strip()))
    return tuple(records), tuple(diagnostics)


def normalize_fbs_stock(response: dict):
    """Keep each warehouse observation separate for the existing resolver."""
    records = []
    diagnostics = []
    for raw in _result_items(response):
        sku = str(raw.get("sku", raw.get("product_id", ""))).strip()
        warehouse = str(raw.get("warehouse_name", raw.get("warehouse_id", ""))).strip()
        present = raw.get("present", raw.get("available", raw.get("quantity")))
        reserved = raw.get("reserved", 0)
        if not sku or isinstance(present, bool) or not isinstance(present, (int, float)) or int(present) != present or present < 0:
            diagnostics.append(ImportDiagnostic("error", "INVALID_FBS_STOCK", "Invalid seller-stock evidence"))
            continue
        available = int(present) - int(reserved or 0)
        if available < 0:
            diagnostics.append(ImportDiagnostic("error", "INVALID_FBS_STOCK", "Reserved seller stock exceeds present stock"))
            continue
        records.append(AvailabilityRecord(sku, warehouse or "seller", "", float(available), None,
                                          str(raw.get("offer_id", "")).strip(), None, available,
                                          str(raw.get("name", "")).strip()))
    return tuple(records), tuple(diagnostics)


def fetch_stocks(client: OzonClient):
    fbo = client.post_json(FBO_STOCK_PATH, {"limit":1000,"offset":0,"filters":[]}, policy=READ)
    fbs = client.post_json(FBS_STOCK_PATH, {"limit":1000,"offset":0}, policy=READ)
    fbo_records, d1 = normalize_fbo_stock(fbo)
    fbs_records, d2 = normalize_fbs_stock(fbs)
    return fbo_records, fbs_records, d1 + d2
