"""Stateless multipart HTTP boundary."""
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import asyncio
import json
import logging
from pathlib import Path, PurePath
from queue import Queue
from threading import Event, Thread
from time import perf_counter
from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from backend.application import analyze
from backend.decision import (DiagnosticView, InputStatusView, ScenarioSettings,
                              assemble_snapshot)
from backend.supply import AllocationObjective
from backend.ingestion.cluster_resolution import resolve_analysis_clusters
from backend.domain.contracts import ReportMeta, ImportDiagnostic
from backend.ingestion.availability import import_availability
from backend.ingestion.restrictions import import_restrictions
from backend.ingestion.orders import import_orders
from backend.ingestion.tariffs import import_tariffs
from backend.ingestion.product_economics import import_product_economics
from backend.ingestion.unitka import import_unitka_bundle
from backend.project import (EconomicsSettings, OptimizerThresholds, Project,
                             ProjectValidationError, load_project_if_exists,
                             save_project_atomic)
MAX_UPLOAD_BYTES=64*1024*1024
router=APIRouter()
logger=logging.getLogger(__name__)
PROJECT_PATH=Path(__file__).resolve().parents[1]/"data"/"project.json"
DECIMAL_NAMES=['acquiring_rate','advertising_rate','buyout_rate','fixed_fbo_fee','income_tax_rate','vat_rate','co_invest_rate','min_profit_per_unit','min_margin_rate','min_roi']
STAGES={
    "preparing":(1,"Подготовка файлов"), "reports":(2,"Чтение отчётов"),
    "demand":(3,"Анализ спроса"), "routes":(4,"Анализ маршрутов"),
    "distortions":(5,"Поиск искажений остатков"),
    "logistics_economics":(6,"Расчёт логистики и экономики"),
    "placements":(7,"Проверка размещений"), "optimizer":(8,"Оптимизация поставки"),
    "serialization":(9,"Подготовка результата"),
}

def _decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text

