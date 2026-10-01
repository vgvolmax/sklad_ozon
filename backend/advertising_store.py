"""Atomic, normalized advertising directory; campaign/SKU/day is the identity."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from backend.domain.advertising import AdvertisingCampaign, AdvertisingDay


@dataclass(frozen=True, slots=True)
class AdvertisingData:
    days: tuple[AdvertisingDay, ...] = ()
    campaigns: tuple[AdvertisingCampaign, ...] = ()


def apply_report(data, report, current_skus):
    matched = {r.sku for r in report.days} & current_skus
    unmatched = sorted({r.sku for r in report.days} - current_skus)
    result = {'filename': report.filename, 'campaign_id': report.campaign_id,
              'period_start': report.period_start, 'period_end': report.period_end,
              'matched_sku_count': len(matched), 'unmatched_skus': unmatched}
    suffix = f' {report.warning}' if report.warning else ''
    if not matched:
        return data, {**result, 'status': 'unmatched', 'message': 'SKU отчёта не найдены в текущем ассортименте.'}
    incoming = tuple(r for r in report.days if r.sku in matched)
    retained = tuple(r for r in data.days if not (
        r.campaign_id == report.campaign_id and report.period_start <= r.day <= report.period_end))
    updated_days = tuple(sorted(retained + incoming, key=lambda r: (r.campaign_id, r.sku, r.day)))
    if updated_days == data.days:
        return data, {**result, 'status': 'duplicate', 'message': 'Уже загружено; расходы не продублированы.' + suffix}
    campaign = AdvertisingCampaign(report.campaign_id, report.filename, datetime.now(timezone.utc).isoformat())
    campaigns = tuple(sorted(tuple(c for c in data.campaigns if c.campaign_id != report.campaign_id) + (campaign,),
                             key=lambda c: c.campaign_id))
    return AdvertisingData(updated_days, campaigns), {**result, 'status': 'imported',
        'message': f'Загружено: {len(matched)} SKU. Пересекающиеся дни этой кампании заменены.' + suffix,
        'spend': sum((r.spend for r in incoming), Decimal('0'))}


def _payload(data):
    return {'schema_version': 1,
            'days': [{'campaign_id': r.campaign_id, 'sku': r.sku,
                      'day': r.day.isoformat(), 'spend': format(r.spend, 'f')} for r in data.days],
            'campaigns': [{'campaign_id': c.campaign_id, 'filename': c.filename,
                           'imported_at': c.imported_at} for c in data.campaigns]}


def advertising_fingerprint(data):
    # File labels/timestamps do not alter money; normalized costs do.
    return hashlib.sha256(json.dumps(_payload(data)['days'], sort_keys=True).encode()).hexdigest()


def load_advertising(path):
    path = Path(path)
    if not path.exists(): return AdvertisingData()
    try:
        payload = json.loads(path.read_text('utf-8'))
        if not isinstance(payload, dict) or set(payload) != {'schema_version', 'days', 'campaigns'} or type(payload['schema_version']) is not int or payload['schema_version'] != 1:
            raise ValueError
        if not isinstance(payload['days'], list) or len(payload['days']) > 500_000 or not isinstance(payload['campaigns'], list):
            raise ValueError
        days, seen = [], set()
        for raw in payload['days']:
            if not isinstance(raw, dict) or set(raw) != {'campaign_id', 'sku', 'day', 'spend'}:
                raise ValueError
            if any(not isinstance(raw[k], str) or not raw[k] for k in raw): raise ValueError
            if len(raw['campaign_id']) > 32 or not raw['campaign_id'].isdigit() or int(raw['campaign_id']) <= 0 or len(raw['sku']) > 80: raise ValueError
            row = AdvertisingDay(raw['campaign_id'], raw['sku'], date.fromisoformat(raw['day']), Decimal(raw['spend']))
            if not row.spend.is_finite() or not 0 <= row.spend <= Decimal('1000000000000') or row.spend != row.spend.quantize(Decimal('.01')): raise ValueError
            key = row.campaign_id, row.sku, row.day
            if key in seen: raise ValueError
            seen.add(key); days.append(row)
        campaigns = []
        for raw in payload['campaigns']:
            if not isinstance(raw, dict) or set(raw) != {'campaign_id', 'filename', 'imported_at'} or any(not isinstance(v, str) or not v for v in raw.values()):
                raise ValueError
            if len(raw['filename']) > 200: raise ValueError
            datetime.fromisoformat(raw['imported_at'])
            campaigns.append(AdvertisingCampaign(**raw))
        if len({c.campaign_id for c in campaigns}) != len(campaigns) or {r.campaign_id for r in days} != {c.campaign_id for c in campaigns}:
            raise ValueError
        return AdvertisingData(tuple(sorted(days, key=lambda r: (r.campaign_id, r.sku, r.day))),
                               tuple(sorted(campaigns, key=lambda c: c.campaign_id)))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise ValueError('Не удалось прочитать сохранённые расходы на рекламу. Восстановите advertising.json из копии.') from exc


def save_advertising(path, data):
    if len(data.days) > 500_000: raise ValueError('Слишком много сохранённых товарных дней. Удалите старые кампании.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(_payload(data), ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, prefix='.advertising.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def campaign_items(data):
    result = []
    by_campaign = defaultdict(list)
    for row in data.days: by_campaign[row.campaign_id].append(row)
    for campaign in data.campaigns:
        rows = by_campaign[campaign.campaign_id]
        result.append({'campaign_id': campaign.campaign_id, 'filename': campaign.filename,
                       'sku_count': len({r.sku for r in rows}), 'period_start': min(r.day for r in rows),
                       'period_end': max(r.day for r in rows), 'day_count': len({r.day for r in rows}),
                       'spend': sum((r.spend for r in rows), Decimal('0'))})
    return result
