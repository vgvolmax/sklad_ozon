import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def node(expression):
    script = f"require({json.dumps(str(ROOT / 'frontend/assets/js/core.js'))});console.log(JSON.stringify({expression}))"
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def test_shippable_classifier_and_cluster_evidence():
    assert node("[null,undefined,0,6,-1].map(SkladOzon.classifyShippableQty)") == ["unknown", "unknown", "zero", "positive", "unknown"]
    plan = "{lines:[{destination_cluster_id:'A',working_qty:6,status:'READY'},{destination_cluster_id:'B',working_qty:null,status:'BLOCKED',reason_codes:['MISSING_PACK_MULTIPLICITY']},{destination_cluster_id:'C',working_qty:0,status:'READY'},{destination_cluster_id:'D',working_qty:6,status:'READY'},{destination_cluster_id:'D',working_qty:null,status:'BLOCKED',reason_codes:['MISSING_UNIT_VOLUME']}]}"
    options = node(f"SkladOzon.buildShipmentClusterOptions({plan})")
    assert {x["clusterId"]: x["state"] for x in options} == {"A": "available", "B": "blocked", "C": "zero", "D": "blocked"}
    assert node(f"SkladOzon.reconcileShipmentClusters(SkladOzon.createInitialState().shipmentView,{plan}).selectedClusters") == ["A"]


def test_degraded_refresh_retains_healthy_source_then_healthy_replaces_it():
    result = node("""(()=>{let s=SkladOzon.createInitialState();const healthy=id=>({source:{source_snapshot_id:id,synced_at_utc:id,endpoint_evidence:[{endpoint:'fbo_stock',complete:true}]},capabilities:{need_fbo:{complete:true}}});const partial=id=>({source:{source_snapshot_id:id,synced_at_utc:id,endpoint_evidence:[{endpoint:'fbo_stock',complete:false}],diagnostics:['failed']},capabilities:{need_fbo:{complete:false}}});s=SkladOzon.beginSourceRun(s);s=SkladOzon.applySourceSuccess(s,s.source.runId,healthy('A'));s={...s,snapshot:{snapshot_id:'analysis'},staleSnapshot:false,shipmentView:{...s.shipmentView,dirty:false,runId:8,plan:{id:'plan'}}};s=SkladOzon.beginSourceRun(s);s=SkladOzon.applySourceSuccess(s,s.source.runId,partial('B'));const retained={active:s.source.snapshotId,degraded:s.source.lastDegradedRefresh.snapshotId,stale:s.staleSnapshot,run:s.shipmentView.runId,plan:s.shipmentView.plan.id};s=SkladOzon.beginSourceRun(s);s=SkladOzon.applySourceSuccess(s,s.source.runId,healthy('C'));return {retained,active:s.source.snapshotId,degraded:s.source.lastDegradedRefresh};})()""")
    assert result == {"retained": {"active": "A", "degraded": "B", "stale": False, "run": 8, "plan": "plan"}, "active": "C", "degraded": None}


def test_export_error_state_is_option_scoped_and_retry_clearable():
    result = node("(()=>{let s=SkladOzon.createInitialState();s=SkladOzon.setShipmentExportError(s,'A','failed');const before=s.shipmentView.exportErrors;s=SkladOzon.clearShipmentExportError(s,'A');return {before,after:s.shipmentView.exportErrors};})()")
    assert result == {"before": {"A": "failed"}, "after": {}}


def test_app_binds_analysis_inputs_once_and_renders_truthful_errors():
    app = (ROOT / "frontend/assets/js/app.js").read_text()
    assert "function bindAnalysisInvalidation" in app
    assert "updateStaleIndicators()" in app
    assert "role=\"alert\"" in app[app.index("function manifestMarkup"):app.index("function shipmentResults")]
    assert "Не указана кратность упаковки" in (ROOT / "frontend/assets/js/core.js").read_text()