def wire(value):
    if is_dataclass(value): return {f:wire(v) for f,v in asdict(value).items()}
    if isinstance(value,Enum): return value.value
    if isinstance(value,Decimal): return _decimal_string(value)
    if isinstance(value,(date,datetime)): return value.isoformat()
    if isinstance(value,dict): return {str(k):wire(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [wire(v) for v in value]
    return value

def error(status,code,message,field): return JSONResponse({"api_version":1,"error":{"code":code,"message":message,"field":field}},status_code=status)
def meta(upload): return ReportMeta(PurePath(upload.filename or 'upload').name,datetime.now(timezone.utc).isoformat())
async def read(upload,field,request_id="http"):
    started=perf_counter()
    data=await upload.read(MAX_UPLOAD_BYTES+1)
    logger.info("[analysis %s] multipart_read done %.3fs field=%s bytes=%d",request_id,perf_counter()-started,field,len(data))
    if len(data)>MAX_UPLOAD_BYTES: raise OverflowError(field)
    return data

def response(kind,result): return {"api_version":1,"kind":kind,**wire(result)}

def input_status(*results):
    return {
        "ok": not any(
            diagnostic.severity == "error"
            for result in results
            for diagnostic in result.diagnostics
        ),
        "record_count": sum(len(result.records) for result in results),
        "diagnostics": wire(tuple(
            diagnostic
            for result in results
            for diagnostic in result.diagnostics
        )),
    }

_IMPORTERS={"availability":import_availability,"restrictions":import_restrictions,"orders":import_orders,"tariffs":import_tariffs,"product-economics":import_product_economics}
for _kind,_importer in _IMPORTERS.items():
    async def endpoint(request:Request, kind=_kind, importer=_importer):
        form=await request.form(); upload=form.get('file')
        if upload is None:return error(400,'MISSING_FIELD','Required multipart field is missing.','file')
        try:data=await read(upload,'file')
        except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.','file')
        return response(kind,importer(data,meta(upload)))
    router.add_api_route('/api/import/'+_kind,endpoint,methods=['POST'])

@router.post('/api/import/unitka')
async def import_unitka(request:Request):
    form=await request.form(); upload=form.get('file')
    if upload is None:return error(400,'MISSING_FIELD','Required multipart field is missing.','file')
    data=await read(upload,'file'); context=meta(upload)
    bundle=import_unitka_bundle(data,context); products=bundle.product_economics; tariffs=bundle.tariffs
    return {"api_version":1,"kind":"unitka","product_economics":wire(products.records),"tariffs":wire(tariffs.records),
            "diagnostics":wire(products.diagnostics+tariffs.diagnostics),"meta":wire(context),
            "record_sources":{"product_economics":list(products.record_sources),"tariffs":list(tariffs.record_sources)}}

async def prepare_analysis(request:Request, request_id="http"):
    form=await request.form(); common=['availability_file','restrictions_file','orders_file']
    explicit_horizon=form.get("horizon_days")
    if explicit_horizon is not None:
        value=str(explicit_horizon).strip()
        if not value.isascii() or not value.isdigit() or value.startswith("+") or int(value)<=0:
            return error(400,"INVALID_HORIZON_DAYS","Expected a positive integer.","horizon_days")
        explicit_horizon=int(value)
    raw_inbound=str(form.get("include_inbound","true")).strip().lower()
    if raw_inbound not in {"true","false"}:
        return error(400,"INVALID_INCLUDE_INBOUND","Expected true or false.","include_inbound")
    raw_objective=str(form.get("optimization_objective","max_profit")).strip()
    try: objective=AllocationObjective(raw_objective)
    except ValueError:
        return error(400,"INVALID_OPTIMIZATION_OBJECTIVE","Unsupported optimization objective.","optimization_objective")
    for field in common:
        if form.get(field) is None:return error(400,'MISSING_FIELD','Required multipart field is missing.',field)
    unitka=form.get('unitka_file'); legacy=(form.get('tariffs_file'),form.get('product_economics_file'))
    if unitka is not None and any(legacy): return error(400,'MIXED_INPUT_MODE','Unitka cannot be combined with legacy economics files.','unitka_file')
    if unitka is None and not all(legacy): return error(400,'MISSING_ECONOMICS_INPUT','Provide unitka_file or both legacy economics files.','unitka_file')
    files=common+(['unitka_file'] if unitka is not None else ['tariffs_file','product_economics_file'])
    try: as_of=date.fromisoformat(str(form.get('as_of','')))
    except ValueError:return error(400,'INVALID_DATE','Expected YYYY-MM-DD.','as_of')
    values={}
    for name in DECIMAL_NAMES:
        try:
            values[name]=Decimal(str(form.get(name,'')))
            if not values[name].is_finite():raise InvalidOperation
        except (InvalidOperation,ValueError):return error(400,'INVALID_DECIMAL','Expected a finite decimal string.',name)
    domains={'acquiring_rate':lambda v:0<=v<=1,'advertising_rate':lambda v:0<=v<=1,'buyout_rate':lambda v:0<v<=1,'fixed_fbo_fee':lambda v:v>=0,'income_tax_rate':lambda v:0<=v<=1,'vat_rate':lambda v:0<=v<=1,'co_invest_rate':lambda v:0<=v<=1}
    for name,accepted in domains.items():
        if not accepted(values[name]):return error(400,'INVALID_SETTING','Value is outside the accepted domain.',name)
    tax=str(form.get('tax_system',''))
    if tax not in {'usn_income','usn_income_minus_expenses','osno','manual'}:return error(400,'INVALID_TAX_SYSTEM','Unsupported tax system.','tax_system')
    raw=[]
    for field in files:
        try: raw.append((form[field],await read(form[field],field,request_id)))
        except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    return raw, unitka, files, values, tax, as_of, (explicit_horizon,raw_inbound=="true",objective)

@router.post('/api/analysis')
async def analysis(request:Request):
    request_id=uuid4().hex[:8]
    prepared=await prepare_analysis(request,request_id)
    if isinstance(prepared,JSONResponse): return prepared
    return run_analysis_pipeline(*prepared,request_id=request_id)

@router.post('/api/analysis/stream')
async def analysis_stream(request:Request):
    request_id=uuid4().hex[:8]
    prepared=await prepare_analysis(request,request_id)
    if isinstance(prepared,JSONResponse): return prepared
    events=Queue()
    cancelled=Event()
    started=perf_counter()
    last_stage={"name":"preparing","started":started,"percent":-1}

    def emit(stage,current=None,total=None,detail=None):
        if cancelled.is_set(): raise AnalysisCancelled
        now=perf_counter(); index,message=STAGES[stage]
        percent=(current*100//total) if current is not None and total else None
        if stage==last_stage["name"] and percent is not None and percent not in {0,100} and percent < last_stage["percent"]+1:
            return
        if stage!=last_stage["name"]:
            logger.info("[analysis %s] %s done %.3fs",request_id,last_stage["name"],now-last_stage["started"])
            last_stage.update(name=stage,started=now,percent=-1)
        if percent is not None:last_stage["percent"]=percent
        event={"type":"progress","request_id":request_id,"stage":stage,"stage_index":index,
               "stage_count":len(STAGES),"message":message,"elapsed_ms":round((now-started)*1000)}
        if current is not None:event.update(current=current,total=total)
        if detail is not None:event["detail"]=detail
        events.put(event)

    def worker():
        logger.info("[analysis %s] started",request_id)
        try:
            emit("preparing",0,len(prepared[2]))
            result=run_analysis_pipeline(*prepared,progress_callback=emit,request_id=request_id)
            now=perf_counter()
            logger.info("[analysis %s] complete total=%.3fs",request_id,now-started)
            events.put({"type":"result","request_id":request_id,"elapsed_ms":round((now-started)*1000),"data":result})
        except AnalysisCancelled:
            logger.info("[analysis %s] cancelled",request_id)
        except Exception:
            logger.exception("[analysis %s] failed at %s",request_id,last_stage["name"])
            events.put({"type":"error","request_id":request_id,"stage":last_stage["name"],
                        "error":{"code":"ANALYSIS_FAILED","message":"Не удалось выполнить анализ."}})
        finally: events.put(None)

    async def stream():
        thread=Thread(target=worker,name=f"analysis-{request_id}");thread.start()
        try:
            while True:
                item=await asyncio.to_thread(events.get)
                if item is None:break
                yield json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n"
        finally:
            cancelled.set()
            await asyncio.shield(asyncio.to_thread(thread.join))
    return StreamingResponse(stream(),media_type="application/x-ndjson")

class AnalysisCancelled(Exception):
    """Internal cooperative cancellation at progress boundaries."""


def run_analysis_pipeline(raw, unitka, files, values, tax, as_of, scenario_request=(None,True,AllocationObjective.MAX_PROFIT), *, progress_callback=None, request_id="http"):
    """Run imports, joins, domain analysis and serialization for both transports."""
    def progress(stage, current=None, total=None, detail=None):
        if progress_callback is not None:
            progress_callback(stage, current, total, detail)

    def timed(name, importer, data, context):
        started=perf_counter(); result=importer(data,context)
        logger.info("[analysis %s] %s done %.3fs rows=%d",request_id,name,perf_counter()-started,len(result.records))
        return result

    reports_started=perf_counter()
    logger.info("[analysis %s] reports started",request_id)
    progress("reports",1,4,"availability")
    availability=timed("availability_import",import_availability,raw[0][1],meta(raw[0][0]))
    progress("reports",2,4,"restrictions")
    restrictions=timed("restrictions_import",import_restrictions,raw[1][1],meta(raw[1][0]))
    progress("reports",3,4,"orders")
    orders=timed("orders_import",import_orders,raw[2][1],meta(raw[2][0]))
    progress("reports",4,4,"unitka" if unitka is not None else "economics")

    if unitka is not None:
        def unitka_timing(name, duration, rows):
            suffix="" if rows is None else f" rows={rows}"
            logger.info("[analysis %s] %s done %.3fs%s",request_id,name,duration,suffix)
        bundle=import_unitka_bundle(raw[3][1],meta(raw[3][0]),timing=unitka_timing)
        tariffs,products=bundle.tariffs,bundle.product_economics
    else:
        tariffs=timed("tariffs_import",import_tariffs,raw[3][1],meta(raw[3][0])); products=timed("product_economics_import",import_product_economics,raw[4][1],meta(raw[4][0]))
    project=load_project_if_exists(PROJECT_PATH)
    resolution = resolve_analysis_clusters(
        availability.records, restrictions.records, orders.records, tariffs.records,
        project.manual_cluster_mappings
    )
    analysis_availability = resolution.availability
    analysis_restrictions = resolution.restrictions
    analysis_orders = resolution.orders
    analysis_tariffs = replace(tariffs, records=resolution.tariffs)
    join_started=perf_counter()
    primary={}; primary_conflicts=set()
    for item in analysis_availability:
        if not item.article: continue
        if item.article in primary and primary[item.article]!=item.sku: primary_conflicts.add(item.article)
        else: primary[item.article]=item.sku
    fallback={}
    for item in analysis_orders:
        if item.article:fallback.setdefault(item.article,set()).add(item.sku)
    joined=[]; join_diags=[]
    for product in products.records:
        if product.sku:joined.append(product);continue
        if product.article in primary_conflicts:
            join_diags.append(ImportDiagnostic('warning','CONFLICTING_ARTICLE_TO_SKU','Unitka article has conflicting availability mappings; affected current SKU remain blocked without economics.'));continue
        sku=primary.get(product.article)
        if sku is None:
            candidates=fallback.get(product.article,set())
            if len(candidates)>1:
                join_diags.append(ImportDiagnostic('warning','AMBIGUOUS_ARTICLE_TO_SKU_FALLBACK','Unitka article has ambiguous historical mappings; affected current SKU remain blocked without economics.'));continue
            sku=next(iter(candidates),None)
        if sku:joined.append(replace(product,sku=sku))
        else:join_diags.append(ImportDiagnostic('warning','MISSING_ARTICLE_TO_SKU','Unitka article is outside the current SKU universe.'))
    products=replace(products,records=tuple(joined),diagnostics=products.diagnostics+tuple(join_diags))
    logger.info("[analysis %s] article_join done %.3fs rows=%d",request_id,perf_counter()-join_started,len(products.records))
    logger.info("[analysis %s] reports done %.3fs",request_id,perf_counter()-reports_started)
    imported=[availability,restrictions,orders,tariffs,products]
    settings=EconomicsSettings(*(values[n] for n in DECIMAL_NAMES[:4]),tax,*(values[n] for n in DECIMAL_NAMES[4:7])); thresholds=OptimizerThresholds(*(values[n] for n in DECIMAL_NAMES[7:]))
    explicit_horizon,include_inbound,objective=scenario_request
    scenario=ScenarioSettings(explicit_horizon or availability.meta.recommendation_horizon_days or 56,include_inbound,objective)
    result=analyze(analysis_availability,analysis_restrictions,analysis_orders,analysis_tariffs,products.records,as_of=as_of,economics_settings=settings,optimizer_thresholds=thresholds,availability_fbs_authoritative=unitka is not None,operational_availability=availability.records,ozon_horizon_days=availability.meta.recommendation_horizon_days,progress_callback=progress_callback,scenario_settings=scenario)
    progress("serialization")
    coverage={key:0 for key in ('complete','partial','none','no_profile')}
    for item in result.logistics:coverage[item.coverage_status.value]+=1
    diagnostics=(tuple(d for item in imported for d in item.diagnostics)
                 + resolution.diagnostics + result.diagnostics)
    complete=not any(d.severity=='error' for d in diagnostics) and all(item.complete for item in result.economics)
    statuses=([availability,restrictions,orders,products] if unitka is not None else imported)
    input_statuses={field:input_status(item) for field,item in zip(files,statuses)}
    if unitka is not None:
        input_statuses["unitka_file"]=input_status(products,tariffs)
    report_meta={field:item.meta for field,item in zip(files,statuses)}
    status_views={name:InputStatusView(value["ok"],value["record_count"],tuple(
        DiagnosticView(d["severity"],d["code"],d["message"]) for d in value["diagnostics"]))
        for name,value in input_statuses.items()}
    diagnostic_views=tuple(DiagnosticView(d.severity,d.code,d.message,getattr(d,"sku",None),getattr(d,"cluster_id",None),getattr(d,"destination_cluster_id",None)) for d in diagnostics)
    warnings=[]
    if availability.meta.recommendation_horizon_days is None and explicit_horizon is None:
        warnings.append("Горизонт рекомендации Ozon неизвестен; для сценария по умолчанию использовано 56 дней.")
    elif availability.meta.recommendation_horizon_days is None:
        warnings.append("Горизонт рекомендации Ozon неизвестен; прямое сравнение горизонтов невозможно.")
    elif availability.meta.recommendation_horizon_days != scenario.horizon_days:
        warnings.append(f"Горизонты различаются: Ozon {availability.meta.recommendation_horizon_days} дней, наш расчёт {scenario.horizon_days} дней.")
    periods={(m.period_start,m.period_end) for m in report_meta.values() if m.period_start and m.period_end}
    if len(periods)>1:warnings.append("Периоды загруженных отчётов различаются.")
    snapshot=assemble_snapshot(scenario=scenario,report_meta=report_meta,input_statuses=status_views,
        demand_estimates=result.demand_estimates,needs=result.needs,observed_routes=result.observed_routes,
        clean_routes=result.clean_routes,stockout_signals=result.stockouts,distortion_signals=result.distortions,
        route_economics=result.route_economics,unit_economics=result.economics,placements=result.placements,
        safe_allocations=result.safe_allocations,calculated_allocations=result.allocations,products=products.records,
        diagnostics=diagnostic_views,freshness_warnings=tuple(warnings),
        product_identities={item.sku:(item.article,item.product_name) for item in analysis_availability})
    return {"api_version":1,"complete":complete,"snapshot":wire(snapshot),"as_of":as_of.isoformat(),"metadata":{field:wire(item.meta) for field,item in zip(files,statuses)},"input_statuses":input_statuses,"demand":wire(result.demand),"observed_routes":wire(result.observed_routes),"clean_routes":wire(result.clean_routes),"stockout_signals":wire(result.stockouts),"distortion_signals":wire(result.distortions),"logistics":wire(result.logistics),"economics":wire(result.economics),"placements":wire(result.placements),"allocations":wire(result.allocations),"safe_allocations":wire(result.safe_allocations),"summary":wire(result.summary),"coverage":coverage,"diagnostics":wire(diagnostics)}


@router.get("/api/project/mappings")
def get_project_mappings():
    project=load_project_if_exists(PROJECT_PATH)
    return {"api_version":1,"mappings":dict(sorted(project.manual_cluster_mappings.items()))}


@router.put("/api/project/mappings")
async def put_project_mappings(request: Request):
    try: payload=await request.json()
    except Exception: return error(400,"INVALID_MAPPINGS","Expected a JSON object.","mappings")
    if not isinstance(payload,dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,str) or not v.strip() for k,v in payload.items()):
        return error(400,"INVALID_MAPPINGS","Expected nonblank string keys and values.","mappings")
    mappings={k.strip():v.strip() for k,v in payload.items()}
    project=load_project_if_exists(PROJECT_PATH)
    project=replace(project,manual_cluster_mappings=mappings)
    try: save_project_atomic(PROJECT_PATH,project)
    except ProjectValidationError: return error(400,"INVALID_MAPPINGS","Mappings are invalid.","mappings")
    return {"api_version":1,"mappings":dict(sorted(mappings.items()))}
