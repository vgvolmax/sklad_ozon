import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    script=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.check_output(['node','-e',script],text=True))
def test_cluster_initialization_and_scope_reconciliation():
    plan="{lines:[{destination_cluster_id:'A',shippable_qty:6},{destination_cluster_id:'B',shippable_qty:0}]}"
    assert node(f"SkladOzon.reconcileShipmentClusters(SkladOzon.createInitialState().shipmentView,{plan}).selectedClusters")==['A']
    result=node("SkladOzon.reconcileShipmentClusters({...SkladOzon.createInitialState().shipmentView,scopeTouched:true,selectedClusters:['A']},{lines:[{destination_cluster_id:'A',shippable_qty:1},{destination_cluster_id:'C',shippable_qty:1}]}).selectedClusters")
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

def test_readiness_and_plan_freshness_follow_source_provenance():
    expression="""(()=>{let s=SkladOzon.createInitialState(),snap={snapshot_id:'A1',source_mode:'api',source_snapshot_id:'S1',shippable_plan:{shippable_plan_id:'SP1'}};s={...s,snapshot:snap,source:{...s.source,snapshotId:'S1'},ozonConnection:{...s.ozonConnection,locked:false},shipmentView:{...s.shipmentView,plan:{analysis_snapshot_id:'A1',source_snapshot_id:'S1',shippable_plan_id:'SP1'},dirty:false}};return {ready:SkladOzon.shipmentReadiness(s),current:SkladOzon.isShipmentPlanCurrent(s),afterSync:SkladOzon.shipmentReadiness(SkladOzon.applySourceSuccess(SkladOzon.beginSourceRun(s),1,{source:{source_snapshot_id:'S2'}}))};})()"""
    result=node(expression)
    assert result['ready']['ready'] is True and result['current'] is True
    assert result['afterSync']['ready'] is False
def test_main_flow_is_candidates_then_plan_without_frontend_trimming_or_validate():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert app.index("fetch('/api/shipment/candidates'") < app.index("fetch('/api/shipment/plan'")
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
