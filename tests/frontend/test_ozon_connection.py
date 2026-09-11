import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    script=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.check_output(['node','-e',script],text=True))
def test_connection_state_is_safe_and_status_only():
    state=node("SkladOzon.createInitialState()")
    assert state['ozonConnection']=={'configured':False,'locked':True,'maskedClientIdSuffix':None,'lastConnectionCheck':None,'credentialContextId':None,'busy':False,'error':None}
    serialized=json.dumps(state)
    for secret in ('apiKey','passwordConfirmation','decryptedCredentials'):
        assert secret not in serialized
def test_source_failure_preserves_evidence_and_mode():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,source:{...s.source,snapshotId:'os_old',source:{source_snapshot_id:'os_old'}}};s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceFailure(s,s.source.runId,'fail').source})()")
    assert result['mode']=='api' and result['snapshotId']=='os_old' and result['syncError']=='fail'
def test_stale_source_response_is_ignored():
    assert node("(()=>{let s=SkladOzon.beginSourceRun(SkladOzon.createInitialState());s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceSuccess(s,1,{source:{source_snapshot_id:'old'}})===s})()") is True


def test_context_switch_drops_api_snapshot_source_and_shipment_state():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,analysisRunId:3,snapshot:{snapshot_id:'A',source_mode:'api'},source:{...s.source,snapshotId:'S',source:{source_snapshot_id:'S'},runId:4},ozonConnection:{...s.ozonConnection,credentialContextId:'ctx-a'},shipmentView:{...s.shipmentView,candidates:[1],plan:{shipment_plan_id:'P'},resolvedHandoffPoints:[{warehouse_id:2}],runId:5,handoff:{...s.shipmentView.handoff,items:[{warehouse_id:2}],runId:6}}};return SkladOzon.applyConnectionStatus(s,{configured:true,locked:false,credential_context_id:'ctx-b'});})()")
    assert result['snapshot'] is None
    assert result['source']['snapshotId'] is None and result['source']['source'] is None
    assert result['shipmentView']['plan'] is None and result['shipmentView']['handoff']['items'] == []
    assert result['analysisRunId'] == 4 and result['source']['runId'] == 5


def test_same_context_lock_preserves_api_state_and_files_survives_switch():
    same=node("(()=>{let s=SkladOzon.createInitialState();s={...s,snapshot:{source_mode:'api'},source:{...s.source,snapshotId:'S'},ozonConnection:{...s.ozonConnection,credentialContextId:'ctx-a'},shipmentView:{...s.shipmentView,plan:{id:'P'}}};return SkladOzon.applyConnectionStatus(s,{configured:true,locked:true,credential_context_id:'ctx-a'});})()")
    assert same['snapshot']['source_mode']=='api' and same['source']['snapshotId']=='S'
    assert same['shipmentView']['plan']=={'id':'P'}

    files=node("(()=>{let s=SkladOzon.createInitialState();s={...s,snapshot:{source_mode:'files',snapshot_id:'F'},source:{...s.source,snapshotId:'S'},ozonConnection:{...s.ozonConnection,credentialContextId:'ctx-a'},shipmentView:{...s.shipmentView,plan:{id:'P'}}};return SkladOzon.applyConnectionStatus(s,{configured:true,locked:false,credential_context_id:'ctx-b'});})()")
    assert files['snapshot']=={'source_mode':'files','snapshot_id':'F'}
    assert files['source']['snapshotId'] is None and files['shipmentView']['plan'] is None
