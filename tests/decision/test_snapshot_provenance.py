from datetime import date
from typing import get_type_hints

import pytest

from backend.decision.contracts import AnalysisSnapshot
from backend.decision.snapshot import assemble_snapshot
from backend.domain.contracts import SourceMode


def test_analysis_snapshot_as_of_contract_is_date_and_required():
    assert get_type_hints(AnalysisSnapshot)["analysis_as_of"] is date
    assert AnalysisSnapshot.__dataclass_fields__["analysis_as_of"].default.__class__.__name__ == "_MISSING_TYPE"


def test_snapshot_assembly_rejects_missing_date_before_business_assembly():
    with pytest.raises(ValueError, match="analysis_as_of date"):
        assemble_snapshot(
            scenario=None, report_meta={}, input_statuses={}, demand_estimates=(), needs=(),
            observed_routes=(), clean_routes=(), stockout_signals=(), distortion_signals=(),
            route_economics=(), unit_economics=(), placements=(), safe_allocations=(),
            calculated_allocations=(), products=(), diagnostics=(), analysis_as_of=None,
            source_mode=SourceMode.FILES)


def test_api_snapshot_assembly_requires_source_snapshot_identity():
    with pytest.raises(ValueError, match="source snapshot identity"):
        assemble_snapshot(
            scenario=None, report_meta={}, input_statuses={}, demand_estimates=(), needs=(),
            observed_routes=(), clean_routes=(), stockout_signals=(), distortion_signals=(),
            route_economics=(), unit_economics=(), placements=(), safe_allocations=(),
            calculated_allocations=(), products=(), diagnostics=(), analysis_as_of=date(2026, 8, 25),
            source_mode=SourceMode.API, source_snapshot_id=None)
