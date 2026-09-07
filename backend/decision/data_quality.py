"""PII-free, deterministic operator presentation for raw diagnostics."""
from dataclasses import dataclass
from backend.domain.contracts import ImportResult, TariffRow
from backend.economics.tariffs import LogisticsContext
from .contracts import DataQualityAffectedEntity, DataQualityIssueGroup, DataQualityLevel, DataQualityPresentation

@dataclass(frozen=True, slots=True)
class DataQualityFact:
    code: str; entity_type: str; entity_key: str; label: str
    severity: str = "error"; sku: str | None = None; article: str | None = None
    origin_cluster_id: str | None = None; destination_cluster_id: str | None = None
    source_name: str | None = None; source_row: int | None = None
    detail_code: str | None = None; detail: str | None = None

_RULES = {
 "MISSING_SELLER_AVAILABLE_STOCK":(DataQualityLevel.BLOCKING,"sku","SKU без доступного остатка продавца — {n}","План поставки для этих товаров не рассчитан полностью.",( "Безопасный план","Рассчитанный план"),"Проверьте доступный остаток продавца/FBS в отчёте доступности."),
 "CONFLICTING_FBS_AVAILABLE_STOCK":(DataQualityLevel.BLOCKING,"sku","SKU с противоречивым доступным остатком — {n}","План поставки нельзя рассчитать до устранения противоречия.",( "Безопасный план","Рассчитанный план"),"Проверьте повторяющиеся значения FBS в отчёте доступности."),
 "MISSING_PRODUCT_ECONOMICS":(DataQualityLevel.BLOCKING,"sku","SKU без данных юнит-экономики — {n}","Юнит-экономика и размещение для этих товаров недоступны.",( "Юнит-экономика","Размещение","План поставки","Экономика stockout-эпизодов"),"Добавьте товар в Юнитку или исправьте сопоставление артикула с SKU."),
 "MISSING_PRODUCT_VOLUME":(DataQualityLevel.BLOCKING,"sku","SKU без объёма товара — {n}","Тариф логистики и экономика для этих товаров не рассчитаны.",( "Экономика маршрутов","Размещение","План поставки"),"Заполните объём товара в Юнитке."),
 "MISSING_TARIFF":(DataQualityLevel.BLOCKING,"route","Маршруты без тарифа — {n}","Экономика этих маршрутов не рассчитана.",( "Экономика маршрутов","Экономика stockout-эпизодов"),"Проверьте тариф для указанного origin → destination и диапазона объёма/цены в Юнитке."),
 "PRICE_REQUIRED_FOR_TARIFF_LOOKUP":(DataQualityLevel.BLOCKING,"route","Маршруты без цены для выбора тарифа — {n}","Тариф этих маршрутов нельзя выбрать без цены товара.",( "Экономика маршрутов","Экономика stockout-эпизодов"),"Заполните цену товара в Юнитке."),
 "AMBIGUOUS_TARIFF_MATCH":(DataQualityLevel.BLOCKING,"route","Маршруты с несколькими подходящими тарифами — {n}","Экономика этих маршрутов неоднозначна.",( "Экономика маршрутов","Экономика stockout-эпизодов"),"Устраните пересечение диапазонов тарифов в Юнитке."),
 "INCOMPLETE_LOGISTICS_COVERAGE":(DataQualityLevel.BLOCKING,"calculation","Неполное покрытие логистики — {n}","Причина неполного расчёта требует проверки технической диагностики.",( "Экономика маршрутов",),"Откройте техническую диагностику и проверьте покрытие тарифами."),
 "MISSING_ARTICLE_TO_SKU":(DataQualityLevel.WARNING,"article","Статьи Юнитки вне текущего ассортимента — {n}","На расчёт остальных товаров это не влияет.",(),"Действий не требуется, если эти статьи действительно не входят в текущий ассортимент Ozon."),
 "CONFLICTING_ARTICLE_TO_SKU":(DataQualityLevel.BLOCKING,"article","Статьи с конфликтующим сопоставлением SKU — {n}","Юнит-экономика затронутых товаров недоступна.",( "Юнит-экономика","Размещение"),"Исправьте соответствие артикула и SKU в исходных отчётах."),
 "AMBIGUOUS_ARTICLE_TO_SKU_FALLBACK":(DataQualityLevel.BLOCKING,"article","Статьи с неоднозначным сопоставлением SKU — {n}","Юнит-экономика затронутых товаров недоступна.",( "Юнит-экономика","Размещение"),"Укажите однозначное соответствие артикула и SKU."),
 "WORKSHEET_DIMENSION_REPAIRED":(DataQualityLevel.TECHNICAL,"worksheet","Диапазоны Excel восстановлены автоматически — {n}","Данные прочитаны после восстановления некорректно объявленного диапазона листа.",(),"Действий не требуется, если импорт завершился успешно."),
}
_ROOTS={"MISSING_TARIFF","PRICE_REQUIRED_FOR_TARIFF_LOOKUP","AMBIGUOUS_TARIFF_MATCH"}
_ORDER={DataQualityLevel.BLOCKING:0,DataQualityLevel.WARNING:1,DataQualityLevel.TECHNICAL:2}
_PRIORITY={"MISSING_SELLER_AVAILABLE_STOCK":0,"CONFLICTING_FBS_AVAILABLE_STOCK":1,"MISSING_PRODUCT_ECONOMICS":2,"MISSING_PRODUCT_VOLUME":3,"MISSING_TARIFF":4}

