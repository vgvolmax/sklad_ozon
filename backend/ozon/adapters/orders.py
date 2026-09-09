"""Current FBO/FBS posting wire adapters.

Only explicit ``cluster_to`` evidence owns destination demand.  In particular,
the similarly geographic ``region`` field is deliberately ignored.
"""

from datetime import date, datetime, time, timezone

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 1000

_FULFILLED = {"delivered"}
_CANCELLED = {"cancelled", "canceled"}
_IN_PROGRESS = {
    "awaiting_packaging", "awaiting_registration", "acceptance_in_progress",
    "awaiting_approve", "awaiting_verification", "arbitration", "client_arbitration",
    "awaiting_deliver", "delivering", "not_accepted", "driver_pickup", "sent_by_seller",
}


def _lifecycle(status: object) -> OrderLifecycle:
    value = _text(status).casefold()
    if value in _FULFILLED:
        return OrderLifecycle.FULFILLED
    if value in _CANCELLED:
        return OrderLifecycle.CANCELLED
    if value in _IN_PROGRESS:
        return OrderLifecycle.IN_PROGRESS
    return OrderLifecycle.UNKNOWN


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def normalize_posting(posting: dict) -> tuple[tuple[OrderRecord, ...], tuple[ImportDiagnostic, ...]]:
    """Discard all non-domain fields, including customer/address PII."""
    status = _text(posting.get("status"))
    analytics = posting.get("analytics_data")
    if not isinstance(analytics, dict):
        analytics = {}
    origin_cluster = _text(analytics.get("cluster_from"))
    destination = _text(analytics.get("cluster_to"))
    origin_warehouse = _text(analytics.get("warehouse_name")) or None
    accepted = _text(posting.get("in_process_at") or posting.get("created_at"))
    lifecycle = _lifecycle(status)
    diagnostics: list[ImportDiagnostic] = []
    posting_number = _text(posting.get("posting_number"))
    if not destination:
        diagnostics.append(ImportDiagnostic(
            "error", "UNRESOLVED_DESTINATION_CLUSTER",
            f"Posting {posting_number or '<unknown>'} has no cluster_to evidence.",
            field="cluster_to"))
    if lifecycle is OrderLifecycle.UNKNOWN:
        diagnostics.append(ImportDiagnostic(
            "warning", "UNKNOWN_ORDER_STATUS",
            f"Posting {posting_number or '<unknown>'} has unknown status {status or '<blank>'}.",
            field="status"))

    records: list[OrderRecord] = []
    products = posting.get("products")
    for product in products if isinstance(products, list) else ():
        if not isinstance(product, dict):
            continue
        sku = _text(product.get("sku"))
        quantity = product.get("quantity")
        if (not sku or isinstance(quantity, bool) or
                not isinstance(quantity, (int, float)) or quantity <= 0 or int(quantity) != quantity):
            diagnostics.append(ImportDiagnostic("error", "INVALID_ORDER_PRODUCT", "Invalid posting product evidence."))
            continue
        records.append(OrderRecord(
            sku=sku, quantity=int(quantity), origin_cluster=origin_cluster,
            destination_cluster=destination, lifecycle=lifecycle, accepted_at=accepted,
            planned_ship_at=_text(posting.get("shipment_date")) or None,
            handed_to_delivery_at=_text(posting.get("delivering_date")) or None,
            delivered_at=_text(posting.get("delivered_at")) or None,
            raw_status=status, article=_text(product.get("offer_id")),
            product_name=_text(product.get("name")), origin_warehouse=origin_warehouse,
            seller_price=float(product.get("price") or 0),
        ))
    return tuple(records), tuple(diagnostics)


def _result(response: dict) -> dict:
    value = response.get("result", response)
    if not isinstance(value, dict) or not isinstance(value.get("postings", []), list):
        raise ValueError("invalid postings response")
    return value


def fetch_postings(client: OzonClient, path: str, history_from: date, history_to: date):
    since = datetime.combine(history_from, time.min, timezone.utc).isoformat().replace("+00:00", "Z")
    until = datetime.combine(history_to, time.max, timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[OrderRecord] = []
    diagnostics: list[ImportDiagnostic] = []
    cursor = ""
    seen = {cursor}
    while True:
        payload = {
            "filter": {"since": since, "to": until},
            "limit": PAGE_SIZE,
            "sort_dir": "ASC",
            "with": {"analytics_data": True, "financial_data": False},
        }
        if cursor:
            payload["cursor"] = cursor
        result = _result(client.post_json(path, payload, policy=READ))
        postings = result.get("postings", [])
        for posting in postings:
            if isinstance(posting, dict):
                normalized, page_diagnostics = normalize_posting(posting)
                records.extend(normalized)
                diagnostics.extend(page_diagnostics)
        next_cursor = _text(result.get("cursor"))
        has_next = bool(result.get("has_next"))
        if not has_next:
            break
        if not next_cursor or next_cursor in seen:
            diagnostics.append(ImportDiagnostic(
                "error", "NON_PROGRESSING_POSTINGS_CURSOR",
                f"{path} returned a repeated or empty cursor."))
            break
        seen.add(next_cursor)
        cursor = next_cursor
    return tuple(records), tuple(diagnostics)


def fetch_orders(client: OzonClient, history_from: date, history_to: date):
    records: list[OrderRecord] = []
    diagnostics: list[ImportDiagnostic] = []
    for path in (FBO_POSTINGS_PATH, FBS_POSTINGS_PATH):
        endpoint_records, endpoint_diagnostics = fetch_postings(client, path, history_from, history_to)
        records.extend(endpoint_records)
        diagnostics.extend(endpoint_diagnostics)
    return tuple(records), tuple(diagnostics)
