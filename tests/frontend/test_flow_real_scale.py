import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    files=('core.js','components.js','flow_timeline.js','flow.js')
    prefix=';'.join(f"require({json.dumps(str(ROOT/'frontend/assets/js'/f))})" for f in files)
    return json.loads(subprocess.check_output(['node','-e',f'{prefix};console.log(JSON.stringify({expr}))'],text=True))

def test_bounds_timeline_gaps_and_signed_copy():
    assert node("SkladOzon.FlowView.paginate(Array.from({length:250}),1,100).rows.length")==100
    assert node("[SkladOzon.FlowView.paginate(Array.from({length:180}),1,100).rows.length,SkladOzon.FlowView.paginate(Array.from({length:180}),2,100).rows.length]")==[100,80]
    assert node("SkladOzon.FlowTimeline.HEIGHT")==260
    assert node("SkladOzon.FlowTimeline.paginate(Array.from({length:90}),1,50).rows.length")==50
    assert node("SkladOzon.FlowTimeline.segments([{local_share:'1'},{local_share:null},{local_share:'0'}]).length")==2
    assert 'Локальное размещение хуже' in node("SkladOzon.FlowTimeline.impact({complete:true,profit_loss_or_opportunity_rub:'-10',extra_logistics_rub:'-2',margin_delta_pp:'-1'})")
    assert node("SkladOzon.FlowTimeline.impact({complete:false})")=='Экономика: Не рассчитано'

def test_production_has_no_route_count_canvas_height_or_pii():
    source=(ROOT/'frontend/assets/js/flow.js').read_text()+(ROOT/'frontend/assets/js/flow_timeline.js').read_text()
    assert 'links.length*90' not in source and 'length * 90' not in source
    assert 'raw_orders' not in source and 'buyer' not in source.lower()
    assert 'stockout_impact?.destination_daily_series' in source

def test_default_destination_all_episode_bands_and_context_safe_episode():
    js="""(()=>{const episodes=Array.from({length:35},(_,i)=>({episode_id:'m'+i,sku:'A',destination_cluster_id:'Москва',start_date:'2026-08-01',end_date:'2026-08-02'}));episodes.push({episode_id:'k',sku:'A',destination_cluster_id:'Казань'});const snapshot={flow_view_aggregates:{clean_views:[{mode:'destination',key:'Москва',links:[],context_summary:{}},{mode:'sku',key:'A',links:[{route_key:'Казань→Казань',origin_cluster_id:'Казань',destination_cluster_id:'Казань',quantity:1,sku_breakdown:[]}],context_summary:{}}]},stockout_impact:{episodes,destination_daily_series:[{destination_cluster_id:'Москва',points:[]}],destination_summaries:[]},decision_rows:[]};const base={mode:'destination',evidence:'clean',metric:'units',selectedKey:null,selectedRoute:null,selectedEpisodeId:null,selectorQuery:'',selectorPage:1,routeQuery:'',routePage:1,dailyPage:1,episodePage:1,skuQuery:'',skuPage:1};const screen=SkladOzon.FlowView.buildScreenModel(snapshot,base),p1=SkladOzon.FlowTimeline.buildModel(snapshot,{mode:'destination',key:'Москва',destination:'Москва'},base),p2=SkladOzon.FlowTimeline.buildModel(snapshot,{mode:'destination',key:'Москва',destination:'Москва'},{...base,episodePage:2}),sku=SkladOzon.FlowView.buildScreenModel(snapshot,{...base,mode:'sku',selectedKey:'A',selectedRoute:'Казань→Казань',selectedEpisodeId:'m0'});return [screen.view.key,screen.timelineDestination,p1.allEpisodes.length,p1.episodes.rows.length,p2.allEpisodes.length,p2.episodes.rows.length,sku.episode]})()"""
    assert node(js)==['Москва','Москва',35,20,35,15,None]

def test_destination_impact_is_backend_owned_and_incomplete_fails_closed():
    js="""(()=>{const summary={destination_cluster_id:'Москва',stockout_episode_count:3,affected_sku_count:5,episode_external_quantity:155,episode_economics:{complete:false}};return SkladOzon.FlowView.destinationImpact(summary,'ТОЧНЫЙ BACKEND TEXT')})()"""
    rendered=node(js)
    assert '<dt>Периодов</dt><dd>3</dd>' in rendered
    assert '<dt>SKU</dt><dd>5</dd>' in rendered
    assert '<dt>Перекрыто извне</dt><dd>155 шт.</dd>' in rendered
    assert 'Экономика: <strong>Не рассчитано</strong>' in rendered
    assert 'ТОЧНЫЙ BACKEND TEXT' in rendered


