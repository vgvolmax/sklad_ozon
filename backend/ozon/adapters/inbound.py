"""Inbound FBO supply-order wire adapter."""

from collections import Counter
from enum import Enum

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import SUPPLY_ORDER_BUNDLE_PATH, SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_LIST_PATH
from backend.ozon.source_contracts import OzonRecordQualityEvidence

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 100
DETAIL_BATCH_SIZE = 50

# Complete documented filter universe for /v3/supply-order/list.  The list call
# discovers order IDs only; supply semantics remain owned by the detail state.
SUPPLY_ORDER_STATES = (
    "DATA_FILLING",
    "READY_TO_SUPPLY",
    "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "IN_TRANSIT",
    "ACCEPTANCE_AT_STORAGE_WAREHOUSE",
    "REPORTS_CONFIRMATION_AWAITING",
    "REPORT_REJECTED",
    "COMPLETED",
    "REJECTED_AT_SUPPLY_WAREHOUSE",
    "CANCELLED",
    "OVERDUE",
)


class SupplyState(str, Enum):
    INBOUND = "inbound"
    FINAL = "final"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


_INBOUND = {"DATA_FILLING", "READY_TO_SUPPLY", "ACCEPTED_AT_SUPPLY_WAREHOUSE", "IN_TRANSIT",
            "ACCEPTANCE_AT_STORAGE_WAREHOUSE", "REPORTS_CONFIRMATION_AWAITING"}
_FINAL = {"COMPLETED", "CANCELLED", "REJECTED_AT_SUPPLY_WAREHOUSE", "OVERDUE"}
_DISPUTED = {"REPORT_REJECTED"}


def classify_supply_state(value: object) -> SupplyState:
    normalized = str(value).strip().upper()
    if normalized in _INBOUND:
        return SupplyState.INBOUND
    if normalized in _FINAL:
        return SupplyState.FINAL
    if normalized in _DISPUTED:
        return SupplyState.DISPUTED
    return SupplyState.UNKNOWN


