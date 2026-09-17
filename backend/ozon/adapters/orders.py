"""Current FBO/FBS posting wire adapters.

Only explicit ``cluster_to`` evidence owns destination demand.  In particular,
the similarly geographic ``region`` field is deliberately ignored.
"""

from datetime import date, datetime, time, timezone
from math import isfinite

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH
from backend.ozon.source_contracts import MOSCOW_BUSINESS_TZ, OzonRecordQualityEvidence

READ = OzonRequestPolicy(retry_safe=True)
POSTINGS_PAGE_SIZE = 100

_FULFILLED = {"delivered"}
_CANCELLED = {"cancelled", "canceled"}
_IN_PROGRESS = {
    "awaiting_packaging", "awaiting_registration", "acceptance_in_progress",
    "awaiting_approve", "awaiting_verification", "arbitration", "client_arbitration",
    "awaiting_deliver", "delivering", "not_accepted", "driver_pickup", "sent_by_seller",
}


def _lifecycle(status: object) -> OrderLifecycle:
    value = _wire_text(status).casefold()
    if value in _FULFILLED:
        return OrderLifecycle.FULFILLED
    if value in _CANCELLED:
        return OrderLifecycle.CANCELLED
    if value in _IN_PROGRESS:
        return OrderLifecycle.IN_PROGRESS
    return OrderLifecycle.UNKNOWN


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _wire_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sku_text(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value) if value > 0 else ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _fallback_value(source: dict, canonical: str, legacy: str, *, fbs: bool) -> object:
    """Use an FBS legacy alias only when canonical evidence is absent or blank."""
    value = source.get(canonical)
    if fbs and (value is None or (isinstance(value, str) and not value.strip())):
        return source.get(legacy)
    return value


def _product_sku(product: dict, *, fbs: bool) -> str:
    return _sku_text(_fallback_value(product, "sku", "product_id", fbs=fbs))


def _product_text(product: dict, canonical: str, legacy: str, *, fbs: bool) -> str:
    return _wire_text(_fallback_value(product, canonical, legacy, fbs=fbs))


def _posting_status(posting: dict, *, fbs: bool) -> str:
    return _wire_text(_fallback_value(posting, "status", "status_alias", fbs=fbs))


def _posting_price(value: object) -> tuple[float, bool]:
    """Parse only the documented scalar and money-object posting price shapes."""
    candidate = value.get("amount") if isinstance(value, dict) else value
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float, str)):
        return 0.0, False
    if isinstance(candidate, str) and not candidate.strip():
        return 0.0, False
    try:
        price = float(candidate)
    except (TypeError, ValueError):
        return 0.0, False
    if not isfinite(price) or price < 0:
        return 0.0, False
    return price, True


def _business_timestamp(value: object, field: str, diagnostics: list[ImportDiagnostic]) -> str:
    raw = _text(value)
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp has no offset")
    except ValueError:
        diagnostics.append(ImportDiagnostic(
            "error", "INVALID_ORDER_TIMESTAMP",
            f"Invalid Ozon posting timestamp for {field}.", field=field,
        ))
        return ""
    return parsed.astimezone(MOSCOW_BUSINESS_TZ).isoformat()


