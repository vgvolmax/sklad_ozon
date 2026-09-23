"""Pure materialization of user quantities over an immutable ShippablePlan."""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json

from backend.domain.contracts import RestrictionCapacityKind
from backend.project import WorkingQuantityOverride
from backend.supply.contracts import ShippableLine, ShippablePlan

READY = "READY"
ATTENTION = "ATTENTION"
BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class WorkingPlanDiagnostic:
    severity: str
    code: str
    message: str
    sku: str | None = None
    destination_cluster_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkingPlanLine:
    sku: str
    article: str
    destination_cluster_id: str
    system_qty: int | None
    working_qty: int | None
    override_qty: int | None
    pack_multiple: int | None
    resolved_seller_stock: int | None
    delta_qty: int | None
    unit_volume_l: Decimal | None
    total_volume_l: Decimal | None
    is_overridden: bool
    recommendation_changed: bool
    status: str
    reason_codes: tuple[str, ...]
    capacity_kind: RestrictionCapacityKind
    whole_pack_capacity_qty: int | None


@dataclass(frozen=True, slots=True)
class WorkingPlan:
    working_plan_id: str
    analysis_snapshot_id: str
    shippable_plan_id: str
    lines: tuple[WorkingPlanLine, ...]
    diagnostics: tuple[WorkingPlanDiagnostic, ...]
    ready_count: int
    attention_count: int
    blocked_count: int
    overridden_count: int
    active_override_count: int
    orphan_override_count: int


