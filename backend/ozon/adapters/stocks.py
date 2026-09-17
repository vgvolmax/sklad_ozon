"""Current FBO and operational seller-stock adapters."""

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.adapters.wire import nonnegative_int, optional_text, positive_int, sku as parse_sku
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_STOCK_PATH, FBS_STOCK_PATH
from backend.ozon.source_contracts import OzonRecordQualityEvidence

READ = OzonRequestPolicy(retry_safe=True)


def _fbo_items(response: dict) -> list:
    if "items" in response:
        items = response["items"]
    else:
        result = response.get("result")
        if not isinstance(result, dict) or "items" not in result:
            raise ValueError("invalid FBO stock response")
        items = result["items"]
    if not isinstance(items, list):
        raise ValueError("invalid FBO stock response")
    return items


def _display(raw, key):
    return optional_text(raw.get(key), key) or ""


def normalize_fbo_stock(response: dict, cluster_by_warehouse: dict[str, str] | None = None):
    mapping = cluster_by_warehouse or {}
    records, diagnostics, incomplete = [], [], set()
    rejected = 0
    for raw in _fbo_items(response):
        if not isinstance(raw, dict):
            raise ValueError("invalid FBO stock record")
        try:
            sku = parse_sku(raw.get("sku"))
        except ValueError as exc:
            raise ValueError("invalid FBO stock SKU") from exc
        valid = True
        try:
            quantity = nonnegative_int(raw.get("available_stock_count"), "FBO quantity")
            warehouse = _display(raw, "warehouse_name")
            offer = _display(raw, "offer_id")
            name = _display(raw, "name")
            if "cluster_name" in raw:
                direct = raw["cluster_name"]
                if not isinstance(direct, str) or not direct.strip():
                    raise ValueError("invalid direct cluster")
                cluster = direct.strip()
            else:
                wid = raw.get("warehouse_id")
                key = str(wid) if isinstance(wid, int) and not isinstance(wid, bool) else None
                cluster = mapping.get(key or "", "")
                if not cluster:
                    raise ValueError("missing cluster")
        except ValueError:
            valid = False
        if not valid:
            rejected += 1; incomplete.add(sku)
            diagnostics.append(ImportDiagnostic("warning", "INVALID_FBO_STOCK", f"Invalid FBO stock evidence for SKU {sku}"))
            continue
        records.append(AvailabilityRecord(sku, warehouse or cluster, cluster, float(quantity), None,
                                          offer, quantity, None, name))
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def normalize_fbs_stock(response: dict):
    if "products" not in response or not isinstance(response["products"], list):
        raise ValueError("invalid seller-stock response")
    records, diagnostics, incomplete = [], [], set()
    rejected = 0
    for raw in response["products"]:
        if not isinstance(raw, dict):
            raise ValueError("invalid seller-stock record")
        try:
            sku = parse_sku(raw.get("sku"))
        except ValueError as exc:
            raise ValueError("invalid seller-stock SKU") from exc
        try:
            available = nonnegative_int(raw.get("free_stock"), "seller stock")
            warehouse_name = optional_text(raw.get("warehouse_name"), "warehouse name")
            warehouse_id = raw.get("warehouse_id")
            if warehouse_name is None:
                warehouse = str(positive_int(warehouse_id, "seller warehouse ID"))
            else:
                if warehouse_id is not None:
                    positive_int(warehouse_id, "seller warehouse ID")
                warehouse = warehouse_name
            offer = _display(raw, "offer_id"); name = _display(raw, "name")
        except ValueError:
            rejected += 1; incomplete.add(sku)
            diagnostics.append(ImportDiagnostic("warning", "INVALID_FBS_STOCK", f"Invalid seller-stock evidence for SKU {sku}"))
            continue
        records.append(AvailabilityRecord(sku, warehouse, "", float(available), None, offer, None, available, name))
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def fetch_fbo_stock(client: OzonClient, skus: tuple[str, ...], cluster_by_warehouse=None,
                    progress_callback=None):
    records, diagnostics, incomplete = [], [], set(); rejected = 0
    if progress_callback: progress_callback(current=0, total=len(skus), unit="sku")
    for start in range(0, len(skus), 100):
        batch = skus[start:start + 100]
        page, page_diagnostics, quality = normalize_fbo_stock(
            client.post_json(FBO_STOCK_PATH, {"skus": list(batch)}, policy=READ), cluster_by_warehouse)
        if any(row.sku not in batch for row in page) or any(sku not in batch for sku in quality.incomplete_skus):
            raise ValueError("FBO stock returned unrequested SKU")
        records.extend(page); diagnostics.extend(page_diagnostics)
        rejected += quality.rejected_record_count; incomplete.update(quality.incomplete_skus)
        if progress_callback:
            progress_callback(current=min(start + len(batch), len(skus)), total=len(skus), unit="sku")
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))


def fetch_seller_stock(client: OzonClient, skus: tuple[str, ...], progress_callback=None):
    records, diagnostics, incomplete = [], [], set(); rejected = 0
    if progress_callback: progress_callback(current=0, total=len(skus), unit="sku")
    for start in range(0, len(skus), 1000):
        batch = skus[start:start + 1000]; cursor = ""; seen = {cursor}
        while True:
            payload = {"limit": 1000, "sku": list(batch)}
            if cursor: payload["cursor"] = cursor
            response = client.post_json(FBS_STOCK_PATH, payload, policy=READ)
            page, page_diagnostics, quality = normalize_fbs_stock(response)
            if any(row.sku not in batch for row in page) or any(sku not in batch for sku in quality.incomplete_skus):
                raise ValueError("seller stock returned unrequested SKU")
            records.extend(page); diagnostics.extend(page_diagnostics)
            rejected += quality.rejected_record_count; incomplete.update(quality.incomplete_skus)
            has_next = response.get("has_next")
            if not isinstance(has_next, bool):
                raise ValueError("invalid seller-stock has_next")
            if not has_next: break
            next_cursor = response.get("cursor")
            if not isinstance(next_cursor, str) or not next_cursor.strip() or next_cursor.strip() in seen:
                raise ValueError("non-progressing seller-stock cursor")
            cursor = next_cursor.strip(); seen.add(cursor)
        if progress_callback:
            progress_callback(current=min(start + len(batch), len(skus)), total=len(skus), unit="sku")
    return tuple(records), tuple(diagnostics), OzonRecordQualityEvidence(rejected, tuple(sorted(incomplete)))
