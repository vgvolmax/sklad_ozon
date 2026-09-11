"""Stateless multipart HTTP boundary."""
from dataclasses import asdict, dataclass, is_dataclass, replace
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
from fastapi.responses import JSONResponse, StreamingResponse, Response
from backend.application import analyze
from backend.economics import LogisticsContext
from backend.decision import (DataQualityFact, DiagnosticView, InputStatusView,
                              ScenarioSettings, assemble_snapshot,
                              build_data_quality_presentation,
                              build_stockout_tariff_quality_facts,
                              classify_product_economics_gap,
                              classify_tariff_gap, tariff_gap_user_detail)
from backend.decision.snapshot import first_nonblank
from backend.supply import (AllocationObjective, SupplyProductIdentity,
                            build_shippable_plan)
from backend.supply.facts import build_operational_supply_facts
from backend.ingestion.cluster_resolution import resolve_analysis_clusters
from backend.domain.contracts import (AnalysisSourceCoverage, ImportResult,
                                      ReportMeta, ImportDiagnostic, SourceMode)
from backend.ingestion.availability import import_availability
from backend.ingestion.restrictions import import_restrictions
from backend.ingestion.orders import import_orders
from backend.ingestion.tariffs import import_tariffs
from backend.ingestion.product_economics import import_product_economics
from backend.ingestion.unitka import import_unitka_bundle
from backend.project import (EconomicsSettings, OptimizerThresholds, Project,
                             ProjectValidationError, load_project_if_exists,
                             save_project_atomic)
from backend.ozon.client import OzonClient, OzonClientError, OzonRequestPolicy
from backend.ozon.contracts import OzonCredentials, OzonErrorCode
from backend.ozon.endpoints import CONNECTION_TEST_PATH
from backend.ozon.vault import CredentialVault, OzonVaultError
from backend.ozon.handoff import HandoffPointStore, handoff_supply_types, search_handoff_points
from backend.ozon.source_store import OzonSourceSnapshotStore
from backend.ozon.sync import capability_matrix, sync_ozon_source
from backend.ozon.draft_validation import DraftValidationService
from backend.shipment import DEFAULT_MAX_CANDIDATES, build_candidate_result
from backend.shipment.store import AnalysisSnapshotStore, ShipmentPlanStore
from backend.shipment.orchestration import build_shipment_plan, ShipmentOrchestrationError
from backend.shipment.export import render_export, ShipmentExportError
from backend.shipment.wire import parse_shipment_scenario
from backend.shipment.api_context import (ShipmentPreparationError,
                                          prepare_shipment_validation)
MAX_UPLOAD_BYTES=64*1024*1024
router=APIRouter()
logger=logging.getLogger(__name__)
PROJECT_PATH=Path(__file__).resolve().parents[1]/"data"/"project.json"
OZON_VAULT=CredentialVault(Path(__file__).resolve().parents[1]/"data"/"ozon-credentials.json")
OZON_CLIENT=OzonClient(OZON_VAULT)
HANDOFF_STORE=HandoffPointStore()
OZON_SOURCE_STORE=OzonSourceSnapshotStore()
ANALYSIS_STORE=AnalysisSnapshotStore()
DRAFT_VALIDATION_SERVICE=DraftValidationService(OZON_CLIENT)
SHIPMENT_PLAN_STORE=ShipmentPlanStore()
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

def vault_response(status): return wire(status)

async def json_object(request:Request):
    try:
        value=await request.json()
    except (json.JSONDecodeError,UnicodeDecodeError):
        return None
    return value if isinstance(value,dict) else None

@router.get('/api/ozon/credentials/status')
def ozon_credentials_status():
    return vault_response(OZON_VAULT.status())

