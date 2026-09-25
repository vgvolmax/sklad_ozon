"""Pure materialization of user quantities over an immutable ShippablePlan."""

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from datetime import datetime, timezone, timedelta

from backend.domain.contracts import RestrictionCapacityKind, SourceMode
from backend.supply.contracts import PlacementZoneKind
from backend.ozon.adapters.local_sale import supply_period_for_days
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
    selected_source: str = "CALCULATED"
    requested_qty: int | None = None
    ozon_eligible: bool = False
    ozon_unavailable_reason: str | None = None


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
    selected_ozon_count: int = 0


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


def _plan_id(plan: ShippablePlan, lines: tuple[WorkingPlanLine, ...], recommendation) -> str:
    payload = {"analysis_snapshot_id": plan.analysis_snapshot_id,
               "shippable_plan_id": plan.shippable_plan_id,
               "recommendation": (None if not any(x.selected_source == "OZON" for x in lines)
                                  else [recommendation.fetched_at_utc,
                                        recommendation.analytics_from.isoformat(),
                                        recommendation.analytics_to.isoformat(),
                                        recommendation.supply_period]),
               "lines": [{"sku": x.sku, "destination_cluster_id": x.destination_cluster_id,
                          "working_qty": x.working_qty, "pack_multiple": x.pack_multiple,
                          "selected_source": x.selected_source, "requested_qty": x.requested_qty,
                          "capacity_kind": x.capacity_kind.value,
                          "whole_pack_capacity_qty": x.whole_pack_capacity_qty}
                         for x in lines]}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
    return "wp_" + hashlib.sha256(canonical).hexdigest()


def ozon_choice_reason(plan, line, decision_row, recommendation, unit_economics=(),
                       thresholds=None) -> str | None:
    """Return a concrete reason if this exact source row is unsafe to select."""
    if plan.source_mode is not SourceMode.API:
        return "OZON_ONLY_API"
    if recommendation is None:
        return "OZON_RECOMMENDATION_MISSING"
    if (recommendation.horizon_days != plan.horizon_days or
            recommendation.supply_period != supply_period_for_days(plan.horizon_days)):
        return "UNSUPPORTED_OZON_PERIOD"
    try:
        fetched = datetime.fromisoformat(recommendation.fetched_at_utc)
        if fetched.tzinfo is None or datetime.now(timezone.utc)-fetched > timedelta(hours=24):
            return "OZON_RECOMMENDATION_STALE"
    except (ValueError, TypeError):
        return "OZON_RECOMMENDATION_STALE"
    if decision_row is None:
        return "OZON_DECISION_ROW_MISSING"
    confidence = getattr(decision_row.confidence, "value", decision_row.confidence)
    if confidence != "low" and not set(decision_row.status_codes).intersection(
            {"PROBABLE_STOCKOUT", "RECOMMENDATION_DISTORTION"}):
        return "DEMAND_CONFIDENCE_SUFFICIENT"
    values = {(item.sku, item.cluster_id): item.quantity for item in recommendation.items}
    key = (line.sku, line.destination_cluster_id)
    if key not in values or decision_row.need.ozon_recommended_qty != values[key]:
        return "OZON_RECOMMENDATION_MISSING"
    if line.resolved_seller_stock is None:
        return "SELLER_STOCK_UNCONFIRMED"
    if line.pack_multiple is None or line.pack_multiple <= 0:
        return "MISSING_PACK_MULTIPLICITY"
    if line.unit_volume_l is None or line.unit_volume_l <= 0:
        return "MISSING_UNIT_VOLUME"
    if line.placement_zone_kind is PlacementZoneKind.UNKNOWN or not line.placement_zones:
        return "UNKNOWN_PLACEMENT_ZONE"
    if any(code in line.reason_codes for code in (
            "INVALID_UNIT_VOLUME", "MISSING_SUPPLIER_ARTICLE", "CONFLICTING_PACK_MULTIPLICITY")):
        return "PHYSICAL_INPUT_INCOMPLETE"
    if (values[key] > 0 and line.capacity_kind is RestrictionCapacityKind.ZERO):
        return "KNOWN_CAPACITY_ZERO"
    economics = [item for item in unit_economics if item.sku == line.sku
                 and item.placement_cluster_id == line.destination_cluster_id]
    if not economics or not economics[0].complete or economics[0].profit_per_unit is None:
        return "PRODUCT_ECONOMICS_INCOMPLETE"
    item = economics[0]
    if item.profit_per_unit <= 0:
        return "PRODUCT_ECONOMICS_BLOCKED"
    if thresholds is not None and (
            item.profit_per_unit < thresholds.min_profit_per_unit or
            item.margin_rate is None or item.margin_rate < thresholds.min_margin_rate or
            item.roi is None or item.roi < thresholds.min_roi):
        return "PRODUCT_ECONOMICS_BLOCKED"
    return None


