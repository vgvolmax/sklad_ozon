"""Inbound FBO supply-order wire adapter."""

from enum import Enum

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import SUPPLY_ORDER_BUNDLE_PATH, SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_LIST_PATH

READ = OzonRequestPolicy(retry_safe=True)
PAGE_SIZE = 100
DETAIL_BATCH_SIZE = 100


class SupplyState(str, Enum):
    INBOUND = "inbound"
    FINAL = "final"
    UNKNOWN = "unknown"


_INBOUND = {"DATA_FILLING", "READY_TO_SUPPLY", "ACCEPTED_AT_SUPPLY_WAREHOUSE", "IN_TRANSIT",
            "ACCEPTANCE_AT_STORAGE_WAREHOUSE", "REPORTS_CONFIRMATION_AWAITING"}
_FINAL = {"COMPLETED", "CANCELLED", "REJECTED_AT_SUPPLY_WAREHOUSE", "OVERDUE"}


def classify_supply_state(value: object) -> SupplyState:
    normalized = str(value).strip().upper()
    return SupplyState.INBOUND if normalized in _INBOUND else SupplyState.FINAL if normalized in _FINAL else SupplyState.UNKNOWN


def _items(response: dict, key: str) -> list:
    value = response.get(key)
    if isinstance(value, list):
        return value
    result = response.get("result")
    return result.get(key, []) if isinstance(result, dict) and isinstance(result.get(key, []), list) else []


def normalize_inbound(details: list[dict], bundle_items: dict[str, list[dict]], clusters: dict[int, str],
                      warehouse_to_macrolocal: dict[int, int]):
    totals: dict[tuple[str, str], int] = {}
    diagnostics: list[ImportDiagnostic] = []
    for order in details:
        order_id = int(order.get("order_id", 0))
        supplies = order.get("supplies")
        for supply in supplies if isinstance(supplies, list) else ():
            if not isinstance(supply, dict):
                continue
            state = classify_supply_state(supply.get("state"))
            if state is SupplyState.FINAL:
                continue
            if state is SupplyState.UNKNOWN:
                diagnostics.append(ImportDiagnostic("error", "UNKNOWN_SUPPLY_STATE", f"Unknown state for supply order {order_id}."))
                continue
            storage = supply.get("storage_warehouse")
            warehouse_id = storage.get("warehouse_id") if isinstance(storage, dict) else None
            try:
                cluster = clusters[warehouse_to_macrolocal[int(warehouse_id)]]
            except (KeyError, TypeError, ValueError):
                diagnostics.append(ImportDiagnostic("error", "UNRESOLVED_SUPPLY_CLUSTER", f"Supply order {order_id} has unmapped storage warehouse."))
                continue
            bundle_id = str(supply.get("bundle_id") or "").strip()
            if not bundle_id:
                diagnostics.append(ImportDiagnostic("error", "MISSING_SUPPLY_BUNDLE_ID", f"Supply order {order_id} has no bundle ID."))
                continue
            for item in bundle_items.get(bundle_id, ()):
                sku = str(item.get("sku", "")).strip()
                quantity = item.get("quantity")
                if not sku or isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity < 0 or int(quantity) != quantity:
                    diagnostics.append(ImportDiagnostic("error", "INVALID_SUPPLY_BUNDLE_ITEM", f"Bundle {bundle_id} contains invalid product evidence."))
                    continue
                totals[(sku, cluster)] = totals.get((sku, cluster), 0) + int(quantity)
    records = tuple(AvailabilityRecord(sku, cluster, cluster, 0.0, None, fbo_quantity=None, inbound_quantity=quantity)
                    for (sku, cluster), quantity in sorted(totals.items()))
    return records, tuple(diagnostics)


def _fetch_order_ids(client: OzonClient) -> list[int]:
    order_ids: list[int] = []
    last_id = ""
    seen = {last_id}
    while True:
        payload = {"filter": {}, "limit": PAGE_SIZE, "sort_by": "ORDER_CREATION"}
        if last_id:
            payload["last_id"] = last_id
        response = client.post_json(SUPPLY_ORDER_LIST_PATH, payload, policy=READ)
        order_ids.extend(int(value) for value in _items(response, "order_ids"))
        root = response.get("result") if isinstance(response.get("result"), dict) else response
        next_id = str(root.get("last_id") or "")
        if not next_id:
            break
        if next_id in seen:
            raise ValueError("non-progressing supply-order cursor")
        seen.add(next_id); last_id = next_id
    return order_ids


def _fetch_details(client: OzonClient, order_ids: list[int]) -> list[dict]:
    details = []
    for start in range(0, len(order_ids), DETAIL_BATCH_SIZE):
        response = client.post_json(SUPPLY_ORDER_GET_PATH, {"order_ids": order_ids[start:start + DETAIL_BATCH_SIZE]}, policy=READ)
        batch = order_ids[start:start + DETAIL_BATCH_SIZE]
        returned = [item for item in _items(response, "orders") if isinstance(item, dict)]
        returned_ids = []
        for item in returned:
            value = item.get("order_id")
            if isinstance(value, bool):
                raise ValueError("invalid supply-order detail ID")
            try:
                returned_ids.append(int(value))
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid supply-order detail ID") from exc
        if len(returned_ids) != len(set(returned_ids)):
            raise ValueError("duplicate supply-order detail ID")
        if set(returned_ids) != set(batch):
            raise ValueError("supply-order details do not match requested IDs")
        details.extend(returned)
    return details


def _fetch_bundles(client: OzonClient, bundle_ids: list[str]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {bundle_id: [] for bundle_id in bundle_ids}
    for bundle_id in bundle_ids:
        last_id = ""
        seen = {last_id}
        while True:
            payload = {"bundle_ids": [bundle_id], "limit": 100}
            if last_id:
                payload["last_id"] = last_id
            response = client.post_json(SUPPLY_ORDER_BUNDLE_PATH, payload, policy=READ)
            result[bundle_id].extend(item for item in _items(response, "items") if isinstance(item, dict))
            root = response.get("result") if isinstance(response.get("result"), dict) else response
            if not bool(root.get("has_next")):
                break
            next_id = str(root.get("last_id") or "")
            if not next_id or next_id in seen:
                raise ValueError("non-progressing supply bundle cursor")
            seen.add(next_id); last_id = next_id
    return result


def fetch_inbound(client: OzonClient, cluster_by_id: dict[int, str] | None = None,
                  warehouse_to_macrolocal: dict[int, int] | None = None):
    order_ids = _fetch_order_ids(client)
    details = _fetch_details(client, order_ids)
    bundle_ids = sorted({str(supply.get("bundle_id") or "").strip() for order in details
                         for supply in order.get("supplies", ()) if isinstance(supply, dict)
                         and str(supply.get("bundle_id") or "").strip()})
    bundles = _fetch_bundles(client, bundle_ids)
    return normalize_inbound(details, bundles, cluster_by_id or {}, warehouse_to_macrolocal or {})
