import json, subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def node(expression):
    files = [ROOT/'frontend/assets/js/core.js']
    prefix = ';'.join(f"require({json.dumps(str(x))})" for x in files)
    return json.loads(subprocess.check_output(['node','-e',f"{prefix};console.log(JSON.stringify({expression}))"], text=True))


def app_node(expression):
    files = [ROOT/'frontend/assets/js/core.js', ROOT/'frontend/assets/js/components.js', ROOT/'frontend/assets/js/app.js']
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
    snap={'summary':{'total_ozon_recommended_qty':0,'total_calculated_need_qty':None,'total_calculated_plan_qty':9,'total_safe_plan_qty':None},'freshness_warnings':['Горизонты различаются: Ozon 28 дней, наш расчёт 56 дней.']}
    model=node(f"SkladOzon.buildDecisionLineModel({json.dumps(snap, ensure_ascii=False)})")
    assert [x['label'] for x in model['steps']] == ['Ozon','Наша потребность','Наш план']
    assert model['safe']['label'] == 'Safe Plan'
    assert model['safe']['value'] is None
    assert model['differentHorizon'] is True
    assert node("[SkladOzon.presentNumber(null),SkladOzon.presentNumber(0)]") == ['Не рассчитано','0']


def test_horizon_comparability_has_human_labels_for_every_state():
    assert node("['same_horizon','different_horizon','ozon_horizon_unknown','ozon_recommendation_missing'].map(SkladOzon.presentHorizonComparability)") == [
        'Горизонты совпадают',
        'Горизонты различаются',
        'Горизонт Ozon неизвестен',
        'Рекомендация Ozon отсутствует',
    ]


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


def test_plan_has_no_objective_control_and_explains_margin_priority():
    app = (ROOT / "frontend/assets/js/app.js").read_text()
    assert 'id="objective"' not in app
    assert "optimization_objective" not in app
    assert "Макс. прибыль" not in app
    assert "Макс. маржа" not in app
    assert "План отдаёт приоритет более маржинальным вариантам размещения." in app

def test_article_plan_identity_search_and_reconciliation():
    snap={'decision_rows':[{'sku':'100','article':'40750','product_name':'Кран','destination_cluster_id':'A'},{'sku':'200','article':'40750','product_name':'Кран другой','destination_cluster_id':'B'}],'shippable_plan':{'lines':[]}}
    fixture=json.dumps(snap,ensure_ascii=False)
    items=node(f"SkladOzon.buildArticlePlanItems({fixture})")
    assert [x['sku'] for x in items]==['100','200'] and all(x['duplicateArticle'] for x in items)
    for query,sku in [('40750','100'),('200','200'),('другой','200')]:
        got=node(f"SkladOzon.filterArticlePlanItems(SkladOzon.buildArticlePlanItems({fixture}),{json.dumps(query,ensure_ascii=False)}).map(x=>x.sku)")
        assert sku in got
    assert node(f"SkladOzon.reconcileSelectedSku(SkladOzon.buildArticlePlanItems({fixture}),'200')")=='200'
    assert node(f"SkladOzon.reconcileSelectedSku(SkladOzon.buildArticlePlanItems({fixture}),'missing')")=='100'

def test_product_summary_aggregates_every_cluster_and_preserves_unknowns():
    complete="{clusterRows:[{need:{ozon_recommended_qty:10,calculated_need_qty:12},calculated_plan_qty:12,shippable:{shippable_qty:12,resolved_seller_stock:17,pack_multiple:6,unit_volume_l:0.3},working:{working_qty:18,total_volume_l:5.4}},{need:{ozon_recommended_qty:5,calculated_need_qty:6},calculated_plan_qty:6,shippable:{shippable_qty:6,resolved_seller_stock:17,pack_multiple:6,unit_volume_l:0.3},working:{working_qty:6,total_volume_l:1.8}}]}"
    summary=node(f"SkladOzon.buildProductPlanSummary({complete})")
    assert summary['ozonRecommendedQty']==15 and summary['calculatedNeedQty']==18 and summary['calculatedPlanQty']==18
    assert summary['sellerStock']==17 and summary['wholePackAvailable']==12 and summary['packMultiple']==6
    assert summary['shippableQty']==24 and summary['totalVolumeL']==7.2
    assert node("SkladOzon.buildProductPlanSummary({clusterRows:[{need:{ozon_recommended_qty:10}},{need:{ozon_recommended_qty:null}}]}).ozonRecommendedQty") is None


