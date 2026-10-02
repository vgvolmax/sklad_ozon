"""Explicit account-scoped financial reporting, independent of planning sources."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from queue import Queue
from threading import Event, Thread

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend.economics.buyouts import build_buyout_report
from backend.economics.export import export_buyouts
from backend.ozon.adapters.finance import fetch_finance, finance_period
from backend.ozon.client import OzonClientError
from backend.ozon.vault import OzonVaultError
from backend.shipment.api_context import ShipmentPreparationError

router = APIRouter(prefix='/api/economics/buyouts')


def _current(api, snapshot):
    if api.ANALYSIS_STORE.latest() is not snapshot:
        raise ShipmentPreparationError('ANALYSIS_SNAPSHOT_STALE',
            'Данные изменились. Пересчитайте план.', 'analysis_snapshot_id', 409)


async def _report(request, *, export=False):
    from backend import api
    body = await api.json_object(request)
    if body is None:
        return api.error(400, 'INVALID_BUYOUT_REPORT', 'Укажите данные расчёта.', None)
    try:
        context = api.OZON_VAULT.capture_context()
        analysis_id = body.get('analysis_snapshot_id')
        finance_id = body.get('finance_snapshot_id')
        with api.PROJECT_PERSISTENCE_LOCK:
            snapshot = api.ANALYSIS_STORE.get(analysis_id) if isinstance(analysis_id, str) else None
            if snapshot is None:
                return api.error(409, 'ANALYSIS_SNAPSHOT_STALE', 'Загрузите себестоимость и пересчитайте план.', 'analysis_snapshot_id')
            _current(api, snapshot)
        finance = api.FINANCE_STORE.get(finance_id) if isinstance(finance_id, str) else None
        if finance is None or finance.credential_context_id != context.context_id:
            return api.error(409, 'FINANCE_SNAPSHOT_STALE', 'Загрузите начисления для текущего кабинета.', 'finance_snapshot_id')
        names = {row.sku: (row.article, row.product_name) for row in snapshot.decision_rows}
        report = build_buyout_report(finance, snapshot.buyout_cost_inputs, names,
            search=body.get('search', ''), filter=body.get('filter', 'all'))
        if export and not report['products'] and report['catalog_product_count']:
            return api.error(400, 'EMPTY_SELECTION', 'В фильтре нет товаров для выгрузки.', 'filter')
        data = export_buyouts(report) if export else api.wire(report)

        def commit():
            with api.PROJECT_PERSISTENCE_LOCK:
                _current(api, snapshot)
                if export:
                    return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="buyouts.xlsx"', 'Cache-Control': 'no-store'})
                return JSONResponse({'api_version': 1, 'workspace': data}, headers={'Cache-Control': 'no-store'})
        return api.commit_active_credential_context(context, commit)
    except OzonVaultError:
        return api.error(423, 'OZON_VAULT_LOCKED', 'Разблокируйте доступ к Ozon на экране Данные.', None)
    except ShipmentPreparationError as exc:
        return api.error(exc.http_status, exc.code, exc.message, exc.field)
    except ValueError as exc:
        return api.error(400, 'INVALID_BUYOUT_REPORT', str(exc), None)


@router.post('/workspace')
async def workspace(request: Request):
    return await _report(request)


@router.post('/export')
async def export(request: Request):
    return await _report(request, export=True)


@router.post('/sync')
async def sync(request: Request):
    from backend import api
    body = await api.json_object(request)
    if body is None:
        return api.error(400, 'INVALID_FINANCE_PERIOD', 'Укажите период начислений.', 'period')
    try:
        start, end = finance_period(body.get('period_from'), body.get('period_to'),
            today=datetime.now(timezone(timedelta(hours=3))).date())
        context = api.OZON_VAULT.capture_context()
    except ValueError as exc:
        return api.error(400, 'INVALID_FINANCE_PERIOD', str(exc), 'period')
    except OzonVaultError:
        return api.error(423, 'OZON_VAULT_LOCKED', 'Разблокируйте доступ к Ozon на экране Данные.', None)
    events, stopped = Queue(), Event()

    def progress(value):
        if stopped.is_set():
            raise InterruptedError()
        events.put({'type': 'progress', **value})

    def worker():
        try:
            finance = fetch_finance(api.OZON_CLIENT.bind_context(context), start, end,
                context.context_id, progress_callback=progress)
            if stopped.is_set():
                return
            api.commit_active_credential_context(context, lambda: api.FINANCE_STORE.put(finance))
            events.put({'type': 'result', 'data': {'finance_snapshot_id': finance.snapshot_id,
                'period': {'from': start.isoformat(), 'to': end.isoformat()}, 'loaded_at': finance.loaded_at}})
        except InterruptedError:
            pass
        except ShipmentPreparationError as exc:
            events.put({'type': 'error', 'error': {'code': exc.code, 'message': exc.message}})
        except ValueError as exc:
            events.put({'type': 'error', 'error': {'code': 'INVALID_FINANCE_DATA', 'message': str(exc)}})
        except OzonClientError as exc:
            events.put({'type': 'error', 'error': {'code': exc.code.value,
                'message': 'Не удалось загрузить начисления Ozon. Проверьте доступ и повторите загрузку.'}})
        except Exception:
            events.put({'type': 'error', 'error': {'code': 'FINANCE_SYNC_FAILED',
                'message': 'Не удалось загрузить начисления. Повторите загрузку.'}})
        finally:
            events.put(None)

    async def stream():
        thread = Thread(target=worker, name='finance-sync', daemon=True)
        thread.start()
        try:
            while True:
                item = await asyncio.to_thread(events.get)
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n'
        finally:
            stopped.set()
    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})
