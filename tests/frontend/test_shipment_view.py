import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    script=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.check_output(['node','-e',script],text=True))
def test_cluster_initialization_and_scope_reconciliation():
    plan="{lines:[{destination_cluster_id:'A',working_qty:6,status:'READY'},{destination_cluster_id:'B',working_qty:0,status:'READY'}]}"
    assert node(f"SkladOzon.reconcileShipmentClusters(SkladOzon.createInitialState().shipmentView,{plan}).selectedClusters")==['A']
    result=node("SkladOzon.reconcileShipmentClusters({...SkladOzon.createInitialState().shipmentView,scopeTouched:true,selectedClusters:['A']},{lines:[{destination_cluster_id:'A',working_qty:1,status:'READY'},{destination_cluster_id:'C',working_qty:1,status:'READY'}]}).selectedClusters")
    assert result==['A']
def test_seller_warehouse_zero_one_many_and_direct():
    assert node("SkladOzon.sellerWarehouseMode(['direct'],[]).kind")=='not-required'
    assert node("SkladOzon.sellerWarehouseMode(['sc_crossdock'],[]).kind")=='blocked'
    wire="{seller_warehouse_id:1,name:'Москва',address:'ул. Тестовая, 1',is_active:true,is_pickup:false}"
    assert node(f"SkladOzon.sellerWarehouseMode(['sc_crossdock'],[{wire}]).kind")=='fixed'
    assert node(f"SkladOzon.sellerWarehouseMode(['pvz_crossdock'],[{wire},{{seller_warehouse_id:2,name:'Тверь',address:'ул. 2',is_active:true,is_pickup:false}}]).kind")=='select'
    assert node("SkladOzon.sellerWarehouseMode(['sc_crossdock'],[{seller_warehouse_id:3}]).kind")=='blocked'
def test_statuses_have_distinct_causal_copy():
    codes=['accepted','partial','rejected','no_timeslot','rate_limited','unavailable','outcome_unknown']
    labels=[node(f"SkladOzon.validationStatus('{x}')[1]") for x in codes]
    assert len(set(labels))==len(codes)
def test_handoff_clear_invalidates_pending_and_keeps_no_resolved_preference():
    result=node("(()=>{let s=SkladOzon.beginHandoffRun(SkladOzon.createInitialState());const id=s.shipmentView.handoff.runId;s=SkladOzon.clearHandoff(s);const after=SkladOzon.applyHandoffResult(s,id,[{warehouse_id:1}]);return {ids:after.shipmentView.selectedHandoffPointIds,items:after.shipmentView.handoff.items,run:after.shipmentView.handoff.runId}})()")
    assert result['ids']==[] and result['items']==[] and result['run']==2

def test_shipment_edit_invalidates_pending_run_and_preserves_old_plan():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,shipmentView:{...s.shipmentView,runId:5,busyStage:'plan',dirty:false,plan:{shipment_plan_id:'old'}}};s=SkladOzon.editShipment(s,{dateFrom:'2026-09-12'});return s.shipmentView})()")
    assert result['runId']==6 and result['busyStage'] is None and result['dirty'] is True
    assert result['plan']['shipment_plan_id']=='old'

def test_source_mode_change_invalidates_pending_shipment_run():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,snapshot:{snapshot_id:'A1'},shipmentView:{...s.shipmentView,runId:5,busyStage:'plan',dirty:false,plan:{shipment_plan_id:'old'}}};return SkladOzon.selectSourceMode(s,'files').shipmentView})()")
    assert result['runId']==6 and result['busyStage'] is None and result['dirty'] is True
    assert result['plan']['shipment_plan_id']=='old'

def test_readiness_and_plan_freshness_follow_source_provenance():
    expression="""(()=>{let s=SkladOzon.createInitialState(),snap={snapshot_id:'A1',source_mode:'api',source_snapshot_id:'S1',shippable_plan:{shippable_plan_id:'SP1'}};s={...s,snapshot:snap,source:{...s.source,snapshotId:'S1',source:{source_snapshot_id:'S1',credential_context_id:'C1'}},workingPlan:{...s.workingPlan,plan:{working_plan_id:'WP1',analysis_snapshot_id:'A1',shippable_plan_id:'SP1'}},ozonConnection:{...s.ozonConnection,locked:false,credentialContextId:'C1'},shipmentView:{...s.shipmentView,plan:{analysis_snapshot_id:'A1',source_snapshot_id:'S1',shippable_plan_id:'SP1',working_plan_id:'WP1'},dirty:false}};return {ready:SkladOzon.shipmentReadiness(s),current:SkladOzon.isShipmentPlanCurrent(s),afterSync:SkladOzon.shipmentReadiness(SkladOzon.applySourceSuccess(SkladOzon.beginSourceRun(s),1,{source:{source_snapshot_id:'S2',credential_context_id:'C1'}}))};})()"""
    result=node(expression)
    assert result['ready']['ready'] is True and result['current'] is True
    assert result['afterSync']['ready'] is False


def test_working_plan_saving_blocks_shipment_until_mutation_finishes():
    expression = """(()=>{let s=SkladOzon.createInitialState(),snap={snapshot_id:'A1',source_mode:'api',source_snapshot_id:'S1',shippable_plan:{shippable_plan_id:'SP1'}};s={...s,snapshot:snap,source:{...s.source,snapshotId:'S1',source:{source_snapshot_id:'S1',credential_context_id:'C1'}},workingPlan:{...s.workingPlan,mutationBusy:true,plan:{working_plan_id:'WP1',analysis_snapshot_id:'A1',shippable_plan_id:'SP1'}},ozonConnection:{...s.ozonConnection,locked:false,credentialContextId:'C1'}};const saving=SkladOzon.shipmentReadiness(s);return {saving,afterSuccess:SkladOzon.shipmentReadiness({...s,workingPlan:{...s.workingPlan,mutationBusy:false}}),afterFailure:SkladOzon.shipmentReadiness({...s,workingPlan:{...s.workingPlan,mutationBusy:false,error:'Не удалось сохранить'}})};})()"""
    result = node(expression)
    assert result["saving"] == {
        "ready": False,
        "code": "WORKING_PLAN_SAVING",
        "message": "Сохраняем изменения рабочего плана.",
    }
    assert result["afterSuccess"] == {"ready": True, "code": "READY", "message": ""}
    assert result["afterFailure"] == {"ready": True, "code": "READY", "message": ""}


