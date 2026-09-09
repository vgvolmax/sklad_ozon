from datetime import date
from backend.domain.contracts import OrderLifecycle,OrderRecord
from backend.ozon.history import history_window,next_backfill,MAX_COMPLETED_WEEKS,usable_completed_weeks
def test_backend_history_is_12_weeks_and_bounded():
 window=history_window(date(2026,9,9)); assert window.completed_weeks==12
 while (n:=next_backfill(window)) is not None: window=n
 assert window.completed_weeks==MAX_COMPLETED_WEEKS

def test_current_partial_week_is_not_usable_completed_coverage():
 records=(OrderRecord('S',1,'A','B',OrderLifecycle.FULFILLED,'2026-09-08'),
          OrderRecord('S',1,'A','B',OrderLifecycle.FULFILLED,'2026-09-01'))
 assert usable_completed_weeks(records,date(2026,9,9))=={(2026,36)}