def _normalize_posting(posting: dict, *, fbs: bool) -> tuple[
        tuple[OrderRecord, ...], tuple[ImportDiagnostic, ...], OzonRecordQualityEvidence]:
    """Normalize only documented endpoint fields and discard all PII."""
    products = posting.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("posting has no usable products collection")
    if any(not isinstance(product, dict) for product in products):
        raise ValueError("posting contains a non-object product")
    if any(not _product_sku(product, fbs=fbs) for product in products):
        raise ValueError("posting product has no usable SKU")

    status = _posting_status(posting, fbs=fbs)
    analytics = posting.get("analytics_data")
    if not isinstance(analytics, dict):
        analytics = {}
    financial = posting.get("financial_data")
    if not isinstance(financial, dict):
        financial = {}
    origin_cluster = _text(financial.get("cluster_from"))
    destination = _wire_text(financial.get("cluster_to"))
    origin_warehouse = _text(analytics.get("warehouse_name")) or None
    lifecycle = _lifecycle(status)
    diagnostics: list[ImportDiagnostic] = []
    event_timestamp = posting.get("in_process_at") or posting.get("created_at")
    accepted = _business_timestamp(event_timestamp, "accepted_at", diagnostics)
    planned_ship = _business_timestamp(posting.get("shipment_date"), "planned_ship_at", diagnostics)
    handed_to_delivery = _business_timestamp(
        posting.get("delivering_date"), "handed_to_delivery_at", diagnostics)
    delivered = _business_timestamp(posting.get("delivered_at"), "delivered_at", diagnostics)
    posting_number = _text(posting.get("posting_number"))
    if lifecycle is OrderLifecycle.UNKNOWN:
        diagnostics.append(ImportDiagnostic(
            "warning", "UNKNOWN_ORDER_STATUS",
            f"Posting {posting_number or '<unknown>'} has unknown status {status or '<blank>'}.",
            field="status"))
    missing_event_date = (
        lifecycle in {OrderLifecycle.FULFILLED, OrderLifecycle.IN_PROGRESS}
        and not _text(event_timestamp)
    )
    if missing_event_date:
        diagnostics.append(ImportDiagnostic(
            "warning", "MISSING_ORDER_EVENT_DATE",
            f"Posting {posting_number or '<unknown>'} has no demand event date.",
            field="accepted_at"))

    records: list[OrderRecord] = []
    rejected_record_count = 0
    incomplete_skus: set[str] = set()
    for product in products:
        sku = _product_sku(product, fbs=fbs)
        quantity = product.get("quantity")
        invalid_quantity = (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or not isfinite(quantity)
            or quantity <= 0
            or int(quantity) != quantity
        )
        demand_relevant = lifecycle in {OrderLifecycle.FULFILLED, OrderLifecycle.IN_PROGRESS}
        quarantined = (
            invalid_quantity
            or lifecycle is OrderLifecycle.UNKNOWN
            or missing_event_date
            or not destination
        )
        if invalid_quantity:
            diagnostics.append(ImportDiagnostic(
                "warning", "INVALID_ORDER_PRODUCT", "Invalid posting product evidence."))
        if quarantined:
            rejected_record_count += 1
            if demand_relevant or lifecycle is OrderLifecycle.UNKNOWN:
                incomplete_skus.add(sku)
            continue
        seller_price = 0.0
        if "price" in product:
            seller_price, valid_price = _posting_price(product["price"])
            if not valid_price:
                diagnostics.append(ImportDiagnostic(
                    "warning", "INVALID_ORDER_PRICE",
                    "Posting product has invalid seller price.", field="price"))
        records.append(OrderRecord(
            sku=sku, quantity=int(quantity), origin_cluster=origin_cluster,
            destination_cluster=destination, lifecycle=lifecycle, accepted_at=accepted,
            planned_ship_at=planned_ship or None,
            handed_to_delivery_at=handed_to_delivery or None,
            delivered_at=delivered or None,
            raw_status=status,
            article=_product_text(product, "offer_id", "product_offer_id", fbs=fbs),
            product_name=_product_text(product, "name", "product_name", fbs=fbs),
            origin_warehouse=origin_warehouse, seller_price=seller_price,
        ))
    if not destination and lifecycle in {OrderLifecycle.FULFILLED, OrderLifecycle.IN_PROGRESS}:
        diagnostics.append(ImportDiagnostic(
            "warning" if incomplete_skus else "error",
            "UNRESOLVED_DESTINATION_CLUSTER",
            f"Posting {posting_number or '<unknown>'} has no cluster_to evidence.",
            field="cluster_to"))
    return (
        tuple(records),
        tuple(diagnostics),
        OzonRecordQualityEvidence(rejected_record_count, tuple(sorted(incomplete_skus))),
    )


def normalize_fbo_posting(posting: dict):
    return _normalize_posting(posting, fbs=False)


def normalize_fbs_posting(posting: dict):
    return _normalize_posting(posting, fbs=True)


def _result(response: dict) -> dict:
    value = response.get("result", response)
    if not isinstance(value, dict) or not isinstance(value.get("postings"), list):
        raise ValueError("invalid postings response")
    return value


def fetch_postings(client: OzonClient, path: str, history_from: date, history_to: date):
    since = datetime.combine(history_from, time.min, MOSCOW_BUSINESS_TZ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    until = datetime.combine(history_to, time.max, MOSCOW_BUSINESS_TZ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[OrderRecord] = []
    diagnostics: list[ImportDiagnostic] = []
    rejected_record_count = 0
    incomplete_skus: set[str] = set()
    cursor = ""
    seen = {cursor}
    while True:
        payload = {
            "filter": {"since": since, "to": until},
            "limit": POSTINGS_PAGE_SIZE,
            "sort_dir": "ASC",
            "with": {"analytics_data": True, "financial_data": True},
        }
        if cursor:
            payload["cursor"] = cursor
        result = _result(client.post_json(path, payload, policy=READ))
        postings = result["postings"]
        for posting in postings:
            if not isinstance(posting, dict):
                raise ValueError("postings response contains a non-object posting")
            normalizer = normalize_fbs_posting if path == FBS_POSTINGS_PATH else normalize_fbo_posting
            normalized, page_diagnostics, page_quality = normalizer(posting)
            records.extend(normalized)
            diagnostics.extend(page_diagnostics)
            rejected_record_count += page_quality.rejected_record_count
            incomplete_skus.update(page_quality.incomplete_skus)
        has_next = result.get("has_next")
        if not isinstance(has_next, bool):
            raise ValueError("postings response has invalid has_next")
        if not has_next:
            break
        raw_cursor = result.get("cursor")
        if not isinstance(raw_cursor, str) or not raw_cursor.strip():
            raise ValueError("postings response has invalid cursor")
        next_cursor = raw_cursor.strip()
        if next_cursor in seen:
            diagnostics.append(ImportDiagnostic(
                "error", "NON_PROGRESSING_POSTINGS_CURSOR",
                f"{path} returned a repeated cursor."))
            break
        seen.add(next_cursor)
        cursor = next_cursor
    return (tuple(records), tuple(diagnostics),
            OzonRecordQualityEvidence(rejected_record_count, tuple(sorted(incomplete_skus))))


def fetch_orders(client: OzonClient, history_from: date, history_to: date):
    records: list[OrderRecord] = []
    diagnostics: list[ImportDiagnostic] = []
    for path in (FBO_POSTINGS_PATH, FBS_POSTINGS_PATH):
        endpoint_records, endpoint_diagnostics, _quality = fetch_postings(
            client, path, history_from, history_to)
        records.extend(endpoint_records)
        diagnostics.extend(endpoint_diagnostics)
    return tuple(records), tuple(diagnostics)
