"""Shared completed-ISO-week policy for analytics populations."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum


class WeekPolicy(str, Enum):
    COMPLETED_ISO_WEEKS = "completed_iso_weeks"


@dataclass(frozen=True, slots=True)
class ObservationCoverage:
    """Inclusive calendar interval in which missing observations are known zeros."""

    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise ValueError("coverage period_end must not precede period_start")


@dataclass(frozen=True, slots=True)
class AnalyticsWindow:
    as_of: date
    current_iso_year: int
    current_iso_week: int
    included_weeks: tuple[tuple[int, int], ...]
    excluded_current_week_observations: int
    excluded_future_observations: int
    excluded_undated_observations: int
    coverage_start: date | None = None
    coverage_end: date | None = None
    coverage_current: bool = False


def parse_source_date(value: str) -> date | None:
    """Return the represented calendar date, without timezone conversion."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def require_completed_iso_weeks(policy: WeekPolicy) -> None:
    if policy != WeekPolicy.COMPLETED_ISO_WEEKS:
        raise ValueError(f"unsupported week policy: {policy!r}")


def completed_iso_week_axis(
    *,
    first_week: tuple[int, int] | None,
    as_of: date,
) -> tuple[tuple[int, int], ...]:
    """Return completed ISO weeks from ``first_week`` through the week before ``as_of``."""
    if first_week is None:
        return ()

    cursor = date.fromisocalendar(first_week[0], first_week[1], 1)
    current = as_of.isocalendar()
    current_monday = date.fromisocalendar(current.year, current.week, 1)
    weeks: list[tuple[int, int]] = []

    while cursor < current_monday:
        iso = cursor.isocalendar()
        weeks.append((iso.year, iso.week))
        cursor += timedelta(days=7)

    return tuple(weeks)


def fully_covered_completed_iso_weeks(
    *, coverage: ObservationCoverage, as_of: date,
) -> tuple[tuple[int, int], ...]:
    """Return ISO weeks wholly inside coverage and completed before ``as_of``."""
    start_monday = coverage.period_start + timedelta(
        days=(7 - coverage.period_start.weekday()) % 7
    )
    current_iso = as_of.isocalendar()
    current_monday = date.fromisocalendar(current_iso.year, current_iso.week, 1)
    weeks: list[tuple[int, int]] = []
    cursor = start_monday
    while cursor + timedelta(days=6) <= coverage.period_end and cursor < current_monday:
        iso = cursor.isocalendar()
        weeks.append((iso.year, iso.week))
        cursor += timedelta(days=7)
    return tuple(weeks)


def coverage_includes_latest_completed_week(
    coverage: ObservationCoverage, *, as_of: date,
) -> bool:
    current_iso = as_of.isocalendar()
    latest_monday = date.fromisocalendar(current_iso.year, current_iso.week, 1) - timedelta(days=7)
    return (
        coverage.period_start <= latest_monday
        and latest_monday + timedelta(days=6) <= coverage.period_end
    )


def make_window(
    *,
    as_of: date,
    included_weeks: set[tuple[int, int]],
    excluded_current: int,
    excluded_future: int,
    excluded_undated: int,
    coverage: ObservationCoverage | None = None,
) -> AnalyticsWindow:
    current = as_of.isocalendar()
    return AnalyticsWindow(
        as_of=as_of,
        current_iso_year=current.year,
        current_iso_week=current.week,
        included_weeks=tuple(sorted(included_weeks)),
        excluded_current_week_observations=excluded_current,
        excluded_future_observations=excluded_future,
        excluded_undated_observations=excluded_undated,
        coverage_start=coverage.period_start if coverage else None,
        coverage_end=coverage.period_end if coverage else None,
        coverage_current=(
            coverage_includes_latest_completed_week(coverage, as_of=as_of)
            if coverage else False
        ),
    )
