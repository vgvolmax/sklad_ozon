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
