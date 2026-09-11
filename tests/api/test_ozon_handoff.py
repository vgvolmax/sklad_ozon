import pytest

from backend.ozon.handoff import HandoffPointStore, handoff_supply_types
def test_restart_store_does_not_resolve_old_id():
 assert HandoffPointStore().get(42) is None

@pytest.mark.parametrize(("methods", "expected"), [
    (("pvz_crossdock",), ("CREATE_TYPE_CROSSDOCK",)),
    (("sc_crossdock",), ("CREATE_TYPE_CROSSDOCK",)),
    (("pvz_crossdock", "sc_crossdock"), ("CREATE_TYPE_CROSSDOCK",)),
    (("direct",), ("CREATE_TYPE_DIRECT",)),
])
def test_handoff_methods_map_to_deduplicated_ozon_wire(methods, expected):
    assert handoff_supply_types(methods) == expected

def test_unknown_handoff_method_is_rejected_before_ozon():
    with pytest.raises(ValueError):
        handoff_supply_types(("unknown_method",))
