import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def run_working_plan_lifecycle(scenario):
    core = ROOT / 'frontend/assets/js/core.js'
    app = ROOT / 'frontend/assets/js/app.js'
    javascript = f"""
const fs=require('fs'),vm=require('vm');
require({json.dumps(str(core))});
let requests=[];
globalThis.fetch=(path,options)=>path==='/api/local-session'
  ? Promise.resolve({{ok:true,json:async()=>({{session_token:'test-session'}})}})
  : new Promise((resolve,reject)=>requests.push({{path,options,resolve,reject}}));
let source=fs.readFileSync({json.dumps(str(app))},'utf8');
source=source.replace("if(root.document)document.addEventListener('DOMContentLoaded',S.boot);", "S.__workingPlanTest={{mutateWorking,loadWorkingPlan,workingEditor,setState(value){{state=value;S.AppState=value;}},getState(){{return state;}}}};");
vm.runInThisContext(source);
globalThis.document={{querySelector:()=>null,querySelectorAll:()=>[]}};
const base=SkladOzon.createInitialState();
const snapshot={{snapshot_id:'A',shippable_plan:{{shippable_plan_id:'SP-A'}}}};
SkladOzon.__workingPlanTest.setState({{...base,snapshot,workingPlan:{{...base.workingPlan,plan:{{working_plan_id:'WP-A',lines:[]}}}}}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{{{scenario}}})().catch(error=>{{console.error(error);process.exit(1);}});
"""
    return json.loads(subprocess.check_output(['node', '-e', javascript], text=True))


def test_working_plan_ui_uses_one_server_authoritative_state():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    core = (ROOT / 'frontend/assets/js/core.js').read_text()
    for text in ('/api/working-plan', 'Рекомендация', 'К поставке', 'data-working-step',
                 'data-working-input', 'data-working-reset', 'Сбросить все ручные изменения'):
        assert text in app
    assert 'workingLine(row)' in app
    assert "workingPlan:{plan:null,busy:false,mutationBusy:false,error:null" in core
    assert 'workingPlan.plan?.lines' in app
    assert 'localStorage' not in app[app.index('async function loadWorkingPlan'):app.index('function sellerWarehouses')]


def test_working_plan_failure_and_legacy_shipment_guard_are_explicit():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    core = (ROOT / 'frontend/assets/js/core.js').read_text()
    assert 'Рабочий план недоступен' in app
    assert 'Для создания поставки требуется рабочий план поставки' in core
    assert "workingPlan?.plan?.active_override_count>0" in core
    assert 'expectedRunId===state.workingPlan.runId' in app
    assert 'runId:state.shipmentView.runId+1,candidates:null,plan:null' in app


def test_second_mutation_waits_for_success_before_another_request_can_start():
    result = run_working_plan_lifecycle("""
const test=SkladOzon.__workingPlanTest;
const first=test.mutateWorking('/api/working-plan/override',{sku:'1',destination_cluster_id:'M',quantity:40},'1|||M');
const ignored=test.mutateWorking('/api/working-plan/override',{sku:'2',destination_cluster_id:'K',quantity:40},'2|||K');
await flush();
const whilePending={calls:requests.length,busy:test.getState().workingPlan.mutationBusy};
requests[0].resolve({ok:true,json:async()=>({working_plan:{working_plan_id:'WP-1',lines:[]}})});
await first;await ignored;
const afterSuccess=test.getState().workingPlan;
const second=test.mutateWorking('/api/working-plan/override',{sku:'2',destination_cluster_id:'K',quantity:40},'2|||K');
await flush();
console.log(JSON.stringify({whilePending,afterSuccess:{busy:afterSuccess.mutationBusy,savingKeys:afterSuccess.savingKeys},calls:requests.length}));
requests[1].resolve({ok:true,json:async()=>({working_plan:{working_plan_id:'WP-2',lines:[]}})});await second;
""")
    assert result == {
        'whilePending': {'calls': 1, 'busy': True},
        'afterSuccess': {'busy': False, 'savingKeys': []},
        'calls': 2,
    }


def test_failed_mutation_unlocks_and_can_be_retried():
    result = run_working_plan_lifecycle("""
const test=SkladOzon.__workingPlanTest;
const first=test.mutateWorking('/api/working-plan/override',{sku:'1',destination_cluster_id:'M',quantity:40},'1|||M');await flush();
requests[0].resolve({ok:false,json:async()=>({error:{message:'Конфликт'}})});await first;
const failed=test.getState().workingPlan;
const retry=test.mutateWorking('/api/working-plan/override',{sku:'1',destination_cluster_id:'M',quantity:40},'1|||M');await flush();
console.log(JSON.stringify({failed:{busy:failed.mutationBusy,savingKeys:failed.savingKeys,error:failed.error},calls:requests.length}));
requests[1].resolve({ok:true,json:async()=>({working_plan:{working_plan_id:'WP-2',lines:[]}})});await retry;
""")
    assert result == {'failed': {'busy': False, 'savingKeys': [], 'error': 'Конфликт'}, 'calls': 2}


def test_new_analysis_unlocks_and_late_mutation_cannot_replace_new_plan():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    commit = app[app.index('const immutable=S.deepFreezeSnapshot'):app.index('S.AppState=state;const inputsUnchanged')]
    assert 'mutationBusy:false' in commit
    assert 'savingKeys:[]' in commit
    result = run_working_plan_lifecycle("""
const test=SkladOzon.__workingPlanTest;
const pending=test.mutateWorking('/api/working-plan/override',{sku:'1',destination_cluster_id:'M',quantity:40},'1|||M');await flush();
let next=test.getState();
next={...next,snapshot:{snapshot_id:'B',shippable_plan:{shippable_plan_id:'SP-B'}},workingPlan:{...next.workingPlan,plan:null,busy:true,mutationBusy:false,savingKeys:[],error:null,runId:next.workingPlan.runId+1}};
test.setState(next);
const planB={working_plan_id:'WP-B',lines:[]};
test.setState({...test.getState(),workingPlan:{...test.getState().workingPlan,plan:planB,busy:false}});
requests[0].resolve({ok:true,json:async()=>({working_plan:{working_plan_id:'STALE',lines:[]}})});await pending;
const final=test.getState().workingPlan;
console.log(JSON.stringify({id:final.plan.working_plan_id,busy:final.mutationBusy,savingKeys:final.savingKeys,runId:final.runId}));
""")
    assert result == {'id': 'WP-B', 'busy': False, 'savingKeys': [], 'runId': 2}


def test_all_working_plan_controls_use_global_mutation_lock():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    assert 'busy=state.workingPlan.mutationBusy' in app
    assert "rowSaving=state.workingPlan.savingKeys.includes(key)" in app
    assert "line.is_overridden?`<button type=\"button\" class=\"working-reset\" data-working-reset ${busy?'disabled':''}" in app
    assert app.count("data-working-bulk=\"reset_to_system\" ${state.workingPlan.mutationBusy?'disabled':''}") == 2
    assert app.count("data-working-bulk=\"set_zero\" ${state.workingPlan.mutationBusy?'disabled':''}") == 2
    assert "<button data-working-global-reset ${state.workingPlan.mutationBusy?'disabled':''}" in app
