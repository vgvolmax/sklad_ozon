from datetime import date

from backend.ozon.handoff import HandoffPoint, HandoffPointStore
from backend.ozon.source_contracts import SellerWarehouse
from backend.shipment.candidates import build_candidate_result, build_candidate_shipments, select_shipment_scope
from backend.shipment.contracts import ShipmentMethod, ShipmentScenario


def scenario(clusters, methods=(ShipmentMethod.DIRECT,), preferred=20, maximum=20,
             warehouse=None, handoffs=()):
    return ShipmentScenario(tuple(clusters), date(2026, 9, 11), date(2026, 9, 12),
                            methods, preferred, maximum, warehouse, handoffs)


def test_scope_is_filter_only_and_never_redistributes(line_factory, plan_factory):
    plan = plan_factory((line_factory("s", "Moscow", 60),
                         line_factory("s2", "Perm", 24),
                         line_factory("s3", "Samara", 18)))
    selected = select_shipment_scope(plan, ("Moscow", "Perm"))
    assert {(line.destination_cluster_id, line.shippable_qty) for line in selected} == {
        ("Moscow", 60), ("Perm", 24)}


def test_direct_hard_limit_and_deterministic_identity(line_factory, plan_factory):
    plan = plan_factory(tuple(line_factory(f"s{i}", cluster, 2, pack=2)
                              for i, cluster in enumerate(("b", "a", "c"), 1)))
    kwargs = dict(plan=plan, scenario=scenario(("a", "b", "c"), preferred=3, maximum=20),
                  seller_warehouses=(), handoff_store=HandoffPointStore())
    first = build_candidate_shipments(**kwargs)
    assert first == build_candidate_shipments(**kwargs)
    assert [item.cluster_ids for item in first] == [("a",), ("b",), ("c",)]
    assert all(item.assignments[0].quantity == 2 for item in first)


def test_pvz_aggregate_limit_accepts_boundary_and_splits_overage(line_factory, plan_factory):
    store = HandoffPointStore(); store.put_all((HandoffPoint(7, None, None, "PVZ", None),))
    warehouses = (SellerWarehouse(9, None, None, True, None),)
    plan = plan_factory((line_factory("a", "a", 1, volume="999"),
                         line_factory("b", "b", 1, volume="1"),
                         line_factory("c", "c", 1, volume="600"),))
    result = build_candidate_shipments(
        plan=plan, scenario=scenario(("a", "b", "c"),
            (ShipmentMethod.PVZ_CROSSDOCK,), warehouse=None, handoffs=(7,)),
        seller_warehouses=warehouses, handoff_store=store)
    assert [item.total_volume_l for item in result] == [1000, 600]


def test_indivisible_pvz_cluster_over_limit_is_blocked_not_reduced(line_factory, plan_factory):
    store = HandoffPointStore(); store.put_all((HandoffPoint(7, None, None, "PVZ", None),))
    plan = plan_factory((line_factory("a", "a", 1, volume="700"),
                         line_factory("b", "a", 1, volume="600"),))
    result = build_candidate_result(
        plan=plan, scenario=scenario(("a",), (ShipmentMethod.PVZ_CROSSDOCK,), handoffs=(7,)),
        seller_warehouses=(SellerWarehouse(9, None, None, True, None),), handoff_store=store)
    assert result.candidates == ()
    assert result.diagnostics[0].code == "PVZ_PRELIMINARY_VOLUME_LIMIT"


def test_realistic_generation_is_linear_bounded_stable_and_handoff_ordered(line_factory, plan_factory):
    lines = tuple(line_factory(f"sku-{sku}", f"cluster-{cluster:02}", 2, pack=2,
                               volume="0.1", rank=cluster + 1)
                  for cluster in range(21) for sku in range(6))  # 126 rows
    plan = plan_factory(lines)
    store = HandoffPointStore(); store.put_all((
        HandoffPoint(2, None, None, "SC", None), HandoffPoint(1, None, None, "SC", None)))
    kwargs = dict(plan=plan, scenario=scenario(
        tuple(f"cluster-{i:02}" for i in range(21)),
        (ShipmentMethod.DIRECT, ShipmentMethod.SC_CROSSDOCK), preferred=5, maximum=20,
        handoffs=(2, 1)), seller_warehouses=(SellerWarehouse(9, None, None, True, None),),
        handoff_store=store, max_candidates=12)
    first = build_candidate_shipments(**kwargs)
    assert first == build_candidate_shipments(**kwargs)
    assert len(first) == 12
    crossdock = [item for item in first if item.method is ShipmentMethod.SC_CROSSDOCK]
    assert all(item.handoff_point_id == 2 for item in crossdock)  # bound reached before fan-out