def test_working_plan_drives_selector_and_cluster_aggregates_fail_closed():
    snapshot={'decision_rows':[{'sku':'A','article':'A','destination_cluster_id':'M'},
                               {'sku':'B','article':'B','destination_cluster_id':'M'}],
              'shippable_plan':{'lines':[{'sku':'A','destination_cluster_id':'M','shippable_qty':40},
                                          {'sku':'B','destination_cluster_id':'M','shippable_qty':40}]}}
    working={'lines':[{'sku':'A','destination_cluster_id':'M','working_qty':80,'total_volume_l':8},
                      {'sku':'B','destination_cluster_id':'M','working_qty':40,'total_volume_l':4}]}
    fixture=json.dumps(snapshot); wp=json.dumps(working)
    assert node(f"SkladOzon.buildClusterPlanItems({fixture},{wp})[0].knownWorkingQty") == 120
    summary=node(f"SkladOzon.buildClusterPlanSummary(SkladOzon.buildClusterPlanItems({fixture},{wp})[0])")
    assert summary['shippableQty']==120 and summary['totalVolumeL']==12
    working['lines'][1]['working_qty']=None
    incomplete=json.dumps(working)
    item=node(f"SkladOzon.buildClusterPlanItems({fixture},{incomplete})[0]")
    assert item['knownWorkingQty'] is None and item['hasUnknownWorking'] is True
    assert node(f"SkladOzon.buildClusterPlanSummary(SkladOzon.buildClusterPlanItems({fixture},{incomplete})[0]).shippableQty") is None


def test_ordered_demand_presentation_preserves_partial_unknowns_and_zero():
    cases = node("[SkladOzon.presentOrderedDemand({ordered_qty_56d:31,ordered_qty_horizon:18},28),SkladOzon.presentOrderedDemand({ordered_qty_56d:31,ordered_qty_horizon:31},56),SkladOzon.presentOrderedDemand({ordered_qty_56d:31,ordered_qty_horizon:null},120),SkladOzon.presentOrderedDemand({ordered_qty_56d:0,ordered_qty_horizon:0},28)]")
    assert cases == [
        {'heading': 'Заказано, 56 дн. / 28 дн.', 'value': '31 / 18'},
        {'heading': 'Заказано, 56 дн.', 'value': '31'},
        {'heading': 'Заказано, 56 дн. / 120 дн.', 'value': '31 / Не рассчитано'},
        {'heading': 'Заказано, 56 дн. / 28 дн.', 'value': '0 / 0'},
    ]


def test_product_cluster_columns_place_ordered_demand_after_inbound():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    columns = "['plan-table-identity',identity,'',identity],['col-fbo','FBO','', 'FBO'],['col-inbound','В пути','', 'В пути'],['col-ordered','Заказано',orderedSecondary,orderedHeading]"
    assert columns in app

def test_search_selection_reconciles_against_visible_items():
    app=(ROOT/'frontend/assets/js/app.js').read_text()
    assert 'selected=S.reconcileSelectedSku(visible,state.planView.selectedSku)' in app


