"""PII-free, deterministic operator presentation for raw diagnostics."""
from collections import defaultdict, deque
from dataclasses import dataclass
from backend.domain.contracts import ImportResult, ProductEconomicsInput, TariffRow
from backend.economics.tariffs import LogisticsContext, RouteProfileSource
from .contracts import DataQualityAffectedEntity, DataQualityIssueGroup, DataQualityLevel, DataQualityPresentation

@dataclass(frozen=True, slots=True)
class DataQualityFact:
    code: str; entity_type: str; entity_key: str; label: str
    severity: str = "error"; sku: str | None = None; article: str | None = None
    origin_cluster_id: str | None = None; destination_cluster_id: str | None = None
    source_name: str | None = None; source_row: int | None = None
    detail_code: str | None = None; detail: str | None = None

@dataclass(frozen=True, slots=True)
class _FactOccurrence:
    fact: DataQualityFact
    raw_occurrence_indices: tuple[int, ...] = ()

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

def _calculation_identity(f):
    return (f.sku,f.origin_cluster_id or f.destination_cluster_id)

def build_data_quality_presentation(*,diagnostics,structured_facts=(),**_context):
    """Group by structured fields and codes. Diagnostic message is never read."""
    diagnostics=tuple(diagnostics); supplied=list(structured_facts)
    raw_facts=[_generic(d,i) for i,d in enumerate(diagnostics)]
    unused=set(range(len(raw_facts))); facts=[]
    by_identity=defaultdict(deque); by_code=defaultdict(deque)
    for i,raw_fact in enumerate(raw_facts):
        by_identity[(raw_fact.code,_calculation_identity(raw_fact))].append(i)
        by_code[raw_fact.code].append(i)
    def take(queue):
        while queue and queue[0] not in unused: queue.popleft()
        return queue.popleft() if queue else None
    for supplied_fact in supplied:
        raw_indices=()
        raw_index=take(by_identity[(supplied_fact.code,_calculation_identity(supplied_fact))])
        if raw_index is None: raw_index=take(by_code[supplied_fact.code])
        if raw_index is not None:
            unused.remove(raw_index); raw_indices=(raw_index,)
        facts.append(_FactOccurrence(supplied_fact,raw_indices))
    facts.extend(_FactOccurrence(raw_facts[i],(i,)) for i in sorted(unused))
    roots={_calculation_identity(item.fact):item.fact.code for item in facts if item.fact.code in _ROOTS}
    attached={}; visible=[]
    for item in facts:
        f=item.fact; identity=_calculation_identity(f)
        if f.code=="INCOMPLETE_LOGISTICS_COVERAGE" and identity in roots: attached.setdefault(roots[identity],[]).append(item)
        else: visible.append(item)
    by={}
    for item in visible: by.setdefault(item.fact.code,[]).append(item)
    groups=[]
    for code,items in by.items():
        item_facts=[item.fact for item in items]
        if code in _RULES: level,entity_type,title,explanation,blocks,hint=_RULES[code]
        else:
            sev=item_facts[0].severity; level=DataQualityLevel.BLOCKING if sev=="error" else DataQualityLevel.WARNING if sev=="warning" else DataQualityLevel.TECHNICAL
            entity_type=item_facts[0].entity_type
            title={DataQualityLevel.BLOCKING:"Есть блокирующая проблема данных — {n}",DataQualityLevel.WARNING:"Есть предупреждение о данных — {n}",DataQualityLevel.TECHNICAL:"Техническое событие — {n}"}[level]
            explanation="Часть расчёта недоступна. Подробности есть в технической диагностике." if level is DataQualityLevel.BLOCKING else "Подробности доступны в технической диагностике."
            blocks=(); hint="Откройте техническую диагностику для подробностей."
        unique={}
        for f in item_facts: unique.setdefault((f.entity_type,f.entity_key),_entity(f))
        entities=tuple(sorted(unique.values(),key=lambda x:(x.label,x.key)))
        consequence=attached.get(code,[]); related=(code,"INCOMPLETE_LOGISTICS_COVERAGE") if consequence else (code,)
        raw_count=sum(len(item.raw_occurrence_indices) for item in items)
        raw_count+=sum(len(item.raw_occurrence_indices) for item in consequence)
        groups.append(DataQualityIssueGroup(level,code,related,title.format(n=len(entities)),explanation,len(entities),entity_type,entities,raw_count,blocks,hint))
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

