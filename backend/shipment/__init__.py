"""Pure local shipment candidate construction."""

from .candidates import (DEFAULT_MAX_CANDIDATES, build_candidate_result,
                         build_candidate_shipments, select_shipment_scope)
from .contracts import (
    CandidateAssignment,
    CandidateBuildResult,
    CandidateShipment,
    MethodRule,
    ShipmentDiagnostic,
    ShipmentOptionOutcome, RankedShipmentOption, ShipmentPlan,
    ShipmentMethod,
    ShipmentScenario,
    ShipmentInput, ShipmentInputLine,
)
from .working_input import build_shipment_input, WorkingPlanIdentityError

__all__ = (
    "CandidateAssignment", "CandidateBuildResult", "CandidateShipment", "MethodRule",
    "ShipmentDiagnostic", "ShipmentMethod", "ShipmentScenario", "build_candidate_result",
    "ShipmentOptionOutcome", "RankedShipmentOption", "ShipmentPlan",
    "DEFAULT_MAX_CANDIDATES", "build_candidate_shipments", "select_shipment_scope",
    "ShipmentInput", "ShipmentInputLine", "build_shipment_input", "WorkingPlanIdentityError",
)
