from datetime import date
from backend.ozon.history import history_window,next_backfill,MAX_COMPLETED_WEEKS
def test_backend_history_is_12_weeks_and_bounded():
 window=history_window(date(2026,9,9)); assert window.completed_weeks==12
 while (n:=next_backfill(window)) is not None: window=n
 assert window.completed_weeks==MAX_COMPLETED_WEEKS
