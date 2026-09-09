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


_INBOUND = {
    "DATA_FILLING", "READY_TO_SUPPLY", "ACCEPTED_AT_SUPPLY_WAREHOUSE",
    "IN_TRANSIT", "ACCEPTANCE_AT_STORAGE_WAREHOUSE", "REPORTS_CONFIRMATION_AWAITING",
}
_FINAL = {"COMPLETED", "CANCELLED", "REJECTED_AT_SUPPLY_WAREHOUSE", "OVERDUE"}


def classify_supply_state(value: object) -> SupplyState:
    normalized = str(value).strip().upper()
    if normalized in _INBOUND:
        return SupplyState.INBOUND
    if normalized in _FINAL:
        return SupplyState.FINAL
    return SupplyState.UNKNOWN


def _items(response: dict, key: str) -> list:
    value = response.get(key)
    if isinstance(value, list):
        return value
    result = response.get("result")
    if isinstance(result, dict) and isinstance(result.get(key), list):
        return result[key]
    return []


def _order_id(raw: dict) -> int:
    return int(raw.get("order_id", 0))


def normalize_inbound(details: list[dict], bundle_items: dict[int, list[dict]], clusters: dict[int, str]):
    totals: dict[tuple[str, str], int] = {}
    diagnostics: list[ImportDiagnostic] = []
    for order in details:
        order_id = _order_id(order)
        supplies = order.get("supplies")
        for supply in supplies if isinstance(supplies, list) else ():
            if not isinstance(supply, dict):
                continue
            state = classify_supply_state(supply.get("state"))
            if state is SupplyState.FINAL:
                continue
            if state is SupplyState.UNKNOWN:
                diagnostics.append(ImportDiagnostic("error", "UNKNOWN_SUPPLY_STATE",
                                                    f"Unknown state for supply order {order_id}."))
                continue
            cluster_id = supply.get("macrolocal_cluster_id", order.get("macrolocal_cluster_id"))
            try:
                cluster = clusters[int(cluster_id)]
            except (KeyError, TypeError, ValueError):
                diagnostics.append(ImportDiagnostic("error", "UNRESOLVED_SUPPLY_CLUSTER",
                                                    f"Supply order {order_id} has unknown macrolocal cluster ID."))
                continue
            try:
                bundle_id = int(supply["bundle_id"])
            except (KeyError, TypeError, ValueError):
                diagnostics.append(ImportDiagnostic("error", "MISSING_SUPPLY_BUNDLE_ID",
                                                    f"Supply order {order_id} has no bundle ID."))
                continue
            for item in bundle_items.get(bundle_id, ()):
                sku = str(item.get("sku", "")).strip()
                quantity = item.get("quantity")
                if (not sku or isinstance(quantity, bool) or not isinstance(quantity, (int, float))
                        or quantity < 0 or int(quantity) != quantity):
                    diagnostics.append(ImportDiagnostic("error", "INVALID_SUPPLY_BUNDLE_ITEM",
                                                        f"Bundle {bundle_id} contains invalid product evidence."))
                    continue
                totals[(sku, cluster)] = totals.get((sku, cluster), 0) + int(quantity)
    records = tuple(AvailabilityRecord(
        sku, cluster, cluster, 0.0, None, fbo_quantity=None, inbound_quantity=quantity)
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
        page = _items(response, "order_ids")
        order_ids.extend(int(value) for value in page)
        next_id = str(response.get("last_id") or (response.get("result") or {}).get("last_id") or "")
        if not next_id:
            break
        if next_id in seen:
            raise ValueError("non-progressing supply-order cursor")
        seen.add(next_id)
        last_id = next_id
    return order_ids


def _fetch_details(client: OzonClient, order_ids: list[int]) -> list[dict]:
    details: list[dict] = []
    for start in range(0, len(order_ids), DETAIL_BATCH_SIZE):
        response = client.post_json(SUPPLY_ORDER_GET_PATH,
                                    {"order_ids": order_ids[start:start + DETAIL_BATCH_SIZE]}, policy=READ)
        details.extend(item for item in _items(response, "orders") if isinstance(item, dict))
    return details


def _fetch_bundles(client: OzonClient, bundle_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {bundle_id: [] for bundle_id in bundle_ids}
    last_id = ""
    seen = {last_id}
    while bundle_ids:
        payload = {"bundle_ids": bundle_ids, "limit": 1000}
        if last_id:
            payload["last_id"] = last_id
        response = client.post_json(SUPPLY_ORDER_BUNDLE_PATH, payload, policy=READ)
        bundles = _items(response, "bundles")
        for bundle in bundles:
            if isinstance(bundle, dict):
                try:
                    bundle_id = int(bundle["bundle_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                items = bundle.get("items")
                if isinstance(items, list):
                    result.setdefault(bundle_id, []).extend(item for item in items if isinstance(item, dict))
        root = response.get("result") if isinstance(response.get("result"), dict) else response
        next_id = str(root.get("last_id") or "")
        has_next = bool(root.get("has_next"))
        if not has_next:
            break
        if not next_id or next_id in seen:
            raise ValueError("non-progressing supply bundle cursor")
        seen.add(next_id)
        last_id = next_id
    return result


def fetch_inbound(client: OzonClient, cluster_by_id: dict[int, str] | None = None):
    order_ids = _fetch_order_ids(client)
    details = _fetch_details(client, order_ids)
    bundle_ids = sorted({int(supply["bundle_id"]) for order in details
                         for supply in order.get("supplies", ()) if isinstance(supply, dict)
                         and supply.get("bundle_id") is not None})
    bundles = _fetch_bundles(client, bundle_ids)
    return normalize_inbound(details, bundles, cluster_by_id or {})
