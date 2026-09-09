from backend.ozon.handoff import HandoffPointStore
def test_restart_store_does_not_resolve_old_id():
 assert HandoffPointStore().get(42) is None
