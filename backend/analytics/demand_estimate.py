"""Explainable current-demand estimates by customer destination."""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from statistics import median

from backend.domain.signals import SignalConfidence

from .demand import DemandResult


ZERO = Decimal("0")
TEN_PERCENT = Decimal("0.10")
TWENTY_PERCENT = Decimal("0.20")
HALF = Decimal("0.5")


class DemandRegime(str, Enum):
    GROWTH = "growth"
    STABLE = "stable"
    DECLINE = "decline"
    TRANSITION = "transition"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class DemandEstimate:
    sku: str
    destination_cluster_id: str
    eligible_week_count: int
    m1: Decimal | None
    m2: Decimal | None
    latest_week_qty: Decimal | None
    regime: DemandRegime
    regime_confirmed: bool | None
    raw_adjustment: Decimal
    applied_adjustment: Decimal
    current_weekly_rate: Decimal | None
    confidence: SignalConfidence
    explanation_codes: tuple[str, ...]


def _median(values: list[Decimal]) -> Decimal:
    return median(values)


def _estimate(sku: str, destination: str, series: list[Decimal]) -> DemandEstimate:
    count = len(series)
    if not series:
        return DemandEstimate(
            sku, destination, 0, None, None, None, DemandRegime.INCOMPLETE,
            None, ZERO, ZERO, None, SignalConfidence.LOW,
            ("NO_ELIGIBLE_WEEKS",),
        )
    latest = series[-1]
    if count < 8:
        baseline = _median(series)
        confidence = SignalConfidence.MEDIUM if count >= 4 else SignalConfidence.LOW
        code = "SHORT_HISTORY_MEDIAN" if count >= 4 else "VERY_SHORT_HISTORY"
        return DemandEstimate(
            sku, destination, count, None, baseline, latest,
            DemandRegime.INCOMPLETE, None, ZERO, ZERO, baseline, confidence,
            (code,),
        )

    recent = series[-8:]
    m1 = _median(recent[:4])
    m2 = _median(recent[4:])
    latest = recent[-1]
    codes = ["FULL_8_WEEK_MODEL"]
    if m1 == ZERO and m2 > ZERO:
        codes.append("REGIME_TRANSITION")
        return DemandEstimate(
            sku, destination, count, m1, m2, latest,
            DemandRegime.TRANSITION, None, ZERO, ZERO, m2,
            SignalConfidence.MEDIUM, tuple(codes),
        )

    if m1 == ZERO or -TEN_PERCENT <= (m2 / m1 - Decimal(1)) <= TEN_PERCENT:
        regime = DemandRegime.STABLE
        confirmed = m2 * (Decimal(1) - TEN_PERCENT) <= latest <= m2 * (Decimal(1) + TEN_PERCENT)
    elif m2 / m1 - Decimal(1) > TEN_PERCENT:
        regime = DemandRegime.GROWTH
        confirmed = latest > m2 * (Decimal(1) + TEN_PERCENT)
    else:
        regime = DemandRegime.DECLINE
        confirmed = latest < m2 * (Decimal(1) - TEN_PERCENT)
    codes.extend((f"REGIME_{regime.name}", "REGIME_CONFIRMED" if confirmed else "REGIME_NOT_CONFIRMED"))

    raw = ZERO
    applied = ZERO
    if confirmed and regime in (DemandRegime.GROWTH, DemandRegime.DECLINE):
        raw = HALF * (latest - m2)
        lower, upper = -TWENTY_PERCENT * m2, TWENTY_PERCENT * m2
        applied = max(lower, min(raw, upper))
        if applied != raw:
            codes.append("ADJUSTMENT_CAPPED")
    return DemandEstimate(
        sku, destination, count, m1, m2, latest, regime, confirmed,
        raw, applied, m2 + applied, SignalConfidence.HIGH, tuple(codes),
    )


def estimate_destination_demand(demand: DemandResult) -> tuple[DemandEstimate, ...]:
    """Estimate demand without consulting origin routes, stock, or Ozon signals."""
    weeks = sorted(demand.window.included_weeks)
    identities = sorted({(cell.sku, cell.destination_cluster_id) for cell in demand.cells})
    quantities = {
        (cell.sku, cell.destination_cluster_id, cell.iso_year, cell.iso_week): Decimal(cell.quantity)
        for cell in demand.cells
    }
    return tuple(
        _estimate(sku, destination, [
            quantities.get((sku, destination, year, week), ZERO)
            for year, week in weeks
        ])
        for sku, destination in identities
    )
