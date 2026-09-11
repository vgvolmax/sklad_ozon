"""Shared, transport-free preparation for live shipment validation."""
from dataclasses import dataclass

from backend.domain.contracts import SourceMode
from .candidates import DEFAULT_MAX_CANDIDATES, build_candidate_result
from .wire import parse_shipment_scenario


class ShipmentPreparationError(ValueError):
    def __init__(self, code, message, field=None, http_status=409):
        self.code=code; self.message=message; self.field=field; self.http_status=http_status
        super().__init__(code)


CREDENTIAL_CONTEXT_MESSAGE = (
    'Подключение Ozon изменилось. Обновите данные Ozon и пересчитайте план.'
)


def require_source_credential_context(source, expected_context_id, *, field='source_snapshot_id'):
    """Validate API source provenance without requiring plaintext credentials."""
    if (not expected_context_id or
            source.credential_context_id != expected_context_id):
        raise ShipmentPreparationError(
            'OZON_CREDENTIAL_CONTEXT_CHANGED', CREDENTIAL_CONTEXT_MESSAGE,
            field, 409)
    return source


@dataclass(frozen=True, slots=True)
class PreparedShipmentValidation:
    snapshot: object
    shippable_plan: object
    source_snapshot: object
    scenario: object
    candidates: tuple
    diagnostics: tuple


def prepare_shipment_validation(*, analysis_store, source_store, handoff_store,
                                analysis_id, plan_id, scenario_payload, candidate_ids,
                                expected_credential_context_id=None):
    snapshot=analysis_store.get(analysis_id)
    if snapshot is None:
        raise ShipmentPreparationError('ANALYSIS_SNAPSHOT_NOT_FOUND','Analysis snapshot was not found.','analysis_snapshot_id',404)
    plan=snapshot.shippable_plan
    if plan is None or plan.shippable_plan_id!=plan_id or plan.analysis_snapshot_id!=analysis_id:
        raise ShipmentPreparationError('SHIPPABLE_PLAN_IDENTITY_MISMATCH','Shippable Plan does not belong to this analysis.','shippable_plan_id')
    if snapshot.source_mode is not SourceMode.API or plan.source_mode is not SourceMode.API:
        raise ShipmentPreparationError('LIVE_VALIDATION_REQUIRES_API_SOURCE','Live validation requires an API-backed analysis.','analysis_snapshot_id')
    source_id=snapshot.source_snapshot_id
    if not source_id or source_id!=plan.source_snapshot_id:
        raise ShipmentPreparationError('SOURCE_PROVENANCE_MISMATCH','Analysis and plan provenance do not match.','analysis_snapshot_id')
    source=source_store.get(source_id)
    if source is None:
        raise ShipmentPreparationError('OZON_SOURCE_SNAPSHOT_NOT_FOUND','The analysis source snapshot is no longer available.','analysis_snapshot_id')
    require_source_credential_context(
        source, expected_credential_context_id, field='analysis_snapshot_id')
    if snapshot.analysis_as_of!=source.source_as_of or plan.analysis_as_of!=source.source_as_of:
        raise ShipmentPreparationError('SOURCE_PROVENANCE_MISMATCH','Analysis and source provenance do not match.','analysis_snapshot_id')
    try: scenario=parse_shipment_scenario(scenario_payload)
    except ValueError as exc:
        raise ShipmentPreparationError('INVALID_SHIPMENT_SCENARIO','Shipment scenario is invalid.','scenario',400) from exc
    if any(method.value.endswith('crossdock') for method in scenario.allowed_methods):
        active={row.seller_warehouse_id for row in source.seller_warehouses if row.is_active}
        if scenario.seller_warehouse_id is not None and scenario.seller_warehouse_id not in active:
            raise ShipmentPreparationError('SELLER_WAREHOUSE_INVALID','Seller warehouse is no longer active.','scenario.seller_warehouse_id')
        for point_id in scenario.selected_handoff_point_ids:
            point=handoff_store.get(point_id)
            if point is None or not point.warehouse_type:
                raise ShipmentPreparationError('HANDOFF_POINT_UNRESOLVED','Select the handoff point again.','scenario.selected_handoff_point_ids')
    result=build_candidate_result(plan=plan,scenario=scenario,
        seller_warehouses=source.seller_warehouses,handoff_store=handoff_store,
        max_candidates=DEFAULT_MAX_CANDIDATES)
    wanted=set(candidate_ids)
    if not wanted.issubset({candidate.candidate_id for candidate in result.candidates}):
        raise ShipmentPreparationError('CANDIDATE_PROVENANCE_MISMATCH','Candidate does not belong to the stored plan and scenario.','candidate_ids')
    selected=tuple(candidate for candidate in result.candidates if candidate.candidate_id in wanted)
    return PreparedShipmentValidation(snapshot,plan,source,scenario,selected,result.diagnostics)
