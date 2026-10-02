"""Current FBO/FBS posting wire adapters.

Only explicit ``cluster_to`` evidence owns destination demand.  In particular,
the similarly geographic ``region`` field is deliberately ignored.
"""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timezone
from math import isfinite
from hashlib import sha256

from backend.domain.contracts import ImportDiagnostic, OrderLifecycle, OrderRecord
from backend.ozon.client import OzonClient, OzonClientError, OzonRequestPolicy
from backend.ozon.contracts import OzonErrorCode
from backend.ozon.endpoints import (
    FBO_POSTINGS_PATH, FBS_POSTINGS_PATH, FBO_POSTING_GET_PATH, FBS_POSTING_GET_PATH,
)
from backend.ozon.source_contracts import MOSCOW_BUSINESS_TZ, OzonRecordQualityEvidence

READ = OzonRequestPolicy(retry_safe=True)


def _price_key(path, posting_number):
    return sha256((path + '\0' + posting_number).encode()).hexdigest() if posting_number else None


@dataclass(frozen=True, slots=True)
class OrderPriceRequest:
    path: str
    posting_number: str
    key: str
    lifecycle: OrderLifecycle
    skus: tuple[str, ...]


def seed_order_price_cache(orders):
    cache = {}
    for row in orders:
        if (row.buyer_price_key and row.buyer_price is not None and
                row.lifecycle in {OrderLifecycle.FULFILLED, OrderLifecycle.CANCELLED}):
            prices, _ = cache.setdefault((row.buyer_price_key, row.lifecycle.value), ({}, False))
            prices[row.sku] = row.buyer_price
    return cache


class OrderPriceReader:
    """Optional endpoint circuit; each call still uses the shared paced transport."""
    def __init__(self, client):
        self.client = client
        self.blocked = set()
        self.failures = Counter()

    def read(self, request):
        if request.path in self.blocked:
            return {}, True
        try:
            prices = _detail_buyer_prices(self.client.post_json(request.path,
                {'posting_number': request.posting_number, 'with': {'financial_data': True}},
                policy=READ), request.posting_number)
            self.failures[request.path] = 0
            for sku in request.skus:
                prices.setdefault(sku, None)
            return prices, False
        except OzonClientError as exc:
            if exc.code in {OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED, OzonErrorCode.LOCKED}:
                raise
            self.failures[request.path] += 1
            if exc.status in {401, 403, 404, 405} or self.failures[request.path] >= 3:
                self.blocked.add(request.path)
            return {}, True
        except ValueError:
            self.failures[request.path] += 1
            if self.failures[request.path] >= 3:
                self.blocked.add(request.path)
            return {}, True
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


def _financial_product(financial: dict, sku: str) -> dict:
    """Only one unambiguous canonical SKU may own financial evidence."""
    rows = financial.get("products")
    matches = [row for row in (rows if isinstance(rows, list) else [])
               if isinstance(row, dict) and _product_sku(row, fbs=True) == sku]
    return matches[0] if len(matches) == 1 else {}


def _historical_price(candidates, *, buyer=False) -> float | None:
    for source, field in candidates:
        value = source.get(field)
        if isinstance(value, dict) and "amount" not in value:
            return None if buyer else 0.0
        amount = value.get("amount") if isinstance(value, dict) else value
        if amount is None or isinstance(amount, str) and not amount.strip():
            continue
        currency = ((value.get("currency") or value.get("currency_code"))
                    if isinstance(value, dict) else
                    source.get("customer_currency_code" if buyer else "currency_code"))
        if currency and currency != "RUB":
            return None if buyer else 0.0
        price, valid = _posting_price(value)
        # Malformed explicit evidence must not be replaced with another price.
        return price if valid else (None if buyer else 0.0)
    return None


def _buyer_price_candidates(product: dict, financial: dict, sku: str):
    matched = _financial_product(financial, sku)
    return [(product, "customer_price"), (matched, "customer_price"),
            (product, "client_price"), (matched, "client_price")]


def _buyer_price(product: dict, financial: dict, sku: str) -> float | None:
    return _historical_price(_buyer_price_candidates(product, financial, sku), buyer=True)


def _buyer_price_absent(product: dict, financial: dict, sku: str) -> bool:
    """Only absent/blank evidence permits recovery; malformed prices stay unknown."""
    for source, field in _buyer_price_candidates(product, financial, sku):
        value = source.get(field)
        if isinstance(value, dict):
            if "amount" not in value:
                return False
            value = value["amount"]
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return False
    return True


def _detail_buyer_prices(response: dict, posting_number: str) -> dict[str, float | None]:
    """Whitelist numeric buyer prices; financial product_id is an Ozon SKU."""
    detail = response.get("result") if isinstance(response, dict) else None
    if not isinstance(detail, dict) or _wire_text(detail.get("posting_number")) != posting_number:
        raise ValueError("invalid posting detail identity")
    financial = detail.get("financial_data")
    products = financial.get("products") if isinstance(financial, dict) else None
    if not isinstance(products, list):
        raise ValueError("invalid posting detail financial products")
    skus = {_product_sku(product, fbs=True) for product in products
            if isinstance(product, dict)} - {""}
    return {sku: _buyer_price({}, financial, sku) for sku in skus}


