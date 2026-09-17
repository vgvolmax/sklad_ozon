import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    script=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.check_output(['node','-e',script],text=True))
def test_connection_state_is_safe_and_status_only():
    state=node("SkladOzon.createInitialState()")
    assert state['ozonConnection']=={'configured':False,'locked':True,'maskedClientIdSuffix':None,'lastConnectionCheck':None,'credentialContextId':None,'busy':False,'error':None,'diagnostic':None,'diagnosticForSync':False,'transportComparison':None,'transportComparisonBusy':False,'transportComparisonError':None}
    serialized=json.dumps(state)
    for secret in ('apiKey','passwordConfirmation','decryptedCredentials'):
        assert secret not in serialized
def test_source_failure_preserves_evidence_and_mode():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,source:{...s.source,snapshotId:'os_old',source:{source_snapshot_id:'os_old'}}};s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceFailure(s,s.source.runId,'fail').source})()")
    assert result['mode']=='api' and result['snapshotId']=='os_old' and result['syncError']=='fail'
def test_stale_source_response_is_ignored():
    assert node("(()=>{let s=SkladOzon.beginSourceRun(SkladOzon.createInitialState());s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceSuccess(s,1,{source:{source_snapshot_id:'old'}})===s})()") is True


def test_preflight_state_keeps_connection_valid_separate_from_sync_readiness():
    result=node("(()=>{let s=SkladOzon.beginOzonDiagnostic(SkladOzon.createInitialState(),true);return SkladOzon.applyOzonDiagnostic(s,{status:'failed',connection_valid:true,sync_ready:false,checks:[{name:'roles',status:'failed',code:'OZON_PERMISSION_MISSING'}]}).ozonConnection})()")
    assert result['busy'] is False and result['diagnosticForSync'] is True
    assert result['diagnostic']['connection_valid'] is True
    assert result['diagnostic']['sync_ready'] is False


def test_sync_uses_diagnostic_endpoint_before_stream_and_fail_fast_copy_is_present():
    source=(ROOT/'frontend/assets/js/app.js').read_text()
    diagnose=source.index("apiFetch('/api/ozon/connection/diagnose'")
    stream=source.index("apiFetch('/api/ozon/sync/stream'")
    assert diagnose > stream  # functions are separate; the diagnostic calls streamSource conditionally
    assert "if(forSync&&data.sync_ready===true)await streamSource()" in source
    assert "Синхронизация данных не запускалась." in source
    assert "Seller API" in source and "timeout" not in source  # reason comes from safe backend wire


def test_source_progress_is_stateful_and_stale_events_are_ignored():
    result=node("(()=>{let s=SkladOzon.beginSourceRun(SkladOzon.createInitialState()),id=s.source.runId;s=SkladOzon.applySourceProgress(s,id,{stage:'inbound',stage_index:8,stage_count:9,label:'Поставки в пути',detail:'Получение состава поставок',current:12,total:19,unit:'bundles'});const same=SkladOzon.applySourceProgress(s,id-1,{stage:'old',stage_index:1,stage_count:9,label:'old'});return {progress:s.source.syncProgress,staleIgnored:same===s,busy:s.source.syncBusy};})()")
    assert result['busy'] is True and result['staleIgnored'] is True
    assert result['progress']['stage']=='inbound'
    assert result['progress']['current']==12 and result['progress']['total']==19


def test_transport_diagnostics_are_allowlisted_for_presentation():
    rows=node("SkladOzon.buildSourceStatusRows({capabilities:{shipment_compatibility:{complete:false}},endpointStates:[{name:'placement_zones',complete:false,record_count:0,diagnostics:[],api_error:{code:'OZON_UNAVAILABLE',endpoint:'/v1/product/placement-zone/info',transport_kind:'timeout',attempts:3,elapsed_ms:46100,raw_exception:'secret'}}]})")
    technical=next(row for row in rows if row['key']=='shipment_compatibility')['endpoints'][0]['technical']
    assert technical['transportKind']=='timeout' and technical['attempts']==3
    assert technical['elapsedMs']==46100 and 'raw_exception' not in technical


def test_transport_comparison_state_is_bounded_and_replaces_previous_result():
    result=node("(()=>{let s=SkladOzon.createInitialState();s=SkladOzon.beginTransportComparison(s);s=SkladOzon.applyTransportComparison(s,{endpoint:'/v1/seller/info',outcome:'all_reached_http'});return s.ozonConnection})()")
    assert result['transportComparisonBusy'] is False
    assert result['transportComparison']['outcome']=='all_reached_http'
    assert result['transportComparisonError'] is None


def test_transport_comparison_ui_is_explicit_and_calls_dedicated_endpoint():
    source=(ROOT/'frontend/assets/js/app.js').read_text()
    assert "Сравнить HTTP-транспорт" in source
    assert "Тот же endpoint:" in source
    assert "urllib / production" in source
    assert "httpx sync" in source and "httpx async / рабочий профиль" in source
    assert "Среда" in source and "DNS" in source
    assert "HTTP достигнут" in source
    assert "только httpx async достиг HTTP" in source and "ни один транспорт не достиг HTTP" in source
    assert "apiFetch('/api/ozon/connection/transport-compare',{method:'POST'})" in source


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
