"""Exercise the production UI with synthetic API responses; never contact Ozon."""
import copy
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[2]
ARTIFACTS = ROOT / 'test-artifacts/plan-ui'


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def fixture():
    rows = []
    lines = []
    for sku, article, name, cluster, qty in [
        ('S1', '40750', 'Кран шаровой ½″', 'Москва', 20),
        ('S2', '40750', 'Кран шаровой ¾″, длинное название товара для проверки', 'Москва', None),
        ('S1', '40750', 'Кран шаровой ½″', 'Казань', 0),
        ('S3', '39439', 'Коллекторная группа, 3 контура', 'Москва', 10),
    ]:
        row = dict(sku=sku, article=article, product_name=name, destination_cluster_id=cluster,
                   current_fbo_stock=3, inbound_qty=2, ordered_qty_56d=30,
                   ordered_qty_horizon=30, need={'ozon_recommended_qty': 25, 'calculated_need_qty': 28},
                   calculated_plan_qty=20, status_codes=[], explanations=['Источник — тестовый снимок.'])
        rows.append(row)
        lines.append(dict(sku=sku, article=article, destination_cluster_id=cluster, system_qty=20,
                          working_qty=qty, total_volume_l=None if qty is None else qty * .2,
                          pack_multiple=10, status='ATTENTION' if qty is None else 'READY',
                          is_overridden=False, selected_source='CALCULATED', ozon_eligible=True,
                          reason_codes=[], delta_qty=None if qty is None else qty-20))
    ship = [dict(sku=r['sku'], destination_cluster_id=r['destination_cluster_id'], shippable_qty=20,
                 pack_multiple=10, unit_volume_l=.2, resolved_seller_stock=200,
                 placement_zones=['SORT'], reason_codes=[]) for r in rows]
    snap = dict(snapshot_id='A', created_at='2026-09-30T08:00:00+00:00', analysis_as_of='2026-09-30',
                source_mode='api', source_snapshot_id='source-A', scenario={'horizon_days': 56},
                decision_rows=rows, shippable_plan={'shippable_plan_id': 'SP', 'lines': ship},
                summary={}, diagnostics=[], freshness_warnings=[],
                ozon_recommendation={'horizon_days': 56, 'supply_period': 'EIGHT_WEEKS',
                    'analytics_from': '2026-07-08', 'analytics_to': '2026-09-30', 'fetched_at_utc': '2026-09-30T07:00:00Z'})
    return snap, dict(working_plan_id='WP', lines=lines, ready_count=3, attention_count=1,
                     blocked_count=0, overridden_count=0, orphan_override_count=0)


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT / 'frontend')))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    snapshot, working = fixture()
    requests, errors, external = [], [], []
    source = (ROOT / 'frontend/assets/js/app.js').read_text()
    hook = "if(root.document)document.addEventListener('DOMContentLoaded',S.boot);"
    assert hook in source
    source = source.replace(hook, "S.__browserPlan={setState(value){state=value;S.AppState=value;renderPlan();},getState(){return state;}};")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 960}, locale='ru-RU')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))

            def route_api(route):
                nonlocal working
                path = route.request.url.split('/api/', 1)[1]
                if path == 'local-session':
                    route.fulfill(json={'session_token': 'synthetic-session'})
                    return
                if path.startswith('working-plan/'):
                    payload = route.request.post_data_json
                    requests.append({'path': path, 'payload': payload})
                    if path.endswith('/override') and payload['quantity'] % 10:
                        route.fulfill(status=400, json={'error': {'message': 'Количество должно быть кратно 10 шт.'}})
                        return
                    next_plan = copy.deepcopy(working)
                    targets = next_plan['lines'] if path.endswith('reset-all') else payload.get('lines') or [payload]
                    for target in targets:
                        for line in next_plan['lines']:
                            if line['sku'] == target.get('sku') and line['destination_cluster_id'] == target.get('destination_cluster_id'):
                                if '/source' in path:
                                    line['selected_source'] = payload['source']
                                    line['system_qty'] = 30 if payload['source'] == 'OZON' else 20
                                    if payload['source'] == 'CALCULATED' and line['is_overridden']:
                                        continue
                                    qty, manual = line['system_qty'], False
                                else:
                                    line.update(selected_source='CALCULATED', system_qty=20)
                                    qty = payload.get('quantity', 0 if payload.get('action') == 'set_zero' else 20)
                                    manual = qty != 20
                                line.update(working_qty=qty, total_volume_l=qty*.2, status='READY', is_overridden=manual)
                    next_plan['working_plan_id'] += '-new'
                    working = next_plan
                    route.fulfill(json={'working_plan': working})
                    return
                route.fulfill(status=404, json={'error': {'message': 'Тест не разрешает этот запрос'}})

            page.route('**/api/**', route_api)
            page.route('**/assets/js/app.js', lambda route: route.fulfill(body=source, content_type='text/javascript'))
            def block_external(route):
                if not route.request.url.startswith('http://127.0.0.1:'):
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.fallback()
            page.route('**/*', block_external)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate("""({snapshot,working})=>{const S=SkladOzon,base=S.createInitialState();S.__browserPlan.setState({...base,snapshot,workingPlan:{...base.workingPlan,plan:working},planView:{...base.planView,selectedSku:'S1',selectedClusterId:'Москва'}});} """, {'snapshot': snapshot, 'working': working})
            assert page.locator('#plan-context-strip button').count() == 3
            assert page.locator('.plan-compact-table tbody[data-working-row]').count() == 2
            page.screenshot(path=str(ARTIFACTS / 'products.png'), full_page=True)
            search = page.locator('#article-search input')
            search.fill('ничего нет')
            assert page.locator('.plan-strip-empty').is_visible()
            assert page.locator('.plan-selected-heading').inner_text().startswith('40750')
            page.locator('#article-search button').click()
            assert page.locator('#article-search input').evaluate('(node)=>document.activeElement===node')
            page.locator('[data-perspective="cluster"]').click()
            page.locator('#plan-open-picker').click()
            page.locator('#plan-picker-search input').fill('Москва')
            page.locator('#plan-picker-grid button').click()
            assert page.locator('.plan-selected-heading h2').inner_text() == 'Москва'
            target_row = page.locator('[data-working-row="S1|||Москва"]')
            quantity_input = '[data-working-row="S1|||Москва"] [data-working-input]'
            target_row.locator('[data-plan-expand]').click()
            assert page.locator('.plan-row-group--expanded').count() == 1
            colors = page.locator('.plan-row-group--expanded td').evaluate_all('(nodes)=>nodes.map(n=>getComputedStyle(n).backgroundColor)')
            assert len(set(colors)) == 1
            page.screenshot(path=str(ARTIFACTS / 'cluster-expanded.png'), full_page=True)
            field = page.locator(quantity_input)
            field.fill('7')
            field.press('Enter')
            page.wait_for_function("(selector)=>document.querySelector(selector)?.getAttribute('aria-invalid')==='true'", arg=quantity_input)
            assert page.locator(quantity_input).input_value() == '7'
            assert target_row.locator('[data-working-input-error]').inner_text() == 'Количество должно быть кратно 10 шт.'
            field = page.locator(quantity_input)
            field.fill('40')
            field.press('Enter')
            page.wait_for_function("(selector)=>document.querySelector(selector)?.value==='40' && !SkladOzon.__browserPlan.getState().workingPlan.mutationBusy", arg=quantity_input)
            assert page.locator(quantity_input).evaluate('(node)=>document.activeElement===node')
            page.locator(quantity_input).fill('99')
            page.locator(quantity_input).press('Escape')
            assert page.locator(quantity_input).input_value() == '40'
            page.locator('#plan-row-filter-overridden').click()
            page.locator('.plan-bulk-menu summary').click()
            page.locator('#plan-zero-context').click()
            assert page.locator('dialog').is_visible()
            before = len(requests)
            page.locator('[data-dialog-cancel]').click()
            assert len(requests) == before
            page.locator('#plan-zero-context').click()
            page.locator('[data-dialog-confirm]').click()
            page.wait_for_function("!SkladOzon.__browserPlan.getState().workingPlan.mutationBusy")
            assert requests[-1]['payload']['lines'] == [{'sku': 'S1', 'destination_cluster_id': 'Москва'}]
            assert page.locator(quantity_input).input_value() == '0'
            # Returning to the system quantity removes the sole manual row.
            page.locator(quantity_input).fill('20')
            page.locator(quantity_input).press('Enter')
            page.wait_for_function("!SkladOzon.__browserPlan.getState().workingPlan.mutationBusy && !document.querySelector('[data-working-input]')")
            assert page.locator('#plan-row-filter-all').evaluate('(node)=>document.activeElement===node')
            page.locator('#plan-row-filter-all').click()
            page.locator('.plan-bulk-menu summary').click()
            page.locator('[data-working-source-bulk="OZON"]').click()
            assert page.locator('dialog').is_visible()
            before = len(requests)
            page.locator('[data-dialog-cancel]').click()
            assert len(requests) == before
            page.locator('[data-working-source-bulk="OZON"]').click()
            page.locator('[data-dialog-confirm]').click()
            page.wait_for_function("!SkladOzon.__browserPlan.getState().workingPlan.mutationBusy")
            assert requests[-1]['path'] == 'working-plan/source/bulk'
            assert len(requests[-1]['payload']['lines']) == 3
            page.locator('.plan-working-footer details summary').click()
            page.locator('#plan-reset-all').click()
            assert 'сняты ручные количества и выбор Ozon' in page.locator('dialog').inner_text()
            page.locator('[data-dialog-confirm]').click()
            page.wait_for_function("!SkladOzon.__browserPlan.getState().workingPlan.mutationBusy")
            assert all(line['selected_source'] == 'CALCULATED' for line in working['lines'])
            # A dialog opened against A must not apply old scope to a replacement B.
            page.locator('.plan-bulk-menu summary').click()
            page.locator('#plan-zero-context').click()
            before = len(requests)
            page.evaluate("""()=>{const S=SkladOzon,current=S.__browserPlan.getState();S.__browserPlan.setState({...current,snapshot:{...current.snapshot,snapshot_id:'B'}});} """)
            page.locator('[data-dialog-confirm]').click()
            assert len(requests) == before
            assert 'План изменился' in page.locator('.notice-error').inner_text()
            page.locator('#plan-go-shipments').click()
            assert page.locator('#shipment-date-from').is_visible()
            assert page.locator('[data-cluster]').count() >= 1
            assert not any('shipment/' in r['path'] for r in requests)
            page.locator('#plan-tab-products').click()
            page.set_viewport_size({'width': 720, 'height': 900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
            assert page.locator('.plan-compact-scroll').evaluate('(node)=>node.scrollWidth>node.clientWidth')
            page.screenshot(path=str(ARTIFACTS / 'narrow.png'), full_page=True)
            page.locator('#plan-open-picker').click()
            page.keyboard.press('Escape')
            assert page.locator('#plan-open-picker').evaluate('(node)=>document.activeElement===node')
            page.emulate_media(reduced_motion='reduce')
            assert not external, external
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps({'status': 'passed', 'screenshots': 3, 'external_requests': len(external),
                      'mutations': len(requests), 'browser_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