@router.post('/api/ozon/credentials/setup')
async def ozon_credentials_setup(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    required=('client_id','api_key','password','password_confirmation')
    if any(not isinstance(body.get(name),str) or not body[name].strip() for name in required):
        return error(400,'MISSING_FIELD','Required credential field is missing.',None)
    if body['password']!=body['password_confirmation']:
        return error(400,'PASSWORD_CONFIRMATION_MISMATCH','Password confirmation does not match.','password_confirmation')
    try:
        credentials=OzonCredentials(body['client_id'],body['api_key'])
        return vault_response(OZON_VAULT.setup(credentials,body['password']))
    except ValueError:
        return error(400,'INVALID_CREDENTIALS','Credentials and password must be nonblank.',None)
    except OSError:
        return error(500,'OZON_VAULT_WRITE_FAILED','Could not save the encrypted credential vault.',None)

@router.post('/api/ozon/credentials/unlock')
async def ozon_credentials_unlock(request:Request):
    body=await json_object(request)
    if body is None or not isinstance(body.get('password'),str) or not body['password'].strip():
        return error(400,'MISSING_FIELD','Vault password is required.','password')
    try:return vault_response(OZON_VAULT.unlock(body['password']))
    except OzonVaultError as exc:return error(401,exc.code.value,'Vault password or encrypted data is invalid.',None)

@router.post('/api/ozon/credentials/lock')
def ozon_credentials_lock():
    return vault_response(OZON_VAULT.lock())

@router.post('/api/ozon/connection/test')
def ozon_connection_test():
    try:
        OZON_VAULT.require_credentials()
        OZON_CLIENT.post_json(CONNECTION_TEST_PATH,{},policy=OzonRequestPolicy(retry_safe=True))
    except OzonVaultError as exc:
        return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        statuses={OzonErrorCode.AUTH_FAILED:401,OzonErrorCode.RATE_LIMITED:429,
                  OzonErrorCode.UNAVAILABLE:503,OzonErrorCode.INVALID_RESPONSE:502}
        return error(statuses.get(exc.code,502),exc.code.value,str(exc),None)
    return vault_response(OZON_VAULT.record_connection_check())

@router.post('/api/ozon/handoff/search')
async def ozon_handoff_search(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    query=body.get('query')
    supply_types=body.get('supply_types',[])
    if not isinstance(query,str) or len(query.strip())<4:
        return error(400,'HANDOFF_QUERY_TOO_SHORT','Enter at least 4 characters.','query')
    if not isinstance(supply_types,list) or not all(isinstance(item,str) and item.strip() for item in supply_types):
        return error(400,'INVALID_SUPPLY_TYPES','Expected a list of supply types.','supply_types')
    try:
        ozon_supply_types=handoff_supply_types(tuple(supply_types))
    except ValueError:
        return error(400,'INVALID_SUPPLY_TYPES','Unknown shipment method.','supply_types')
    try:
        OZON_VAULT.require_credentials()
        points=search_handoff_points(OZON_CLIENT,query,ozon_supply_types)
        HANDOFF_STORE.put_all(points)
        return {'api_version':1,'items':wire(points)}
    except OzonVaultError as exc:return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:return error(503,exc.code.value,str(exc),None)

@router.post('/api/ozon/sync')
def ozon_sync():
    try:
        OZON_VAULT.require_credentials()
        snapshot=sync_ozon_source(OZON_CLIENT)
        OZON_SOURCE_STORE.put(snapshot)
        return {'api_version':1,'source':wire(snapshot),'capabilities':capability_matrix(snapshot)}
    except OzonVaultError as exc:return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)

@router.get('/api/ozon/source/{source_snapshot_id}/status')
def ozon_source_status(source_snapshot_id:str):
    snapshot=OZON_SOURCE_STORE.get(source_snapshot_id)
    if snapshot is None:return error(404,'OZON_SOURCE_SNAPSHOT_NOT_FOUND','Ozon source snapshot was not found.','source_snapshot_id')
    return {'api_version':1,'source_snapshot_id':source_snapshot_id,'source_as_of':snapshot.source_as_of.isoformat(),
            'source_timezone':snapshot.source_timezone,'capabilities':capability_matrix(snapshot),
            'endpoint_evidence':wire(snapshot.endpoint_evidence),'diagnostics':wire(snapshot.diagnostics)}

@router.post('/api/shipment/candidates')
async def shipment_candidates(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported_fields={'analysis_snapshot_id','shippable_plan_id','scenario'}
    unsupported_fields=set(body)-supported_fields
    if unsupported_fields:
        field=sorted(unsupported_fields)[0]
        return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',field)
    analysis_id=body.get('analysis_snapshot_id')
    plan_id=body.get('shippable_plan_id')
    if not isinstance(analysis_id,str) or not analysis_id.strip():
        return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():
        return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    snapshot=ANALYSIS_STORE.get(analysis_id)
    if snapshot is None:
        return error(404,'ANALYSIS_SNAPSHOT_NOT_FOUND','Analysis snapshot was not found.','analysis_snapshot_id')
    plan=snapshot.shippable_plan
    if plan is None or plan.shippable_plan_id != plan_id or plan.analysis_snapshot_id != analysis_id:
        return error(409,'SHIPPABLE_PLAN_IDENTITY_MISMATCH','Shippable Plan does not belong to this analysis.','shippable_plan_id')
    try:
        scenario=parse_shipment_scenario(body.get('scenario'))
    except ValueError:
        return error(400,'INVALID_SHIPMENT_SCENARIO','Shipment scenario is invalid.','scenario')
    seller_warehouses=()
    if plan.source_snapshot_id is not None:
        source=OZON_SOURCE_STORE.get(plan.source_snapshot_id)
        if source is None:
            return error(409,'OZON_SOURCE_SNAPSHOT_NOT_FOUND','The analysis source snapshot is no longer available.','analysis_snapshot_id')
        if source.source_as_of != plan.analysis_as_of:
            return error(409,'SOURCE_PROVENANCE_MISMATCH','Analysis and source provenance do not match.','analysis_snapshot_id')
        seller_warehouses=source.seller_warehouses
    result=build_candidate_result(plan=plan,scenario=scenario,
        seller_warehouses=seller_warehouses,handoff_store=HANDOFF_STORE,
        max_candidates=DEFAULT_MAX_CANDIDATES)
    return {'api_version':1,'analysis_snapshot_id':analysis_id,
            'shippable_plan_id':plan_id,'candidates':wire(result.candidates),
            'diagnostics':wire(result.diagnostics)}

@router.post('/api/shipment/validate')
async def shipment_validate(request:Request):
    """Validate reconstructed backend candidates; client rows are never authoritative."""
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported={'analysis_snapshot_id','shippable_plan_id','scenario','candidate_ids'}
    extra=set(body)-supported
    if extra:return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',sorted(extra)[0])
    analysis_id=body.get('analysis_snapshot_id'); plan_id=body.get('shippable_plan_id')
    candidate_ids=body.get('candidate_ids')
    if not isinstance(analysis_id,str) or not analysis_id.strip():
        return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():
        return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    if not isinstance(candidate_ids,list) or not candidate_ids or any(not isinstance(x,str) or not x.strip() for x in candidate_ids) or len(candidate_ids)!=len(set(candidate_ids)):
        return error(400,'INVALID_CANDIDATE_IDS','Candidate identities must be a nonempty unique list.','candidate_ids')
    try: prepared=prepare_shipment_validation(analysis_store=ANALYSIS_STORE,
        source_store=OZON_SOURCE_STORE,handoff_store=HANDOFF_STORE,
        analysis_id=analysis_id,plan_id=plan_id,scenario_payload=body.get('scenario'),
        candidate_ids=candidate_ids)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try: OZON_VAULT.require_credentials()
    except OzonVaultError:return error(423,'OZON_VAULT_LOCKED','Unlock the Ozon credential vault first.',None)
    source_id=prepared.snapshot.source_snapshot_id
    options=await asyncio.to_thread(DRAFT_VALIDATION_SERVICE.validate,prepared.candidates,prepared.scenario,
                                    provenance=f'{analysis_id}:{plan_id}:{source_id}',
                                    source_clusters=prepared.source_snapshot.clusters)
    return {'api_version':1,'analysis_snapshot_id':analysis_id,
            'shippable_plan_id':plan_id,'options':wire(options)}

@router.post('/api/shipment/plan')
async def shipment_plan(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported={'analysis_snapshot_id','shippable_plan_id','scenario','candidate_ids'}
    extra=set(body)-supported
    if extra:return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',sorted(extra)[0])
    analysis_id=body.get('analysis_snapshot_id');plan_id=body.get('shippable_plan_id');ids=body.get('candidate_ids')
    if not isinstance(analysis_id,str) or not analysis_id.strip():return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x.strip() for x in ids) or len(ids)!=len(set(ids)):
        return error(400,'INVALID_CANDIDATE_IDS','Candidate identities must be a nonempty unique list.','candidate_ids')
    try: prepared=prepare_shipment_validation(analysis_store=ANALYSIS_STORE,
        source_store=OZON_SOURCE_STORE,handoff_store=HANDOFF_STORE,
        analysis_id=analysis_id,plan_id=plan_id,scenario_payload=body.get('scenario'),
        candidate_ids=ids)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try:OZON_VAULT.require_credentials()
    except OzonVaultError:return error(423,'OZON_VAULT_LOCKED','Unlock the Ozon credential vault first.',None)
    source_id=prepared.snapshot.source_snapshot_id
    options=await asyncio.to_thread(DRAFT_VALIDATION_SERVICE.validate,prepared.candidates,prepared.scenario,provenance=f'{analysis_id}:{plan_id}:{source_id}',source_clusters=prepared.source_snapshot.clusters)
    try:shipment=build_shipment_plan(source_snapshot_id=source_id,analysis_snapshot_id=analysis_id,shippable_plan_id=plan_id,analysis_as_of=prepared.snapshot.analysis_as_of,scenario=prepared.scenario,candidates=prepared.candidates,validations=options,diagnostics=tuple(x.code for x in prepared.diagnostics))
    except ShipmentOrchestrationError as exc:return error(502,exc.code,'Ozon validation returned inconsistent candidate evidence.',None)
    SHIPMENT_PLAN_STORE.put(shipment)
    return {'api_version':1,'shipment_plan':wire(shipment)}

@router.post('/api/shipment/export')
async def shipment_export(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    extra=set(body)-{'shipment_plan_id','option_id'}
    if extra:return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',sorted(extra)[0])
    plan_id=body.get('shipment_plan_id');option_id=body.get('option_id')
    if not isinstance(plan_id,str) or not plan_id.strip():return error(400,'SHIPMENT_PLAN_ID_REQUIRED','Shipment plan identity is required.','shipment_plan_id')
    if not isinstance(option_id,str) or not option_id.strip():return error(400,'SHIPMENT_OPTION_ID_REQUIRED','Shipment option identity is required.','option_id')
    plan=SHIPMENT_PLAN_STORE.get(plan_id)
    if plan is None:return error(404,'SHIPMENT_PLAN_NOT_FOUND','Shipment plan was not found.','shipment_plan_id')
    option=next((x for x in plan.ranked_options if x.option_id==option_id),None)
    if option is None:
        if any(x.candidate.candidate_id==option_id for x in plan.unavailable_options):return error(409,'EXPORT_OPTION_NOT_EXPORTABLE','Shipment option is not exportable.','option_id')
        return error(404,'SHIPMENT_OPTION_NOT_FOUND','Shipment option was not found.','option_id')
    try:artifact=render_export(option,plan_id)
    except ShipmentExportError as exc:return error(409,exc.code,'Shipment option cannot be exported.',None)
    return Response(artifact.content,media_type=artifact.media_type,headers={'Content-Disposition':f'attachment; filename="{artifact.filename}"'})

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

@dataclass(frozen=True, slots=True)
class PreparedAnalysisInputs:
    """Typed source boundary shared by FILES import results and API evidence."""
    availability: ImportResult
    restrictions: ImportResult
    orders: ImportResult
    operational_availability: tuple
    placement_zone_evidence: tuple = ()
    source_coverage: AnalysisSourceCoverage | None = None


def _api_prepared_inputs(snapshot, *, include_inbound: bool = True) -> PreparedAnalysisInputs:
    imported_at = snapshot.synced_at_utc
    availability_meta = ReportMeta("ozon-api:availability", imported_at)
    restrictions_meta = ReportMeta("ozon-api:restrictions-unavailable", imported_at)
    orders_meta = ReportMeta(
        "ozon-api:orders", imported_at, period_start=snapshot.history_from.isoformat(),
        period_end=snapshot.history_to.isoformat())
    # Restrictions are explicitly unavailable, never fabricated as "allowed".
    restrictions = ImportResult((), (), restrictions_meta)
    diagnostics_by_endpoint = {evidence.name: tuple(evidence.diagnostics)
                               for evidence in snapshot.endpoint_evidence}
    completeness = {evidence.name: evidence.complete
                    for evidence in snapshot.endpoint_evidence}
    order_diagnostics = diagnostics_by_endpoint.get("orders_fbo", ()) + diagnostics_by_endpoint.get("orders_fbs", ())
    availability_diagnostics = diagnostics_by_endpoint.get("fbo_stock", ())
    if include_inbound:
        availability_diagnostics += diagnostics_by_endpoint.get("inbound", ())
    return PreparedAnalysisInputs(
        ImportResult(tuple(snapshot.availability), availability_diagnostics, availability_meta),
        restrictions,
        ImportResult(tuple(snapshot.orders), order_diagnostics, orders_meta),
        tuple(snapshot.availability) + tuple(snapshot.operational_seller_stock),
        tuple(snapshot.placement_zones),
        AnalysisSourceCoverage(
            completeness.get("orders_fbo", False),
            completeness.get("orders_fbs", False),
            completeness.get("fbo_stock", False),
            completeness.get("inbound", False),
        ),
    )

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
    bundle=import_unitka_bundle(data,context)
    products, tariffs, packs = bundle.product_economics, bundle.tariffs, bundle.pack_multiplicity
    return {"api_version":1,"kind":"unitka","product_economics":wire(products.records),"tariffs":wire(tariffs.records),
            "pack_multiplicity":wire(packs.records),
            "diagnostics":wire(products.diagnostics+tariffs.diagnostics+packs.diagnostics),"meta":wire(context),
            "record_sources":{"product_economics":list(products.record_sources),"tariffs":list(tariffs.record_sources),
                              "pack_multiplicity":list(packs.record_sources)}}

async def prepare_analysis(request:Request, request_id="http"):
    form=await request.form(); common=['availability_file','restrictions_file','orders_file']
    try: source_mode=SourceMode(str(form.get('source_mode','files')).strip().lower())
    except ValueError:return error(400,'INVALID_SOURCE_MODE','Expected api or files.','source_mode')
    explicit_horizon=form.get("horizon_days")
    if explicit_horizon is not None:
        value=str(explicit_horizon).strip()
        if not value.isascii() or not value.isdigit() or value.startswith("+") or int(value)<=0:
            return error(400,"INVALID_HORIZON_DAYS","Expected a positive integer.","horizon_days")
        explicit_horizon=int(value)
    raw_inbound=str(form.get("include_inbound","true")).strip().lower()
    if raw_inbound not in {"true","false"}:
        return error(400,"INVALID_INCLUDE_INBOUND","Expected true or false.","include_inbound")
    raw_objective=str(form.get("optimization_objective","max_margin")).strip()
    if raw_objective != AllocationObjective.MAX_MARGIN.value:
        return error(400,"INVALID_OPTIMIZATION_OBJECTIVE","Unsupported optimization objective.","optimization_objective")
    objective=AllocationObjective.MAX_MARGIN
    snapshot=None
    if source_mode is SourceMode.API:
        if any(form.get(field) is not None for field in common):
            return error(400,'MIXED_SOURCE_MODE','API source cannot be combined with Ozon report files.',None)
        source_snapshot_id=str(form.get('source_snapshot_id','')).strip()
        if not source_snapshot_id:return error(400,'MISSING_SOURCE_SNAPSHOT_ID','API source snapshot identity is required.','source_snapshot_id')
        snapshot=OZON_SOURCE_STORE.get(source_snapshot_id)
        if snapshot is None:return error(400,'OZON_SOURCE_SNAPSHOT_NOT_FOUND','Ozon source snapshot was not found.','source_snapshot_id')
    else:
        for field in common:
            if form.get(field) is None:return error(400,'MISSING_FIELD','Required multipart field is missing.',field)
    unitka=form.get('unitka_file'); legacy=(form.get('tariffs_file'),form.get('product_economics_file'))
    if unitka is not None and any(legacy): return error(400,'MIXED_INPUT_MODE','Unitka cannot be combined with legacy economics files.','unitka_file')
    if unitka is None and not all(legacy): return error(400,'MISSING_ECONOMICS_INPUT','Provide unitka_file or both legacy economics files.','unitka_file')
    files=common+(['unitka_file'] if unitka is not None else ['tariffs_file','product_economics_file'])
    if source_mode is SourceMode.API:
        legacy_as_of=str(form.get('as_of','')).strip()
        if legacy_as_of and legacy_as_of != snapshot.source_as_of.isoformat():
            return error(400,'API_AS_OF_MISMATCH','API analysis date must equal source snapshot date.','as_of')
        as_of=snapshot.source_as_of
    else:
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
    raw=[]; source_inputs=None
    if source_mode is SourceMode.API:
        source_inputs=_api_prepared_inputs(snapshot, include_inbound=raw_inbound == "true")
        economic_files=(['unitka_file'] if unitka is not None else ['tariffs_file','product_economics_file'])
        for field in economic_files:
            try: raw.append((form[field],await read(form[field],field,request_id)))
            except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    else:
        for field in files:
            try: raw.append((form[field],await read(form[field],field,request_id)))
            except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    provenance=(source_mode,snapshot.source_snapshot_id if snapshot else None)
    return raw, unitka, files, values, tax, as_of, (explicit_horizon,raw_inbound=="true",objective), provenance, source_inputs

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


def run_analysis_pipeline(raw, unitka, files, values, tax, as_of, scenario_request=(None,True,AllocationObjective.MAX_MARGIN), provenance=(SourceMode.FILES,None), source_inputs=None, *, progress_callback=None, request_id="http"):
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
    if source_inputs is None:
        availability=timed("availability_import",import_availability,raw[0][1],meta(raw[0][0]))
        progress("reports",2,4,"restrictions")
        restrictions=timed("restrictions_import",import_restrictions,raw[1][1],meta(raw[1][0]))
        progress("reports",3,4,"orders")
        orders=timed("orders_import",import_orders,raw[2][1],meta(raw[2][0]))
        economics_offset=3
        operational_availability=availability.records
    else:
        availability=source_inputs.availability
        progress("reports",2,4,"restrictions")
        restrictions=source_inputs.restrictions
        progress("reports",3,4,"orders")
        orders=source_inputs.orders
        economics_offset=0
        operational_availability=source_inputs.operational_availability
    progress("reports",4,4,"unitka" if unitka is not None else "economics")

    if unitka is not None:
        def unitka_timing(name, duration, rows):
            suffix="" if rows is None else f" rows={rows}"
            logger.info("[analysis %s] %s done %.3fs%s",request_id,name,duration,suffix)
        bundle=import_unitka_bundle(raw[economics_offset][1],meta(raw[economics_offset][0]),timing=unitka_timing)
        tariffs,products=bundle.tariffs,bundle.product_economics
        pack_evidence=bundle.pack_multiplicity.records
    else:
        tariffs=timed("tariffs_import",import_tariffs,raw[economics_offset][1],meta(raw[economics_offset][0])); products=timed("product_economics_import",import_product_economics,raw[economics_offset+1][1],meta(raw[economics_offset+1][0]))
        pack_evidence=()
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
    raw_unitka_products=products.records
    current_article_skus={}
    for item in analysis_availability:
        if item.article:current_article_skus.setdefault(item.article,set()).add(item.sku)
    primary={}; primary_conflicts=set()
    for item in analysis_availability:
        if not item.article: continue
        if item.article in primary and primary[item.article]!=item.sku: primary_conflicts.add(item.article)
        else: primary[item.article]=item.sku
    fallback={}
    for item in analysis_orders:
        if item.article:fallback.setdefault(item.article,set()).add(item.sku)
    joined=[]; join_diags=[]; quality_facts=[]
    product_sources = products.record_sources or (None,) * len(products.records)
    for product, source_row in zip(products.records, product_sources):
        if product.sku:joined.append(product);continue
        if product.article in primary_conflicts:
            join_diags.append(ImportDiagnostic('warning','CONFLICTING_ARTICLE_TO_SKU','Unitka article has conflicting availability mappings; affected current SKU remain blocked without economics.'))
            quality_facts.append(DataQualityFact('CONFLICTING_ARTICLE_TO_SKU','article',product.article,product.article,'warning',article=product.article,source_name=products.meta.source_name,source_row=source_row));continue
        sku=primary.get(product.article)
        if sku is None:
            candidates=fallback.get(product.article,set())
            if len(candidates)>1:
                join_diags.append(ImportDiagnostic('warning','AMBIGUOUS_ARTICLE_TO_SKU_FALLBACK','Unitka article has ambiguous historical mappings; affected current SKU remain blocked without economics.'))
                quality_facts.append(DataQualityFact('AMBIGUOUS_ARTICLE_TO_SKU_FALLBACK','article',product.article,product.article,'warning',article=product.article,source_name=products.meta.source_name,source_row=source_row));continue
            sku=next(iter(candidates),None)
        if sku:joined.append(replace(product,sku=sku))
        else:
            join_diags.append(ImportDiagnostic('warning','MISSING_ARTICLE_TO_SKU','Unitka article is outside the current SKU universe.'))
            quality_facts.append(DataQualityFact('MISSING_ARTICLE_TO_SKU','article',product.article,product.article,'warning',article=product.article,source_name=products.meta.source_name,source_row=source_row))
    products=replace(products,records=tuple(joined),diagnostics=products.diagnostics+tuple(join_diags))
    logger.info("[analysis %s] article_join done %.3fs rows=%d",request_id,perf_counter()-join_started,len(products.records))
    logger.info("[analysis %s] reports done %.3fs",request_id,perf_counter()-reports_started)
    imported=[availability,restrictions,orders,tariffs,products]
    settings=EconomicsSettings(*(values[n] for n in DECIMAL_NAMES[:4]),tax,*(values[n] for n in DECIMAL_NAMES[4:7])); thresholds=OptimizerThresholds(*(values[n] for n in DECIMAL_NAMES[7:]))
    explicit_horizon,include_inbound,objective=scenario_request
    scenario=ScenarioSettings(explicit_horizon or availability.meta.recommendation_horizon_days or 56,include_inbound,objective)
    result=analyze(analysis_availability,analysis_restrictions,analysis_orders,analysis_tariffs,products.records,as_of=as_of,economics_settings=settings,optimizer_thresholds=thresholds,availability_fbs_authoritative=unitka is not None,operational_availability=operational_availability,ozon_horizon_days=availability.meta.recommendation_horizon_days,source_mode=provenance[0],source_coverage=(source_inputs.source_coverage if source_inputs is not None else None),progress_callback=progress_callback,scenario_settings=scenario)
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
    product_identities = {}
    for item in analysis_availability:
        previous = product_identities.get(item.sku, ("", ""))
        product_identities[item.sku] = (
            first_nonblank(previous[0], item.article),
            first_nonblank(previous[1], item.product_name),
        )
    # Import recovery evidence retains source/row without copying arbitrary source data.
    for imported_result in imported:
        for occurrence, diagnostic in enumerate(imported_result.diagnostics):
            if diagnostic.code == "WORKSHEET_DIMENSION_REPAIRED":
                row = diagnostic.row
                key = f"{imported_result.meta.source_name}::{row if row is not None else occurrence}"
                quality_facts.append(DataQualityFact(diagnostic.code, "worksheet", key,
                    imported_result.meta.source_name, diagnostic.severity,
                    source_name=imported_result.meta.source_name, source_row=row))
    # Canonical logistics results remain the sole money lookup. These facts only
    # explain its already-incomplete contributions.
    product_map = {item.sku: item for item in products.records}
    for logistics in result.logistics:
        product = product_map.get(logistics.sku)
        if product is None:
            continue
        context = LogisticsContext(
            logistics.sku, logistics.origin_cluster_id, product.volume_liters,
            product.price, logistics.route_profile_source)
        for contribution in logistics.contributions:
            if contribution.lookup_status.value == "matched":
                continue
            code = "AMBIGUOUS_TARIFF_MATCH" if contribution.lookup_status.value == "ambiguous" else (
                "PRICE_REQUIRED_FOR_TARIFF_LOOKUP" if classify_tariff_gap(
                    analysis_tariffs, context, contribution.destination_cluster_id) == "PRICE_REQUIRED" else "MISSING_TARIFF")
            detail_code = classify_tariff_gap(analysis_tariffs, context, contribution.destination_cluster_id)
            key = f"{logistics.sku}::{logistics.origin_cluster_id}::{contribution.destination_cluster_id}::{product.volume_liters}::{product.price}"
            detail = tariff_gap_user_detail(detail_code,product.volume_liters,product.price)
            quality_facts.append(DataQualityFact(code,"route",key,
                f"{logistics.origin_cluster_id} → {contribution.destination_cluster_id} · {logistics.sku}",
                "error",sku=logistics.sku,origin_cluster_id=logistics.origin_cluster_id,
                destination_cluster_id=contribution.destination_cluster_id,
                detail_code=detail_code,detail=detail))
    quality_facts.extend(build_stockout_tariff_quality_facts(
        stockout_episode_impacts=result.stockout_episode_impacts,
        products=products.records,tariffs=analysis_tariffs))
    # Structured SKU identities improve labels and classify stock/economics gaps.
    for diagnostic in diagnostic_views:
        if diagnostic.code not in {"MISSING_SELLER_AVAILABLE_STOCK", "CONFLICTING_FBS_AVAILABLE_STOCK", "MISSING_PRODUCT_ECONOMICS", "MISSING_PRODUCT_VOLUME", "INCOMPLETE_LOGISTICS_COVERAGE"}:
            continue
        article, name = product_identities.get(diagnostic.sku, ("", ""))
        label = " · ".join(x for x in (article, diagnostic.sku, name) if x)
        detail_code = None
        if diagnostic.code == "MISSING_SELLER_AVAILABLE_STOCK":
            rows = [x for x in availability.records if x.sku == diagnostic.sku]
            detail_code = "NO_AVAILABILITY_FOR_SKU" if not rows else "FBS_VALUE_MISSING"
        elif diagnostic.code == "CONFLICTING_FBS_AVAILABLE_STOCK":
            detail_code = "CONFLICTING_FBS_AVAILABLE_STOCK"
        elif diagnostic.code == "MISSING_PRODUCT_ECONOMICS":
            candidates={x.article for x in analysis_availability
                        if x.sku==diagnostic.sku and x.article}
            candidates.update(x.article for x in analysis_orders
                              if x.sku==diagnostic.sku and x.article)
            detail_code, detail = classify_product_economics_gap(
                diagnostic.sku,candidates,raw_unitka_products,
                current_article_skus,fallback)
        else:
            detail = None
        origin = diagnostic.cluster_id if diagnostic.code == "INCOMPLETE_LOGISTICS_COVERAGE" else None
        key = f"{diagnostic.sku}::{origin}" if origin else diagnostic.sku
        quality_facts.append(DataQualityFact(diagnostic.code,"calculation" if origin else "sku",key,label or diagnostic.sku,
            diagnostic.severity,sku=diagnostic.sku,article=article or None,origin_cluster_id=origin,
            detail_code=detail_code,detail=detail if diagnostic.code=="MISSING_PRODUCT_ECONOMICS" else None))
    data_quality = build_data_quality_presentation(diagnostics=diagnostic_views,
                                                   structured_facts=quality_facts)
    snapshot=assemble_snapshot(scenario=scenario,report_meta=report_meta,input_statuses=status_views,
        demand_estimates=result.demand_estimates,needs=result.needs,observed_routes=result.observed_routes,
        clean_routes=result.clean_routes,stockout_signals=result.stockouts,distortion_signals=result.distortions,
        route_economics=result.route_economics,unit_economics=result.economics,placements=result.placements,
        safe_allocations=result.safe_allocations,calculated_allocations=result.allocations,products=products.records,
        diagnostics=diagnostic_views,data_quality=data_quality,freshness_warnings=tuple(warnings),
        product_identities=product_identities, daily_locality=result.daily_locality,
        stockout_episode_impacts=result.stockout_episode_impacts,analysis_as_of=as_of,
        source_mode=provenance[0],source_snapshot_id=provenance[1])
    cluster_ids=tuple(sorted({row.destination_cluster_id for row in snapshot.decision_rows}))
    supply_facts=build_operational_supply_facts(
        products=(SupplyProductIdentity(product.sku, product.article)
                  for product in products.records),
        cluster_ids=cluster_ids,
        pack_evidence=pack_evidence,
        source_mode=snapshot.source_mode,
        placement_zone_evidence=(() if source_inputs is None
                                 else source_inputs.placement_zone_evidence),
        restrictions=(analysis_restrictions if snapshot.source_mode is SourceMode.FILES else ()),
        restriction_report_date=None,
    )
    shippable_plan=build_shippable_plan(
        analysis_snapshot_id=snapshot.snapshot_id,
        source_mode=snapshot.source_mode,
        source_snapshot_id=snapshot.source_snapshot_id,
        analysis_as_of=snapshot.analysis_as_of,
        horizon_days=snapshot.scenario.horizon_days,
        include_inbound=snapshot.scenario.include_inbound,
        objective=snapshot.scenario.objective,
        calculated_allocations=snapshot.calculated_allocations,
        products=products.records,
        supply_facts=supply_facts,
        blocked_decision_rows=snapshot.decision_rows,
    )
    snapshot=replace(snapshot,shippable_plan=shippable_plan)
    ANALYSIS_STORE.put(snapshot)
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
