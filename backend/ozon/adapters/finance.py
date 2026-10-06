"""Current Seller finance accruals, normalized without raw IDs or customer PII."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from uuid import uuid4

from backend.economics.buyouts import FinanceExpense, FinanceProductLine, FinanceSnapshot
from backend.ozon.client import OzonRequestPolicy
from backend.ozon.endpoints import FINANCE_ACCRUAL_TYPES_PATH, FINANCE_ACCRUAL_BY_DAY_PATH, FBO_POSTING_GET_PATH, FBS_POSTING_GET_PATH

READ = OzonRequestPolicy(retry_safe=True)
ZERO = Decimal('0')
MAX_PAGES_PER_DAY = 200
MAX_ACCRUALS = 200000


def finance_period(start, end, *, today=None):
    dates = []
    for value in (start, end):
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError('Укажите обе даты в формате ГГГГ-ММ-ДД.')
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError('Укажите даты в формате ГГГГ-ММ-ДД.')
        dates.append(parsed)
    first, last = dates
    if first > last or first < date(2022, 1, 1) or (last-first).days >= 366:
        raise ValueError('Выберите период до 366 дней начиная с 01.01.2022.')
    if today is not None and last > today:
        raise ValueError('Конец периода не может быть в будущем.')
    return first, last


def _money(value, *, optional=False):
    if value is None and optional:
        return ZERO
    if not isinstance(value, dict) or value.get('currency') != 'RUB':
        raise ValueError('Некорректная сумма или валюта финансового начисления.')
    raw = value.get('amount')
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        raise ValueError('Некорректная финансовая сумма.')
    try:
        result = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError('Некорректная финансовая сумма.') from exc
    if not result.is_finite() or abs(result) > Decimal('1e15'):
        raise ValueError('Некорректная финансовая сумма.')
    return result


def _sku(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError('Отсутствует SKU финансового начисления.')
    return str(value).strip()


def _objects(value):
    if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
        raise ValueError('Некорректный список финансовых начислений.')
    return value


def _category(name):
    name = name.casefold()
    for key, words in (
        ('advertising', ('advert', 'promo', 'marketing', 'реклам', 'продвиж', 'оплата за клик')),
        ('crossdock', ('crossdock', 'cross_dock', 'cross-dock', 'кросс')),
        ('storage', ('storage', 'placement', 'хранен', 'размещен')),
        ('acceptance', ('acceptance', 'приёмк', 'приемк')),
        ('penalty', ('penalty', 'fine', 'штраф')),
        ('commission', ('commission', 'комисси')),
        ('acquiring', ('acquir', 'эквайр')),
        ('returns', ('return', 'refund', 'возврат')),
        ('logistics', ('delivery', 'logistic', 'lastmile', 'достав', 'логист')),
    ):
        if any(word in name for word in words):
            return key
    return 'other'


def _quantity(product, posting, unit_number, request, cache):
    commission = product.get('commission') or {}
    sale = _money(commission.get('sale_amount'), optional=True)
    if sale == 0:
        if not _money(commission.get('seller_price'), optional=True):
            return 0
        # A fully discounted purchase can still be compensated by Ozon.
        # Only a positive sale settlement may use the original posting quantity.
        if _money(commission.get('commission'), optional=True) <= 0:
            return None
    price = _money(commission.get('sale_price'), optional=True)
    if price:
        with localcontext() as context:
            context.prec = 40
            ratio = abs(sale / price)
            if ratio == ratio.to_integral_value() and 0 < ratio <= 1000000:
                return int(ratio) * (1 if sale > 0 else -1)
    # A return can contain fewer units than the original posting. Never guess.
    if sale < 0 or not unit_number:
        return None
    schema = posting.get('delivery_schema', '').casefold()
    path = FBO_POSTING_GET_PATH if schema == 'fbo' else FBS_POSTING_GET_PATH if schema in ('fbs', 'rfbs') else None
    if path is None:
        return None
    key = sha256((path+'\0'+unit_number).encode()).hexdigest()
    if key not in cache:
        response = request(path, {'posting_number': unit_number, 'with': {'financial_data': False}}, 'posting')
        detail = response.get('result')
        if not isinstance(detail, dict) or detail.get('posting_number') != unit_number:
            raise ValueError('Ответ отправления не соответствует финансовому начислению.')
        quantities = {}
        for p in _objects(detail.get('products')):
            q = p.get('quantity')
            if type(q) is not int or not 0 < q <= 1000000:
                raise ValueError('Некорректное количество товара в отправлении.')
            sku = _sku(p.get('sku', p.get('product_id')))
            quantities[sku] = quantities.get(sku, 0) + q
        cache[key] = quantities
    return cache[key].get(_sku(product.get('sku')))


def fetch_finance(client, start, end, credential_context_id, progress_callback=None):
    if type(start) is not date or type(end) is not date or not credential_context_id:
        raise ValueError('Нужны даты и контекст аккаунта для финансового отчёта.')
    finance_period(start.isoformat(), end.isoformat())
    status = {'current': 0, 'total': (end-start).days+1, 'day': start.isoformat(),
              'page': 0, 'processed': 0, 'page_processed': 0, 'page_total': 0}

    def notify(stage, **values):
        status.update(values, stage=stage)
        if progress_callback:
            progress_callback(status.copy())

    def request(path, payload, stage):
        # Also a cancellation checkpoint before/after every potentially slow read.
        notify(stage)
        response = client.post_json(path, payload, policy=READ, check_cancelled=lambda: notify(stage))
        notify('processing')
        return response

    response = request(FINANCE_ACCRUAL_TYPES_PATH, {}, 'types')
    types = {}
    for t in _objects(response.get('accrual_types')):
        identifier = t.get('id')
        if type(identifier) is not int:
            raise ValueError('Некорректный справочник начислений.')
        name = t.get('name') or ''
        description = t.get('description') or name or f'Начисление {identifier}'
        if not isinstance(name, str) or not isinstance(description, str):
            raise ValueError('Некорректное описание начисления.')
        types[identifier] = (_category(name+' '+description), description[:200])
    products, expenses, seen, cache = [], [], {}, {}

    def fee(day, value, sku=None):
        kind = value.get('type_id')
        if type(kind) is not int:
            raise ValueError('Отсутствует вид начисления услуги.')
        amount = _money(value.get('accrued'))
        category, label = types.get(kind, ('other', f'Другие начисления · тип {kind}'))
        expenses.append(FinanceExpense(day, category, label, -amount, sku))
        if sku is not None:
            products.append(FinanceProductLine(day, sku, 0, ZERO, amount))
        return amount

    day = start
    with localcontext() as context:
        context.prec = 40
        while day <= end:
            cursor, cursors = '', set()
            for page in range(1, MAX_PAGES_PER_DAY+1):
                notify('day', current=(day-start).days, day=day.isoformat(), page=page,
                       page_processed=0, page_total=0)
                response = request(FINANCE_ACCRUAL_BY_DAY_PATH,
                    {'date': day.isoformat(), 'last_id': cursor}, 'day')
                rows = _objects(response.get('accruals'))
                notify('processing', page_total=len(rows))
                next_cursor = response.get('last_id')
                if not isinstance(next_cursor, str):
                    raise ValueError('Отсутствует курсор финансового ответа.')
                for index, row in enumerate(rows):
                    notify('processing', page_processed=index, processed=len(seen))
                    if row.get('date') != day.isoformat():
                        raise ValueError('Начисление находится вне запрошенного дня.')
                    identifier = row.get('accrual_id', row.get('type_id'))
                    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier):
                        raise ValueError('Отсутствует идентификатор начисления.')
                    # Hash raw content only for duplicate/conflict detection, never retain it.
                    digest = sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    identity = (day, str(identifier))
                    if identity in seen:
                        if seen[identity] != digest:
                            raise ValueError('Повторное начисление содержит противоречивые суммы.')
                        continue
                    seen[identity] = digest
                    if len(seen) > MAX_ACCRUALS:
                        raise ValueError('Слишком много начислений. Выберите меньший период.')
                    total = _money(row.get('total_amount'))
                    nested = ZERO
                    category = row.get('accrued_category')
                    if category == 'POSTING':
                        posting = row.get('posting')
                        if not isinstance(posting, dict):
                            raise ValueError('Некорректные начисления по отправлению.')
                        for p in _objects(posting.get('products')):
                            sku = _sku(p.get('sku'))
                            commission = p.get('commission') or {}
                            delivery = p.get('delivery') or {}
                            if not isinstance(commission, dict) or not isinstance(delivery, dict):
                                raise ValueError('Некорректные суммы товара.')
                            sale = _money(commission.get('sale_amount'), optional=True)
                            commission_net = _money(commission.get('commission'), optional=True)
                            delivery_net = _money(delivery.get('total_accrued'), optional=True)
                            net = sale + commission_net + delivery_net
                            quantity = _quantity(p, posting, row.get('unit_number'), request, cache)
                            unit_price = _money(commission.get('seller_price'), optional=True)
                            revenue = abs(unit_price) * quantity if quantity is not None else None
                            if quantity and unit_price == 0:
                                revenue = None
                            products.append(FinanceProductLine(day, sku, quantity, revenue, net))
                            nested += net
                            if revenue is not None:
                                expenses.append(FinanceExpense(day, 'commission', 'Комиссия и корректировки цены Ozon', revenue-sale-commission_net, sku))
                            if delivery_net:
                                expenses.append(FinanceExpense(day, 'logistics', 'Доставка по выкупленным товарам', -delivery_net, sku))
                    elif category == 'ITEM':
                        item = row.get('item_fees')
                        if not isinstance(item, dict):
                            raise ValueError('Некорректные начисления по товарам.')
                        for group in _objects(item.get('fees')):
                            sku = _sku(group.get('sku'))
                            for f in _objects(group.get('fees')):
                                nested += fee(day, f, sku)
                    elif category == 'NON_ITEM':
                        value = row.get('non_item_fee')
                        if not isinstance(value, dict):
                            raise ValueError('Некорректные общие начисления.')
                        nested += fee(day, value)
                    # Preserve unknown/new components, including container fees, once.
                    difference = total - nested
                    if difference:
                        expenses.append(FinanceExpense(day, 'other', 'Другие начисления и корректировки', -difference))
                notify('processing', page_processed=len(rows), processed=len(seen))
                if not next_cursor:
                    break
                if not rows or next_cursor in cursors or next_cursor == cursor:
                    raise ValueError('Финансовая пагинация не продвигается.')
                cursors.add(next_cursor)
                cursor = next_cursor
            else:
                raise ValueError('Слишком много страниц начислений. Выберите меньший период.')
            day += timedelta(days=1)
    notify('complete', current=(end-start).days+1, day=end.isoformat())
    return FinanceSnapshot(uuid4().hex, credential_context_id, start, end,
        tuple(products), tuple(expenses), datetime.now(timezone.utc).isoformat())