def materialize_working_plan(
    shippable_plan: ShippablePlan,
    overrides: dict[str, dict[str, WorkingQuantityOverride]],
    *, recommendation=None, decision_rows=(), unit_economics=(),
    selected_sources=frozenset(), thresholds=None,
) -> WorkingPlan:
    if not isinstance(shippable_plan, ShippablePlan):
        raise TypeError("shippable_plan must be ShippablePlan")
    indexed = {(line.sku, line.destination_cluster_id): line for line in shippable_plan.lines}
    flat = {(sku, cluster): record for sku, clusters in overrides.items()
            for cluster, record in clusters.items()}
    decisions = {(row.sku, row.destination_cluster_id): row for row in decision_rows}
    values = ({(item.sku, item.cluster_id): item.quantity for item in recommendation.items}
              if recommendation is not None else {})
    reasons_by_key = {key: ozon_choice_reason(shippable_plan, line, decisions.get(key),
                       recommendation, unit_economics, thresholds)
                      for key, line in indexed.items()}
    stale_selections={key for key in selected_sources if
                      key not in indexed or reasons_by_key[key] is not None}
    selected_sources=set(selected_sources)-stale_selections
    requested = {key: (values[key] if key in selected_sources else line.shippable_qty)
                 for key, line in indexed.items()}
    # Reserve manual quantities, then give the manager-selected destinations
    # priority over the model's original rank for this SKU.
    allocated = {}
    selected_skus = {sku for sku, _ in selected_sources}
    for sku in selected_skus:
        lines = sorted(((key, line) for key, line in indexed.items() if key[0] == sku),
                       key=lambda pair: (pair[0] not in selected_sources,
                                         pair[1].allocation_priority_rank or 10**9, pair[0][1]))
        committed = sum(flat[key].quantity for key, _ in lines if key in flat)
        remaining = max(0, (lines[0][1].resolved_seller_stock or 0)-committed)
        for key, line in lines:
            if key in flat:
                allocated[key] = flat[key].quantity
                continue
            quantity = requested[key]
            if quantity is None:
                allocated[key] = None
                continue
            pack = line.pack_multiple
            if key in selected_sources and pack:
                quantity = ((quantity + pack - 1) // pack) * pack
            if line.whole_pack_capacity_qty is not None:
                quantity = min(quantity, line.whole_pack_capacity_qty)
            quantity = min(quantity, (remaining // pack)*pack if pack else remaining)
            allocated[key] = quantity
            remaining -= quantity
    drafts = []
    for identity, line in indexed.items():
        override = flat.get(identity)
        working = (allocated.get(identity) if line.sku in selected_skus else
                   line.shippable_qty if override is None else override.quantity)
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
        if identity in selected_sources:
            if working < ((values[identity]+line.pack_multiple-1)//line.pack_multiple)*line.pack_multiple:
                reasons.append("OZON_QTY_LIMITED")
            reasons.append("OZON_SOURCE_SELECTED")
        drafts.append([line, override, working, reasons, changed])

    totals = {}
    stocks = {}
    for line, _, working, _, _ in drafts:
        totals[line.sku] = totals.get(line.sku, 0) + (working or 0)
        stocks[line.sku] = line.resolved_seller_stock
    exceeded = {sku for sku, total in totals.items()
                if stocks[sku] is not None and total > stocks[sku]}
    diagnostics = []
    for sku, cluster in sorted(stale_selections):
        diagnostics.append(WorkingPlanDiagnostic(
            "warning", "STALE_OZON_SELECTION",
            "Выбор Ozon устарел. Пересчитайте план и выберите источник заново.",
            sku, cluster))
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
            override is not None, changed, _status(reasons, override is not None or
                                                  (line.sku, line.destination_cluster_id) in selected_sources),
            tuple(reasons), line.capacity_kind, line.whole_pack_capacity_qty,
            "OZON" if (line.sku, line.destination_cluster_id) in selected_sources else "CALCULATED",
            (requested[(line.sku, line.destination_cluster_id)]
             if (line.sku, line.destination_cluster_id) in selected_sources
             else line.analytical_qty),
            reasons_by_key[(line.sku, line.destination_cluster_id)] is None,
            reasons_by_key[(line.sku, line.destination_cluster_id)]))
    lines_tuple = tuple(lines)
    orphan_count = len(set(flat)-set(indexed))
    if orphan_count:
        diagnostics.append(WorkingPlanDiagnostic(
            "warning", "ORPHAN_OVERRIDES", f"Устаревшие ручные изменения: {orphan_count}."))
    return WorkingPlan(
        _plan_id(shippable_plan, lines_tuple, recommendation), shippable_plan.analysis_snapshot_id,
        shippable_plan.shippable_plan_id, lines_tuple, tuple(diagnostics),
        sum(x.status == READY for x in lines_tuple),
        sum(x.status == ATTENTION for x in lines_tuple),
        sum(x.status == BLOCKED for x in lines_tuple),
        sum(x.is_overridden for x in lines_tuple),
        sum(x.is_overridden and x.working_qty != x.system_qty for x in lines_tuple),
        orphan_count, len(selected_sources))


def has_active_overrides(plan: ShippablePlan, overrides) -> bool:
    for line in plan.lines:
        record = overrides.get(line.sku, {}).get(line.destination_cluster_id)
        if record is not None and record.quantity != line.shippable_qty:
            return True
    return False
