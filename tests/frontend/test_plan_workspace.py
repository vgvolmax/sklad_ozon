import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def node(expression):
    scripts = ['core.js', 'components.js', 'plan_workspace.js']
    prefix = ';'.join(f'require({json.dumps(str(ROOT / "frontend/assets/js" / name))})' for name in scripts)
    return json.loads(subprocess.check_output(['node', '-e', f'{prefix};console.log(JSON.stringify({expression}))'], text=True))


def fixture():
    rows = [
        {'sku': 'S1', 'article': '40750', 'product_name': 'Кран', 'destination_cluster_id': 'Москва'},
        {'sku': 'S2', 'article': '40750', 'product_name': 'Кран другой', 'destination_cluster_id': 'Москва'},
        {'sku': 'S1', 'article': '40750', 'product_name': 'Кран', 'destination_cluster_id': 'Казань'},
    ]
    lines = [
        {**rows[0], 'working_qty': 40, 'total_volume_l': 4, 'status': 'READY', 'is_overridden': True},
        {**rows[1], 'working_qty': None, 'total_volume_l': None, 'status': 'ATTENTION'},
        {**rows[2], 'working_qty': 0, 'total_volume_l': 0, 'status': 'READY'},
    ]
    return {'decision_rows': rows, 'shippable_plan': {'lines': []}}, {'lines': lines}


def model(view):
    snapshot, working = fixture()
    return node(f'SkladOzon.PlanWorkspace.buildModel({json.dumps(snapshot, ensure_ascii=False)},{json.dumps(working, ensure_ascii=False)},{json.dumps(view, ensure_ascii=False)})')


def test_search_filters_cards_without_changing_selected_workspace():
    result = model({'perspective': 'cluster', 'selectedClusterId': 'Москва', 'clusterQuery': 'Казань'})
    assert [x['id'] for x in result['visible']] == ['Казань']
    assert result['selected']['id'] == 'Москва'
    empty = model({'perspective': 'cluster', 'selectedClusterId': 'Москва', 'clusterQuery': 'нет совпадений'})
    assert empty['visible'] == [] and empty['selected']['id'] == 'Москва'


def test_duplicate_articles_remain_separate_sku_cards():
    result = model({'perspective': 'product', 'selectedSku': 'S2'})
    assert [x['id'] for x in result['all']] == ['S1', 'S2']
    assert result['selected']['id'] == 'S2'
    assert all(x['duplicateArticle'] for x in result['all'])


def test_partial_context_labels_known_subtotal_without_unknown_as_zero():
    result = model({'perspective': 'cluster', 'selectedClusterId': 'Москва'})
    assert result['selected']['stats']['qty'] == 40
    assert result['selected']['stats']['unknown'] == 1
    assert result['selected']['stats']['attention'] == 1
    assert result['selected']['stats']['manual'] == 1
    kazan = next(item for item in result['all'] if item['id'] == 'Казань')
    assert kazan['stats']['qty'] == 0
    assert kazan['stats']['unknown'] == 0


def test_row_filters_include_zero_as_decided_and_exclude_unknown_positive():
    snapshot, working = fixture()
    prefix = f'const m=SkladOzon.PlanWorkspace.buildModel({json.dumps(snapshot)},{json.dumps(working)},{{perspective:"cluster",selectedClusterId:"Москва"}});'
    result = node('(()=>{' + prefix + 'return ["all","attention","positive","overridden"].map(f=>SkladOzon.PlanWorkspace.filterRows(m.rows,f).map(r=>r.sku));})()')
    assert result == [['S1', 'S2'], ['S2'], ['S1'], ['S1']]


def test_next_attention_wraps_and_full_list_selection_reveals_card():
    snapshot, working = fixture()
    expression = '(()=>{const S=SkladOzon;const state={...S.createInitialState(),snapshot:'+json.dumps(snapshot)+',workingPlan:{plan:'+json.dumps(working)+'},planView:{perspective:"cluster",selectedClusterId:"Казань",clusterQuery:"Казань",selectorFilter:"manual"}};const m=S.PlanWorkspace.buildModel(state.snapshot,state.workingPlan.plan,state.planView);const next=S.PlanWorkspace.nextAttention(m);const selected=S.PlanWorkspace.selectContext(state,"Москва");return {next,query:selected.planView.clusterQuery,filter:selected.planView.selectorFilter,selected:selected.planView.selectedClusterId,shipmentScope:selected.shipmentView.selectedClusters};})()'
    assert node(expression) == {'next': 'Москва', 'query': '', 'filter': 'all', 'selected': 'Москва', 'shipmentScope': []}


def test_card_html_escapes_identity_and_has_usable_keyboard_target():
    result = node('SkladOzon.PlanWorkspace.cardMarkup({id:"A\\\"<",article:"<b>",name:"<script>",sku:"A",stats:{qty:0,unknown:1,attention:1,manual:0}},"A\\\"<","product",0)')
    assert '<script>' not in result and '&lt;script&gt;' in result
    assert 'aria-pressed="true"' in result and 'tabindex="0"' in result
    assert 'Принято' in result


def test_loading_failure_keeps_unknown_context_without_browser_quantity_fallback():
    snapshot, _ = fixture()
    result = node(f'SkladOzon.PlanWorkspace.buildModel({json.dumps(snapshot)},null,{{perspective:"product",selectedSku:"S1"}}).selected.stats')
    assert result['unknown'] == 2
    assert result['qty'] == 0
    assert result['ready'] == 0
