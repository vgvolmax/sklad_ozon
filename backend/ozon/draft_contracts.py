"""Immutable, normalized evidence returned by temporary Ozon drafts."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from backend.shipment.contracts import CandidateAssignment, ShipmentMethod


def _text(value: object, name: str, *, blank: bool = False) -> None:
    if not isinstance(value, str) or (not blank and not value.strip()):
        raise ValueError(f"{name} must be a {'string' if blank else 'nonblank string'}")


def _positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value <= 0:
        raise ValueError(f"{name} must be positive")


class ValidationState(str, Enum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    REJECTED = "rejected"
    NO_TIMESLOT = "no_timeslot"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True)
class OzonRejectedAssignment:
    sku: str
    article: str
    destination_cluster_id: str
    quantity: int
    code: str
    message: str

    def __post_init__(self) -> None:
        _text(self.sku, "sku"); _text(self.article, "article", blank=True)
        _text(self.destination_cluster_id, "destination_cluster_id")
        _positive_int(self.quantity, "quantity")
        _text(self.code, "code"); _text(self.message, "message", blank=True)


@dataclass(frozen=True, slots=True)
class OzonTimeslot:
    from_dt: datetime
    to_dt: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.from_dt, datetime) or not isinstance(self.to_dt, datetime):
            raise TypeError("timeslot bounds must be datetime values")
        if self.from_dt.tzinfo is None or self.from_dt.utcoffset() is None or self.to_dt.tzinfo is None or self.to_dt.utcoffset() is None:
            raise ValueError("timeslot bounds must be offset-aware")
        if self.from_dt >= self.to_dt:
            raise ValueError("timeslot from_dt must precede to_dt")


@dataclass(frozen=True, slots=True)
class OzonWarehouseEvidence:
    destination_cluster_id: str
    warehouse_id: int
    score: float | None = None

    def __post_init__(self) -> None:
        _text(self.destination_cluster_id, "destination_cluster_id")
        _positive_int(self.warehouse_id, "warehouse_id")
        if self.score is not None and (isinstance(self.score, bool) or not isinstance(self.score, (int, float))):
            raise TypeError("score must be numeric")


@dataclass(frozen=True, slots=True)
class ValidatedShipmentOption:
    candidate_id: str
    draft_id: int | None
    state: ValidationState
    method: ShipmentMethod
    seller_warehouse_id: int | None
    handoff_point_id: int | None
    accepted_assignments: tuple[CandidateAssignment, ...]
    rejected_assignments: tuple[OzonRejectedAssignment, ...]
    warehouse_evidence: tuple[OzonWarehouseEvidence, ...]
    travel_time_days: int | None
    timeslots: tuple[OzonTimeslot, ...]
    checked_at_utc: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id")
        if self.draft_id is not None: _positive_int(self.draft_id, "draft_id")
        if not isinstance(self.state, ValidationState) or not isinstance(self.method, ShipmentMethod):
            raise TypeError("state and method must use their enums")
        for name in ("seller_warehouse_id", "handoff_point_id", "travel_time_days"):
            value = getattr(self, name)
            if value is not None: _positive_int(value, name)
        for name in ("accepted_assignments", "rejected_assignments", "warehouse_evidence", "timeslots", "reason_codes"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be a tuple")
        if any(not isinstance(row, CandidateAssignment) for row in self.accepted_assignments):
            raise TypeError("accepted_assignments contains an invalid value")
        if any(not isinstance(row, OzonRejectedAssignment) for row in self.rejected_assignments):
            raise TypeError("rejected_assignments contains an invalid value")
        if any(not isinstance(row, OzonWarehouseEvidence) for row in self.warehouse_evidence):
            raise TypeError("warehouse_evidence contains an invalid value")
        if any(not isinstance(row, OzonTimeslot) for row in self.timeslots):
            raise TypeError("timeslots contains an invalid value")
        try:
            checked = datetime.fromisoformat(self.checked_at_utc)
        except (TypeError, ValueError) as exc:
            raise ValueError("checked_at_utc must be an offset-aware ISO datetime") from exc
        if checked.tzinfo is None or checked.utcoffset() is None:
            raise ValueError("checked_at_utc must be offset-aware")
        if any(not isinstance(x, str) or not x.strip() for x in self.reason_codes):
            raise ValueError("reason_codes must be a tuple of nonblank strings")
