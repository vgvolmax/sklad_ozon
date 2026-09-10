import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    script=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"
    return json.loads(subprocess.check_output(['node','-e',script],text=True))
def test_connection_state_is_safe_and_status_only():
    state=node("SkladOzon.createInitialState()")
    assert state['ozonConnection']=={'configured':False,'locked':True,'maskedClientIdSuffix':None,'lastConnectionCheck':None,'busy':False,'error':None}
    serialized=json.dumps(state)
    for secret in ('apiKey','passwordConfirmation','decryptedCredentials'):
        assert secret not in serialized
def test_source_failure_preserves_evidence_and_mode():
    result=node("(()=>{let s=SkladOzon.createInitialState();s={...s,source:{...s.source,snapshotId:'os_old',source:{source_snapshot_id:'os_old'}}};s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceFailure(s,s.source.runId,'fail').source})()")
    assert result['mode']=='api' and result['snapshotId']=='os_old' and result['syncError']=='fail'
def test_stale_source_response_is_ignored():
    assert node("(()=>{let s=SkladOzon.beginSourceRun(SkladOzon.createInitialState());s=SkladOzon.beginSourceRun(s);return SkladOzon.applySourceSuccess(s,1,{source:{source_snapshot_id:'old'}})===s})()") is True
