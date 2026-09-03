import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    prefix=';'.join(f"require({json.dumps(str(ROOT/p))})" for p in ('frontend/assets/js/core.js','frontend/assets/js/components.js','frontend/assets/js/flow.js'))
    return json.loads(subprocess.check_output(['node','-e',f'{prefix};console.log(JSON.stringify({expr}))'],text=True))
def fixture():
    def link(origin,destination,qty,margin='3',profit='100',sku='SKU-A'):
        return {'origin_cluster_id':origin,'destination_cluster_id':destination,'quantity':qty,'destination_share':str(qty/100),'economics':{'route_cost_rub_per_unit':'20','route_cost_pct_of_realization':'.2','margin_delta_pp':margin,'profit_opportunity_rub':profit,'complete':True,'reason_codes':[]},'sku_breakdown':[{'sku':sku,'quantity':qty,'route_share':'1','destination_demand_share':str(qty/100),'margin_delta_pp':margin,'observed_profit_opportunity_rub':'1000','profit_opportunity_rub':profit}]}
    view={'mode':'destination','key':'Москва','evidence_source':'clean','total_quantity':100,'local_share':'.78','external_share':'.22','donor_count':2,'external_economics':{'complete':True,'route_cost_rub_per_unit':'20','route_cost_pct_of_realization':'.2','margin_delta_pp':'3','profit_opportunity_rub':'1400'},'links':[link('Москва','Москва',78),link('Казань','Москва',14),link('Самара','Москва',8)]}
    origin={'mode':'origin','key':'Казань','evidence_source':'clean','total_quantity':20,'local_share':'0','external_share':'1','donor_count':1,'external_economics':None,'links':[link('Казань','Москва',14),link('Казань','Самара',6)]}
    sku={'mode':'sku','key':'SKU-A','evidence_source':'clean','total_quantity':98,'local_share':str(78/98),'external_share':str(20/98),'donor_count':1,'external_economics':None,'links':[link('Москва','Москва',78),link('Казань','Москва',14),link('Казань','Самара',6)]}
    return {'flow_view_aggregates':{'clean_views':[view,origin,sku],'observed_views':[dict(view,total_quantity=115,evidence_source='observed')]}}
def test_three_modes_four_metrics_and_route_reconciliation():
    f=json.dumps(fixture(),ensure_ascii=False)
    assert node(f"SkladOzon.FlowView.buildScreenModel({f},{{mode:'destination',metric:'units',evidence:'clean',selectedKey:null,selectedRoute:null}}).links.map(x=>x.quantity)")==[78,14,8]
    assert node(f"SkladOzon.FlowView.reconcile(SkladOzon.FlowView.selectView({f},{{mode:'destination',evidence:'clean'}}))") is True
    assert node("Object.keys(SkladOzon.FlowView.metrics)")==['units','share','margin_pp','profit_rub']
    for mode in ('destination','origin','sku'):
        assert node(f"SkladOzon.FlowView.selectView({f},{{mode:'{mode}',evidence:'clean'}}).mode")==mode
    assert node("SkladOzon.FlowView.buildTopologyLink({origin_cluster_id:'Казань',destination_cluster_id:'Москва'},'destination').endpointLabel") == 'Казань'
    assert node("SkladOzon.FlowView.buildTopologyLink({origin_cluster_id:'Казань',destination_cluster_id:'Москва'},'origin').endpointLabel") == 'Москва'
    assert node("SkladOzon.FlowView.buildTopologyLink({origin_cluster_id:'Казань',destination_cluster_id:'Москва'},'sku').endpointLabel") == 'Казань → Москва'
def test_none_zero_negative_and_evidence_identity():
    assert node("[SkladOzon.FlowView.buildLinkModel({quantity:0,destination_share:0,economics:{margin_delta_pp:0,profit_opportunity_rub:0},origin_cluster_id:'К',destination_cluster_id:'М'},'profit_rub').metricText,SkladOzon.FlowView.buildLinkModel({quantity:1,destination_share:1,economics:{profit_opportunity_rub:null},origin_cluster_id:'К',destination_cluster_id:'М'},'profit_rub').metricText]")==['0 ₽','Не рассчитано']
    assert node("SkladOzon.FlowView.buildLinkModel({quantity:1,destination_share:1,economics:{margin_delta_pp:'-1.5'},origin_cluster_id:'К',destination_cluster_id:'М'},'margin_pp').metricText").replace('\xa0',' ')=='−1,5 п.п.'
    f=json.dumps(fixture(),ensure_ascii=False)
    assert node(f"[SkladOzon.FlowView.selectView({f},{{mode:'destination',evidence:'clean'}}).total_quantity,SkladOzon.FlowView.selectView({f},{{mode:'destination',evidence:'observed'}}).total_quantity]")==[100,115]
