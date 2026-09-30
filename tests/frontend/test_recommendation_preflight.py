import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def run(scenario):
    javascript = """
const fs=require('fs'),vm=require('vm');
require(CORE);
require(COMPONENTS);
globalThis.FormData=class{constructor(){this.entries={};}append(key,value){this.entries[key]=value;}};
const requests=[];
globalThis.fetch=(path,options)=>path==='/api/local-session'
 ? Promise.resolve({ok:true,json:async()=>({session_token:'session'})})
 : new Promise(resolve=>requests.push({path,options,resolve}));
const source=fs.readFileSync(APP,'utf8').replace("if(root.document)document.addEventListener('DOMContentLoaded',S.boot);",
 "S.__preflightTest={preflightRecommendations,ensureRecommendationValidation,bindAnalysisInvalidation,updateAnalysisFormState,set(value){state=value;S.AppState=value;},get(){return state;}};");
vm.runInThisContext(source);
const S=SkladOzon,t=S.__preflightTest;
const required={hidden:true,textContent:''},submit={disabled:false};
const file={name:'report.xlsx'},status={innerHTML:'',textContent:''};
const input={name:'recommendation_file',type:'file',files:[file],nextElementSibling:status,
 addEventListener(type,fn){this[type]=fn;}};
const elements=[input];elements.recommendation_file=input;
const form={elements,dataset:{},closest:()=>document,
 querySelector:selector=>selector==='#analysis-submit'?submit:selector==='#analysis-source-required'?required:null};
globalThis.document={querySelector:selector=>selector==='#analysis-form'?form:null,querySelectorAll:()=>[]};
let base=S.createInitialState();
base={...base,unitkaValidation:{...base.unitkaValidation,valid:true},source:{...base.source,snapshotId:'source-a'}};
t.set(base);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const reply=(index,body)=>requests[index].resolve({ok:true,json:async()=>body});
(async()=>{SCENARIO})().catch(error=>{console.error(error);process.exit(1);});
""".replace('CORE', json.dumps(str(ROOT/'frontend/assets/js/core.js'))).replace(
        'COMPONENTS', json.dumps(str(ROOT/'frontend/assets/js/components.js'))).replace(
        'APP', json.dumps(str(ROOT/'frontend/assets/js/app.js'))).replace('SCENARIO', scenario)
    return json.loads(subprocess.check_output(['node', '-e', javascript], text=True))


def test_selecting_file_starts_validation_and_noncomparable_report_allows_own_plan():
    result = run("""
t.bindAnalysisInvalidation(form);input.change();await flush();
const busy=submit.disabled;
const request=requests[0];
reply(0,{valid:true,usable_for_comparison:false,message:'Горизонт файла отличается',record_count:3,
 excluded_record_count:1,report_meta:{recommendation_horizon_days:56},diagnostics:[]});await flush();
console.log(JSON.stringify({path:request.path,source:request.options.body.entries.source_snapshot_id,
 horizon:request.options.body.entries.horizon_days,busy,disabled:submit.disabled,
 warning:status.innerHTML.includes('Горизонт файла отличается'),valid:t.get().recommendationValidation.valid}));
""")
    assert result == {'path':'/api/import/recommendations/validate','source':'source-a','horizon':'56',
                      'busy':True,'disabled':False,'warning':True,'valid':True}


def test_invalid_selected_file_blocks_calculation_and_removal_restores_it():
    result = run("""
t.preflightRecommendations(file,form);await flush();
reply(0,{valid:false,usable_for_comparison:false,message:'Неверный формат',diagnostics:[]});await flush();
const blocked=submit.disabled,invalid=t.get().recommendationValidation.status;
input.files=[];await t.preflightRecommendations(null,form);
console.log(JSON.stringify({blocked,invalid,disabled:submit.disabled,status:t.get().recommendationValidation.status}));
""")
    assert result == {'blocked':True,'invalid':'invalid','disabled':False,'status':'empty'}


def test_old_file_and_old_source_responses_never_authorize_calculation():
    result = run("""
t.preflightRecommendations(file,form);await flush();
const next={name:'new.xlsx'};input.files=[next];t.preflightRecommendations(next,form);await flush();
reply(0,{valid:true,usable_for_comparison:true,diagnostics:[]});await flush();
const afterOldFile=t.get().recommendationValidation.status;
t.set({...t.get(),source:{...t.get().source,snapshotId:'source-b'}});
reply(1,{valid:true,usable_for_comparison:true,diagnostics:[]});await flush();
const afterOldSource=submit.disabled;
t.ensureRecommendationValidation(form);await flush();
const request=requests[2];
reply(2,{valid:true,usable_for_comparison:true,record_count:2,diagnostics:[]});await flush();
t.set(S.updateScenario(t.get(),{horizonDays:28}));t.ensureRecommendationValidation(form);await flush();
console.log(JSON.stringify({afterOldFile,afterOldSource,newSource:request.options.body.entries.source_snapshot_id,
 horizon:requests[3].options.body.entries.horizon_days,blocked:submit.disabled}));
""")
    assert result == {'afterOldFile':'validating','afterOldSource':True,'newSource':'source-b',
                      'horizon':'28','blocked':True}
