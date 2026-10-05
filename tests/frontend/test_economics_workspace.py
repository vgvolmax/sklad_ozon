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
               'price': '100', 'commission_rate': '.25', 'real_drr_rate': '.05',
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
    assert 'Реальный 5 %' in markup and 'econ-drr-error-0' in markup


def test_local_design_has_a_shared_surface_for_sku_and_cluster_disclosure():
    css = (ROOT / 'frontend/assets/css/workspace.css').read_text()
    assert '.econ-table tr.econ-sku-row.is-open>td' in css
    assert '.econ-table tr.econ-sku-detail>td' in css
    assert '.econ-cluster.is-open.is-below' in css
    html = (ROOT / 'frontend/index.html').read_text()
    assert '/assets/js/economics_workspace.js' in html
    assert '/assets/css/workspace.css' in html


def test_manual_model_drr_is_removed_and_cost_editor_keeps_saved_value():
    targets = node('SkladOzon.EconomicsWorkspace.validateTargets()')
    assert 'modeled_drr' not in targets
    product = {'sku': 'S', 'article': 'A', 'name': 'Товар', 'cost': '125.5',
               'cost_source': 'manual', 'qty': 0, 'price': '200', 'groups': {}}
    markup = node(f'SkladOzon.EconomicsWorkspace.productRows({json.dumps([product])})')
    assert 'data-econ-cost="S"' in markup and 'value="125.5"' in markup
    assert 'Ручная' in markup and 'econ-cost-error-0' in markup


def test_client_prices_keep_fact_above_plan_with_independent_coverage_and_zero():
    product = {'sku': 'S', 'article': 'A', 'name': 'Товар', 'price': '100',
        'target_price_all_routes': '80', 'groups': {}, 'buyer_prices': {
            'buyer_price_mean': '0', 'target_buyer_price': '32.00', 'spp_mean': '.6',
            'ordered_qty': 4, 'buyer_priced_qty': 2, 'spp_priced_qty': 3,
            'complete': False, 'pending': True}}
    markup = node(f'SkladOzon.EconomicsWorkspace.productRows({json.dumps([product])})')
    assert 'data-econ-buyer-price>0 ₽' in markup
    assert 'data-econ-target-buyer-price>32 ₽' in markup
    assert markup.index('data-econ-buyer-price') < markup.index('econ-plan') < markup.index('data-econ-target-buyer-price')
    assert 'Клиента · средняя' in markup and 'Клиента при цели' in markup
    assert '2 из 4 шт.' in markup and '3 из 4 шт.' in markup
    assert 'История неполная' in markup and 'Цены уточняются' in markup
    product['buyer_prices'].update(buyer_price_mean=None, target_buyer_price=None, spp_mean=None)
    markup = node(f'SkladOzon.EconomicsWorkspace.productRows({json.dumps([product])})')
    assert 'data-econ-buyer-price>Не рассчитано' in markup
    assert 'data-econ-target-buyer-price>Не рассчитано' in markup


def test_cost_validation_and_save_failure_restore_focus_with_dom_node_lists():
    script = f"""
    const assert=require('node:assert/strict');
    const calls=[];
    const input={{dataset:{{econCost:'S',article:'A'}},value:'',focus(){{calls.push('focus');}}}};
    const retry={{dataset:{{econCostRetry:'S'}}}},form={{}},download={{addEventListener(){{}}}};
    const list=values=>({{forEach:fn=>values.forEach(fn),[Symbol.iterator]:()=>values[Symbol.iterator]()}});
    const container={{innerHTML:'',querySelector(selector){{
      return selector==='#econ-target-form'?form:selector==='#econ-export'?download:null;
    }},querySelectorAll(selector){{
      return list(selector==='[data-econ-cost]'?[input]:selector==='[data-econ-cost-retry]'?[retry]:[]);
    }}}};
    let markup='',notifyChange=false;
    Object.defineProperty(container,'innerHTML',{{get(){{return markup;}},set(value){{
      if(notifyChange){{notifyChange=false;assert.equal(input.onchange(),undefined);}}
      markup=value;
    }}}});
    globalThis.document={{body:{{}},activeElement:null}};
    document.activeElement=document.body;
    globalThis.SkladOzon={{escapeHtml:String}};
    require({json.dumps(str(MODULE))});
    const product={{sku:'S',article:'A',name:'Товар',qty:0,cost:'100',price:'200',no_observations:true,groups:{{destination:[],origin:[]}}}};
    const report={{products:[product],goal:'margin',modeled_shortfall:'0',incomplete_sku_count:0,period:null}};
    const fetch=async url=>url.includes('cost-prices')
      ?(calls.push('save'),{{ok:false,json:async()=>({{error:{{message:'Диск недоступен'}}}})}})
      :{{ok:true,json:async()=>({{snapshot_id:'snap',workspace:report}})}};
    (async()=>{{
      SkladOzon.EconomicsWorkspace.render(container,{{snapshot_id:'snap'}},fetch);
      await new Promise(resolve=>setImmediate(resolve));
      notifyChange=true; // Removing a focused edited input can emit change while rendering.
      await input.onchange();
      assert.deepEqual(calls,['focus']);
      assert.ok(container.innerHTML.includes('Введите себестоимость'));
      input.value='125.5';
      await input.onchange();
      assert.ok(container.innerHTML.includes('Диск недоступен'));
      assert.ok(container.innerHTML.includes('Повторить сохранение'));
      await retry.onclick();
      assert.deepEqual(calls,['focus','save','focus','save','focus']);
    }})().catch(error=>{{console.error(error);process.exit(1);}});
    """
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
