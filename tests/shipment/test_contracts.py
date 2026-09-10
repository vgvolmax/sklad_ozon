from datetime import date
from decimal import Decimal

import pytest

from backend.shipment.contracts import CandidateAssignment, METHOD_RULES, ShipmentMethod, ShipmentScenario


def scenario(**changes):
    values = dict(selected_cluster_ids=("Moscow",), date_from=date(2026, 9, 10),
                  date_to=date(2026, 9, 11), allowed_methods=(ShipmentMethod.DIRECT,),
                  preferred_clusters_per_shipment=1, max_clusters_per_shipment=1,
                  seller_warehouse_id=None, selected_handoff_point_ids=())
    values.update(changes)
    return ShipmentScenario(**values)


@pytest.mark.parametrize("changes", [
    {"selected_cluster_ids": ("x", "x")}, {"selected_handoff_point_ids": (1, 1)},
    {"date_from": date(2026, 9, 12)}, {"preferred_clusters_per_shipment": 0},
    {"max_clusters_per_shipment": 0},
    {"preferred_clusters_per_shipment": 2}, {"seller_warehouse_id": True},
])
def test_scenario_rejects_invalid_values(changes):
    with pytest.raises((TypeError, ValueError)):
        scenario(**changes)


def test_candidate_assignment_enforces_whole_pack_and_exact_volume():
    with pytest.raises(ValueError, match="divisible"):
        CandidateAssignment("s", "a", "c", 3, 2, Decimal("1"), Decimal("3"),
                            "single", ("A",))
    with pytest.raises(TypeError):
        CandidateAssignment("s", "a", "c", True, 1, Decimal("1"), Decimal("1"),
                            "single", ("A",))


def test_canonical_method_rules():
    assert METHOD_RULES[ShipmentMethod.DIRECT].hard_max_clusters == 1
    assert METHOD_RULES[ShipmentMethod.PVZ_CROSSDOCK].preliminary_max_shipment_item_volume_l == Decimal("1000")
    assert METHOD_RULES[ShipmentMethod.SC_CROSSDOCK].hard_max_clusters == 20