def test_sku_episode_without_route_resolves_timeline_destination():
    js = r"""(()=>{const episode={episode_id:'m1',sku:'A',destination_cluster_id:'Москва',start_date:'2026-08-01',end_date:'2026-08-02'};const points=[{date:'2026-08-01',destination_demand_qty:10,local_share:0.5}];const snapshot={flow_view_aggregates:{clean_views:[{mode:'sku',key:'A',links:[],context_summary:{}}]},stockout_impact:{episodes:[episode],destination_daily_series:[{destination_cluster_id:'Москва',points}],destination_summaries:[]},decision_rows:[]};const state={mode:'sku',evidence:'clean',metric:'units',selectedKey:'A',selectedRoute:null,selectedEpisodeId:'m1',selectorQuery:'',selectorPage:1,routeQuery:'',routePage:1,dailyPage:1,episodePage:1,skuQuery:'',skuPage:1};const screen=SkladOzon.FlowView.buildScreenModel(snapshot,state);const timeline=SkladOzon.FlowTimeline.buildModel(snapshot,{mode:'sku',key:'A',destination:screen.timelineDestination},state);return {episode:screen.episode?.episode_id||null,destination:screen.timelineDestination,prompt:timeline.prompt,selectedEpisode:timeline.selectedEpisode?.episode_id||null,points:timeline.points};})()"""
    assert node(js) == {
        'episode': 'm1',
        'destination': 'Москва',
        'prompt': None,
        'selectedEpisode': 'm1',
        'points': [{'date': '2026-08-01', 'destination_demand_qty': 10, 'local_share': 0.5}],
    }


def test_sku_render_offers_bounded_episodes_before_destination_is_resolved():
    js = r"""(()=>{const makeEpisode=(id,destination)=>({episode_id:id,sku:'A',destination_cluster_id:destination,start_date:'2026-08-01',end_date:'2026-08-02',external_quantity:3,economics:{complete:false}});const episodes=[makeEpisode('m1','Москва'),makeEpisode('k1','Казань'),...Array.from({length:33},(_,i)=>makeEpisode('x'+i,'Город '+i))];const snapshot={stockout_impact:{episodes,destination_daily_series:[]}},render=episodePage=>{const state={selectedEpisodeId:null,dailyPage:1,episodePage},container={innerHTML:'',querySelectorAll:()=>[]};SkladOzon.FlowTimeline.render(container,snapshot,{mode:'sku',key:'A',destination:null},state,()=>{});return container.innerHTML},html=render(1),page2=render(2);return {html,rendered:(html.match(/data-episode=/g)||[]).length,page2Rendered:(page2.match(/data-episode=/g)||[]).length,page2};})()"""
    rendered = node(js)
    assert 'Выберите маршрут или период замещения.' in rendered['html']
    assert 'Вероятные периоды замещения' in rendered['html']
    assert 'Москва' in rendered['html'] and 'Казань' in rendered['html']
    assert 'data-episode="m1"' in rendered['html']
    assert 'data-episode="k1"' in rendered['html']
    assert rendered['rendered'] == 20
    assert '1 / 2' in rendered['html']
    assert rendered['page2Rendered'] == 15
    assert '2 / 2' in rendered['page2']


def test_sku_pre_destination_episode_button_updates_selected_episode():
    js = r"""(()=>{const episode={episode_id:'m1',sku:'A',destination_cluster_id:'Москва',start_date:'2026-08-01',end_date:'2026-08-02',external_quantity:3,economics:{complete:false}};let changed=null;const button={dataset:{episode:'m1'},onclick:null};const container={innerHTML:'',querySelectorAll:selector=>selector==='[data-episode]'?[button]:[]};const state={selectedEpisodeId:null,dailyPage:1,episodePage:1};SkladOzon.FlowTimeline.render(container,{stockout_impact:{episodes:[episode],destination_daily_series:[]}},{mode:'sku',key:'A',destination:null},state,next=>{changed=next});button.onclick();return changed.selectedEpisodeId;})()"""
    assert node(js) == 'm1'


def test_unresolved_timeline_empty_and_origin_copy_remain_explicit():
    js = r"""(()=>{const snapshot={stockout_impact:{episodes:[],destination_daily_series:[]}},state={selectedEpisodeId:null,dailyPage:1,episodePage:1},render=mode=>{const container={innerHTML:'',querySelectorAll:()=>[]};SkladOzon.FlowTimeline.render(container,snapshot,{mode,key:'A',destination:null},state,()=>{});return container.innerHTML};return [render('sku'),render('origin')]})()"""
    sku, origin = node(js)
    assert 'Вероятных периодов замещения не обнаружено.' in sku
    assert 'Выберите destination-маршрут.' in origin
    assert 'Вероятные периоды замещения' not in origin
