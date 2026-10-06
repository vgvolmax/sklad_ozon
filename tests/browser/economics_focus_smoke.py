"""Filtered downloads, price directions and focused articles on the real API."""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import socket
import tempfile
import threading
import time

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect
import uvicorn

import backend.api as api
from backend.advertising_store import AdvertisingData, save_advertising
from backend.domain.advertising import AdvertisingDay, AdvertisingCampaign
from backend.main import app
from backend.security import LOCAL_SESSION_HEADER, current_local_session_token
from tests.api.test_analysis import _analysis_files, _analysis_data, PRODUCT_HEADERS, TARIFF_HEADERS
from tests.helpers.xlsx_fixtures import make_xlsx

ROOT = Path(__file__).parents[2]
ARTIFACTS = ROOT / 'test-artifacts/economics-focus'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        api.PROJECT_PATH = Path(directory) / 'project.json'
        api.ANALYSIS_STORE.clear()
        files = _analysis_files()
        clusters = [f'Кластер {i:02}' for i in range(1, 22)]
        files['tariffs_file'] = ('tariffs.xlsx', make_xlsx(headers=TARIFF_HEADERS,
            rows=[['Москва', destination, 0, '', '', '', 50] for destination in ['Москва', *clusters]]))
        files['product_economics_file'] = ('products.xlsx', make_xlsx(headers=PRODUCT_HEADERS,
            rows=[[f'SKU-{i}', 'DUP' if i < 3 else f'ART-{i}', 900 if i == 2 else 100,
                   20, 1000, '10%', 1] for i in range(1, 15)]))
        orders = [f'SKU-1;1;1000;200;Москва;{c};Доставлен;2026-09-01T10:00:00' for c in clusters]
        orders += ['SKU-1;3;1000;800;Москва;Москва;Доставлен;2026-09-02T10:00:00',
                   'SKU-1;4;1000;500;Москва;Москва;Доставлен;2026-09-30T10:00:00']
        orders += [f'SKU-{i};2;1000;500;Москва;Москва;Доставлен;2026-09-02T10:00:00' for i in range(2, 15)]
        files['orders_file'] = ('orders.csv', ('SKU;Количество;Цена продавца;Цена покупателя;Кластер отгрузки;Кластер доставки;Статус;Принят в обработку\n' + '\n'.join(orders)).encode())
        save_advertising(api.PROJECT_PATH.with_name('advertising.json'), AdvertisingData(
            tuple(AdvertisingDay('1', 'SKU-1', date(2026, 9, day), Decimal(spend))
                  for day, spend in ((1, 100), (2, 50), (30, 900))),
            (AdvertisingCampaign('1', 'test.xlsx', '2026-10-02T08:00:00+00:00'),)))
        with TestClient(app, base_url='http://127.0.0.1', headers={LOCAL_SESSION_HEADER: current_local_session_token()}) as client:
            response = client.post('/api/analysis', files=files, data=_analysis_data(
                as_of='2026-09-30', orders_period_from='2026-09-01', orders_period_to='2026-09-30'))
            assert response.status_code == 200, response.text
            snapshot = response.json()['snapshot']
        before = api.wire(api.ANALYSIS_STORE.latest())
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ru-RU', accept_downloads=True,
                                              permissions=['clipboard-read', 'clipboard-write'])
                page = context.new_page(); page.set_default_timeout(5000)
                errors = []; external = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: external.append(request.url) if not request.url.startswith(f'http://127.0.0.1:{sock.getsockname()[1]}/') else None)
                source = (ROOT / 'frontend/assets/js/app.js').read_text()
                source = source.replace("if(root.document)document.addEventListener('DOMContentLoaded',S.boot);",
                    'S.__focusTest={setState(value){setState(value);}};')
                page.route('**/assets/js/app.js', lambda route: route.fulfill(body=source, content_type='text/javascript'))
                page.goto(f'http://127.0.0.1:{sock.getsockname()[1]}/')
                page.evaluate("snapshot=>{const S=SkladOzon;S.__focusTest.setState({...S.createInitialState(),section:'economics',snapshot});}", snapshot)
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                expect(page.locator('[data-econ-profit]')).to_be_visible()
                # Export includes every matching SKU, even beyond the display limit.
                with page.expect_download() as downloaded:
                    page.locator('#econ-export').click()
                sheet = load_workbook(BytesIO(Path(downloaded.value.path()).read_bytes())).active
                assert sheet.max_row == 15
                assert {sheet.cell(r, 15).value for r in range(2, 16)} == {f'SKU-{i}' for i in range(1, 15)}
                # Search/summary/export use exactly the same selection.
                page.locator('#econ-search').fill('SKU-14')
                expect(page.locator('.econ-sku-row')).to_have_count(1)
                with page.expect_download() as downloaded:
                    page.locator('#econ-export').click()
                sheet = load_workbook(BytesIO(Path(downloaded.value.path()).read_bytes())).active
                assert sheet.max_row == 2 and sheet.cell(2, 15).value == 'SKU-14'
                page.locator('#econ-search').fill('нет такого')
                expect(page.locator('.econ-sku-row')).to_have_count(0)
                expect(page.locator('#econ-export')).to_be_disabled()
                page.locator('#econ-search-clear').click()
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                page.locator('[data-econ-filter="lower"]').click()
                expect(page.locator('[data-econ-filter="lower"]')).to_have_attribute('aria-pressed', 'true')
                expect(page.locator('.econ-price-lower')).to_have_count(12)
                with page.expect_download() as downloaded:
                    page.locator('#econ-export').click()
                sheet = load_workbook(BytesIO(Path(downloaded.value.path()).read_bytes())).active
                assert sheet.max_row == 14 and 'SKU-2' not in {sheet.cell(r, 15).value for r in range(2, 15)}
                page.locator('[data-econ-filter="all"]').click()
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                # Export failure keeps the report usable and the button retryable.
                page.route('**/api/economics/export', lambda route: route.fulfill(status=503,
                    json={'error': {'message': 'Проверочная временная ошибка выгрузки'}}), times=1)
                page.locator('#econ-export').click()
                expect(page.locator('#econ-export-error')).to_contain_text('временная ошибка')
                expect(page.locator('#econ-export')).to_be_enabled()
                with page.expect_download() as downloaded:
                    page.locator('#econ-export').click()
                assert downloaded.value.failure() is None
                # A late search response cannot overwrite a newer selection.
                pending = []
                def delay_workspace(route):
                    pending.append((route, route.fetch()))
                page.route('**/api/economics/workspace', delay_workspace, times=1)
                page.locator('#econ-search').fill('SKU-14')
                for _ in range(100):
                    if pending: break
                    page.wait_for_timeout(25)
                assert pending
                page.locator('#econ-search').fill('DUP')
                expect(page.locator('.econ-sku-row')).to_have_count(2)
                route, response = pending.pop(); route.fulfill(response=response)
                expect(page.locator('.econ-sku-row')).to_have_count(2)
                # A download captured for a previous filter must not be offered.
                downloads = []; page.on('download', lambda value: downloads.append(value))
                page.route('**/api/economics/export', delay_workspace, times=1)
                page.locator('#econ-export').click()
                for _ in range(100):
                    if pending: break
                    page.wait_for_timeout(25)
                assert pending
                page.locator('#econ-search').fill('нет такого')
                expect(page.locator('.econ-sku-row')).to_have_count(0)
                route, response = pending.pop(); route.fulfill(response=response)
                expect(page.locator('#econ-export-error')).to_contain_text('Параметры изменились')
                assert not downloads
                page.locator('#econ-search-clear').click()
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                # IME input does not submit an unfinished query.
                search = page.locator('#econ-search')
                search.dispatch_event('compositionstart')
                search.evaluate("el=>{el.value='DUP';el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,data:'DUP'}));}")
                page.wait_for_timeout(350)
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                search.dispatch_event('compositionend')
                expect(page.locator('.econ-sku-row')).to_have_count(2)
                page.locator('#econ-search-clear').click()
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                page.locator('#econ-search').fill('SKU-1')
                # Search matches SKU-10...14 too; exact product-name search isolates SKU-1.
                page.locator('#econ-search').fill('Кластер 01')
                expect(page.locator('.econ-sku-row')).to_have_count(1)
                page.locator('#econ-period-from').fill('2026-09-02')
                page.locator('#econ-period-to').fill('2026-09-02')
                page.locator('#econ-period-apply').click()
                # This selection has no matching cluster on this date.
                expect(page.locator('.econ-sku-row')).to_have_count(0)
                page.locator('#econ-search-clear').click()
                page.locator('#econ-search').fill('DUP')
                expect(page.locator('.econ-sku-row')).to_have_count(2)
                # Store total: 3×680 + 2×(-120) + 12×2×680 = 18120.
                # SKU advertising files affect DRR; they are not the store ledger.
                expect(page.locator('[data-econ-profit-before]')).to_contain_text('18\u00a0120')
                expect(page.locator('[data-buyout-ads]')).to_contain_text('Не рассчитано')
                expect(page.locator('[data-buyout-final]')).to_contain_text('Не рассчитано')
                page.screenshot(path=str(ARTIFACTS / 'filtered-summary.png'), full_page=True)
                page.locator('#econ-period-reset').click()
                page.locator('#econ-search-clear').click()
                expect(page.locator('.econ-sku-row')).to_have_count(12)
                page.locator('[data-econ-more]').click()
                expect(page.locator('.econ-sku-row')).to_have_count(14)
                table = page.locator('.econ-table-scroll')
                table.evaluate('el=>el.scrollTop=90')
                article = page.locator('[data-econ-sku="SKU-1"]')
                article.scroll_into_view_if_needed()
                return_y = page.evaluate('scrollY'); return_top = table.evaluate('el=>el.scrollTop')
                article.click()
                expect(page.locator('.econ-sku-row')).to_have_count(1)
                expect(page.locator('[data-econ-close]')).to_be_in_viewport()
                clusters = page.locator('.econ-clusters')
                assert clusters.evaluate('el=>el.scrollHeight>el.clientHeight')
                expect(clusters).to_have_css('overscroll-behavior-y', 'contain')
                fixed_y = article.bounding_box()['y']; window_y = page.evaluate('scrollY')
                box = clusters.bounding_box()
                page.mouse.move(box['x'] + 100, box['y'] + 80); page.mouse.wheel(0, 10000)
                page.wait_for_timeout(150)
                assert clusters.evaluate('el=>el.scrollTop') > 0
                page.mouse.wheel(0, 10000); page.wait_for_timeout(150)
                assert abs(article.bounding_box()['y']-fixed_y)<2
                assert abs(page.evaluate('scrollY')-window_y)<2
                expect(page.locator('[data-econ-close]')).to_be_in_viewport()
                # Scenario edits keep the focused article and cluster scroll stable.
                cluster_top = clusters.evaluate('el=>el.scrollTop')
                drr = page.locator('[data-econ-drr="SKU-1"]')
                drr.fill('7'); drr.dispatch_event('change')
                expect(page.locator('.econ-page')).to_have_attribute('aria-busy', 'false')
                expect(page.locator('.econ-sku-row')).to_have_count(1)
                assert abs(clusters.evaluate('el=>el.scrollTop')-cluster_top)<2
                assert abs(article.bounding_box()['y']-fixed_y)<2
                # Copy has no hover tooltip and does not collapse the article.
                copy = page.locator('[data-econ-copy="SKU-1"]')
                assert copy.get_attribute('title') is None
                copy.click()
                expect(page.locator('[data-econ-copy-status]')).to_have_text('SKU скопирован')
                assert page.evaluate('navigator.clipboard.readText()') == 'SKU-1'
                expect(article).to_have_attribute('aria-expanded', 'true')
                assert abs(page.evaluate('scrollY')-window_y)<2
                # Denial is reported truthfully and remains keyboard-operable.
                page.evaluate("()=>{window.realWrite=navigator.clipboard.writeText.bind(navigator.clipboard);navigator.clipboard.writeText=()=>Promise.reject(Error('denied'));}")
                copy.press('Enter')
                expect(page.locator('[data-econ-copy-status]')).to_contain_text('Не удалось скопировать')
                page.evaluate('()=>{navigator.clipboard.writeText=window.realWrite;}')
                # Older async clicks cannot show a false success for a newer one.
                page.evaluate("()=>{window.copyCalls=[];navigator.clipboard.writeText=()=>new Promise((resolve,reject)=>copyCalls.push({resolve,reject}));}")
                copy.click(); copy.click()
                page.evaluate("()=>{copyCalls[1].reject(Error('denied'));copyCalls[0].resolve();}")
                expect(page.locator('[data-econ-copy-status]')).to_contain_text('Не удалось скопировать')
                page.evaluate('()=>{navigator.clipboard.writeText=window.realWrite;}')
                # The selected article's own charts remain accessible.
                daily = page.locator('[data-daily-sku="SKU-1"]')
                daily.locator('[data-daily-toggle]').click()
                expect(daily.locator('.econ-daily-plot')).to_be_visible()
                daily.locator('.econ-daily-plot').focus(); page.keyboard.press('Escape')
                expect(article).to_have_attribute('aria-expanded', 'true')
                page.screenshot(path=str(ARTIFACTS / 'focused-desktop.png'), full_page=True)
                # A resized shared header cannot cover the sticky close strip.
                page.set_viewport_size({'width':390,'height':844})
                bar=page.locator('.econ-focus-bar')
                bar.evaluate("el=>window.scrollTo(0,el.offsetTop+80)")
                header_bottom=page.locator('.app-header').bounding_box()['y']+page.locator('.app-header').bounding_box()['height']
                assert bar.bounding_box()['y'] >= header_bottom-1
                page.set_viewport_size({'width':1440,'height':1000})
                # Applying even unchanged global targets preserves load-more extent.
                page.locator('#econ-target-form button[type="submit"]').click()
                expect(page.locator('.econ-page')).to_have_attribute('aria-busy', 'false')
                expect(page.locator('.econ-sku-row')).to_have_count(1)
                page.locator('[data-econ-close]').click()
                expect(page.locator('.econ-sku-row')).to_have_count(14)
                assert abs(page.evaluate('scrollY')-return_y)<2
                assert abs(table.evaluate('el=>el.scrollTop')-return_top)<2
                expect(article).to_be_focused()
                article.click(); clusters.focus(); page.keyboard.press('Escape')
                expect(page.locator('.econ-sku-row')).to_have_count(14)
                # Independent horizontal overflow and reachable close on narrow screens.
                page.set_viewport_size({'width':390,'height':844})
                page.emulate_media(reduced_motion='reduce')
                article.click()
                expect(page.locator('[data-econ-close]')).to_be_in_viewport()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                copy.click(); expect(page.locator('[data-econ-copy-status]')).to_have_text('SKU скопирован')
                popup=page.locator('[data-econ-copy-status]').bounding_box()
                assert popup['x']>=0 and popup['x']+popup['width']<=390
                expect(page.locator('[data-econ-close]')).to_be_in_viewport()
                page.screenshot(path=str(ARTIFACTS / 'focused-narrow.png'))
                page.locator('[data-econ-close]').click()
                assert not errors, errors
                assert not external, external
                assert api.wire(api.ANALYSIS_STORE.latest()) == before
                browser.close()
                print('Economics focus browser: filtered XLSX, stale requests, lower prices, retry, period profit, cluster containment/restoration, stable edit, charts, clipboard success/denial/races, keyboard and narrow layout passed.')
        finally:
            server.should_exit = True; thread.join(timeout=10); sock.close()


if __name__ == '__main__':
    main()