def _number(value):
    if value is None:return None
    rendered=format(value,"f")
    if "." in rendered: rendered=rendered.rstrip("0").rstrip(".")
    if rendered in {"","-0"}: rendered="0"
    return rendered.replace(".",",")

def tariff_gap_user_detail(detail_code,volume_liters,price):
    """Translate a machine tariff classification into operator-facing copy."""
    text={
        "ROUTE_PAIR_ABSENT":"Нет тарифа для этого маршрута.",
        "VOLUME_RANGE_MISSING":"Нет тарифного диапазона для объёма товара.",
        "PRICE_RANGE_MISSING":"Нет тарифного диапазона для цены товара.",
        "PRICE_REQUIRED":"Для выбора тарифа не указана цена товара.",
        "AMBIGUOUS_MATCH":"Найдено несколько подходящих тарифов.",
    }.get(detail_code,"Тариф для маршрута не найден.")
    if detail_code=="VOLUME_RANGE_MISSING" and volume_liters is not None:
        return f"{text[:-1]} · объём {_number(volume_liters)} л"
    if detail_code=="PRICE_RANGE_MISSING" and price is not None:
        return f"{text[:-1]} · цена {_number(price)} ₽"
    return text

def _tariff_fact(*,sku,origin,destination,product,tariffs):
    context=LogisticsContext(sku,origin,product.volume_liters,product.price,
                             RouteProfileSource.OBSERVED)
    detail_code=classify_tariff_gap(tariffs,context,destination)
    if detail_code is None:return None
    code=("AMBIGUOUS_TARIFF_MATCH" if detail_code=="AMBIGUOUS_MATCH" else
          "PRICE_REQUIRED_FOR_TARIFF_LOOKUP" if detail_code=="PRICE_REQUIRED" else
          "MISSING_TARIFF")
    key=f"{sku}::{origin}::{destination}::{product.volume_liters}::{product.price}"
    return DataQualityFact(code,"route",key,f"{origin} → {destination} · {sku}",
        sku=sku,origin_cluster_id=origin,destination_cluster_id=destination,
        detail_code=detail_code,
        detail=tariff_gap_user_detail(detail_code,product.volume_liters,product.price))

def build_stockout_tariff_quality_facts(*,stockout_episode_impacts,products,tariffs):
    """Explain only tariff reason codes emitted by stockout counterfactuals."""
    product_map={product.sku:product for product in products}
    facts=[]
    for episode in stockout_episode_impacts:
        for route in episode.routes:
            product=product_map.get(route.sku)
            if product is None or product.volume_liters is None:continue
            identities=[]
            if "CURRENT_ROUTE_INCOMPLETE" in route.reason_codes:
                identities.append((route.origin_cluster_id,route.destination_cluster_id))
            if "LOCAL_ROUTE_INCOMPLETE" in route.reason_codes:
                identities.append((route.destination_cluster_id,route.destination_cluster_id))
            for origin,destination in identities:
                fact=_tariff_fact(sku=route.sku,origin=origin,destination=destination,
                                  product=product,tariffs=tariffs)
                if fact is not None:facts.append(fact)
    return tuple(facts)

def classify_product_economics_gap(sku,article_candidates,unitka_products,
                                    current_article_skus,historical_article_skus):
    """Classify why an active SKU has no joined Unitka economics row."""
    articles=tuple(sorted({article for article in article_candidates if article}))
    if len(articles)>1:
        return "ARTICLE_TO_SKU_AMBIGUOUS","Нельзя однозначно определить SKU для артикула."
    article=articles[0] if articles else None
    if article and len(current_article_skus.get(article,set()))>1:
        return "ARTICLE_TO_SKU_CONFLICT","Артикул сопоставлен нескольким SKU в текущих данных."
    unitka_articles={row.article for row in unitka_products if row.article}
    if article in unitka_articles and len(historical_article_skus.get(article,set()))>1:
        return "ARTICLE_TO_SKU_AMBIGUOUS","Нельзя однозначно определить SKU для артикула."
    if article:
        return "UNITKA_ROW_ABSENT",f"В Юнитке нет строки для артикула {article}."
    return "UNITKA_ROW_ABSENT","Товар отсутствует в Юнитке."
