"""Real loopback application and Seller client, with synthetic finance transport."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect
import uvicorn

import backend.api as api
from backend.main import app
from backend.ozon.client import OzonClient, TransportResponse
from backend.ozon.contracts import OzonCredentials
from backend.ozon.vault import CredentialVault
from backend.security import LOCAL_SESSION_HEADER, current_local_session_token
from tests.api.test_analysis import _two_sku_analysis_files, _analysis_data
from tests.ozon.test_finance import posting, money

ROOT = Path(__file__).parents[2]
ARTIFACTS = ROOT / 'test-artifacts/economics-buyouts'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        api.PROJECT_PATH = Path(directory) / 'project.json'
        api.OZON_VAULT = CredentialVault(Path(directory) / 'vault.json')
        api.OZON_VAULT.setup(OzonCredentials('synthetic-account', 'synthetic-key'), 'test-password')
        api.ANALYSIS_STORE.clear(); api.FINANCE_STORE.clear()
        fail = [False]
        switch_account = [False]
        calls = []
        def transport(request, timeout):
            path = urlparse(request.full_url).path
            body = json.loads(request.data)
            calls.append((path, body))
            if path.endswith('/types'):
                payload = {'accrual_types': [{'id': 1, 'name': 'Реклама'}, {'id': 2, 'name': 'Кросс-докинг'}]}
            elif path.endswith('/by-day'):
                if switch_account[0]:
                    switch_account[0] = False
                    api.OZON_VAULT.setup(OzonCredentials('other-account', 'other-key'), 'test-password')
                day = body['date']; rows = []
                if fail[0]:
                    payload = {'accruals': [posting(total_amount=money('NaN'))], 'last_id': ''}
                else:
                    if day == '2026-09-01':
                        first = posting(); first['posting']['products'][0]['sku'] = 'SKU-1'
                        second = deepcopy(first); second['accrual_id'] = '2'; second['total_amount'] = money(600)
                        product = second['posting']['products'][0]; product['sku'] = 'SKU-2'
                        product['commission'].update(sale_amount=money(400), commission=money(300))
                        product['delivery']['total_accrued'] = money(-100)
                        rows = [first, second, {'accrual_id': 'ad', 'accrued_category': 'NON_ITEM', 'date': day,
                            'total_amount': money(-100), 'non_item_fee': {'type_id': 1, 'accrued': money(-100)}}]
                    if day == '2026-09-02':
                        returned = posting('return', date=day, total_amount=money(-600))
                        product = returned['posting']['products'][0]; product['sku'] = 'SKU-1'
                        product['commission'].update(sale_amount=money(-400), sale_price=money(-400), commission=money(-100))
                        product['delivery']['total_accrued'] = money(-100)
                        rows = [returned, {'accrual_id': 'crossdock', 'accrued_category': 'NON_ITEM', 'date': day,
                            'total_amount': money(-50), 'non_item_fee': {'type_id': 2, 'accrued': money(-50)}}]
                    payload = {'accruals': rows, 'last_id': ''}
            else:
                raise AssertionError(path)
            return TransportResponse(200, {}, json.dumps(payload).encode())
        api.OZON_CLIENT = OzonClient(api.OZON_VAULT, transport=transport, sleeper=lambda _: None)
        with TestClient(app, base_url='http://127.0.0.1', headers={LOCAL_SESSION_HEADER: current_local_session_token()}) as client:
            client.put('/api/project/cost-prices/ART-1', json={'cost': '999'})
            response = client.post('/api/analysis', files=_two_sku_analysis_files(), data=_analysis_data())
            assert response.status_code == 200, response.text
            snapshot = response.json()['snapshot']
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
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
                page = context.new_page(); page.set_default_timeout(7000)
                errors, external = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: external.append(request.url) if not request.url.startswith(f'http://127.0.0.1:{port}/') else None)
                source = (ROOT/'frontend/assets/js/app.js').read_text().replace(
                    "if(root.document)document.addEventListener('DOMContentLoaded',S.boot);",
                    'S.__buyoutTest={setState(value){setState(value);}};')
                page.route('**/assets/js/app.js', lambda route: route.fulfill(body=source, content_type='text/javascript'))
                page.goto(f'http://127.0.0.1:{port}/')
                page.evaluate("snapshot=>{const S=SkladOzon;S.__buyoutTest.setState({...S.createInitialState(),section:'economics',snapshot});}", snapshot)
                page.locator('[data-econ-calculation="buyouts"]').click()
                expect(page.locator('#buyout-load')).to_be_enabled()
                page.locator('#buyout-from').fill('2026-09-01'); page.locator('#buyout-to').fill('2026-09-02')
                page.locator('#buyout-load').click()
                expect(page.locator('[data-buyout-row]')).to_have_count(2)
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                expect(page.locator('[data-buyout-ads]')).to_have_text('100 ₽')
                expect(page.locator('[data-buyout-row="SKU-1"]')).to_contain_text('100 ₽')
                page.screenshot(path=str(ARTIFACTS/'desktop.png'), full_page=True)
                page.locator('#buyout-search').fill('SKU-1')
                expect(page.locator('[data-buyout-row]')).to_have_count(1)
                expect(page.locator('[data-buyout-selected]')).to_have_text('1 000 ₽')
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                with page.expect_download() as download:
                    page.locator('#buyout-export').click()
                book = load_workbook(BytesIO(Path(download.value.path()).read_bytes()))
                assert book.sheetnames == ['Выкупы', 'Итог периода', 'Расходы']
                assert book['Выкупы'].max_row == 2 and book['Выкупы']['A2'].value == 'SKU-1'
                page.locator('[data-econ-copy="SKU-1"]').click()
                expect(page.locator('[data-econ-copy-status]')).to_contain_text('SKU скопирован')
                assert page.evaluate('navigator.clipboard.readText()') == 'SKU-1'
                page.locator('#buyout-search').fill('нет такого')
                expect(page.locator('#buyout-export')).to_be_disabled()
                page.locator('#buyout-clear').click(); expect(page.locator('[data-buyout-row]')).to_have_count(2)
                page.route('**/api/economics/buyouts/workspace', lambda route: route.fulfill(status=503,
                    json={'error': {'message': 'Временная ошибка расчёта'}}), times=1)
                page.locator('#buyout-search').fill('SKU-1')
                expect(page.locator('#buyout-error')).to_contain_text('Временная ошибка')
                expect(page.locator('#buyout-export')).to_be_disabled()
                page.locator('#buyout-retry').click()
                expect(page.locator('[data-buyout-row]')).to_have_count(1)
                expect(page.locator('#buyout-export')).to_be_enabled()
                page.locator('#buyout-clear').click(); expect(page.locator('[data-buyout-row]')).to_have_count(2)
                # Acquisition can succeed while final aggregation fails: preserve the prior pair.
                page.route('**/api/economics/buyouts/workspace', lambda route: route.fulfill(status=503,
                    json={'error': {'message': 'Временная ошибка итогового расчёта'}}), times=1)
                page.locator('#buyout-to').fill('2026-09-01'); page.locator('#buyout-load').click()
                expect(page.locator('#buyout-error')).to_contain_text('Временная ошибка итогового')
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                expect(page.locator('#buyout-progress')).to_contain_text('02.09.2026')
                with page.expect_download() as previous:
                    page.locator('#buyout-export').click()
                previous_book = load_workbook(BytesIO(Path(previous.value.path()).read_bytes()))
                previous_summary = {row[0].value: row[1].value for row in previous_book['Итог периода']}
                assert previous_summary['Период по'] == '2026-09-02'
                before_retry = len(calls)
                page.locator('#buyout-retry').click()
                expect(page.locator('[data-buyout-final]')).to_have_text('1 800 ₽')
                assert len(calls) == before_retry  # Retry aggregation without reloading Seller accruals.
                page.locator('#buyout-to').fill('2026-09-02'); page.locator('#buyout-load').click()
                expect(page.locator('#buyout-load')).to_be_enabled()
                fail[0] = True
                page.locator('#buyout-load').click()
                expect(page.locator('#buyout-error')).to_contain_text('Некорректная')
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                expect(page.locator('#buyout-load')).to_be_enabled()
                fail[0] = False
                page.locator('#buyout-load').click(); expect(page.locator('#buyout-error')).to_be_hidden()
                expect(page.locator('[data-buyout-row]')).to_have_count(2)
                # Retain selected period and filters when switching calculation mode.
                page.locator('[data-econ-calculation="orders"]').click()
                expect(page.locator('#econ-target-form')).to_be_visible()
                page.locator('[data-econ-calculation="buyouts"]').click()
                expect(page.locator('#buyout-from')).to_have_value('2026-09-01')
                expect(page.locator('[data-buyout-row]')).to_have_count(2)
                # Typed native dates validate accessibly and keep prior loaded period honest.
                page.locator('#buyout-to').fill('2026-08-01'); page.locator('#buyout-load').click()
                expect(page.locator('#buyout-period-error')).to_be_visible()
                expect(page.locator('#buyout-from')).to_be_focused()
                expect(page.locator('#buyout-progress')).to_contain_text('02.09.2026')
                page.locator('#buyout-to').fill('2026-09-02')
                page.locator('.buyout-expenses summary').click()
                expect(page.locator('.buyout-expenses')).to_contain_text('Кросс-докинг')
                page.set_viewport_size({'width': 760, 'height': 800})
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(ARTIFACTS/'narrow.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("[...document.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().width>innerWidth).slice(0,15).map(n=>[n.tagName,n.className,getComputedStyle(n).minWidth,n.getBoundingClientRect().width])")
                page.evaluate("document.documentElement.style.zoom='2'")
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(ARTIFACTS/'zoom-200.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), page.evaluate("[...document.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().width>innerWidth).slice(0,15).map(n=>[n.tagName,n.className,getComputedStyle(n).minWidth,n.getBoundingClientRect().width])")
                page.evaluate("document.documentElement.style.zoom='1'")
                # Returning to the same FILES analysis while an export is pending revalidates.
                pending = []
                page.route('**/api/economics/buyouts/export', lambda route: pending.append(route), times=1)
                page.locator('#buyout-export').click()
                for _ in range(100):
                    if pending: break
                    page.wait_for_timeout(25)
                assert pending
                api.OZON_VAULT.lock()
                page.evaluate("()=>{const S=SkladOzon;S.__buyoutTest.setState({...S.AppState});}")
                expect(page.locator('[data-buyout-final]')).to_have_count(0)
                pending.pop().continue_()
                expect(page.locator('#buyout-error')).to_contain_text('Разблокируйте')
                api.OZON_VAULT.unlock('test-password')
                page.locator('#buyout-load').click()
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                expect(page.locator('#buyout-load')).to_be_enabled()
                # Export alone handles a locked cabinet even without a navigation render.
                api.OZON_VAULT.lock(); page.locator('#buyout-export').click()
                expect(page.locator('#buyout-error')).to_contain_text('Разблокируйте')
                expect(page.locator('[data-buyout-final]')).to_have_count(0)
                api.OZON_VAULT.unlock('test-password'); page.locator('#buyout-load').click()
                expect(page.locator('[data-buyout-final]')).to_have_text('1 250 ₽')
                expect(page.locator('#buyout-load')).to_be_enabled()
                # A cabinet change while syncing must not leave the old cabinet's profit on screen.
                switch_account[0] = True
                page.locator('#buyout-load').click()
                expect(page.locator('#buyout-error')).to_be_visible()
                expect(page.locator('[data-buyout-final]')).to_have_count(0)
                assert not errors, errors
                assert not external, external
                browser.close()
        finally:
            server.should_exit = True; thread.join(timeout=10); sock.close()
        assert any(path.endswith('/by-day') for path, _ in calls)
    print('Economics buyout browser smoke passed')


if __name__ == '__main__':
    main()