def validate_override_quantity(line: ShippableLine, quantity: object) -> int:
    """Validate syntax/local pack rules without changing user input."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise ValueError("quantity must be a nonnegative integer")
    if quantity > 0 and line.pack_multiple is None:
        raise ValueError("positive quantity requires a known pack multiplicity")
    if quantity > 0 and quantity % line.pack_multiple:
        raise ValueError("quantity must be a whole pack")
    return quantity


def _status(reasons: list[str], overridden: bool) -> str:
    blocking = {"OVERRIDE_NOT_PACK_MULTIPLE",
                "POSITIVE_QTY_WITHOUT_PACK", "KNOWN_CAPACITY_EXCEEDED",
                "SKU_SELLER_STOCK_EXCEEDED"}
    if blocking.intersection(reasons):
        return BLOCKED
    return ATTENTION if overridden or reasons else READY


def _plan_id(plan: ShippablePlan, lines: tuple[WorkingPlanLine, ...]) -> str:
    payload = {"analysis_snapshot_id": plan.analysis_snapshot_id,
               "shippable_plan_id": plan.shippable_plan_id,
               "lines": [{"sku": x.sku, "destination_cluster_id": x.destination_cluster_id,
                          "working_qty": x.working_qty, "pack_multiple": x.pack_multiple,
                          "capacity_kind": x.capacity_kind.value,
                          "whole_pack_capacity_qty": x.whole_pack_capacity_qty}
                         for x in lines]}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
    return "wp_" + hashlib.sha256(canonical).hexdigest()


def materialize_working_plan(
    shippable_plan: ShippablePlan,
    overrides: dict[str, dict[str, WorkingQuantityOverride]],
) -> WorkingPlan:
    if not isinstance(shippable_plan, ShippablePlan):
        raise TypeError("shippable_plan must be ShippablePlan")
    indexed = {(line.sku, line.destination_cluster_id): line for line in shippable_plan.lines}
    flat = {(sku, cluster): record for sku, clusters in overrides.items()
            for cluster, record in clusters.items()}
    drafts = []
    for identity, line in indexed.items():
        override = flat.get(identity)
        working = line.shippable_qty if override is None else override.quantity
        reasons = []
        changed = bool(override and override.base_system_qty != line.shippable_qty)
        if working is None:
            reasons.append("WORKING_QTY_UNKNOWN")
            if line.analytical_qty is not None and line.analytical_qty > 0 and line.pack_multiple is None:
                reasons.append("POSITIVE_QTY_WITHOUT_PACK")
        elif working > 0 and line.pack_multiple is None:
            reasons.append("POSITIVE_QTY_WITHOUT_PACK")
        elif working > 0 and working % line.pack_multiple:
            reasons.append("OVERRIDE_NOT_PACK_MULTIPLE")
        if working and line.capacity_kind in {RestrictionCapacityKind.FINITE,
                                              RestrictionCapacityKind.ZERO}:
            if line.whole_pack_capacity_qty is None or working > line.whole_pack_capacity_qty:
                reasons.append("KNOWN_CAPACITY_EXCEEDED")
        if (override is not None and working is not None and working > 0 and
                line.shippable_qty is None):
            reasons.extend(("MANUAL_WITHOUT_SYSTEM_RECOMMENDATION",
                            "NEEDS_OZON_VALIDATION"))
        if (override is not None and working is not None and working > 0 and
                line.capacity_kind is RestrictionCapacityKind.UNKNOWN):
            reasons.append("NEEDS_OZON_VALIDATION")
        if working is not None and working > 0 and line.resolved_seller_stock is None:
            reasons.extend(("SELLER_STOCK_UNCONFIRMED", "NEEDS_OZON_VALIDATION"))
        if changed:
            reasons.append("RECOMMENDATION_CHANGED")
        drafts.append([line, override, working, reasons, changed])

    totals = {}
    stocks = {}
    for line, _, working, _, _ in drafts:
        totals[line.sku] = totals.get(line.sku, 0) + (working or 0)
        stocks[line.sku] = line.resolved_seller_stock
    exceeded = {sku for sku, total in totals.items()
                if stocks[sku] is not None and total > stocks[sku]}
    diagnostics = []
    for sku in sorted(exceeded):
        excess = totals[sku] - stocks[sku]
        diagnostics.append(WorkingPlanDiagnostic(
            "error", "SKU_SELLER_STOCK_EXCEEDED",
            f"К поставке: {totals[sku]}; доступно: {stocks[sku]}; превышение: {excess}.", sku))
    lines = []
    for line, override, working, reasons, changed in drafts:
        if line.sku in exceeded:
            reasons.append("SKU_SELLER_STOCK_EXCEEDED")
        reasons = list(dict.fromkeys(reasons))
        lines.append(WorkingPlanLine(
            line.sku, line.article, line.destination_cluster_id, line.shippable_qty,
            working, None if override is None else override.quantity, line.pack_multiple,
            line.resolved_seller_stock,
            None if working is None or line.shippable_qty is None else working-line.shippable_qty,
            line.unit_volume_l,
            None if working is None or line.unit_volume_l is None else working*line.unit_volume_l,
            override is not None, changed, _status(reasons, override is not None),
            tuple(reasons), line.capacity_kind, line.whole_pack_capacity_qty))
    lines_tuple = tuple(lines)
    orphan_count = len(set(flat)-set(indexed))
    if orphan_count:
        diagnostics.append(WorkingPlanDiagnostic(
            "warning", "ORPHAN_OVERRIDES", f"Устаревшие ручные изменения: {orphan_count}."))
    return WorkingPlan(
        _plan_id(shippable_plan, lines_tuple), shippable_plan.analysis_snapshot_id,
        shippable_plan.shippable_plan_id, lines_tuple, tuple(diagnostics),
        sum(x.status == READY for x in lines_tuple),
        sum(x.status == ATTENTION for x in lines_tuple),
        sum(x.status == BLOCKED for x in lines_tuple),
        sum(x.is_overridden for x in lines_tuple),
        sum(x.is_overridden and x.working_qty != x.system_qty for x in lines_tuple),
        orphan_count)


def has_active_overrides(plan: ShippablePlan, overrides) -> bool:
    for line in plan.lines:
        record = overrides.get(line.sku, {}).get(line.destination_cluster_id)
        if record is not None and record.quantity != line.shippable_qty:
            return True
    return False