def test_run_shipment_rechecks_readiness_before_identity_or_api_request():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    run = app[app.index('async function runShipment'):app.index('async function exportShipmentOption')]
    readiness = run.index('S.shipmentReadiness(state)')
    early_return = run.index('return;', readiness)
    identity = run.index('identity=')
    request = run.index("apiFetch('/api/shipment/candidates'")
    assert readiness < early_return < identity < request
    assert 'error:readiness.message' in run

    script = f"""
const fs=require('fs'),vm=require('vm');
require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});
const requests=[];
globalThis.fetch=(path,options)=>{{requests.push({{path,options}});return Promise.reject(new Error('unexpected request'));}};
globalThis.document={{querySelector:()=>null,querySelectorAll:()=>[]}};
let source=fs.readFileSync({json.dumps(str(ROOT/'frontend/assets/js/app.js'))},'utf8');
source=source.replace("if(root.document)document.addEventListener('DOMContentLoaded',S.boot);", "S.__shipmentTest={{runShipment,setState(value){{state=value;S.AppState=value;}},getState(){{return state;}}}};");
vm.runInThisContext(source);
let state=SkladOzon.createInitialState();
const snapshot={{snapshot_id:'A1',source_mode:'api',source_snapshot_id:'S1',shippable_plan:{{shippable_plan_id:'SP1'}}}};
state={{...state,snapshot,source:{{...state.source,snapshotId:'S1',source:{{source_snapshot_id:'S1',credential_context_id:'C1'}}}},ozonConnection:{{...state.ozonConnection,locked:false,credentialContextId:'C1'}},workingPlan:{{...state.workingPlan,mutationBusy:true,plan:{{working_plan_id:'WP1',analysis_snapshot_id:'A1',shippable_plan_id:'SP1'}}}}}};
SkladOzon.__shipmentTest.setState(state);
SkladOzon.__shipmentTest.runShipment(true,{{kind:'not-required'}}).then(()=>console.log(JSON.stringify({{requests:requests.length,error:SkladOzon.__shipmentTest.getState().shipmentView.error}})));
"""
    result = json.loads(subprocess.check_output(['node', '-e', script], text=True))
    assert result == {"requests": 0, "error": "Сохраняем изменения рабочего плана."}


def test_new_analysis_resets_scope_before_working_plan_reconciliation():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    analysis_start = app.index('async function runAnalysis')
    analysis = app[analysis_start:app.index('async function ', analysis_start + 1)]
    assert 'shipmentView:{...state.shipmentView,selectedClusters:[],scopeTouched:false' in analysis

    reconciled = node("SkladOzon.reconcileShipmentClusters({...SkladOzon.createInitialState().shipmentView,scopeTouched:false,selectedClusters:[]},{lines:[{destination_cluster_id:'A',working_qty:1,status:'READY'},{destination_cluster_id:'C',working_qty:2,status:'ATTENTION'}]}).selectedClusters")
    assert reconciled == ['A', 'C']
def test_main_flow_is_candidates_then_plan_without_frontend_trimming_or_validate():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert app.index("apiFetch('/api/shipment/candidates'") < app.index("apiFetch('/api/shipment/plan'")
    assert '/api/shipment/validate' not in app
    assert '.slice(0,6)' not in app and '.slice(0, 6)' not in app
    assert 'candidateIds=candidates.map' in app
def test_native_controls_disclosure_and_no_success_claims():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert 'type="date" id="shipment-date-from"' in app
    assert '<select id="seller-warehouse"' in (ROOT/'frontend/assets/js/components.js').read_text()
    assert 'Реальные заявки на поставку не создаются.' in app
    for forbidden in ('Поставка создана','Окно забронировано','Заявка подтверждена'):
        assert forbidden not in app

def test_handoff_search_and_keyboard_navigation_use_local_region_only():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert 'id="handoff-selector-region"' in app
    search=app[app.index('async function searchHandoff'):app.index('async function runShipment')]
    keyboard=app[app.index('function bindHandoff'):app.index('function queueHandoffSearch')]
    assert 'renderHandoffSelector()' in search
    assert 'renderPlan()' not in search
    assert 'updateHandoffActiveState(root)' in keyboard
    assert 'renderPlan()' not in keyboard
    assert "input.addEventListener('compositionstart'" in keyboard
    assert "input.addEventListener('compositionend'" in keyboard

def test_manifest_renders_complete_operational_evidence():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    manifest=app[app.index('function manifestMarkup'):app.index('function shipmentResults')]
    for label in ('Кластеры назначения','Зоны размещения','Время проверки',
                  'Период отгрузки','Склад отправления','Точка отгрузки',
                  'Доступные окна','Отклонённые позиции'):
        assert label in manifest
    for evidence in ('candidate.cluster_ids','placement_zones','checked_at_utc',
                     'warehouse_evidence','travel_time_days','x.message','x.code'):
        assert evidence in manifest
    assert 'zones.size>1' in manifest
    assert 'разделите грузоместа по зонам размещения' in manifest
