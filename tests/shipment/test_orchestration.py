from dataclasses import replace
from decimal import Decimal
import pytest
from .test_ranking import assignment, outcome
from backend.shipment.orchestration import assemble_outcomes,ShipmentOrchestrationError
from backend.ozon.draft_contracts import OzonRejectedAssignment,ValidationState

def test_validation_identity_mismatch_fails_closed():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    bad=replace(original.validation,candidate_id="cs_invented")
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((original.candidate,),(bad,))

def test_global_rejection_leaves_original_assignment_unresolved():
    original=outcome("cs_a",ValidationState.REJECTED,accepted=False)
    result=assemble_outcomes((original.candidate,),(original.validation,))
    assert result[0].unresolved_assignments==original.candidate.assignments

def test_duplicate_validation_result_fails_closed():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((original.candidate,),(original.validation,original.validation))

def test_missing_validation_result_fails_closed():
    first=outcome("cs_a",ValidationState.ACCEPTED)
    second=outcome("cs_b",ValidationState.ACCEPTED)
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((first.candidate,second.candidate),(first.validation,))

def test_accepted_assignment_identity_mismatch_fails_closed():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    foreign=replace(original.candidate.assignments[0],sku="foreign-sku")
    validation=replace(original.validation,accepted_assignments=(foreign,))
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((original.candidate,),(validation,))

def test_accepted_assignment_quantity_mismatch_fails_closed():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    candidate_row=replace(original.candidate.assignments[0],quantity=12,total_volume_l=Decimal("12"))
    candidate=replace(original.candidate,assignments=(candidate_row,),total_qty=12,total_volume_l=Decimal("12"))
    accepted_row=replace(candidate_row,quantity=6,total_volume_l=Decimal("6"))
    validation=replace(original.validation,accepted_assignments=(accepted_row,))
    with pytest.raises(ShipmentOrchestrationError,match="VALIDATION_RESULT_IDENTITY_MISMATCH"):
        assemble_outcomes((candidate,),(validation,))

def test_partial_item_evidence_conserves_all_candidate_assignments():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    rejected_assignment=assignment("K",6)
    candidate=replace(original.candidate,cluster_ids=("M","K"),
        assignments=original.candidate.assignments+(rejected_assignment,),total_qty=12,total_volume_l=Decimal("12"))
    rejected=OzonRejectedAssignment("sku","40750","K",6,"REJECTED","Rejected by Ozon")
    validation=replace(original.validation,state=ValidationState.PARTIAL,
        accepted_assignments=original.candidate.assignments,rejected_assignments=(rejected,))
    result=assemble_outcomes((candidate,),(validation,))[0]
    assert result.unresolved_assignments==()
    terminal={(row.sku,row.destination_cluster_id,row.quantity)
              for row in result.validation.accepted_assignments+result.validation.rejected_assignments}
    assert terminal=={(row.sku,row.destination_cluster_id,row.quantity) for row in candidate.assignments}

def test_unavailable_without_item_evidence_preserves_all_assignments_as_unresolved():
    original=outcome("cs_a",ValidationState.REJECTED,accepted=False)
    validation=replace(original.validation,state=ValidationState.UNAVAILABLE)
    result=assemble_outcomes((original.candidate,),(validation,))[0]
    assert result.unresolved_assignments==original.candidate.assignments
