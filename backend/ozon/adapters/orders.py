"""Paginated FBO/FBS postings normalized into the canonical OrderRecord."""

from datetime import date, datetime, time, timezone
from typing import Iterable

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH

READ = OzonRequestPolicy(retry_safe=True)


def _lifecycle(status: str) -> OrderLifecycle:
    value = status.casefold()
    if any(x in value for x in ("cancel", "отмен")):
        return OrderLifecycle.CANCELLED
    if any(x in value for x in ("deliver", "delivered", "достав")):
        return OrderLifecycle.FULFILLED
    if value:
        return OrderLifecycle.IN_PROGRESS
    return OrderLifecycle.UNKNOWN


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def normalize_posting(posting: dict) -> tuple[OrderRecord, ...]:
    status = _text(posting.get("status"))
    analytics = posting.get("analytics_data") or posting.get("analytics") or {}
    financial = posting.get("financial_data") or {}
    origin = _text(analytics.get("warehouse_name") or posting.get("warehouse_name") or posting.get("warehouse"))
    origin_cluster = _text(analytics.get("warehouse") or analytics.get("origin_cluster") or posting.get("origin_cluster") or origin)
    destination = _text(analytics.get("region") or analytics.get("destination_cluster") or posting.get("destination_cluster"))
    accepted = _text(posting.get("in_process_at") or posting.get("created_at") or posting.get("accepted_at"))
    products = posting.get("products") or []
    result = []
    for product in products:
        sku = _text(product.get("sku") or product.get("product_id"))
        quantity = product.get("quantity", 0)
        if not sku or isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0 or int(quantity) != quantity:
            continue
        result.append(OrderRecord(
            sku=sku, quantity=int(quantity), origin_cluster=origin_cluster,
            destination_cluster=destination, lifecycle=_lifecycle(status), accepted_at=accepted,
            planned_ship_at=_text(posting.get("shipment_date")) or None,
            handed_to_delivery_at=_text(posting.get("delivering_date")) or None,
            delivered_at=_text(posting.get("delivered_at")) or None, raw_status=status,
            article=_text(product.get("offer_id") or product.get("article")),
            product_name=_text(product.get("name")), origin_warehouse=origin or None,
            seller_price=float(product.get("price") or financial.get("price") or 0),
        ))
    return tuple(result)


def fetch_orders(client: OzonClient, history_from: date, history_to: date) -> tuple[tuple[OrderRecord, ...], tuple[ImportDiagnostic, ...]]:
    records: list[OrderRecord] = []
    diagnostics: list[ImportDiagnostic] = []
    since = datetime.combine(history_from, time.min, timezone.utc).isoformat().replace("+00:00", "Z")
    to = datetime.combine(history_to, time.max, timezone.utc).isoformat().replace("+00:00", "Z")
    for path in (FBO_POSTINGS_PATH, FBS_POSTINGS_PATH):
        offset = 0
        last_id = 0
        while True:
            if path == FBO_POSTINGS_PATH:
                payload = {"dir":"ASC", "filter":{"since":since,"to":to}, "limit":1000, "offset":offset,
                           "with":{"analytics_data":True,"financial_data":False}}
            else:
                payload = {"dir":"ASC", "filter":{"since":since,"to":to}, "limit":1000, "with":{"analytics_data":True}}
                if last_id:
                    payload["last_id"] = last_id
            response = client.post_json(path, payload, policy=READ)
            result = response.get("result") or response
            postings = result.get("postings") or result.get("items") or []
            if not isinstance(postings, list):
                raise ValueError("invalid postings response")
            for posting in postings:
                if isinstance(posting, dict):
                    records.extend(normalize_posting(posting))
            has_next = bool(result.get("has_next"))
            new_last = result.get("last_id")
            if not has_next and len(postings) < 1000:
                break
            if path == FBO_POSTINGS_PATH:
                offset += len(postings)
            elif new_last and new_last != last_id:
                last_id = new_last
            else:
                break
    return tuple(records), tuple(diagnostics)
