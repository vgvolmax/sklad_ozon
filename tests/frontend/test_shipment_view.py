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
    assert node("SkladOzon.sellerWarehouseMode(['sc_crossdock'],[{warehouse_id:1,active:true}]).kind")=='fixed'
    assert node("SkladOzon.sellerWarehouseMode(['pvz_crossdock'],[{warehouse_id:1,active:true},{warehouse_id:2,active:true}]).kind")=='select'
def test_statuses_have_distinct_causal_copy():
    codes=['ACCEPTED','PARTIAL','REJECTED','NO_TIMESLOT','RATE_LIMITED','UNAVAILABLE','OUTCOME_UNKNOWN']
    labels=[node(f"SkladOzon.validationStatus('{x}')[1]") for x in codes]
    assert len(set(labels))==len(codes)
def test_handoff_clear_invalidates_pending_and_keeps_no_resolved_preference():
    result=node("(()=>{let s=SkladOzon.beginHandoffRun(SkladOzon.createInitialState());const id=s.shipmentView.handoff.runId;s=SkladOzon.clearHandoff(s);const after=SkladOzon.applyHandoffResult(s,id,[{warehouse_id:1}]);return {ids:after.shipmentView.selectedHandoffPointIds,items:after.shipmentView.handoff.items,run:after.shipmentView.handoff.runId}})()")
    assert result['ids']==[] and result['items']==[] and result['run']==2
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
