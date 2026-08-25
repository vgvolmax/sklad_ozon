"""Fail-closed physical supply feasibility calculation."""

from collections import defaultdict
from collections.abc import Iterable

from backend.ingestion.restrictions import RestrictionRecord, RestrictionState

from .contracts import SupplyFeasibility, WarehouseCapability, _require_nonblank


_REASON_ORDER = (
    "NO_WAREHOUSES_FOR_CLUSTER",
    "RESTRICTION_DATA_MISSING",
    "UNKNOWN_RESTRICTION_STATE",
    "PROHIBITED_WAREHOUSE_PRESENT",
    "CONFLICTING_RESTRICTIONS",
    "NO_EXPLICIT_ALLOWED_WAREHOUSE",
    "CONSERVATIVE_WAREHOUSE_MAXIMUM",
    "ZERO_PHYSICAL_CEILING",
    "ELIGIBLE_WAREHOUSE_FOUND",
)


def assess_feasibility(
    sku: str,
    cluster_id: str,
    restrictions: Iterable[RestrictionRecord],
    warehouses: Iterable[WarehouseCapability],
) -> SupplyFeasibility:
    """Assess a SKU only against explicitly mapped warehouses and restrictions."""
    _require_nonblank(sku, "sku")
    _require_nonblank(cluster_id, "cluster_id")

    cluster_warehouses: dict[str, WarehouseCapability] = {}
    for capability in warehouses:
        if not isinstance(capability, WarehouseCapability):
            raise TypeError("warehouses must contain WarehouseCapability values")
        if capability.cluster_id != cluster_id:
            continue
        previous = cluster_warehouses.get(capability.warehouse)
        if previous is not None and previous != capability:
            raise ValueError(f"Conflicting capabilities for warehouse {capability.warehouse!r}")
        cluster_warehouses[capability.warehouse] = capability

    if not cluster_warehouses:
        return SupplyFeasibility(sku, cluster_id, False, 0, (), ("NO_WAREHOUSES_FOR_CLUSTER",))

    states_by_warehouse: dict[str, set[RestrictionState]] = defaultdict(set)
    for record in restrictions:
        if not isinstance(record, RestrictionRecord):
            raise TypeError("restrictions must contain RestrictionRecord values")
        if record.sku == sku and record.warehouse in cluster_warehouses:
            states_by_warehouse[record.warehouse].add(record.state)

    found_reasons: set[str] = set()
    eligible: list[WarehouseCapability] = []
    for warehouse, capability in sorted(cluster_warehouses.items()):
        states = states_by_warehouse.get(warehouse)
        if not states:
            found_reasons.add("RESTRICTION_DATA_MISSING")
        elif len(states) > 1:
            found_reasons.add("CONFLICTING_RESTRICTIONS")
        else:
            state = next(iter(states))
            if state is RestrictionState.ALLOWED:
                eligible.append(capability)
            elif state is RestrictionState.UNKNOWN:
                found_reasons.add("UNKNOWN_RESTRICTION_STATE")
            elif state is RestrictionState.PROHIBITED:
                found_reasons.add("PROHIBITED_WAREHOUSE_PRESENT")

    if not eligible:
        found_reasons.add("NO_EXPLICIT_ALLOWED_WAREHOUSE")
        maximum: int | None = 0
    elif len(eligible) == 1:
        maximum = eligible[0].max_supply_qty
    else:
        explicit_maxima = [item.max_supply_qty for item in eligible if item.max_supply_qty is not None]
        maximum = min(explicit_maxima) if explicit_maxima else None
        if explicit_maxima:
            found_reasons.add("CONSERVATIVE_WAREHOUSE_MAXIMUM")

    if eligible and maximum == 0:
        found_reasons.add("ZERO_PHYSICAL_CEILING")
    if eligible:
        found_reasons.add("ELIGIBLE_WAREHOUSE_FOUND")
    reasons = tuple(reason for reason in _REASON_ORDER if reason in found_reasons)
    return SupplyFeasibility(
        sku, cluster_id, bool(eligible), maximum,
        tuple(item.warehouse for item in eligible), reasons,
    )
