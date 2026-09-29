import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
MODULE = ROOT / 'frontend/assets/js/economics_workspace.js'


def node(expression):
    script = (f"globalThis.SkladOzon={{escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;')}};"
              f"require({json.dumps(str(MODULE))});"
              f"console.log(JSON.stringify({expression}))")
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def test_real_report_rows_show_ozon_commission_target_and_sku_disclosure():
    product = {'sku': 'SKU-1', 'article': '26572', 'name': '<Розетка>',
               'qty': 15, 'covered_qty': 10, 'partial': True,
               'price': '100', 'commission_rate': '.25', 'assumed_drr_rate': '.05',
               'planned_drr_rate': '.10', 'profit_per_unit': '13', 'margin': '.13',
               'roi': '.325', 'modeled_shortfall': '70',
               'target_price_all_routes': None, 'below_margin': True,
               'below_roi': True, 'groups': {'destination': [], 'origin': []}}
    markup = node(f"SkladOzon.EconomicsWorkspace.productRows({json.dumps([product], ensure_ascii=False)},{{target_margin:'0.2',target_roi:'0.4'}})")
    assert '26572' in markup and 'SKU-1' in markup
    assert '&lt;Розетка>' in markup and '<Розетка>' not in markup
    assert 'aria-expanded="false"' in markup and 'data-econ-sku="SKU-1"' in markup
    assert 'Неполный расчёт' in markup and 'Не рассчитано' in markup
    assert '25 %' in markup and '70 ₽' in markup
    assert 'В модели 5 %' in markup and 'econ-drr-error-0' in markup


def test_local_design_has_a_shared_surface_for_sku_and_cluster_disclosure():
    css = (ROOT / 'frontend/assets/css/workspace.css').read_text()
    assert '.econ-table tr.econ-sku-row.is-open>td' in css
    assert '.econ-table tr.econ-sku-detail>td' in css
    assert '.econ-cluster.is-open.is-below' in css
    html = (ROOT / 'frontend/index.html').read_text()
    assert '/assets/js/economics_workspace.js' in html
    assert '/assets/css/workspace.css' in html
