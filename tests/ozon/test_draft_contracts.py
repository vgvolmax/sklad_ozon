from datetime import datetime, timezone

import pytest

from backend.ozon.draft_contracts import OzonTimeslot


def test_timeslot_requires_ordered_aware_datetimes():
    start=datetime(2026,9,11,9,tzinfo=timezone.utc)
    assert OzonTimeslot(start,datetime(2026,9,11,10,tzinfo=timezone.utc)).from_dt==start
    with pytest.raises(ValueError): OzonTimeslot(start.replace(tzinfo=None),start)
    with pytest.raises(ValueError): OzonTimeslot(start,start)
