import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]


def node(expression):
    script = f"require({json.dumps(str(ROOT / 'frontend/assets/js/core.js'))});console.log(JSON.stringify({expression}))"
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


CURRENT_PLAN = """(()=>{let s=SkladOzon.createInitialState();const snap={snapshot_id:'A1',source_mode:'api',source_snapshot_id:'S1',shippable_plan:{shippable_plan_id:'SP1'}};return {...s,snapshot:snap,source:{...s.source,mode:'api',snapshotId:'S1',source:{source_snapshot_id:'S1',credential_context_id:'C1'}},ozonConnection:{...s.ozonConnection,locked:false,credentialContextId:'C1'},shipmentView:{...s.shipmentView,dirty:false,planGeneration:4,plan:{shipment_plan_id:'SHIP1',analysis_snapshot_id:'A1',source_snapshot_id:'S1',shippable_plan_id:'SP1'}}};})()"""


def apply_failure(code="null", message="Ошибка"):
    return node(
        f"(()=>{{const s={CURRENT_PLAN};const next=SkladOzon.applyShipmentExportFailure(s,'SHIP1',4,'OPTION1',{{code:{code},message:{json.dumps(message)}}});return {{view:next.shipmentView,current:SkladOzon.isShipmentPlanCurrent(next),accepted:SkladOzon.canAcceptShipmentExportResponse(next,'SHIP1',4)}};}})()"
    )


def test_plan_not_found_invalidates_current_shipment_plan():
    result = apply_failure("'SHIPMENT_PLAN_NOT_FOUND'")
    assert result["view"]["plan"]["shipment_plan_id"] == "SHIP1"
    assert result["view"]["dirty"] is True
    assert result["view"]["planInvalidationCode"] == "SHIPMENT_PLAN_NOT_FOUND"
    assert result["view"]["exportErrors"] == {}
    assert result["current"] is False
    assert result["accepted"] is False


def test_transient_export_failure_remains_retryable():
    result = apply_failure(message="Соединение прервано.")
    assert result["view"]["dirty"] is False
    assert result["view"]["planInvalidationCode"] is None
    assert result["view"]["exportErrors"] == {"OPTION1": "Соединение прервано."}
    assert result["current"] is True
    assert result["accepted"] is True


@pytest.mark.parametrize(
    "code",
    [
        "SHIPMENT_OPTION_NOT_FOUND",
        "EXPORT_OPTION_NOT_EXPORTABLE",
        "EXPORT_ARTICLE_REQUIRED",
        "EXPORT_PACK_VIOLATION",
        "EXPORT_IDENTITY_CONFLICT",
        "EXPORT_EMPTY",
    ],
)
def test_structured_option_error_does_not_invalidate_plan(code):
    result = apply_failure(repr(code), "Ошибка варианта")
    assert result["view"]["dirty"] is False
    assert result["view"]["planInvalidationCode"] is None
    assert result["view"]["exportErrors"] == {"OPTION1": "Ошибка варианта"}
    assert result["current"] is True


def test_old_failure_cannot_invalidate_newer_plan():
    result = node(
        f"(()=>{{let s={CURRENT_PLAN};s={{...s,shipmentView:{{...s.shipmentView,planGeneration:5,plan:{{...s.shipmentView.plan,shipment_plan_id:'SHIP2'}}}}}};const next=SkladOzon.applyShipmentExportFailure(s,'SHIP1',4,'OPTION1',{{code:'SHIPMENT_PLAN_NOT_FOUND'}});return {{same:next===s,id:next.shipmentView.plan.shipment_plan_id,dirty:next.shipmentView.dirty,code:next.shipmentView.planInvalidationCode,current:SkladOzon.isShipmentPlanCurrent(next)}};}})()"
    )
    assert result == {"same": True, "id": "SHIP2", "dirty": False, "code": None, "current": True}


def test_export_response_acceptance_is_bound_to_current_plan():
    result = node(
        f"(()=>{{const current={CURRENT_PLAN};const stale=SkladOzon.invalidateShipmentPlan(current,'SHIPMENT_PLAN_NOT_FOUND');const newer={{...current,shipmentView:{{...current.shipmentView,planGeneration:5,plan:{{...current.shipmentView.plan,shipment_plan_id:'SHIP2'}}}}}};return {{stale:SkladOzon.canAcceptShipmentExportResponse(stale,'SHIP1',4),old:SkladOzon.canAcceptShipmentExportResponse(newer,'SHIP1',4),newer:SkladOzon.canAcceptShipmentExportResponse(newer,'SHIP2',5)}};}})()"
    )
    assert result == {"stale": False, "old": False, "newer": True}


