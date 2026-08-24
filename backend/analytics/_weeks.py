"""Shared completed-ISO-week policy for analytics populations."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class WeekPolicy(str, Enum):
    COMPLETED_ISO_WEEKS = "completed_iso_weeks"


@dataclass(frozen=True, slots=True)
class AnalyticsWindow:
    as_of: date
    current_iso_year: int
    current_iso_week: int
    included_weeks: tuple[tuple[int, int], ...]
    excluded_current_week_observations: int
    excluded_future_observations: int
    excluded_undated_observations: int


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


def make_window(
    *,
    as_of: date,
    included_weeks: set[tuple[int, int]],
    excluded_current: int,
    excluded_future: int,
    excluded_undated: int,
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
    )
