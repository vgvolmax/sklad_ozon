"""Map stockout replacement origins to donor-oriented distortion signals."""

from collections import defaultdict
from typing import Iterable

from backend.analytics.routes import RouteProfile
from backend.domain.signals import (
    AffectedDestinationEvidence,
    RecommendationDistortionSignal,
    SignalConfidence,
    StockoutSignal,
)


def _parse_week(value: str) -> tuple[int, int]:
    year, week = value.split("-W")
    return int(year), int(week)


def detect_recommendation_distortion(
    signals: Iterable[StockoutSignal], routes: RouteProfile,
) -> tuple[RecommendationDistortionSignal, ...]:
    positive_routes = {(r.sku, r.iso_year, r.iso_week, r.origin_cluster_id, r.destination_cluster_id)
                       for r in routes.routes if r.quantity > 0}
    rank = {SignalConfidence.LOW: 0, SignalConfidence.MEDIUM: 1, SignalConfidence.HIGH: 2}
    grouped = defaultdict(dict)
    for signal in signals:
        year, week = _parse_week(signal.observed_week)
        for donor in signal.replacement_origins:
            key = (signal.sku, year, week, donor.origin_cluster_id, signal.destination_cluster_id)
            if key not in positive_routes:
                continue
            evidence = AffectedDestinationEvidence(
                signal.destination_cluster_id, signal.confidence, donor.share_after,
                donor.share_after - donor.share_before,
            )
            destinations = grouped[(signal.sku, donor.origin_cluster_id)]
            previous = destinations.get(signal.destination_cluster_id)
            if previous is None or (
                rank[evidence.stockout_confidence], evidence.donor_share_increase,
                evidence.donor_share_after,
            ) > (
                rank[previous.stockout_confidence], previous.donor_share_increase,
                previous.donor_share_after,
            ):
                destinations[signal.destination_cluster_id] = evidence
    result = []
    for (sku, donor), destinations in sorted(grouped.items()):
        affected = [destinations[key] for key in sorted(destinations)]
        codes = ["DONOR_FOR_PROBABLE_STOCKOUT"]
        if len(affected) > 1:
            codes.append("MULTIPLE_AFFECTED_DESTINATIONS")
        result.append(RecommendationDistortionSignal(
            sku, donor, max((item.stockout_confidence for item in affected), key=rank.__getitem__),
            tuple(affected), tuple(codes),
        ))
    return tuple(result)
