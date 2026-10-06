"""Thin period-model routes reusing immutable pricing and account finance reads."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from backend.ozon.vault import OzonVaultError
from .period_profit import build_period_profit
from .selection import select_products
from .export import export_period_profit

router = APIRouter(prefix='/api/economics/period')


async def _report(request, export=False):
    from backend import api
    body = await api.json_object(request)
    if body is None:
        return api.error(400, 'INVALID_PERIOD_PROFIT', 'Укажите параметры расчёта.', None)
    context = None
    finance = None
    try:
        finance_id = body.get('finance_snapshot_id')
        if finance_id is not None:
            context = api.OZON_VAULT.capture_context()
            finance = api.FINANCE_STORE.get(finance_id) if isinstance(finance_id, str) else None
            if finance is None or finance.credential_context_id != context.context_id:
                return api.error(409, 'FINANCE_SNAPSHOT_STALE', 'Загрузите расходы текущего кабинета.', None)
        result = await api._economics_report(request, scenario={**body, 'search':'', 'filter':'all'},
            include_historical=True, additional_skus={p.sku for p in finance.products} if finance else ())
        if not isinstance(result, tuple):
            return result
        snapshot, pricing = result
        if finance is not None:
            if (pricing['period'] is None or finance.period_start > pricing['period']['from'] or
                    finance.period_end < pricing['period']['to']):
                return api.error(409, 'FINANCE_PERIOD_CHANGED', 'Загрузите расходы за выбранные даты.', None)
        search, filter = body.get('search', ''), body.get('filter', 'all')
        selected = select_products(pricing['products'], search=search, filter=filter)
        if pricing['period'] is None:
            raise ValueError('Загрузите датированную историю заказов.')
        report = build_period_profit(pricing['products'], pricing['period'],
            getattr(snapshot, 'economics_order_quantities', ()), finance, body.get('mode', 'orders'),
            selected_skus=None if not search.strip() and filter == 'all' else {p['sku'] for p in selected},
            history_complete=getattr(snapshot, 'economics_order_quantities_complete', pricing['history_complete']))
        if export and report['mode'] == 'buyouts' and not report['expenses_complete']:
            return api.error(400, 'FINANCE_REQUIRED',
                'Загрузите начисления за выбранный период: для отчёта нужны количества выкупов.', 'finance_snapshot_id')
        report['pricing_basis_id'] = pricing.get('pricing_basis_id', snapshot.snapshot_id)
        report['analysis_snapshot_id'] = snapshot.snapshot_id
        if export and not report['products'] and report['catalog_product_count']:
            raise ValueError('В фильтре нет товаров для выгрузки.')
        data = export_period_profit(report) if export else api.wire(report)

        def commit():
            if not api._economics_report_is_current(snapshot, pricing):
                return api.error(409, 'ECONOMICS_INPUT_CHANGED', 'Данные изменились. Обновите расчёт.', None)
            if export:
                return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':'attachment; filename="period-profit.xlsx"', 'Cache-Control':'no-store'})
            return JSONResponse({'api_version':2, 'workspace':data}, headers={'Cache-Control':'no-store'})
        return api.commit_active_credential_context(context, commit) if context is not None else commit()
    except OzonVaultError:
        return api.error(423, 'OZON_VAULT_LOCKED', 'Разблокируйте доступ к Ozon на экране Данные.', None)
    except ValueError as exc:
        return api.error(400, 'INVALID_PERIOD_PROFIT', str(exc), None)


@router.post('/workspace')
async def workspace(request: Request):
    return await _report(request)


@router.post('/export')
async def export(request: Request):
    return await _report(request, export=True)
