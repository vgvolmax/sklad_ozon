from datetime import date
from decimal import Decimal

from backend.domain.contracts import ProductEconomicsInput, SourceMode
from backend.ozon.handoff import HandoffPoint, HandoffPointStore
from backend.ozon.source_contracts import SellerWarehouse
from backend.shipment.candidates import build_candidate_result, build_candidate_shipments, select_shipment_scope
from backend.shipment.contracts import ShipmentMethod, ShipmentScenario
from backend.supply import (
    AllocationDecision,
    AllocationObjective,
    OperationalSupplyFact,
    OptimizationResult,
    PlacementZoneKind,
    PlanFamily,
    RestrictionCapacityKind,
    RestrictionEligibility,
    build_shippable_plan,
)


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


def test_candidate_excludes_allocation_when_no_whole_pack_fits_physical_capacity():
    allocation = AllocationDecision(
        "SKU-1", "A", 5, 5, Decimal("1"), Decimal("5"), True,
        ("ELIGIBLE_FOR_ALLOCATION",), 1,
    )
    optimization = OptimizationResult(
        "SKU-1", 100, 5, 95, 5, Decimal("5"), (allocation,), (),
        PlanFamily.CALCULATED, AllocationObjective.MAX_MARGIN,
    )
    fact = OperationalSupplyFact(
        "SKU-1", "ART-1", "A", 6, PlacementZoneKind.SINGLE, ("DEFAULT",),
        RestrictionEligibility.ALLOWED, RestrictionCapacityKind.FINITE, 5,
        date(2026, 9, 10), (),
    )
    plan = build_shippable_plan(
        analysis_snapshot_id="analysis-1", source_mode=SourceMode.FILES,
        source_snapshot_id=None, analysis_as_of=date(2026, 9, 10),
        horizon_days=56, include_inbound=True,
        objective=AllocationObjective.MAX_MARGIN,
        calculated_allocations=(optimization,),
        products=(ProductEconomicsInput(
            "SKU-1", "ART-1", None, 100, None, None, Decimal("1")),),
        supply_facts=(fact,),
    )

    assert plan.lines[0].shippable_qty == 0
    result = build_candidate_result(
        plan=plan, scenario=scenario(("A",)), seller_warehouses=(),
        handoff_store=HandoffPointStore(),
    )
    assert result.candidates == ()
    assert tuple(item.code for item in result.diagnostics) == ("EMPTY_SHIPMENT_SCOPE",)


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
    direct = [item for item in first if item.method is ShipmentMethod.DIRECT]
    crossdock = [item for item in first if item.method is ShipmentMethod.SC_CROSSDOCK]
    assert direct
    assert crossdock
    assert all(len(item.cluster_ids) == 1 for item in direct)
    assert all(item.handoff_point_id == 2 for item in crossdock)  # bound reached before fan-out


def test_crossdock_hard_max_splits_twenty_one_clusters(line_factory, plan_factory):
    clusters = tuple(f"cluster-{index:02}" for index in range(21))
    plan = plan_factory(tuple(
        line_factory(f"sku-{index}", cluster, 1, rank=1)
        for index, cluster in enumerate(clusters)
    ))
    store = HandoffPointStore()
    store.put_all((HandoffPoint(7, None, None, "SC", None),))

    candidates = build_candidate_shipments(
        plan=plan,
        scenario=scenario(
            clusters, (ShipmentMethod.SC_CROSSDOCK,), preferred=20, maximum=20,
            handoffs=(7,),
        ),
        seller_warehouses=(SellerWarehouse(9, None, None, True, None),),
        handoff_store=store,
    )

    assert [len(candidate.cluster_ids) for candidate in candidates] == [20, 1]
    assert all(len(candidate.cluster_ids) <= 20 for candidate in candidates)


def test_crossdock_user_max_reduces_method_hard_max(line_factory, plan_factory):
    clusters = tuple(f"cluster-{index:02}" for index in range(10))
    plan = plan_factory(tuple(
        line_factory(f"sku-{index}", cluster, 1, rank=1)
        for index, cluster in enumerate(clusters)
    ))
    store = HandoffPointStore()
    store.put_all((HandoffPoint(7, None, None, "SC", None),))

    candidates = build_candidate_shipments(
        plan=plan,
        scenario=scenario(
            clusters, (ShipmentMethod.SC_CROSSDOCK,), preferred=5, maximum=5,
            handoffs=(7,),
        ),
        seller_warehouses=(SellerWarehouse(9, None, None, True, None),),
        handoff_store=store,
    )

    assert [len(candidate.cluster_ids) for candidate in candidates] == [5, 5]
    assert all(len(candidate.cluster_ids) <= 5 for candidate in candidates)


def test_method_coverage_preserves_explicit_user_order(line_factory, plan_factory):
    clusters = ("a", "b", "c")
    plan = plan_factory(tuple(
        line_factory(f"sku-{index}", cluster, 1, rank=1)
        for index, cluster in enumerate(clusters)
    ))
    store = HandoffPointStore()
    store.put_all((HandoffPoint(7, None, None, "SC", None),))

    candidates = build_candidate_shipments(
        plan=plan,
        scenario=scenario(
            clusters, (ShipmentMethod.SC_CROSSDOCK, ShipmentMethod.DIRECT),
            preferred=1, maximum=20, handoffs=(7,),
        ),
        seller_warehouses=(SellerWarehouse(9, None, None, True, None),),
        handoff_store=store,
        max_candidates=2,
    )

    assert [candidate.method for candidate in candidates] == [
        ShipmentMethod.SC_CROSSDOCK, ShipmentMethod.DIRECT,
    ]
