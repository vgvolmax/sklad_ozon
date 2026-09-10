"""Fail-closed seller warehouse resolution against normalized source evidence."""

from dataclasses import dataclass

from backend.ozon.source_contracts import SellerWarehouse


@dataclass(frozen=True, slots=True)
class SellerWarehouseResolution:
    warehouse: SellerWarehouse | None
    reason_code: str | None


def resolve_seller_warehouse(
    warehouses, selected_id: int | None, *, required: bool = True,
) -> SellerWarehouseResolution:
    if not required:
        return SellerWarehouseResolution(None, None)
    rows = tuple(warehouses)
    if any(not isinstance(item, SellerWarehouse) for item in rows):
        raise TypeError("seller warehouses must contain SellerWarehouse values")
    active = tuple(item for item in rows if item.is_active)
    if selected_id is not None:
        if isinstance(selected_id, bool) or not isinstance(selected_id, int):
            raise TypeError("selected_id must be an int")
        match = next((item for item in active if item.seller_warehouse_id == selected_id), None)
        return SellerWarehouseResolution(match, None if match else "SELLER_WAREHOUSE_INVALID")
    if not active:
        return SellerWarehouseResolution(None, "SELLER_WAREHOUSE_UNAVAILABLE")
    if len(active) > 1:
        return SellerWarehouseResolution(None, "SELLER_WAREHOUSE_REQUIRED")
    return SellerWarehouseResolution(active[0], None)
