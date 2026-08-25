"""Stateless multipart HTTP boundary."""
from dataclasses import asdict, is_dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import PurePath
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from backend.application import analyze
from backend.domain.contracts import ReportMeta, ImportDiagnostic
from backend.ingestion.availability import import_availability
from backend.ingestion.restrictions import import_restrictions
from backend.ingestion.orders import import_orders
from backend.ingestion.tariffs import import_tariffs
from backend.ingestion.product_economics import import_product_economics
from backend.project import EconomicsSettings, OptimizerThresholds
MAX_UPLOAD_BYTES=64*1024*1024
router=APIRouter()

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
async def read(upload,field):
    data=await upload.read(MAX_UPLOAD_BYTES+1)
    if len(data)>MAX_UPLOAD_BYTES: raise OverflowError(field)
    return data

def response(kind,result): return {"api_version":1,"kind":kind,**wire(result)}

def input_status(result):
    return {
        "ok": not any(diagnostic.severity == "error" for diagnostic in result.diagnostics),
        "record_count": len(result.records),
        "diagnostics": wire(result.diagnostics),
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
    products=import_product_economics(data,context); tariffs=import_tariffs(data,context)
    return {"api_version":1,"kind":"unitka","product_economics":wire(products.records),"tariffs":wire(tariffs.records),
            "diagnostics":wire(products.diagnostics+tariffs.diagnostics),"meta":wire(context),
            "record_sources":{"product_economics":list(products.record_sources),"tariffs":list(tariffs.record_sources)}}

@router.post('/api/analysis')
async def analysis(request:Request):
    form=await request.form(); common=['availability_file','restrictions_file','orders_file']
    for field in common:
        if form.get(field) is None:return error(400,'MISSING_FIELD','Required multipart field is missing.',field)
    unitka=form.get('unitka_file'); legacy=(form.get('tariffs_file'),form.get('product_economics_file'))
    if unitka is not None and any(legacy): return error(400,'MIXED_INPUT_MODE','Unitka cannot be combined with legacy economics files.','unitka_file')
    if unitka is None and not all(legacy): return error(400,'MISSING_ECONOMICS_INPUT','Provide unitka_file or both legacy economics files.','unitka_file')
    files=common+(['unitka_file'] if unitka is not None else ['tariffs_file','product_economics_file'])
    try: as_of=date.fromisoformat(str(form.get('as_of','')))
    except ValueError:return error(400,'INVALID_DATE','Expected YYYY-MM-DD.','as_of')
    decimal_names=['acquiring_rate','advertising_rate','buyout_rate','fixed_fbo_fee','income_tax_rate','vat_rate','co_invest_rate','min_profit_per_unit','min_margin_rate','min_roi']; values={}
    for name in decimal_names:
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
        try: raw.append((form[field],await read(form[field],field)))
        except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    availability=import_availability(raw[0][1],meta(raw[0][0])); restrictions=import_restrictions(raw[1][1],meta(raw[1][0])); orders=import_orders(raw[2][1],meta(raw[2][0]))
    if unitka is not None:
        tariffs=import_tariffs(raw[3][1],meta(raw[3][0])); products=import_product_economics(raw[3][1],meta(raw[3][0]))
    else:
        tariffs=import_tariffs(raw[3][1],meta(raw[3][0])); products=import_product_economics(raw[4][1],meta(raw[4][0]))
    primary={}; primary_conflicts=set()
    for item in availability.records:
        if not item.article: continue
        if item.article in primary and primary[item.article]!=item.sku: primary_conflicts.add(item.article)
        else: primary[item.article]=item.sku
    fallback={}
    for item in orders.records:
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
    imported=[availability,restrictions,orders,tariffs,products]
    settings=EconomicsSettings(*(values[n] for n in decimal_names[:4]),tax,*(values[n] for n in decimal_names[4:7])); thresholds=OptimizerThresholds(*(values[n] for n in decimal_names[7:]))
    result=analyze(availability.records,restrictions.records,orders.records,tariffs,products.records,as_of=as_of,economics_settings=settings,optimizer_thresholds=thresholds)
    coverage={key:0 for key in ('complete','partial','none','no_profile')}
    for item in result.logistics:coverage[item.coverage_status.value]+=1
    diagnostics=tuple(d for item in imported for d in item.diagnostics)+result.diagnostics
    complete=not any(d.severity=='error' for d in diagnostics) and all(item.complete for item in result.economics)
    statuses=([availability,restrictions,orders,products] if unitka is not None else imported)
    return {"api_version":1,"complete":complete,"as_of":as_of.isoformat(),"metadata":{field:wire(item.meta) for field,item in zip(files,statuses)},"input_statuses":{field:input_status(item) for field,item in zip(files,statuses)},"demand":wire(result.demand),"observed_routes":wire(result.observed_routes),"clean_routes":wire(result.clean_routes),"stockout_signals":wire(result.stockouts),"distortion_signals":wire(result.distortions),"logistics":wire(result.logistics),"economics":wire(result.economics),"placements":wire(result.placements),"allocations":wire(result.allocations),"summary":wire(result.summary),"coverage":coverage,"diagnostics":wire(diagnostics)}