def _root(response: object, endpoint: str) -> dict:
    if not isinstance(response, dict):
        raise ValueError(f"invalid {endpoint} response envelope")
    if "result" not in response:
        return response
    result = response["result"]
    if not isinstance(result, dict):
        raise ValueError(f"invalid {endpoint} result envelope")
    return result


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bundle_id(supply: dict) -> str:
    value = supply.get("bundle_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("non-final supply has invalid bundle ID")
    return value.strip()


def _sku(value: object) -> str:
    if _positive_int(value):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError("supply bundle item has invalid SKU")


def _resolve_supply_cluster(
        supply: dict, clusters: dict[int, str],
        warehouse_to_macrolocal: dict[int, int]) -> tuple[str | None, str | None]:
    """Resolve canonical direct cluster evidence, including empty API sentinels."""
    if "macrolocal_cluster_id" in supply:
        direct = supply["macrolocal_cluster_id"]
        if type(direct) is int and direct > 0:
            cluster = clusters.get(direct)
            return (cluster, None) if cluster is not None else (None, "UNRESOLVED_SUPPLY_CLUSTER")
        if direct is not None and not (type(direct) is int and direct == 0):
            return None, "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"

    storage = supply.get("storage_warehouse")
    warehouse_id = storage.get("warehouse_id") if isinstance(storage, dict) else None
    if not _positive_int(warehouse_id):
        return None, "UNRESOLVED_SUPPLY_CLUSTER"
    macrolocal_id = warehouse_to_macrolocal.get(warehouse_id)
    cluster = clusters.get(macrolocal_id) if macrolocal_id is not None else None
    return (cluster, None) if cluster is not None else (None, "UNRESOLVED_SUPPLY_CLUSTER")


def _classify_invalid_direct(value: object) -> str:
    """Return a bounded, value-free token for malformed direct cluster evidence."""
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return "blank_string"
        return "numeric_string" if normalized.isdigit() else "other_string"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and value < 0:
        return "negative_int"
    if isinstance(value, float):
        return "float_integral" if value.is_integer() else "float_fractional"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "other"


def _classify_warehouse_fallback(
        supply: dict, clusters: dict[int, str],
        warehouse_to_macrolocal: dict[int, int]) -> str:
    """Passively classify fallback evidence without resolving the supply."""
    storage = supply.get("storage_warehouse")
    if not isinstance(storage, dict):
        return "storage_missing"
    warehouse_id = storage.get("warehouse_id")
    if not _positive_int(warehouse_id):
        return "storage_invalid"
    if warehouse_id not in warehouse_to_macrolocal:
        return "fallback_unmapped"
    macrolocal_id = warehouse_to_macrolocal[warehouse_id]
    if macrolocal_id not in clusters:
        return "fallback_unknown_cluster"
    return "fallback_resolvable"


def normalize_inbound(details: list[dict], bundle_items: dict[str, list[dict]], clusters: dict[int, str],
                      warehouse_to_macrolocal: dict[int, int]):
    totals: dict[tuple[str, str], int] = {}
    diagnostics: list[ImportDiagnostic] = []
    invalid_cluster_shapes: Counter[tuple[str, str]] = Counter()
    rejected_record_count = 0
    incomplete_skus: set[str] = set()
    for order in details:
        if not isinstance(order, dict) or not _positive_int(order.get("order_id")):
            raise ValueError("invalid supply-order detail")
        order_id = order["order_id"]
        supplies = order.get("supplies")
        if not isinstance(supplies, list):
            raise ValueError(f"supply order {order_id} has invalid supplies evidence")
        for supply in supplies:
            if not isinstance(supply, dict):
                raise ValueError(f"supply order {order_id} contains invalid supply evidence")
            state = classify_supply_state(supply.get("state"))
            if state is SupplyState.FINAL:
                continue
            bundle_id = _bundle_id(supply)
            items = bundle_items.get(bundle_id)
            if not items:
                diagnostics.append(ImportDiagnostic(
                    "error", "MISSING_SUPPLY_BUNDLE_ITEMS",
                    f"Supply order {order_id} has no bundle item evidence."))
                continue
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ValueError(f"bundle {bundle_id} contains malformed items")

            parsed: list[tuple[str, int | None]] = []
            for item in items:
                sku = _sku(item.get("sku"))
                quantity = item.get("quantity")
                valid_quantity = (isinstance(quantity, int) and
                                  not isinstance(quantity, bool) and quantity >= 0)
                parsed.append((sku, quantity if valid_quantity else None))
                if not valid_quantity:
                    diagnostics.append(ImportDiagnostic(
                        "warning", "INVALID_SUPPLY_BUNDLE_ITEM",
                        f"Bundle {bundle_id} contains invalid quantity for SKU {sku}."))

            uncertainty_code = None
            if state is SupplyState.UNKNOWN:
                uncertainty_code = "UNKNOWN_SUPPLY_STATE"
                diagnostics.append(ImportDiagnostic(
                    "warning", uncertainty_code,
                    f"Unknown state for supply order {order_id}; affected inbound quantity is unknown."))
            elif state is SupplyState.DISPUTED:
                uncertainty_code = "REPORT_REJECTED_SUPPLY_STATE"
                diagnostics.append(ImportDiagnostic(
                    "warning", uncertainty_code,
                    f"Supply order {order_id} contains REPORT_REJECTED supply; inbound quantity for affected SKU is unknown."))

            cluster = None
            if state is SupplyState.INBOUND:
                cluster, cluster_error = _resolve_supply_cluster(
                    supply, clusters, warehouse_to_macrolocal)
                if cluster_error is not None:
                    uncertainty_code = cluster_error
                    message = (f"Supply order {order_id} has invalid macrolocal cluster ID."
                               if cluster_error == "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID"
                               else f"Supply order {order_id} has unresolved placement cluster.")
                    diagnostics.append(ImportDiagnostic("warning", cluster_error, message))
                    if cluster_error == "INVALID_SUPPLY_MACROLOCAL_CLUSTER_ID":
                        invalid_cluster_shapes[(
                            _classify_invalid_direct(supply["macrolocal_cluster_id"]),
                            _classify_warehouse_fallback(
                                supply, clusters, warehouse_to_macrolocal),
                        )] += 1

            for sku, quantity in parsed:
                if uncertainty_code is not None or quantity is None:
                    rejected_record_count += 1
                    incomplete_skus.add(sku)
                else:
                    totals[(sku, cluster)] = totals.get((sku, cluster), 0) + quantity

    if invalid_cluster_shapes:
        summary = "; ".join(
            f"{direct_shape}/{fallback_state}={count}"
            for (direct_shape, fallback_state), count
            in sorted(invalid_cluster_shapes.items())
        )
        diagnostics.append(ImportDiagnostic(
            "warning", "SUPPLY_CLUSTER_WIRE_SUMMARY",
            f"Invalid supply cluster wire shapes: {summary}."))

    records = tuple(AvailabilityRecord(sku, cluster, cluster, 0.0, None, fbo_quantity=None, inbound_quantity=quantity)
                    for (sku, cluster), quantity in sorted(totals.items()))
    quality = OzonRecordQualityEvidence(
        rejected_record_count, tuple(sorted(incomplete_skus)))
    return records, tuple(diagnostics), quality


def _fetch_order_ids(client: OzonClient, progress_callback=None) -> list[int]:
    order_ids: list[int] = []
    seen_ids: set[int] = set()
    last_id = ""
    seen_cursors: set[str] = set()
    while True:
        payload = {
            "filter": {"states": list(SUPPLY_ORDER_STATES)},
            "limit": PAGE_SIZE,
            "sort_by": "ORDER_CREATION",
            "sort_dir": "DESC",
        }
        if last_id:
            payload["last_id"] = last_id
        root = _root(client.post_json(SUPPLY_ORDER_LIST_PATH, payload, policy=READ), "supply-order list")
        values = root.get("order_ids")
        if not isinstance(values, list):
            raise ValueError("supply-order list order_ids must be an array")
        for value in values:
            if not _positive_int(value):
                raise ValueError("invalid supply-order ID")
            if value in seen_ids:
                raise ValueError("duplicate supply-order ID")
            seen_ids.add(value)
            order_ids.append(value)
        if progress_callback:
            progress_callback(detail="Поиск заявок", current=len(order_ids), total=None,
                              unit="orders")
        cursor = root.get("last_id", "")
        if cursor is None:
            raise ValueError("invalid supply-order cursor")
        if not isinstance(cursor, str):
            raise ValueError("invalid supply-order cursor")
        next_id = cursor.strip()
        if not next_id:
            break
        if next_id in seen_cursors:
            raise ValueError("non-progressing supply-order cursor")
        seen_cursors.add(next_id)
        last_id = next_id
    return order_ids


def _fetch_details(client: OzonClient, order_ids: list[int], progress_callback=None) -> list[dict]:
    details = []
    for start in range(0, len(order_ids), DETAIL_BATCH_SIZE):
        batch = order_ids[start:start + DETAIL_BATCH_SIZE]
        root = _root(client.post_json(
            SUPPLY_ORDER_GET_PATH, {"order_ids": batch}, policy=READ), "supply-order details")
        returned = root.get("orders")
        if not isinstance(returned, list):
            raise ValueError("supply-order details orders must be an array")
        if any(not isinstance(item, dict) for item in returned):
            raise ValueError("invalid supply-order detail object")
        returned_ids = []
        for item in returned:
            value = item.get("order_id")
            if not _positive_int(value):
                raise ValueError("invalid supply-order detail ID")
            returned_ids.append(value)
        if len(returned_ids) != len(set(returned_ids)):
            raise ValueError("duplicate supply-order detail ID")
        if set(returned_ids) != set(batch):
            raise ValueError("supply-order details do not match requested IDs")
        details.extend(returned)
        if progress_callback:
            progress_callback(detail="Получение деталей заявок", current=len(details),
                              total=len(order_ids), unit="orders")
    return details


def _fetch_bundles(client: OzonClient, bundle_ids: list[str], progress_callback=None) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {bundle_id: [] for bundle_id in bundle_ids}
    for bundle_id in bundle_ids:
        last_id = ""
        seen_cursors: set[str] = set()
        expected_total: int | None = None
        while True:
            payload = {"bundle_ids": [bundle_id], "limit": 100}
            if last_id:
                payload["last_id"] = last_id
            root = _root(client.post_json(
                SUPPLY_ORDER_BUNDLE_PATH, payload, policy=READ), "supply-order bundle")
            items = root.get("items")
            if not isinstance(items, list):
                raise ValueError("supply-order bundle items must be an array")
            if any(not isinstance(item, dict) for item in items):
                raise ValueError("supply-order bundle contains invalid item")
            result[bundle_id].extend(items)

            if "total_count" in root:
                total = root["total_count"]
                if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                    raise ValueError("invalid supply-order bundle total_count")
                if expected_total is not None and total != expected_total:
                    raise ValueError("inconsistent supply-order bundle total_count")
                expected_total = total

            has_next = root.get("has_next")
            if not isinstance(has_next, bool):
                raise ValueError("supply-order bundle has_next must be boolean")
            if not has_next:
                if expected_total is not None and len(result[bundle_id]) != expected_total:
                    raise ValueError("supply-order bundle total_count does not match items")
                break
            cursor = root.get("last_id")
            if not isinstance(cursor, str) or not cursor.strip():
                raise ValueError("invalid supply-order bundle cursor")
            next_id = cursor.strip()
            if next_id in seen_cursors:
                raise ValueError("non-progressing supply bundle cursor")
            seen_cursors.add(next_id)
            last_id = next_id
        if progress_callback:
            progress_callback(detail="Получение состава поставок",
                              current=bundle_ids.index(bundle_id) + 1,
                              total=len(bundle_ids), unit="bundles")
    return result


def fetch_inbound(client: OzonClient, cluster_by_id: dict[int, str] | None = None,
                  warehouse_to_macrolocal: dict[int, int] | None = None,
                  progress_callback=None):
    order_ids = _fetch_order_ids(client, progress_callback)
    details = _fetch_details(client, order_ids, progress_callback)
    bundle_ids: set[str] = set()
    for order in details:
        supplies = order.get("supplies")
        if not isinstance(supplies, list):
            raise ValueError(f"supply order {order['order_id']} has invalid supplies evidence")
        for supply in supplies:
            if not isinstance(supply, dict):
                raise ValueError(f"supply order {order['order_id']} contains invalid supply evidence")
            if classify_supply_state(supply.get("state")) is not SupplyState.FINAL:
                bundle_ids.add(_bundle_id(supply))
    bundles = _fetch_bundles(client, sorted(bundle_ids), progress_callback)
    return normalize_inbound(details, bundles, cluster_by_id or {}, warehouse_to_macrolocal or {})
