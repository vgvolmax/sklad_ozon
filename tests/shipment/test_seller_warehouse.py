from backend.ozon.source_contracts import SellerWarehouse
from backend.shipment.seller_warehouse import resolve_seller_warehouse


def warehouse(identity, active=True):
    return SellerWarehouse(identity, f"W{identity}", None, active, None)


def test_crossdock_resolution_fail_closed_and_auto_selects_only_single_active():
    assert resolve_seller_warehouse((), None).reason_code == "SELLER_WAREHOUSE_UNAVAILABLE"
    assert resolve_seller_warehouse((warehouse(1),), None).warehouse.seller_warehouse_id == 1
    assert resolve_seller_warehouse((warehouse(1), warehouse(2)), None).reason_code == "SELLER_WAREHOUSE_REQUIRED"
    assert resolve_seller_warehouse((warehouse(1),), 999).reason_code == "SELLER_WAREHOUSE_INVALID"
    assert resolve_seller_warehouse((warehouse(1, False),), 1).reason_code == "SELLER_WAREHOUSE_INVALID"
    assert resolve_seller_warehouse((warehouse(1), warehouse(2)), 2).warehouse.seller_warehouse_id == 2


def test_direct_ignores_crossdock_warehouse():
    result = resolve_seller_warehouse((), 999, required=False)
    assert result.warehouse is None and result.reason_code is None
