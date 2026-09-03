import json, subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def node(expression):
    files = [ROOT/'frontend/assets/js/core.js']
    prefix = ';'.join(f"require({json.dumps(str(x))})" for x in files)
    return json.loads(subprocess.check_output(['node','-e',f"{prefix};console.log(JSON.stringify({expression}))"], text=True))


def rows():
    base=[]
    for i in range(6):
        base.append({'sku':f'S{i}','article':f'A{i}','product_name':f'Товар {i}','destination_cluster_id':f'C{i}','need':{'delta_qty':0,'ozon_recommended_qty':0,'calculated_need_qty':0},'safe_plan_qty':0,'calculated_plan_qty':0,'observed_profit_opportunity_rub':0,'status_codes':[],'explanations':['Пояснение']})
    base[0]['need']['delta_qty']=2
    base[1]['status_codes']=['PROBABLE_STOCKOUT']
    base[2]['observed_profit_opportunity_rub']='4.2'
    base[3]['status_codes']=['ECONOMICS_INCOMPLETE']
    base[4]['calculated_plan_qty']=None
    base[5]['status_codes']=['PHYSICALLY_INFEASIBLE']
    return base


def test_decision_line_none_zero_and_different_horizon():
    snap={'summary':{'total_ozon_recommended_qty':0,'total_calculated_need_qty':None,'total_calculated_plan_qty':9,'total_safe_plan_qty':4},'freshness_warnings':['Горизонты различаются: Ozon 28 дней, наш расчёт 56 дней.']}
    model=node(f"SkladOzon.buildDecisionLineModel({json.dumps(snap, ensure_ascii=False)})")
    assert [x['label'] for x in model['steps']] == ['Ozon','Наша потребность','Наш план']
    assert model['safe']['label'] == 'Safe Plan'
    assert model['differentHorizon'] is True
    assert node("[SkladOzon.presentNumber(null),SkladOzon.presentNumber(0)]") == ['Не рассчитано','0']


def test_exact_structured_filters_and_search():
    fixture=json.dumps(rows(),ensure_ascii=False)
    expected={'all':['S0','S1','S2','S3','S4','S5'],'disagreement':['S0'],'probable_stockout':['S1'],'expensive_logistics':['S2'],'incomplete_economics':['S3'],'blocked':['S4','S5']}
    for filter_,keys in expected.items():
        got=node(f"SkladOzon.filterPlanRows(SkladOzon.buildPlanRows({{decision_rows:{fixture}}}),{{search:'',quickFilter:'{filter_}'}}).map(x=>x.sku)")
        assert got == keys
    for query,key in [('s2','S2'),('a3','S3'),('товар 4','S4'),('c5','S5')]:
        assert node(f"SkladOzon.filterPlanRows(SkladOzon.buildPlanRows({{decision_rows:{fixture}}}),{{search:{json.dumps(query,ensure_ascii=False)},quickFilter:'all'}}).map(x=>x.sku)") == [key]


def test_pagination_sort_immutability_and_drawer_order():
    assert node("SkladOzon.paginatePlanRows(Array.from({length:61},(_,i)=>i),9,25)")['page'] == 3
    for size in (25,50,100):
        assert node(f"SkladOzon.paginatePlanRows(Array.from({{length:120}},(_,i)=>i),1,{size}).rows.length") == size
    fixture=json.dumps(rows(),ensure_ascii=False)
    result=node(f"(()=>{{const r={fixture},before=JSON.stringify(r);SkladOzon.sortPlanRows(r,{{key:'identity',direction:'desc'}});return before===JSON.stringify(r)}})()")
    assert result is True
    snap={'diagnostics':[]}
    order=node(f"SkladOzon.buildDrawerModel({fixture}[0],{json.dumps(snap)}).sections.map(x=>x.title)")
    assert order == ['Решение','Динамика спроса','Как исполняется спрос','Ozon vs наша модель','Экономика','Доказательства и диагностика']


def test_frontend_has_no_legacy_business_joins_or_raw_primary_code():
    js='\n'.join((ROOT/f'frontend/assets/js/{name}').read_text() for name in ('core.js','components.js','app.js'))
    for legacy in ('data.placements','data.allocations','data.safe_allocations','data.logistics','data.economics'):
        assert legacy not in js
    assert 'data.snapshot' not in js or 'result.snapshot' in js
    assert 'RECOMMENDATION_DISTORTION_SIGNAL' not in js
    assert 'Колонки' in (ROOT/'frontend/assets/js/components.js').read_text()
    components=(ROOT/'frontend/assets/js/components.js').read_text()
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert 'data-row-index' in components
    assert 'data-open=' not in components
    assert "replace:true,restoreFocus:'#plan-search input'" in app
    assert "latest_week_qty" in app and ".latest)" not in app


def test_demand_wire_contract_and_human_presentation():
    demand={'m1':'19.5','m2':'24.5','latest_week_qty':'29','regime':'growth','regime_confirmed':True,'current_weekly_rate':'26.75'}
    model=node(f"SkladOzon.parseDemandPresentation({json.dumps(demand)})")
    assert model == {'levels':'19,5 → 24,5 → 29','regime':'Рост','confirmation':'подтверждён','weeklyRate':'26,75'}
    assert node("SkladOzon.parseDemandPresentation({regime_confirmed:false}).confirmation") == 'не подтверждён'
    assert node("SkladOzon.parseDemandPresentation({regime_confirmed:null}).confirmation") == 'подтверждение недоступно'


def test_fraction_percent_pp_and_rows_do_not_create_business_derived_dom_ids():
    values=node("[SkladOzon.presentPercentFraction('0.25'),SkladOzon.presentPercentFraction(0),SkladOzon.presentPercentFraction(null),SkladOzon.presentPercentagePoints(2.5)]")
    assert [x.replace('\xa0',' ') for x in values] == ['25 %','0 %','Не рассчитано','2,5 п.п.']
    built=node("SkladOzon.buildPlanRows({decision_rows:[{sku:'A/B',destination_cluster_id:'C'},{sku:'A_2FB',destination_cluster_id:'C'}]})")
    assert all('domKey' not in row for row in built)
    components=(ROOT/'frontend/assets/js/components.js').read_text()
    assert 'plan-row-open-${index}' in components
    assert 'row.domKey' not in components


def test_drawer_diagnostics_model_keeps_messages_and_technical_codes():
    row=rows()[0]; row['destination_cluster_id']='Москва'; row['status_codes']=['CODE']
    snap={'diagnostics':[{'sku':'S0','destination_cluster_id':'Москва','code':'DIAG','message':'Понятное сообщение'}]}
    data=node(f"SkladOzon.buildDrawerModel({json.dumps(row,ensure_ascii=False)},{json.dumps(snap,ensure_ascii=False)}).sections[5].data")
    assert data['explanations'] == ['Пояснение']
    assert data['diagnostics'][0]['message'] == 'Понятное сообщение'
