"""Pure normalization of shipment-oriented supply evidence (not quantities)."""

from collections import Counter
from collections.abc import Iterable
from datetime import date

from backend.domain.contracts import SourceMode
from backend.ingestion.restrictions import RestrictionRecord, RestrictionState
from backend.ingestion.supplier_packaging import PackMultiplicityEvidence
from backend.ozon.source_contracts import PlacementZoneEvidence

from .contracts import (
    OperationalSupplyFact,
    PlacementZoneKind,
    RestrictionCapacityEvidence,
    RestrictionCapacityKind,
    RestrictionEligibility,
    SupplyProductIdentity,
)


def conservative_cluster_capacity(records: Iterable[RestrictionRecord]) -> RestrictionCapacityEvidence:
    """Collapse allowed warehouse evidence without pretending capacities are additive."""
    rows = tuple(records)
    allowed = tuple(row for row in rows if row.state is RestrictionState.ALLOWED)
    if not allowed:
        eligibility = (RestrictionEligibility.INELIGIBLE if rows and all(
            row.state is RestrictionState.PROHIBITED for row in rows
        ) else RestrictionEligibility.UNKNOWN)
        return RestrictionCapacityEvidence(eligibility, RestrictionCapacityKind.UNKNOWN, None)
    if any(row.capacity_kind is RestrictionCapacityKind.UNLIMITED for row in allowed):
        return RestrictionCapacityEvidence(RestrictionEligibility.ALLOWED, RestrictionCapacityKind.UNLIMITED, None)
    finite = [row.max_supply_qty for row in allowed
              if row.capacity_kind is RestrictionCapacityKind.FINITE and row.max_supply_qty is not None]
    if finite:
        return RestrictionCapacityEvidence(RestrictionEligibility.ALLOWED, RestrictionCapacityKind.FINITE, max(finite))
    explicit = [row for row in allowed if row.capacity_kind is RestrictionCapacityKind.ZERO]
    if explicit and len(explicit) == len(allowed):
        return RestrictionCapacityEvidence(RestrictionEligibility.ALLOWED, RestrictionCapacityKind.ZERO, 0)
    return RestrictionCapacityEvidence(RestrictionEligibility.ALLOWED, RestrictionCapacityKind.UNKNOWN, None)


def _zone_kind(zones: tuple[str, ...], complete: bool) -> PlacementZoneKind:
    if not complete or not zones:
        return PlacementZoneKind.UNKNOWN
    return PlacementZoneKind.SINGLE if len(zones) == 1 else PlacementZoneKind.MULTIPLE


def build_operational_supply_facts(
    *, products: Iterable[SupplyProductIdentity], cluster_ids: Iterable[str],
    pack_evidence: Iterable[PackMultiplicityEvidence], source_mode: SourceMode,
    placement_zone_evidence: Iterable[PlacementZoneEvidence] = (),
    restrictions: Iterable[RestrictionRecord] = (),
    restriction_report_date: date | None = None,
) -> tuple[OperationalSupplyFact, ...]:
    """Join evidence by article while preserving every SKU × cluster identity."""
    product_rows = tuple(products)
    clusters = tuple(cluster_ids)
    packs = {}
    for row in pack_evidence:
        previous = packs.get(row.article)
        if previous is None:
            packs[row.article] = row
        elif previous.pack_multiple != row.pack_multiple or previous.reason_codes != row.reason_codes:
            packs[row.article] = PackMultiplicityEvidence(
                row.article, None, None, None, ("CONFLICTING_PACK_MULTIPLICITY",))
    zones_by_sku = {row.sku: row for row in placement_zone_evidence}
    restriction_rows = tuple(restrictions)
    article_counts = Counter(row.article for row in product_rows if row.article)
    facts = []
    for product in product_rows:
        pack = packs.get(product.article) if product.article else None
        for cluster_id in clusters:
            reasons = []
            if not product.article:
                reasons.append("MISSING_SUPPLIER_ARTICLE")
            elif pack is None:
                reasons.append("MISSING_PACK_MULTIPLICITY")
            elif pack.pack_multiple is None:
                reasons.extend(pack.reason_codes or ("MISSING_PACK_MULTIPLICITY",))
            if product.article and article_counts[product.article] > 1:
                reasons.append("ARTICLE_SHARED_BY_MULTIPLE_SKUS")

            if source_mode is SourceMode.API:
                zone_evidence = zones_by_sku.get(product.sku)
                zones = zone_evidence.zones if zone_evidence is not None else ()
                zone_kind = _zone_kind(zones, zone_evidence.complete if zone_evidence else False)
                capacity = RestrictionCapacityEvidence(
                    RestrictionEligibility.UNKNOWN, RestrictionCapacityKind.UNKNOWN, None)
                report_date = None
            else:
                matching = tuple(row for row in restriction_rows
                                 if row.sku == product.sku and row.cluster == cluster_id)
                capacity = conservative_cluster_capacity(matching)
                zones = tuple(dict.fromkeys(zone for row in matching for zone in row.placement_zones))
                zone_kind = _zone_kind(zones, bool(zones))
                report_date = restriction_report_date
            if zone_kind is PlacementZoneKind.UNKNOWN:
                reasons.append("UNKNOWN_PLACEMENT_ZONE")
            facts.append(OperationalSupplyFact(
                sku=product.sku,
                article=product.article,
                cluster_id=cluster_id,
                pack_multiple=pack.pack_multiple if pack is not None else None,
                placement_zone_kind=zone_kind,
                placement_zones=zones,
                restriction_eligibility=capacity.eligibility,
                capacity_kind=capacity.capacity_kind,
                capacity_qty=capacity.capacity_qty,
                restriction_report_date=report_date,
                reason_codes=tuple(dict.fromkeys(reasons)),
            ))
    return tuple(facts)
