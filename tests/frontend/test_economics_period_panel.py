import json
from pathlib import Path
import subprocess


def test_initial_buyout_requires_finance_and_coverage_lists_preserve_article_identity():
    module = Path(__file__).parents[2] / 'frontend/assets/js/economics_buyouts.js'
    script = r'''
    const assert=require('node:assert/strict');
    const buttons=['orders','buyouts'].map(mode=>({dataset:{econCalculation:mode}}));
    const load={},download={},more={addEventListener(_,fn){this.click=fn;}};
    const container={isConnected:true,innerHTML:'',contains(){return false;},
      querySelectorAll(){return buttons;},querySelector(selector){
        return {'#buyout-load':load,'#buyout-export':download,'#buyout-coverage-more':more}[selector]||null;
      }};
    globalThis.document={body:{},activeElement:null};document.activeElement=document.body;
    globalThis.scrollTo=()=>{};
    globalThis.SkladOzon={escapeHtml:value=>String(value).replaceAll('<','&lt;'),presentIsoDate:String,
      EconomicsWorkspace:{formatMoney:value=>String(value)}};
    require(MODULE);
    const products=Array.from({length:15},(_,i)=>({sku:'RAW-'+i,article:'ART-'+i,name:'Name '+i}));
    products[0].article=products[1].article='DUP'; products[2].article='';products[3].article='<unsafe>';
    let loaded=false;
    const fetch=async(_,request)=>{const body=JSON.parse(request.body);return {ok:true,json:async()=>({workspace:{
      mode:body.mode,period:{from:'2026-09-01',to:'2026-09-02'},products:[],expenses:[],
      finance_snapshot_id:loaded?'F':null,quantity_complete:body.mode==='orders'||loaded,
      expenses_complete:loaded,coverage:{unit_available_count:15,ambiguous_articles:['DUP'],
        missing_unit_products:loaded?products:[],missing_quantity_products:[]},
      totals:{qty:loaded?15:null,partial:true,sku_count:15,covered_sku_count:0,covered_qty:0,
        uncovered_skus:products.map(p=>p.sku)}}})};};
    const settings={ready:true,scenario:{period_from:'2026-09-01',period_to:'2026-09-02'}};
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    (async()=>{
      SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:'A'},fetch,settings);await tick();
      buttons[1].onclick();await tick();
      assert.ok(container.innerHTML.includes('data-econ-profit-needs-finance'));
      assert.match(container.innerHTML, /id="buyout-export"[^>]*disabled/);
      assert.ok(!container.innerHTML.includes('Без полной юнитки:'));
      loaded=true;
      SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:'A'},fetch,{...settings,revalidate:true});await tick();
      assert.ok(container.innerHTML.includes('DUP · SKU RAW-0'));
      assert.ok(container.innerHTML.includes('DUP · SKU RAW-1'));
      assert.ok(container.innerHTML.includes('SKU RAW-2'));
      assert.ok(container.innerHTML.includes('&lt;unsafe>'));
      assert.ok(!container.innerHTML.includes('RAW-4'));
      assert.ok(!container.innerHTML.includes('ART-14'));
      more.click();
      assert.ok(container.innerHTML.includes('ART-14'));
      SkladOzon.EconomicsBuyouts.deactivate();
    })().catch(error=>{console.error(error);process.exit(1);});
    '''.replace('require(MODULE)', f'require({json.dumps(str(module))})')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_period_failures_retry_loading_calculation_and_download_respectively():
    js = Path(__file__).parents[2] / 'frontend/assets/js'
    script = r'''
    const assert=require('node:assert/strict');
    const buttons=['orders','buyouts'].map(mode=>({dataset:{econCalculation:mode}}));
    const load={},download={},retry={addEventListener(_,fn){this.click=fn;}};
    const container={isConnected:true,innerHTML:'',contains(){return false;},
      querySelectorAll(){return buttons;},querySelector(selector){
        return {'#buyout-load':load,'#buyout-export':download,'#buyout-retry':retry}[selector]||null;
      }};
    let downloads=0;
    globalThis.document={body:{append(){}},activeElement:null,addEventListener(){},
      createElement(){return {click(){downloads++;},remove(){}};}};document.activeElement=document.body;
    globalThis.scrollTo=()=>{};
    globalThis.SkladOzon={escapeHtml:String,presentIsoDate:String,
      EconomicsWorkspace:{formatMoney:value=>String(value)}};
    require(APP); require(MODULE);
    const calls=[];let syncCount=0,exportCount=0,failWorkspace=false;
    const fetch=async(url,request)=>{
      calls.push(url);const body=JSON.parse(request.body);
      if(url.endsWith('/export')){
        if(++exportCount===1)return {ok:false,status:500,json:async()=>({error:{message:'export failed'}})};
        return new Response('workbook');
      }
      if(url.endsWith('/sync')){
        if(++syncCount===1)return {ok:false,status:400,json:async()=>({error:{message:'load failed'}})};
        return new Response(JSON.stringify({type:'result',data:{finance_snapshot_id:'F'}})+'\n');
      }
      if(failWorkspace)return {ok:false,status:500,json:async()=>({error:{message:'calculation failed'}})};
      return {ok:true,json:async()=>({workspace:{mode:body.mode,period:{from:'2026-09-01',to:'2026-09-02'},
        products:[],expenses:[],quantity_complete:true,expenses_complete:!!body.finance_snapshot_id,
        finance_snapshot_id:body.finance_snapshot_id,totals:{partial:false}}})};
    };
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    (async()=>{
      SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:'A'},fetch,{ready:true,
        scenario:{period_from:'2026-09-01',period_to:'2026-09-02'}});await tick();
      await load.onclick();assert.ok(container.innerHTML.includes('load failed'));
      await retry.click();await tick();
      assert.equal(syncCount,2);assert.ok(!container.innerHTML.includes('load failed'));
      failWorkspace=true;buttons[1].onclick();await tick();
      assert.ok(container.innerHTML.includes('calculation failed'));
      failWorkspace=false;await retry.click();await tick();
      assert.equal(syncCount,2);assert.equal(calls.at(-1),'/api/economics/period/workspace');
      assert.ok(!container.innerHTML.includes('calculation failed'));
      await download.onclick();assert.ok(container.innerHTML.includes('export failed'));
      await retry.click();await tick();
      assert.equal(exportCount,2);assert.equal(syncCount,2);assert.equal(downloads,1);
      assert.ok(!container.innerHTML.includes('export failed'));
      SkladOzon.EconomicsBuyouts.deactivate();
    })().catch(error=>{console.error(error);process.exit(1);});
    '''.replace('require(APP)', f'require({json.dumps(str(js / "app.js"))})').replace(
        'require(MODULE)', f'require({json.dumps(str(js / "economics_buyouts.js"))})')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_shared_article_coverage_uses_whole_store_ambiguity_even_for_covered_sibling():
    module = Path(__file__).parents[2] / 'frontend/assets/js/economics_buyouts.js'
    script = r'''
    const assert=require('node:assert/strict');
    const controls={};
    const container={isConnected:true,innerHTML:'',contains(){return false;},
      querySelectorAll(){return [];},querySelector(selector){
        if(selector==='#buyout-load'||selector==='#buyout-export')return controls[selector]||={};
        return null;
      }};
    globalThis.document={body:{},activeElement:null};document.activeElement=document.body;
    globalThis.scrollTo=()=>{};
    globalThis.SkladOzon={escapeHtml:String,presentIsoDate:String,
      EconomicsWorkspace:{formatMoney:value=>String(value)}};
    require(MODULE);
    const tick=()=>new Promise(resolve=>setImmediate(resolve));
    (async()=>{
      for(const missingQuantity of [true,false]){
        const fetch=async()=>({ok:true,json:async()=>({workspace:{mode:'orders',products:[],expenses:[],
          quantity_complete:true,expenses_complete:true,coverage:{ambiguous_articles:['SHARED'],unit_available_count:1,
            missing_unit_products:[{sku:'SKU-A',article:'SHARED',name:'Same product'}],
            missing_quantity_products:missingQuantity?[{sku:'SKU-B',article:'SHARED',name:'Same product'}]:[]},
          totals:{partial:true,sku_count:2,covered_sku_count:0,covered_qty:0}}})});
        SkladOzon.EconomicsBuyouts.render(container,{snapshot_id:String(missingQuantity)},fetch,{ready:true,
          scenario:{period_from:'2026-09-01',period_to:'2026-09-02'}});await tick();
        assert.ok(container.innerHTML.includes('SHARED · SKU SKU-A'));
        if(missingQuantity)assert.ok(container.innerHTML.includes('SHARED · SKU SKU-B'));
      }
      SkladOzon.EconomicsBuyouts.deactivate();
    })().catch(error=>{console.error(error);process.exit(1);});
    '''.replace('require(MODULE)', f'require({json.dumps(str(module))})')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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
      assert.match(container.innerHTML, /отмен/);
      SkladOzon.EconomicsBuyouts.deactivate();
      finish({ok:false,status:500,json:async()=>({error:{message:'late'}})});await tick();
    })().catch(error=>{console.error(error);process.exit(1);});
    '''.replace('require(MODULE)', f'require({json.dumps(str(module))})')
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