def _entity(f):
    return DataQualityAffectedEntity(f.entity_type,f.entity_key,f.label,f.sku,f.article,f.origin_cluster_id,f.destination_cluster_id,f.source_name,f.source_row,f.detail_code,f.detail)

def _generic(d,i):
    sku=getattr(d,"sku",None); cluster=getattr(d,"destination_cluster_id",None) or getattr(d,"cluster_id",None)
    key="::".join(x for x in (sku,cluster) if x) or f"occurrence::{i}"
    return DataQualityFact(d.code,"calculation",key," · ".join(x for x in (sku,cluster) if x) or "Техническая диагностика",getattr(d,"severity","error"),sku=sku,destination_cluster_id=cluster)

def build_data_quality_presentation(*,diagnostics,structured_facts=(),**_context):
    """Group by structured fields and codes. Diagnostic message is never read."""
    diagnostics=tuple(diagnostics); supplied=list(structured_facts); remaining={}
    for f in supplied: remaining[f.code]=remaining.get(f.code,0)+1
    facts=[]
    for i,d in enumerate(diagnostics):
        if remaining.get(d.code,0): remaining[d.code]-=1
        else: facts.append(_generic(d,i))
    facts.extend(supplied)
    roots={(f.sku,f.origin_cluster_id or f.destination_cluster_id):f.code for f in facts if f.code in _ROOTS}
    attached={}; visible=[]
    for f in facts:
        identity=(f.sku,f.origin_cluster_id or f.destination_cluster_id)
        if f.code=="INCOMPLETE_LOGISTICS_COVERAGE" and identity in roots: attached.setdefault(roots[identity],[]).append(f)
        else: visible.append(f)
    by={}
    for f in visible: by.setdefault(f.code,[]).append(f)
    groups=[]
    for code,items in by.items():
        if code in _RULES: level,entity_type,title,explanation,blocks,hint=_RULES[code]
        else:
            sev=items[0].severity; level=DataQualityLevel.BLOCKING if sev=="error" else DataQualityLevel.WARNING if sev=="warning" else DataQualityLevel.TECHNICAL
            entity_type=items[0].entity_type
            title={DataQualityLevel.BLOCKING:"Есть блокирующая проблема данных — {n}",DataQualityLevel.WARNING:"Есть предупреждение о данных — {n}",DataQualityLevel.TECHNICAL:"Техническое событие — {n}"}[level]
            explanation="Часть расчёта недоступна. Подробности есть в технической диагностике." if level is DataQualityLevel.BLOCKING else "Подробности доступны в технической диагностике."
            blocks=(); hint="Откройте техническую диагностику для подробностей."
        unique={}
        for f in items: unique.setdefault((f.entity_type,f.entity_key),_entity(f))
        entities=tuple(sorted(unique.values(),key=lambda x:(x.label,x.key)))
        consequence=attached.get(code,[]); related=(code,"INCOMPLETE_LOGISTICS_COVERAGE") if consequence else (code,)
        groups.append(DataQualityIssueGroup(level,code,related,title.format(n=len(entities)),explanation,len(entities),entity_type,entities,len(items)+len(consequence),blocks,hint))
    groups.sort(key=lambda g:(_ORDER[g.level],_PRIORITY.get(g.primary_code,99),g.primary_code))
    return DataQualityPresentation(tuple(groups),len(diagnostics),sum(g.level is DataQualityLevel.BLOCKING for g in groups),sum(g.level is DataQualityLevel.WARNING for g in groups),sum(g.level is DataQualityLevel.TECHNICAL for g in groups))

def classify_tariff_gap(tariffs:ImportResult[TariffRow],context:LogisticsContext,destination_cluster_id:str)->str|None:
    pair=[r for r in tariffs.records if r.origin_cluster_id==context.origin_cluster_id and r.destination_cluster_id==destination_cluster_id]
    if not pair:return "ROUTE_PAIR_ABSENT"
    volume=[r for r in pair if r.min_volume_liters<=context.volume_liters and (r.max_volume_liters is None or context.volume_liters<r.max_volume_liters)]
    if not volume:return "VOLUME_RANGE_MISSING"
    if context.price is None and all(r.min_price is not None or r.max_price is not None for r in volume):return "PRICE_REQUIRED"
    matches=[r for r in volume if (r.min_price is None and r.max_price is None) or (context.price is not None and (r.min_price is None or r.min_price<=context.price) and (r.max_price is None or context.price<r.max_price))]
    if len(matches)>1:return "AMBIGUOUS_MATCH"
    if not matches:return "PRICE_RANGE_MISSING"
    return None
