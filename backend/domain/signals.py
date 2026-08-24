"""Immutable evidence contracts for probable stockout hypotheses."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SignalConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AvailabilityCorroboration(str, Enum):
    SUPPORTS = "supports"
    NEUTRAL = "neutral"
    CONTRADICTS = "contradicts"


@dataclass(frozen=True, slots=True)
class ReplacementOriginEvidence:
    origin_cluster_id: str
    share_before: Decimal
    share_after: Decimal


@dataclass(frozen=True, slots=True)
class StockoutSignal:
    sku: str
    destination_cluster_id: str
    confidence: SignalConfidence
    baseline_week: str
    observed_week: str
    baseline_local_share: Decimal
    observed_local_share: Decimal
    demand_retention: Decimal
    availability_corroboration: AvailabilityCorroboration
    replacement_origins: tuple[ReplacementOriginEvidence, ...]
    explanation_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AffectedDestinationEvidence:
    destination_cluster_id: str
    stockout_confidence: SignalConfidence
    donor_share_after: Decimal
    donor_share_increase: Decimal


@dataclass(frozen=True, slots=True)
class RecommendationDistortionSignal:
    sku: str
    recommended_cluster_id: str
    confidence: SignalConfidence
    affected_destinations: tuple[AffectedDestinationEvidence, ...]
    explanation_codes: tuple[str, ...]
