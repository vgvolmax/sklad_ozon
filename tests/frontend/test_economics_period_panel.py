import json
from pathlib import Path
import subprocess


def test_retained_period_report_keeps_its_mode_and_dates_on_failure_loading_and_cancel():
    module = Path(__file__).parents[2] / 'frontend/assets/js/economics_buyouts.js'
    script = r'''
    const assert=require('node:assert/strict');
    const buttons=['orders','buyouts'].map(mode=>({dataset:{econCalculation:mode}}));
    const load={},download={},cancel={addEventListener(_,fn){this.click=fn;}};
    const container={isConnected:true,innerHTML:'',contains(){return false;},
      querySelectorAll(){return buttons;},querySelector(selector){
        return {'#buyout-load':load,'#buyout-export':download,'#buyout-cancel':cancel}[selector]||null;
      }};
    globalThis.document={body:{},activeElement:null};document.activeElement=document.body;
    globalThis.scrollTo=()=>{};
    globalThis.SkladOzon={escapeHtml:String,presentIsoDate:String,
      EconomicsWorkspace:{formatMoney:value=>String(value)}};
    require(MODULE);
    const report={mode:'orders',period:{from:'2026-09-01',to:'2026-09-02'},products:[],expenses:[],
      quantity_complete:true,expenses_complete:false,totals:{qty:9,partial:false}};
    let count=0,finish;
    const fetch=async()=>++count===1?{ok:true,json:async()=>({workspace:report})}:
      new Promise(resolve=>{finish=resolve;});
    const settings={ready:true,scenario:{period_from:'2026-09-01',period_to:'2026-09-02'}};
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    const checkOld=()=>{
      assert.ok(container.innerHTML.includes('Количество · заказы</dt><dd>9 шт.'));
      assert.ok(container.innerHTML.includes('data-econ-profit-stale'));
      assert.ok(container.innerHTML.includes('предыдущий расчёт'));
      assert.ok(container.innerHTML.includes('По заказам · 2026-09-01 — 2026-09-02'));
      assert.ok(!container.innerHTML.includes('data-buyout-final'));
    };
    (async()=>{
      SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:'A'},fetch,settings);await tick();
      buttons[1].onclick();checkOld();
      finish({ok:false,status:500,json:async()=>({error:{message:'failed'}})});await tick();checkOld();
      assert.ok(container.innerHTML.includes('failed'));
      SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:'A'},fetch,{...settings,
        scenario:{period_from:'2026-10-01',period_to:'2026-10-02'}});
      checkOld();cancel.click();checkOld();
      assert.ok(container.innerHTML.includes('отменена'));
      SkladOzon.EconomicsBuyouts.deactivate();
      finish({ok:false,status:500,json:async()=>({error:{message:'late'}})});await tick();
    })().catch(error=>{console.error(error);process.exit(1);});
    '''.replace('require(MODULE)', f'require({json.dumps(str(module))})')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