def test_cluster_plan_items_group_matrix_by_cluster_without_collapsing_skus():
    snapshot = {
        'decision_rows': [
            {'sku': '100', 'article': '40750', 'product_name': 'Кран A', 'destination_cluster_id': 'Москва'},
            {'sku': '200', 'article': '40750', 'product_name': 'Кран B', 'destination_cluster_id': 'Москва'},
            {'sku': '100', 'article': '40750', 'product_name': 'Кран A', 'destination_cluster_id': 'Казань'},
        ],
        'shippable_plan': {'lines': [
            {'sku': '100', 'destination_cluster_id': 'Москва', 'shippable_qty': 12},
            {'sku': '200', 'destination_cluster_id': 'Москва', 'shippable_qty': None},
            {'sku': '100', 'destination_cluster_id': 'Казань', 'shippable_qty': 0},
        ]},
    }
    items = node(f"SkladOzon.buildClusterPlanItems({json.dumps(snapshot, ensure_ascii=False)})")
    assert [item['clusterId'] for item in items] == ['Москва', 'Казань']
    assert [row['sku'] for row in items[0]['productRows']] == ['100', '200']
    assert items[0]['knownShippableQty'] == 12
    assert items[0]['hasUnknownShippable'] is True
    assert items[0]['unknownSkuCount'] == 1
    assert items[0]['positiveSkuCount'] == 1
    assert items[1]['knownShippableQty'] == 0
    assert items[1]['hasUnknownShippable'] is False
    assert len(items[0]['productRows']) + len(items[1]['productRows']) == 3


def test_cluster_sort_search_and_selection_reconciliation():
    items = "[{clusterId:'Zero',knownShippableQty:0,hasUnknownShippable:false},{clusterId:'Unknown 2',knownShippableQty:0,hasUnknownShippable:true},{clusterId:'Москва 10',knownShippableQty:20,hasUnknownShippable:false},{clusterId:'Москва 2',knownShippableQty:20,hasUnknownShippable:false}]"
    ordered = node(f"SkladOzon.sortClusterPlanItems({items}).map(x=>x.clusterId)")
    assert ordered == ['Москва 2', 'Москва 10', 'Unknown 2', 'Zero']
    visible = node(f"SkladOzon.filterClusterPlanItems(SkladOzon.sortClusterPlanItems({items}),'МОСКВА').map(x=>x.clusterId)")
    assert visible == ['Москва 2', 'Москва 10']
    assert node(f"SkladOzon.reconcileSelectedCluster({items},'Unknown 2')") == 'Unknown 2'
    assert node(f"SkladOzon.reconcileSelectedCluster({items},'missing')") == 'Zero'
    assert node("SkladOzon.reconcileSelectedCluster([], 'Москва')") is None


def test_cluster_summary_is_fail_closed_but_preserves_zero():
    complete = "{productRows:[{need:{ozon_recommended_qty:10,calculated_need_qty:8},calculated_plan_qty:6,shippable:{shippable_qty:6,total_volume_l:1.2,placement_zones:['SORT']},working:{working_qty:6,total_volume_l:1.2}},{need:{ozon_recommended_qty:0,calculated_need_qty:0},calculated_plan_qty:0,shippable:{shippable_qty:0,total_volume_l:0,placement_zones:['NON_SORT']},working:{working_qty:0,total_volume_l:0}}]}"
    summary = node(f"SkladOzon.buildClusterPlanSummary({complete})")
    assert summary['skuCount'] == 2
    assert summary['ozonRecommendedQty'] == 10
    assert summary['calculatedNeedQty'] == 8
    assert summary['calculatedPlanQty'] == 6
    assert summary['shippableQty'] == 6
    assert summary['totalVolumeL'] == 1.2
    assert summary['placementZones'] == ['NON_SORT', 'SORT']
    assert summary['unknownRowCount'] == 0
    partial = node("SkladOzon.buildClusterPlanSummary({productRows:[{need:{ozon_recommended_qty:0,calculated_need_qty:0},calculated_plan_qty:0,shippable:{shippable_qty:0,total_volume_l:0,placement_zones:['SORT']},working:{working_qty:0,total_volume_l:0}},{need:{ozon_recommended_qty:null,calculated_need_qty:undefined},calculated_plan_qty:'',shippable:{shippable_qty:null,total_volume_l:NaN,placement_zones:[]},working:{working_qty:null,total_volume_l:NaN}}]})")
    assert partial['ozonRecommendedQty'] is None
    assert partial['calculatedNeedQty'] is None
    assert partial['calculatedPlanQty'] is None
    assert partial['shippableQty'] is None
    assert partial['totalVolumeL'] is None
    assert partial['unknownRowCount'] == 1
    assert partial['hasUnknownZones'] is True


