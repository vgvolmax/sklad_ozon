from datetime import date
from decimal import Decimal

import pytest

from backend.domain.contracts import SourceMode
from backend.supply.contracts import (
    AllocationObjective, PlacementZoneKind, ShippableLine, ShippablePlan,
)


def make_line(sku, cluster, qty, *, volume="1", pack=1, rank=1,
              zone_kind=PlacementZoneKind.SINGLE, zones=("DEFAULT",)):
    return ShippableLine(
        sku, f"ART-{sku}", cluster, qty, qty, 0, rank, pack, 100000, qty,
        Decimal(volume), Decimal(volume) * qty, zone_kind, zones, (),
    )


def make_plan(lines, *, source_mode=SourceMode.API, source_id="source-1"):
    return ShippablePlan(
        "plan-1", "analysis-1", source_mode,
        source_id if source_mode is SourceMode.API else None,
        date(2026, 9, 10), 56, True, AllocationObjective.MAX_MARGIN,
        tuple(lines), (),
    )


@pytest.fixture
def line_factory():
    return make_line


@pytest.fixture
def plan_factory():
    return make_plan
