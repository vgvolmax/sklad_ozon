"""Pure projection of a Working Plan into shipment execution input."""

from backend.supply.contracts import ShippablePlan
from backend.working_plan import WorkingPlan

from .contracts import ShipmentInput, ShipmentInputLine


class WorkingPlanIdentityError(ValueError):
    code = "WORKING_PLAN_IDENTITY_MISMATCH"


def build_shipment_input(
    shippable_plan: ShippablePlan, working_plan: WorkingPlan,
) -> ShipmentInput:
    """Join exact SKU/cluster identities without reading recommendation quantities."""
    if not isinstance(shippable_plan, ShippablePlan):
        raise TypeError("shippable_plan must be ShippablePlan")
    if not isinstance(working_plan, WorkingPlan):
        raise TypeError("working_plan must be WorkingPlan")
    if (working_plan.analysis_snapshot_id != shippable_plan.analysis_snapshot_id or
            working_plan.shippable_plan_id != shippable_plan.shippable_plan_id):
        raise WorkingPlanIdentityError()
    system = {(line.sku, line.destination_cluster_id): line
              for line in shippable_plan.lines}
    working = {(line.sku, line.destination_cluster_id): line
               for line in working_plan.lines}
    if len(system) != len(shippable_plan.lines) or len(working) != len(working_plan.lines):
        raise WorkingPlanIdentityError()
    if set(system) != set(working):
        raise WorkingPlanIdentityError()
    lines = tuple(
        ShipmentInputLine(
            row.sku, row.article, row.destination_cluster_id, row.working_qty,
            row.pack_multiple, row.unit_volume_l, row.total_volume_l,
            system[identity].allocation_priority_rank,
            system[identity].placement_zone_kind.value,
            system[identity].placement_zones, row.status, row.reason_codes,
        )
        for identity, row in working.items()
    )
    return ShipmentInput(
        shippable_plan.analysis_snapshot_id, shippable_plan.shippable_plan_id,
        working_plan.working_plan_id, lines)
