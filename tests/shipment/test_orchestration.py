from dataclasses import replace
import pytest
from .test_ranking import outcome
from backend.shipment.orchestration import assemble_outcomes,ShipmentOrchestrationError
from backend.ozon.draft_contracts import ValidationState

def test_validation_identity_mismatch_fails_closed():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    bad=replace(original.validation,candidate_id="cs_invented")
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((original.candidate,),(bad,))

def test_global_rejection_leaves_original_assignment_unresolved():
    original=outcome("cs_a",ValidationState.REJECTED,accepted=False)
    result=assemble_outcomes((original.candidate,),(original.validation,))
    assert result[0].unresolved_assignments==original.candidate.assignments
