"""Inbound FBO supply normalization with one fail-closed state classifier."""

from enum import Enum

from backend.domain.contracts import ImportDiagnostic
from backend.ingestion.availability import AvailabilityRecord
from backend.ozon.client import OzonClient, OzonRequestPolicy
from backend.ozon.endpoints import SUPPLY_ORDER_BUNDLE_PATH, SUPPLY_ORDER_GET_PATH, SUPPLY_ORDER_LIST_PATH

READ = OzonRequestPolicy(retry_safe=True)


class SupplyState(str, Enum):
    INBOUND = "inbound"
    FINAL = "final"
    UNKNOWN = "unknown"


_ACTIVE = {"created", "confirmed", "ready_to_ship", "in_transit", "accepted_at_supply_warehouse", "awaiting"}
_FINAL = {"completed", "cancelled", "canceled", "rejected", "closed", "finished"}


def classify_supply_state(value: str) -> SupplyState:
    normalized = str(value).strip().casefold()
    if normalized in _ACTIVE:
        return SupplyState.INBOUND
    if normalized in _FINAL:
        return SupplyState.FINAL
    return SupplyState.UNKNOWN


def normalize_inbound_bundles(supplies: list[dict], bundles: dict[int, list[dict]], cluster_by_warehouse: dict[int, str]):
    totals: dict[tuple[str, str], int] = {}
    diagnostics = []
    for supply in supplies:
        supply_id = int(supply.get("supply_order_id", supply.get("order_id", supply.get("id", 0))))
        state = classify_supply_state(supply.get("state", supply.get("status", "")))
        if state is SupplyState.FINAL:
            continue
        if state is SupplyState.UNKNOWN:
            diagnostics.append(ImportDiagnostic("error", "UNKNOWN_SUPPLY_STATE", f"Unknown supply state for supply {supply_id}"))
            continue
        warehouse_id = int(supply.get("warehouse_id", supply.get("destination_warehouse_id", 0)))
        cluster = cluster_by_warehouse.get(warehouse_id, str(supply.get("cluster_name", "")).strip())
        if not cluster:
            diagnostics.append(ImportDiagnostic("error", "UNRESOLVED_SUPPLY_CLUSTER", f"Supply {supply_id} has no canonical cluster"))
            continue
        for item in bundles.get(supply_id, ()):
            sku = str(item.get("sku", item.get("product_id", ""))).strip()
            quantity = item.get("quantity", item.get("items_count", 0))
            if sku and isinstance(quantity, (int, float)) and not isinstance(quantity, bool) and quantity >= 0 and int(quantity) == quantity:
                totals[(sku, cluster)] = totals.get((sku, cluster), 0) + int(quantity)
    records = tuple(AvailabilityRecord(sku, cluster, cluster, 0.0, None, fbo_quantity=None,
                                       inbound_quantity=quantity)
                    for (sku, cluster), quantity in totals.items())
    return records, tuple(diagnostics)


def fetch_inbound(client: OzonClient, cluster_by_warehouse: dict[int, str] | None = None):
    cluster_by_warehouse = cluster_by_warehouse or {}
    response = client.post_json(SUPPLY_ORDER_LIST_PATH, {"filter":{},"limit":100,"offset":0}, policy=READ)
    result = response.get("result", response)
    supplies = result.get("orders", result.get("items", [])) if isinstance(result, dict) else []
    bundles = {}
    for summary in supplies:
        supply_id = int(summary.get("supply_order_id", summary.get("order_id", summary.get("id", 0))))
        detail = client.post_json(SUPPLY_ORDER_GET_PATH, {"order_id":supply_id}, policy=READ)
        detailed = detail.get("result", detail)
        if isinstance(detailed, dict):
            summary.update({k:v for k,v in detailed.items() if k in {"state","status","warehouse_id","destination_warehouse_id","cluster_name"}})
        bundle = client.post_json(SUPPLY_ORDER_BUNDLE_PATH, {"supply_order_id":supply_id,"limit":1000}, policy=READ)
        value = bundle.get("result", bundle)
        bundles[supply_id] = value.get("items", value.get("bundles", [])) if isinstance(value, dict) else []
    return normalize_inbound_bundles(supplies, bundles, cluster_by_warehouse)
