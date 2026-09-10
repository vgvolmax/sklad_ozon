from backend.ozon.handoff import HandoffPoint, HandoffPointStore
from backend.shipment.handoff import resolve_handoff_points


def test_handoff_requires_backend_resolved_evidence_in_user_order():
    store = HandoffPointStore()
    assert resolve_handoff_points(store, ()).reason_code == "HANDOFF_POINT_REQUIRED"
    assert resolve_handoff_points(store, (1,)).reason_code == "HANDOFF_POINT_UNRESOLVED"
    store.put_all((HandoffPoint(1, "one", None, "PVZ", None),
                   HandoffPoint(2, "two", None, "SC", None)))
    assert [point.warehouse_id for point in resolve_handoff_points(store, (2, 1)).points] == [2, 1]
    assert resolve_handoff_points(store, (3,)).reason_code == "HANDOFF_POINT_UNRESOLVED"


def test_handoff_without_ozon_warehouse_type_is_not_guessed():
    store = HandoffPointStore()
    store.put_all((HandoffPoint(1, "one", None, None, "label-only"),))
    assert resolve_handoff_points(store, (1,)).reason_code == "HANDOFF_POINT_UNRESOLVED"
