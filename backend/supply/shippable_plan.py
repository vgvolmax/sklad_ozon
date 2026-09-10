"""Pure all-cluster whole-pack operational planning."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
import hashlib
import json

from backend.domain.contracts import ProductEconomicsInput, SourceMode

from .contracts import (
    AllocationObjective,
    OperationalSupplyFact,
    OptimizationResult,
    PlacementZoneKind,
    PlanFamily,
    ShippableDiagnostic,
    ShippableLine,
    ShippablePlan,
)


def _require_int(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < (1 if positive else 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def round_up_to_pack(quantity: int, pack_multiple: int) -> int:
    """Round a known quantity upward using integer arithmetic only."""
    quantity = _require_int(quantity, "quantity")
    pack_multiple = _require_int(pack_multiple, "pack_multiple", positive=True)
    return ((quantity + pack_multiple - 1) // pack_multiple) * pack_multiple


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _diagnostic(code: str, message: str, sku: str | None = None,
                cluster: str | None = None) -> ShippableDiagnostic:
    return ShippableDiagnostic("error", code, message, sku, cluster)


_DIAGNOSTIC_MESSAGES = {
    "MISSING_PACK_MULTIPLICITY": "Supplier pack multiplicity is missing.",
    "CONFLICTING_PACK_MULTIPLICITY": "Supplier pack multiplicity conflicts.",
    "INVALID_PACK_MULTIPLICITY": "Supplier pack multiplicity is invalid.",
    "MISSING_SUPPLIER_ARTICLE": "Seller article is missing.",
    "MISSING_UNIT_VOLUME": "Canonical unit volume is missing.",
    "INVALID_UNIT_VOLUME": "Canonical unit volume is invalid.",
    "UNKNOWN_PLACEMENT_ZONE": "Placement-zone evidence is unknown.",
}


def _unique_by(rows, key, label):
    result = {}
    for row in rows:
        identity = key(row)
        if identity in result:
            raise ValueError(f"duplicate {label}: {identity!r}")
        result[identity] = row
    return result


def _plan_id(*, analysis_snapshot_id, source_mode, source_snapshot_id,
             analysis_as_of, horizon_days, include_inbound, objective,
             lines, diagnostics):
    payload = {
        "analysis_snapshot_id": analysis_snapshot_id,
        "source_mode": source_mode.value,
        "source_snapshot_id": source_snapshot_id,
        "analysis_as_of": analysis_as_of.isoformat(),
        "horizon_days": horizon_days,
        "include_inbound": include_inbound,
        "objective": objective.value,
        "lines": [{
            "sku": line.sku, "article": line.article,
            "destination_cluster_id": line.destination_cluster_id,
            "analytical_qty": line.analytical_qty,
            "rounded_target_qty": line.rounded_target_qty,
            "rounding_delta_qty": line.rounding_delta_qty,
            "allocation_priority_rank": line.allocation_priority_rank,
            "pack_multiple": line.pack_multiple,
            "resolved_seller_stock": line.resolved_seller_stock,
            "shippable_qty": line.shippable_qty,
            "unit_volume_l": _decimal_text(line.unit_volume_l),
            "total_volume_l": _decimal_text(line.total_volume_l),
            "placement_zone_kind": line.placement_zone_kind.value,
            "placement_zones": line.placement_zones,
            "reason_codes": line.reason_codes,
        } for line in lines],
        "diagnostics": [{
            "severity": item.severity, "code": item.code, "message": item.message,
            "sku": item.sku, "destination_cluster_id": item.destination_cluster_id,
        } for item in diagnostics],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    return "sp_" + hashlib.sha256(canonical).hexdigest()


def build_shippable_plan(
    *, analysis_snapshot_id: str, source_mode: SourceMode,
    source_snapshot_id: str | None, analysis_as_of: date,
    horizon_days: int, include_inbound: bool, objective: AllocationObjective,
    calculated_allocations: Iterable[OptimizationResult],
    products: Iterable[ProductEconomicsInput],
    supply_facts: Iterable[OperationalSupplyFact],
    blocked_decision_rows: Iterable[object] = (),
) -> ShippablePlan:
    """Build one deterministic plan across every Calculated destination cluster."""
    if not isinstance(source_mode, SourceMode):
        raise TypeError("source_mode must be SourceMode")
    if source_mode is SourceMode.API and not source_snapshot_id:
        raise ValueError("API source_snapshot_id is required")
    if source_mode is SourceMode.FILES and source_snapshot_id is not None:
        raise ValueError("FILES source_snapshot_id must be None")
    results = tuple(calculated_allocations)
    if any(not isinstance(item, OptimizationResult) for item in results):
        raise TypeError("calculated_allocations must contain OptimizationResult values")
    if any(item.plan_family is not PlanFamily.CALCULATED for item in results):
        raise ValueError("only CALCULATED OptimizationResult values are accepted")
    if any(item.objective is not objective for item in results):
        raise ValueError("Calculated allocation objective must match plan objective")
    results_by_sku = _unique_by(results, lambda item: item.sku, "Calculated result SKU")
    products_by_sku = _unique_by(tuple(products), lambda item: item.sku, "product SKU")
    facts_by_key = _unique_by(tuple(supply_facts),
                              lambda item: (item.sku, item.cluster_id), "supply fact")

    diagnostics = []
    decision_row_quantities = {}
    for row in blocked_decision_rows:
        key = (getattr(row, "sku"), getattr(row, "destination_cluster_id"))
        if key in decision_row_quantities:
            raise ValueError(f"duplicate DecisionRow identity: {key!r}")
        decision_row_quantities[key] = getattr(row, "calculated_plan_qty")
        if decision_row_quantities[key] is None:
            diagnostics.append(_diagnostic(
                "CALCULATED_PLAN_UNAVAILABLE", "Calculated Plan is unavailable for this identity.",
                key[0], key[1]))

    drafts_by_sku = defaultdict(list)
    for sku, optimization in results_by_sku.items():
        ranks = [item.allocation_priority_rank for item in optimization.decisions
                 if item.allocation_priority_rank is not None]
        if len(ranks) != len(set(ranks)) or sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("allocation priority ranks must be unique and progressing")
        sku_facts = [facts_by_key[(sku, item.cluster_id)] for item in optimization.decisions
                     if (sku, item.cluster_id) in facts_by_key]
        pack_values = {item.pack_multiple for item in sku_facts
                       if item.pack_multiple is not None}
        articles = {item.article for item in sku_facts}
        if len(pack_values) > 1:
            raise ValueError("pack multiplicity must be consistent per SKU")
        if len(articles) > 1:
            raise ValueError("seller article must be consistent per SKU")
        for item in optimization.decisions:
            key = (sku, item.cluster_id)
            decision_row_qty = decision_row_quantities.get(key, item.allocation_qty)
            if decision_row_qty is None or decision_row_qty != item.allocation_qty:
                raise ValueError("DecisionRow and Calculated allocation disagree")
            if item.eligible != (item.allocation_priority_rank is not None):
                raise ValueError("eligible Calculated decisions require priority evidence")
            fact = facts_by_key.get(key)
            reasons = list(() if fact is None else fact.reason_codes)
            if fact is None:
                reasons.extend(("MISSING_SUPPLIER_ARTICLE", "MISSING_PACK_MULTIPLICITY",
                                "UNKNOWN_PLACEMENT_ZONE"))
            product = products_by_sku.get(sku)
            volume = None if product is None else product.volume_liters
            if volume is None:
                reasons.append("MISSING_UNIT_VOLUME")
            elif (not isinstance(volume, Decimal) or not volume.is_finite() or volume <= 0):
                volume = None
                reasons.append("INVALID_UNIT_VOLUME")
            pack = None if fact is None else fact.pack_multiple
            if item.allocation_qty == 0:
                rounded = delta = 0
            elif pack is None:
                rounded = delta = None
            else:
                rounded = round_up_to_pack(item.allocation_qty, pack)
                delta = rounded - item.allocation_qty
                if delta:
                    reasons.append("ROUNDED_UP_TO_WHOLE_PACK")
            drafts_by_sku[sku].append({
                "decision": item, "fact": fact, "pack": pack, "rounded": rounded,
                "delta": delta, "volume": volume,
                "reasons": list(dict.fromkeys(reasons)),
                "stock": optimization.available_stock,
            })

    for sku, drafts in drafts_by_sku.items():
        for draft in drafts:
            cluster = draft["decision"].cluster_id
            for code in draft["reasons"]:
                message = _DIAGNOSTIC_MESSAGES.get(code)
                if message is not None:
                    diagnostics.append(_diagnostic(code, message, sku, cluster))

    lines = []
    for sku in sorted(drafts_by_sku):
        drafts = drafts_by_sku[sku]
        positive = [draft for draft in drafts if draft["decision"].allocation_qty > 0]
        positive.sort(key=lambda draft: draft["decision"].allocation_priority_rank)
        remaining = drafts[0]["stock"]
        shipped_by_cluster = {}
        for draft in positive:
            decision = draft["decision"]
            pack = draft["pack"]
            if pack is None:
                shipped_by_cluster[decision.cluster_id] = None
                remaining = max(0, remaining - min(remaining, decision.allocation_qty))
                continue
            fundable = (remaining // pack) * pack
            shipped = min(draft["rounded"], fundable)
            shipped_by_cluster[decision.cluster_id] = shipped
            remaining -= shipped
            if shipped < draft["rounded"]:
                draft["reasons"].append("WHOLE_PACK_LIMITED_BY_SELLER_STOCK")
        for draft in drafts:
            decision = draft["decision"]
            fact = draft["fact"]
            shipped = (0 if decision.allocation_qty == 0
                       else shipped_by_cluster[decision.cluster_id])
            volume = draft["volume"]
            lines.append(ShippableLine(
                sku=sku,
                article="" if fact is None else fact.article,
                destination_cluster_id=decision.cluster_id,
                analytical_qty=decision.allocation_qty,
                rounded_target_qty=draft["rounded"],
                rounding_delta_qty=draft["delta"],
                allocation_priority_rank=decision.allocation_priority_rank,
                pack_multiple=draft["pack"],
                resolved_seller_stock=draft["stock"],
                shippable_qty=shipped,
                unit_volume_l=volume,
                total_volume_l=None if volume is None or shipped is None else volume * shipped,
                placement_zone_kind=(PlacementZoneKind.UNKNOWN if fact is None
                                     else fact.placement_zone_kind),
                placement_zones=() if fact is None else fact.placement_zones,
                reason_codes=tuple(dict.fromkeys(draft["reasons"])),
            ))
    lines.sort(key=lambda line: (line.sku, line.destination_cluster_id))
    diagnostics = list(dict.fromkeys(diagnostics))
    diagnostics.sort(key=lambda item: (item.sku or "", item.destination_cluster_id or "",
                                       item.code, item.message))
    plan_id = _plan_id(
        analysis_snapshot_id=analysis_snapshot_id, source_mode=source_mode,
        source_snapshot_id=source_snapshot_id, analysis_as_of=analysis_as_of,
        horizon_days=horizon_days, include_inbound=include_inbound, objective=objective,
        lines=lines, diagnostics=diagnostics)
    return ShippablePlan(
        plan_id, analysis_snapshot_id, source_mode, source_snapshot_id,
        analysis_as_of, horizon_days, include_inbound, objective,
        tuple(lines), tuple(diagnostics))