def _spp_base_price(product: dict, financial: dict, sku: str) -> float | None:
    matched = _financial_product(financial, sku)
    return _historical_price([(product, "seller_price"), (matched, "seller_price"),
                              (product, "price")])


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
    sku_counts = Counter(_product_sku(product, fbs=fbs) for product in products)
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
            source_channel="fbs" if fbs else "fbo",
            buyer_price=_buyer_price(product, financial, sku),
            spp_base_price=_spp_base_price(product, financial, sku),
            buyer_price_key=(_price_key(FBS_POSTING_GET_PATH if fbs else FBO_POSTING_GET_PATH,
                                       _wire_text(posting.get('posting_number')))
                if _buyer_price(product, financial, sku) is not None or
                   (sku_counts[sku] == 1 and _buyer_price_absent(product, financial, sku)) else None),
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


def fetch_postings(client: OzonClient, path: str, history_from: date, history_to: date,
                   progress_callback=None, price_cache=None, price_requests=None):
    # The sync owns this ephemeral, normalized-only cache across history backfills.
    # Smart refresh requests details again only for its bounded order overlap.
    price_cache = {} if price_cache is None else price_cache
    detail_path = FBS_POSTING_GET_PATH if path == FBS_POSTINGS_PATH else FBO_POSTING_GET_PATH
    detail_count = 0
    reader = OrderPriceReader(client)
    price_gaps = {"INVALID": 0, "FETCH_FAILED": 0, "ABSENT": 0}

    def enrich(posting, normalized):
        nonlocal detail_count
        financial = posting.get("financial_data")
        financial = financial if isinstance(financial, dict) else {}
        counts = Counter(_product_sku(product, fbs=path == FBS_POSTINGS_PATH)
                         for product in posting['products'])
        eligible_skus = {_product_sku(product, fbs=path == FBS_POSTINGS_PATH)
                         for product in posting["products"]
                         if counts[_product_sku(product, fbs=path == FBS_POSTINGS_PATH)] == 1 and _buyer_price_absent(
                             product, financial, _product_sku(product, fbs=path == FBS_POSTINGS_PATH))}
        missing = [row for row in normalized if row.buyer_price is None]
        price_gaps["INVALID"] += sum(row.sku not in eligible_skus for row in missing)
        recoverable = [row for row in missing if row.sku in eligible_skus]
        if not recoverable:
            return normalized
        posting_number = _wire_text(posting.get("posting_number"))
        if not posting_number:
            price_gaps["FETCH_FAILED"] += len(recoverable)
            return normalized
        key = (_price_key(detail_path, posting_number), normalized[0].lifecycle.value)
        requested_skus = {row.sku for row in recoverable}
        needs_request = key not in price_cache or (not price_cache[key][1] and
            not requested_skus <= price_cache[key][0].keys())
        if needs_request and price_requests is not None:
            price_requests.append(OrderPriceRequest(detail_path, posting_number, key[0],
                normalized[0].lifecycle, tuple(sorted(requested_skus))))
            return normalized
        if needs_request:
            # Callbacks run outside the optional-price exception handler so a
            # cooperative cancellation cannot be mistaken for a missing price.
            if progress_callback:
                progress_callback(current=detail_count, total=None, unit="postings",
                                  detail=f"Уточняем цены покупателей: {detail_count} отправлений")
            price_cache[key] = reader.read(OrderPriceRequest(detail_path, posting_number, key[0],
                normalized[0].lifecycle, tuple(sorted(requested_skus))))
            detail_count += 1
            if progress_callback:
                progress_callback(current=detail_count, total=None, unit="postings",
                                  detail=f"Уточняем цены покупателей: {detail_count} отправлений")
        prices, failed = price_cache[key]
        enriched = []
        for row in normalized:
            if row.buyer_price is None and row.sku in eligible_skus:
                price = prices.get(row.sku)
                if price is None:
                    price_gaps["FETCH_FAILED" if failed else "ABSENT"] += 1
                else:
                    row = replace(row, buyer_price=price)
            enriched.append(row)
        return tuple(enriched)

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
            records.extend(enrich(posting, normalized))
            diagnostics.extend(page_diagnostics)
            rejected_record_count += page_quality.rejected_record_count
            incomplete_skus.update(page_quality.incomplete_skus)
        if progress_callback:
            progress_callback(current=len(records) + rejected_record_count,
                              total=None, unit="records")
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
    messages = {
        "INVALID": "Некорректная цена покупателя в списке отправлений",
        "FETCH_FAILED": "Не удалось получить цену покупателя из деталей отправления",
        "ABSENT": "Ozon не вернул однозначную цену покупателя в деталях отправления",
    }
    for reason, count in price_gaps.items():
        if count:
            diagnostics.append(ImportDiagnostic(
                "warning", f"ORDER_BUYER_PRICE_{reason}",
                f"{messages[reason]}: {count} строк товаров. Заказы сохранены; цена и СПП неизвестны.",
                field="buyer_price"))
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