def test_cluster_workspace_reuses_existing_ordered_demand_and_status_helpers():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    assert 'function clusterWorkspace(item,snap)' in app
    assert 'S.presentOrderedDemand(row,horizon)' in app
    assert '(sh.reason_codes||[]).map(S.shippableReasonLabel)' in app
    assert 'planTableHeaders(\'Товар\',orderedHeading)' in app


def test_compact_plan_tables_keep_identity_and_shared_column_grid():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    css = (ROOT / 'frontend/assets/css/app.css').read_text()

    assert '<strong class="plan-product-article">' in app
    assert '<span class="plan-product-name" title="${productName}">${productName}</span>' in app
    assert '<small class="plan-product-sku">SKU ${S.escapeHtml(row.sku)}</small>' in app
    assert '<td class="plan-table-identity">${S.escapeHtml(row.destination_cluster_id)}</td>' in app
    for column in ('col-fbo', 'col-inbound', 'col-ordered', 'col-ozon', 'col-need',
                   'col-plan', 'col-pack', 'col-ship', 'col-volume', 'col-zone', 'col-status'):
        assert app.count(f'class="{column}') == 2
        assert column in css


def test_compact_plan_table_headers_and_sticky_context_are_presentational():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    css = (ROOT / 'frontend/assets/css/app.css').read_text()

    assert 'function tableHeader(primary,secondary' in app
    assert 'function planTableHeaders(identity,orderedHeading)' in app
    assert 'orderedHeading.replace(/^Заказано,\\s*/' in app
    assert 'S.presentOrderedDemand(row,horizon)' in app
    assert '(sh.reason_codes||[]).map(S.shippableReasonLabel)' in app
    assert '-webkit-line-clamp:3' in css
    assert '.plan-table thead th{position:sticky' in css
    assert '.plan-table-identity{position:sticky' in css


def test_plan_table_compacts_unknown_numbers_without_hiding_zero():
    values = app_node("[SkladOzon.planCellNumber(null),SkladOzon.planCellNumber(undefined),SkladOzon.planCellNumber(NaN),SkladOzon.planCellNumber(0),SkladOzon.planCellNumber(12.5)]")
    assert all('>—</span>' in value for value in values[:3])
    assert all('title="Не рассчитано"' in value and 'aria-label="Не рассчитано"' in value for value in values[:3])
    assert values[3:] == ['0', '12,5']


def test_plan_table_compacts_partial_ordered_demand_and_unknown_zone():
    ordered = app_node("SkladOzon.planOrderedDemand({ordered_qty_56d:31,ordered_qty_horizon:null},120)")
    assert '>31 / —</span>' in ordered
    assert 'title="31 / Не рассчитано"' in ordered
    assert 'aria-label="31 / Не рассчитано"' in ordered
    assert app_node("SkladOzon.planOrderedDemand({ordered_qty_56d:0,ordered_qty_horizon:0},28)") == '0 / 0'
    zone = app_node("SkladOzon.planZone([])")
    assert '>—</span>' in zone
    assert 'title="Зона не рассчитана"' in zone and 'aria-label="Зона не рассчитана"' in zone


def test_plan_table_css_has_one_canonical_geometry_block():
    css = (ROOT / 'frontend/assets/css/app.css').read_text()
    compact = ''.join(css.split())
    assert '.cluster-tabletd{white-space:nowrap}' not in compact
    assert css.count('.plan-table{table-layout:fixed;min-width:1320px}') == 1
    assert css.count('.plan-table .col-ship{width:142px}') == 1
    assert css.count('.plan-table{') == 1
    assert css.count('.plan-table .col-ship{') == 1
    assert '.plan-table--products .plan-table-identity{width:170px' in css
    assert '.plan-table--clusters .plan-table-identity{width:190px' in css