def test_invalidation_preserves_in_flight_validation_identity():
    result = node(
        f"(()=>{{let s={CURRENT_PLAN};s={{...s,shipmentView:{{...s.shipmentView,runId:12,busyStage:'plan'}}}};return SkladOzon.applyShipmentExportFailure(s,'SHIP1',4,'OPTION1',{{code:'SHIPMENT_PLAN_NOT_FOUND'}}).shipmentView;}})()"
    )
    assert result["runId"] == 12
    assert result["busyStage"] == "plan"
    assert result["planGeneration"] == 4
    assert result["dirty"] is True
    assert result["planInvalidationCode"] == "SHIPMENT_PLAN_NOT_FOUND"


def test_stale_message_is_causal():
    result = node(
        "(()=>{const s=SkladOzon.createInitialState();return {terminal:SkladOzon.shipmentPlanStaleMessage({...s,shipmentView:{...s.shipmentView,planInvalidationCode:'SHIPMENT_PLAN_NOT_FOUND'}}),generic:SkladOzon.shipmentPlanStaleMessage({...s,shipmentView:{...s.shipmentView,dirty:true}})};})()"
    )
    assert result["terminal"] == "Результат проверки больше недоступен. Проверьте варианты в Ozon заново."
    assert result["generic"] == "Параметры или данные изменились. Проверьте варианты в Ozon заново."


def test_app_wires_structured_failure_and_successful_recovery():
    app = (ROOT / "frontend/assets/js/app.js").read_text()
    handler = app[app.index("async function exportShipmentOption") : app.index("function scenarioEquals")]
    assert "data?.error?.code" in handler
    assert "SHIPMENT_PLAN_NOT_FOUND" in handler
    assert "S.applyShipmentExportFailure" in handler
    assert "S.canAcceptShipmentExportResponse" in handler
    assert "const planGeneration=state.shipmentView.planGeneration" in handler
    assert "plan_generation" not in handler
    assert "response.status===404" not in handler and "response.status === 404" not in handler
    run = app[app.index("async function runShipment") : app.index("async function exportShipmentOption")]
    for contract in ("plan:data.shipment_plan", "planGeneration:state.shipmentView.planGeneration+1", "dirty:false", "planInvalidationCode:null", "exportErrors:{}"):
        assert contract in run
    assert app.count("planGeneration:state.shipmentView.planGeneration+1") == 1


def test_old_terminal_failure_cannot_invalidate_same_id_new_generation():
    result = node(
        f"(()=>{{let s={CURRENT_PLAN};s={{...s,shipmentView:{{...s.shipmentView,planGeneration:5}}}};const next=SkladOzon.applyShipmentExportFailure(s,'SHIP1',4,'OPTION1',{{code:'SHIPMENT_PLAN_NOT_FOUND'}});return {{same:next===s,id:next.shipmentView.plan.shipment_plan_id,generation:next.shipmentView.planGeneration,dirty:next.shipmentView.dirty,code:next.shipmentView.planInvalidationCode,current:SkladOzon.isShipmentPlanCurrent(next)}};}})()"
    )
    assert result == {"same": True, "id": "SHIP1", "generation": 5, "dirty": False, "code": None, "current": True}


def test_old_success_response_rejected_for_same_plan_id_new_generation():
    result = node(
        f"(()=>{{let s={CURRENT_PLAN};s={{...s,shipmentView:{{...s.shipmentView,planGeneration:5}}}};return {{old:SkladOzon.canAcceptShipmentExportResponse(s,'SHIP1',4),current:SkladOzon.canAcceptShipmentExportResponse(s,'SHIP1',5)}};}})()"
    )
    assert result == {"old": False, "current": True}


def test_plan_generation_starts_at_zero_and_survives_connection_reset():
    result = node(
        "(()=>{let s=SkladOzon.createInitialState();const initial=s.shipmentView.planGeneration;s={...s,snapshot:{source_mode:'api'},ozonConnection:{...s.ozonConnection,credentialContextId:'old'},shipmentView:{...s.shipmentView,planGeneration:8,plan:{shipment_plan_id:'SHIP1'}}};s=SkladOzon.applyConnectionStatus(s,{credential_context_id:'new'});return {initial,plan:s.shipmentView.plan,generation:s.shipmentView.planGeneration};})()"
    )
    assert result == {"initial": 0, "plan": None, "generation": 8}
