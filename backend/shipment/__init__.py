"""Pure local shipment candidate construction."""

from .candidates import build_candidate_result, build_candidate_shipments, select_shipment_scope
from .contracts import (
    CandidateAssignment,
    CandidateBuildResult,
    CandidateShipment,
    MethodRule,
    ShipmentDiagnostic,
    ShipmentMethod,
    ShipmentScenario,
)

__all__ = (
    "CandidateAssignment", "CandidateBuildResult", "CandidateShipment", "MethodRule",
    "ShipmentDiagnostic", "ShipmentMethod", "ShipmentScenario", "build_candidate_result",
    "build_candidate_shipments", "select_shipment_scope",
)
