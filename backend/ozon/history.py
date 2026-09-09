"""Backend-owned, bounded order history policy."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class HistoryWindow:
    history_from: date
    history_to: date
    completed_weeks: int


INITIAL_COMPLETED_WEEKS = 12
BACKFILL_WEEKS = 4
MAX_COMPLETED_WEEKS = 52


def history_window(source_as_of: date, completed_weeks: int = INITIAL_COMPLETED_WEEKS) -> HistoryWindow:
    if completed_weeks < INITIAL_COMPLETED_WEEKS or completed_weeks > MAX_COMPLETED_WEEKS:
        raise ValueError("completed_weeks outside backend history policy")
    week_start = source_as_of - timedelta(days=source_as_of.weekday())
    return HistoryWindow(week_start - timedelta(weeks=completed_weeks), source_as_of, completed_weeks)


def next_backfill(window: HistoryWindow) -> HistoryWindow | None:
    weeks = min(window.completed_weeks + BACKFILL_WEEKS, MAX_COMPLETED_WEEKS)
    if weeks == window.completed_weeks:
        return None
    return HistoryWindow(window.history_from - timedelta(weeks=weeks-window.completed_weeks), window.history_to, weeks)


def usable_completed_weeks(records, source_as_of: date) -> frozenset[tuple[int, int]]:
    """Return source-wide completed ISO weeks with usable fulfilled demand."""
    current_week = tuple(source_as_of.isocalendar()[:2])
    weeks = set()
    for record in records:
        lifecycle = getattr(record, "lifecycle", None)
        if getattr(lifecycle, "value", None) != "fulfilled":
            continue
        raw = str(getattr(record, "accepted_at", ""))[:10]
        try:
            day = date.fromisoformat(raw)
        except ValueError:
            continue
        week = tuple(day.isocalendar()[:2])
        if week != current_week and day < source_as_of:
            weeks.add(week)
    return frozenset(weeks)
