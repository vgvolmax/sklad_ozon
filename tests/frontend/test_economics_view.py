import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    return json.loads(subprocess.check_output(['node','-e',f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))});console.log(JSON.stringify({expr}))"],text=True))
def test_unit_route_models_filters_labels_and_drawers():
    snap={'decision_rows':[{'sku':'A','article':'ART','product_name':'Товар'}],'unit_economics':[{'sku':'A','placement_cluster_id':'Москва','complete':True,'profit_per_unit':0,'line_items':[{'code':'COMMISSION','amount':0,'basis':100,'rate':'.1'}],'blockers':[]},{'sku':'B','placement_cluster_id':'Казань','complete':False,'profit_per_unit':None,'line_items':[],'blockers':['MISSING_PRICE']}],'route_economics':[{'sku':'A','origin_cluster_id':'Казань','destination_cluster_id':'Москва','complete':False,'reason_codes':['LOCAL_PLACEMENT_INFEASIBLE']} ]}
    f=json.dumps(snap,ensure_ascii=False)
    assert node(f"SkladOzon.buildEconomicsRows({f},'unit').map(x=>[x.sku,x.statusText,x.reasonText])")==[['A','Полный расчёт','Не рассчитано'],['B','Неполный расчёт','Нет цены']]
    assert node(f"SkladOzon.filterEconomicsRows(SkladOzon.buildEconomicsRows({f},'unit'),{{search:'товар',status:'all'}}).length")==1
    assert node(f"SkladOzon.buildEconomicsRows({f},'routes')[0].route")=='Казань → Москва'
    assert node(f"SkladOzon.buildUnitDrawerModel(SkladOzon.buildEconomicsRows({f},'unit')[0]).lineItems[0].label")=='Комиссия Ozon'
    assert node(f"SkladOzon.buildRouteDrawerModel(SkladOzon.buildEconomicsRows({f},'routes')[0]).sections.length")==6
