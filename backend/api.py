"""Stateless multipart HTTP boundary."""
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
import asyncio
import inspect
import json
import logging
from pathlib import Path, PurePath
from queue import Queue
from threading import Event, RLock, Thread
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
from backend.ingestion.orders import import_orders, scope_orders_to_coverage
from backend.analytics._weeks import (ObservationCoverage,
                                      fully_covered_completed_iso_weeks)
from backend.ingestion.tariffs import import_tariffs
from backend.ingestion.product_economics import import_product_economics
from backend.ingestion.unitka import import_unitka_bundle
from backend.ingestion.supplier_packaging import normalize_supplier_article
from backend.ingestion.api_product_economics import merge_api_product_economics
from backend.project import (EconomicsSettings, OptimizerThresholds, Project,
                             ProjectValidationError, WorkingQuantityOverride, load_project_if_exists,
                             save_project_atomic)
from backend.working_plan import materialize_working_plan, validate_override_quantity
from backend.pack_multiplicity import (apply_rtp_price_snapshot, build_effective_pack_evidence, export_xlsx, parse_import_xlsx,
                                       pack_multiplicity_fingerprint,
                                       reset_override,
                                       resolve_pack_multiplicity, set_override,
                                       sync_unitka_baseline)
from backend.ozon.client import OzonClient, OzonClientError, OzonRequestPolicy
from backend.ozon.contracts import OzonCredentialContext, OzonCredentials, OzonErrorCode
from backend.ozon.endpoints import CONNECTION_TEST_PATH
from backend.ozon.diagnostics import diagnose_connection
from backend.ozon.transport_compare import compare_transports
from backend.ozon.vault import CredentialVault, OzonVaultError
from backend.ozon.handoff import HandoffPointStore, handoff_supply_types, search_handoff_points
from backend.ozon.source_store import OzonSourceSnapshotStore
from backend.ozon.source_persistence import (delete_source_snapshot,
    load_source_snapshot_if_exists, save_source_snapshot_atomic)
from backend.ozon.sync import (OzonRefreshReport, capability_matrix,
                               refresh_ozon_source, source_refresh_regresses,
                               sync_ozon_source)
_ORIGINAL_SYNC_OZON_SOURCE=sync_ozon_source
from backend.ozon.draft_validation import DraftValidationService
from backend.shipment import (DEFAULT_MAX_CANDIDATES, build_candidate_result,
                              build_shipment_input, WorkingPlanIdentityError)
from backend.shipment.store import AnalysisSnapshotStore, ShipmentPlanStore
from backend.shipment.contracts import ShipmentPlan
from backend.shipment.orchestration import build_shipment_plan, ShipmentOrchestrationError
from backend.shipment.export import render_export, ShipmentExportError
from backend.shipment.wire import parse_shipment_scenario
from backend.shipment.api_context import (ShipmentPreparationError,
                                          CREDENTIAL_CONTEXT_MESSAGE,
                                          prepare_shipment_validation,
                                          require_source_credential_context)
MAX_UPLOAD_BYTES=64*1024*1024
router=APIRouter()
logger=logging.getLogger(__name__)
PROJECT_PATH=Path(__file__).resolve().parents[1]/"data"/"project.json"
OZON_SOURCE_PATH=Path(__file__).resolve().parents[1]/"data"/"ozon-source-snapshot.json"
OZON_VAULT=CredentialVault(Path(__file__).resolve().parents[1]/"data"/"ozon-credentials.json")
OZON_CLIENT=OzonClient(OZON_VAULT)
HANDOFF_STORE=HandoffPointStore()
OZON_SOURCE_STORE=OzonSourceSnapshotStore()
ANALYSIS_STORE=AnalysisSnapshotStore()
DRAFT_VALIDATION_SERVICE=DraftValidationService(OZON_CLIENT)
SHIPMENT_PLAN_STORE=ShipmentPlanStore()
OZON_CONTEXT_COMMIT_LOCK=RLock()
PROJECT_PERSISTENCE_LOCK=RLock()
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
def meta(upload, *, coverage=None):
    return ReportMeta(
        PurePath(upload.filename or 'upload').name,
        datetime.now(timezone.utc).isoformat(),
        period_start=coverage.period_start.isoformat() if coverage else None,
        period_end=coverage.period_end.isoformat() if coverage else None,
    )
async def read(upload,field,request_id="http"):
    started=perf_counter()
    data=await upload.read(MAX_UPLOAD_BYTES+1)
    logger.info("[analysis %s] multipart_read done %.3fs field=%s bytes=%d",request_id,perf_counter()-started,field,len(data))
    if len(data)>MAX_UPLOAD_BYTES: raise OverflowError(field)
    return data

def response(kind,result): return {"api_version":1,"kind":kind,**wire(result)}

def vault_response(status): return wire(status)

def invalidate_ozon_account_context_state():
    OZON_SOURCE_STORE.clear()
    delete_source_snapshot(OZON_SOURCE_PATH)
    HANDOFF_STORE.clear()
    ANALYSIS_STORE.clear_api()
    SHIPMENT_PLAN_STORE.clear()

def source_status_view(snapshot):
    """Small browser view; normalized row collections remain backend-owned."""
    return {
        'source_snapshot_id':snapshot.source_snapshot_id,
        'synced_at_utc':snapshot.synced_at_utc,
        'source_as_of':snapshot.source_as_of.isoformat(),
        'source_timezone':snapshot.source_timezone,
        'history_from':snapshot.history_from.isoformat(),
        'history_to':snapshot.history_to.isoformat(),
        'credential_context_id':snapshot.credential_context_id,
        'seller_warehouses':wire(snapshot.seller_warehouses),
        'endpoint_evidence':wire(snapshot.endpoint_evidence),
        'diagnostics':wire(snapshot.diagnostics),
    }

def _restore_persisted_source():
    try:
        snapshot=load_source_snapshot_if_exists(OZON_SOURCE_PATH)
        if snapshot is not None and snapshot.credential_context_id==OZON_VAULT.credential_context_id():
            OZON_SOURCE_STORE.put(snapshot)
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        logger.warning('Ignoring invalid persisted Ozon source snapshot',exc_info=True)

_restore_persisted_source()

def credential_context_error(field=None):
    return error(409,'OZON_CREDENTIAL_CONTEXT_CHANGED',CREDENTIAL_CONTEXT_MESSAGE,field)

def commit_current_credential_context(context_id, action, *, field=None):
    """Linearize credential replacement against persistence of API-derived state."""
    with OZON_CONTEXT_COMMIT_LOCK:
        if not context_id or OZON_VAULT.credential_context_id()!=context_id:
            raise ShipmentPreparationError(
                'OZON_CREDENTIAL_CONTEXT_CHANGED',CREDENTIAL_CONTEXT_MESSAGE,field,409)
        return action()

def commit_active_credential_context(context: OzonCredentialContext, action, *, field=None):
    """Linearize live-result commits against unlock-session transitions."""
    with OZON_CONTEXT_COMMIT_LOCK:
        if not OZON_VAULT.is_context_active(context):
            raise ShipmentPreparationError(
                'OZON_CREDENTIAL_CONTEXT_CHANGED',CREDENTIAL_CONTEXT_MESSAGE,field,409)
        return action()

PACK_MULTIPLICITY_CHANGED_MESSAGE = (
    'Кратность упаковки изменилась во время расчёта. Запустите расчёт повторно.'
)
PACK_MULTIPLICITY_CHANGED_DURING_SHIPMENT_VALIDATION_MESSAGE = (
    'Кратность упаковки изменилась во время проверки поставки. '
    'Пересчитайте план и проверьте варианты повторно.'
)
SHIPMENT_INPUT_CHANGED_MESSAGE = (
    'Данные плана изменились во время проверки поставки. '
    'Проверьте варианты в Ozon повторно.'
)
WORKING_PLAN_CHANGED_MESSAGE = (
    'Рабочий план изменился. Проверьте варианты поставки повторно.'
)

def _require_current_shippable_plan(analysis_snapshot_id, shippable_plan_id):
    snapshot=ANALYSIS_STORE.get(analysis_snapshot_id)
    latest=ANALYSIS_STORE.latest()
    if (snapshot is None or latest is None or latest.snapshot_id!=analysis_snapshot_id or
            snapshot.shippable_plan is None or
            snapshot.shippable_plan.shippable_plan_id!=shippable_plan_id):
        raise ShipmentPreparationError(
            'SHIPMENT_INPUT_CHANGED',SHIPMENT_INPUT_CHANGED_MESSAGE,
            'analysis_snapshot_id',409)
    return snapshot

def capture_shipment_pack_fingerprint_if_current(
        *, expected_analysis_snapshot_id, expected_shippable_plan_id,
        expected_working_plan_id):
    """Capture pack master-data only while the prepared plan is authoritative."""
    with PROJECT_PERSISTENCE_LOCK:
        current=load_project_if_exists(PROJECT_PATH)
        snapshot,_,_=require_current_working_plan(
            analysis_snapshot_id=expected_analysis_snapshot_id,
            shippable_plan_id=expected_shippable_plan_id,
            working_plan_id=expected_working_plan_id)
        return pack_multiplicity_fingerprint(current)

def require_current_working_plan(*, analysis_snapshot_id, shippable_plan_id,
                                 working_plan_id):
    """Materialize and require the exact current execution identity."""
    with PROJECT_PERSISTENCE_LOCK:
        snapshot=_require_current_shippable_plan(
            analysis_snapshot_id,shippable_plan_id)
        project=load_project_if_exists(PROJECT_PATH)
        working=materialize_working_plan(
            snapshot.shippable_plan,project.working_quantity_overrides)
        if working.working_plan_id!=working_plan_id:
            raise ShipmentPreparationError(
                'WORKING_PLAN_CHANGED',WORKING_PLAN_CHANGED_MESSAGE,
                'working_plan_id',409)
        return snapshot,snapshot.shippable_plan,working

def commit_shipment_plan_if_current(
        shipment: ShipmentPlan, *, expected_analysis_snapshot_id: str,
        expected_shippable_plan_id: str, expected_pack_fingerprint: str,
        expected_working_plan_id: str,
        credential_context: OzonCredentialContext):
    """Atomically reject stale live validation before persisting its plan."""
    with OZON_CONTEXT_COMMIT_LOCK:
        if not OZON_VAULT.is_context_active(credential_context):
            raise ShipmentPreparationError(
                'OZON_CREDENTIAL_CONTEXT_CHANGED',CREDENTIAL_CONTEXT_MESSAGE,
                'analysis_snapshot_id',409)
        with PROJECT_PERSISTENCE_LOCK:
            current=load_project_if_exists(PROJECT_PATH)
            if pack_multiplicity_fingerprint(current)!=expected_pack_fingerprint:
                raise ShipmentPreparationError(
                    'PACK_MULTIPLICITY_CHANGED_DURING_SHIPMENT_VALIDATION',
                    PACK_MULTIPLICITY_CHANGED_DURING_SHIPMENT_VALIDATION_MESSAGE,
                    'analysis_snapshot_id',409)
            require_current_working_plan(
                analysis_snapshot_id=expected_analysis_snapshot_id,
                shippable_plan_id=expected_shippable_plan_id,
                working_plan_id=expected_working_plan_id)
            return SHIPMENT_PLAN_STORE.put(shipment)

def commit_analysis_snapshot_if_current(
        snapshot, *, expected_pack_fingerprint, expected_credential_context_id=None,
        require_credential_context=False):
    """Atomically guard an analysis commit by credential and pack revisions.

    Lock order for the only operation requiring both locks is always Ozon
    context first, then Project persistence.
    """
    def commit_under_project_lock():
        with PROJECT_PERSISTENCE_LOCK:
            current=load_project_if_exists(PROJECT_PATH)
            if pack_multiplicity_fingerprint(current)!=expected_pack_fingerprint:
                raise ShipmentPreparationError(
                    'PACK_MULTIPLICITY_CHANGED_DURING_ANALYSIS',
                    PACK_MULTIPLICITY_CHANGED_MESSAGE,None,409)
            return ANALYSIS_STORE.put(snapshot)

    if require_credential_context:
        return commit_current_credential_context(
            expected_credential_context_id,commit_under_project_lock,
            field='source_snapshot_id')
    return commit_under_project_lock()

def _persist_unitka_baseline(project, evidence):
    """Persist a changed Unitka baseline and invalidate dependent stores."""
    updated=sync_unitka_baseline(project,evidence)
    changed=updated.pack_multiplicity!=project.pack_multiplicity
    if changed:
        save_project_atomic(PROJECT_PATH,updated)
        ANALYSIS_STORE.clear()
        SHIPMENT_PLAN_STORE.clear()
        return updated,True
    return project,False

def current_source(source_snapshot_id, *, field='source_snapshot_id'):
    snapshot=OZON_SOURCE_STORE.get(source_snapshot_id)
    if snapshot is None:
        raise ShipmentPreparationError('OZON_SOURCE_SNAPSHOT_NOT_FOUND','Ozon source snapshot was not found.',field,404)
    return require_source_credential_context(snapshot,OZON_VAULT.credential_context_id(),field=field)

async def json_object(request:Request):
    try:
        value=await request.json()
    except (json.JSONDecodeError,UnicodeDecodeError):
        return None
    return value if isinstance(value,dict) else None

def _working_base(analysis_id, plan_id):
    latest=ANALYSIS_STORE.latest()
    if latest is None or latest.snapshot_id!=analysis_id:
        return None,None
    try:
        snapshot=_require_current_shippable_plan(analysis_id,plan_id)
    except ShipmentPreparationError:
        return None,None
    return snapshot,snapshot.shippable_plan

def require_working_base_current(analysis_id, plan_id):
    """Require the requested Working Plan base while persistence is locked."""
    latest=ANALYSIS_STORE.latest()
    if latest is None or latest.snapshot_id!=analysis_id:
        raise ShipmentPreparationError(
            'WORKING_PLAN_BASE_CHANGED',
            'План уже пересчитан. Повторите изменение на актуальных данных.',
            'analysis_snapshot_id',409)
    snapshot=ANALYSIS_STORE.get(analysis_id)
    if (snapshot is None or snapshot.shippable_plan is None or
            snapshot.shippable_plan.shippable_plan_id!=plan_id):
        raise ShipmentPreparationError(
            'WORKING_PLAN_BASE_CHANGED',
            'План уже пересчитан. Повторите изменение на актуальных данных.',
            'analysis_snapshot_id',409)
    return snapshot.shippable_plan

def _working_response(plan, project):
    return {'api_version':1,'working_plan':wire(materialize_working_plan(
        plan,project.working_quantity_overrides))}

def _working_base_error():
    return error(409,'WORKING_PLAN_BASE_CHANGED',
        'План уже пересчитан. Повторите изменение на актуальных данных.',
        'analysis_snapshot_id')

def _working_identity(body):
    return body.get('sku'),body.get('destination_cluster_id')

def _find_working_line(plan, identity):
    return next((line for line in plan.lines
                 if (line.sku,line.destination_cluster_id)==identity),None)

@router.post('/api/working-plan')
async def working_plan_get(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    if set(body)-{'analysis_snapshot_id','shippable_plan_id'}:
        return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',None)
    _,plan=_working_base(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
    if plan is None:return _working_base_error()
    with PROJECT_PERSISTENCE_LOCK: project=load_project_if_exists(PROJECT_PATH)
    return _working_response(plan,project)

@router.put('/api/working-plan/override')
async def working_plan_override(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    if set(body)-{'analysis_snapshot_id','shippable_plan_id','sku','destination_cluster_id','quantity'}:
        return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',None)
    _,plan=_working_base(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
    if plan is None:return _working_base_error()
    identity=_working_identity(body); line=_find_working_line(plan,identity)
    if line is None:return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','sku')
    try: quantity=validate_override_quantity(line,body.get('quantity'))
    except ValueError as exc:return error(400,'INVALID_WORKING_QUANTITY',str(exc),'quantity')
    with PROJECT_PERSISTENCE_LOCK:
        try: plan=require_working_base_current(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
        line=_find_working_line(plan,identity)
        if line is None:return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','sku')
        try: quantity=validate_override_quantity(line,body.get('quantity'))
        except ValueError as exc:return error(400,'INVALID_WORKING_QUANTITY',str(exc),'quantity')
        project=load_project_if_exists(PROJECT_PATH)
        overrides={sku:dict(rows) for sku,rows in project.working_quantity_overrides.items()}
        if quantity==line.shippable_qty:
            overrides.get(identity[0],{}).pop(identity[1],None)
        else:
            overrides.setdefault(identity[0],{})[identity[1]]=WorkingQuantityOverride(
                quantity,plan.shippable_plan_id,line.shippable_qty,line.pack_multiple,
                datetime.now(timezone(timedelta(hours=3))).isoformat())
        overrides={sku:rows for sku,rows in overrides.items() if rows}
        project=replace(project,working_quantity_overrides=overrides)
        save_project_atomic(PROJECT_PATH,project)
        SHIPMENT_PLAN_STORE.clear()
    return _working_response(plan,project)

@router.post('/api/working-plan/reset')
async def working_plan_reset(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    _,plan=_working_base(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
    if plan is None:return _working_base_error()
    identity=_working_identity(body)
    if _find_working_line(plan,identity) is None:return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','sku')
    with PROJECT_PERSISTENCE_LOCK:
        try: plan=require_working_base_current(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
        if _find_working_line(plan,identity) is None:return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','sku')
        project=load_project_if_exists(PROJECT_PATH)
        overrides={sku:dict(rows) for sku,rows in project.working_quantity_overrides.items()}
        overrides.get(identity[0],{}).pop(identity[1],None)
        overrides={sku:rows for sku,rows in overrides.items() if rows}
        project=replace(project,working_quantity_overrides=overrides);save_project_atomic(PROJECT_PATH,project)
        SHIPMENT_PLAN_STORE.clear()
    return _working_response(plan,project)

@router.post('/api/working-plan/bulk')
async def working_plan_bulk(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    _,plan=_working_base(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
    if plan is None:return _working_base_error()
    action=body.get('action'); raw_lines=body.get('lines')
    if action not in {'reset_to_system','set_zero'} or not isinstance(raw_lines,list):
        return error(400,'INVALID_BULK_ACTION','Некорректное массовое действие.','action')
    identities=[]
    for item in raw_lines:
        if not isinstance(item,dict) or set(item)!={'sku','destination_cluster_id'}:
            return error(400,'INVALID_WORKING_PLAN_LINES','Некорректный набор строк.','lines')
        identities.append((item['sku'],item['destination_cluster_id']))
    found=[_find_working_line(plan,x) for x in identities]
    if any(x is None for x in found):return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','lines')
    with PROJECT_PERSISTENCE_LOCK:
        try: plan=require_working_base_current(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
        found=[_find_working_line(plan,x) for x in identities]
        if any(x is None for x in found):return error(400,'WORKING_PLAN_LINE_NOT_FOUND','Строка рабочего плана не найдена.','lines')
        project=load_project_if_exists(PROJECT_PATH);overrides={sku:dict(rows) for sku,rows in project.working_quantity_overrides.items()}
        for identity,line in zip(identities,found):
            if action=='reset_to_system' or line.shippable_qty==0:overrides.get(identity[0],{}).pop(identity[1],None)
            else:overrides.setdefault(identity[0],{})[identity[1]]=WorkingQuantityOverride(0,plan.shippable_plan_id,line.shippable_qty,line.pack_multiple,datetime.now(timezone(timedelta(hours=3))).isoformat())
        overrides={sku:rows for sku,rows in overrides.items() if rows}
        project=replace(project,working_quantity_overrides=overrides);save_project_atomic(PROJECT_PATH,project)
        SHIPMENT_PLAN_STORE.clear()
    return _working_response(plan,project)

@router.post('/api/working-plan/reset-all')
async def working_plan_reset_all(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    _,plan=_working_base(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
    if plan is None:return _working_base_error()
    with PROJECT_PERSISTENCE_LOCK:
        try: plan=require_working_base_current(body.get('analysis_snapshot_id'),body.get('shippable_plan_id'))
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
        project=replace(load_project_if_exists(PROJECT_PATH),working_quantity_overrides={})
        save_project_atomic(PROJECT_PATH,project);SHIPMENT_PLAN_STORE.clear()
    return _working_response(plan,project)

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
        with OZON_CONTEXT_COMMIT_LOCK:
            status=OZON_VAULT.setup(credentials,body['password'])
            invalidate_ozon_account_context_state()
        return vault_response(status)
    except ValueError:
        return error(400,'INVALID_CREDENTIALS','Credentials and password must be nonblank.',None)
    except OSError:
        return error(500,'OZON_VAULT_WRITE_FAILED','Could not save the encrypted credential vault.',None)

@router.post('/api/ozon/credentials/unlock')
async def ozon_credentials_unlock(request:Request):
    body=await json_object(request)
    if body is None or not isinstance(body.get('password'),str) or not body['password'].strip():
        return error(400,'MISSING_FIELD','Vault password is required.','password')
    try:
        with OZON_CONTEXT_COMMIT_LOCK:
            status=OZON_VAULT.unlock(body['password'])
        return vault_response(status)
    except OzonVaultError as exc:return error(401,exc.code.value,'Vault password or encrypted data is invalid.',None)

@router.post('/api/ozon/credentials/lock')
def ozon_credentials_lock():
    with OZON_CONTEXT_COMMIT_LOCK:
        status=OZON_VAULT.lock()
    return vault_response(status)

@router.post('/api/ozon/connection/test')
def ozon_connection_test():
    try:
        context=OZON_VAULT.capture_context()
        OZON_CLIENT.bind_context(context).post_json(CONNECTION_TEST_PATH,{},policy=OzonRequestPolicy(retry_safe=True))
        status=commit_active_credential_context(context,OZON_VAULT.record_connection_check)
    except OzonVaultError as exc:
        return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error()
        statuses={OzonErrorCode.AUTH_FAILED:401,OzonErrorCode.PERMISSION_DENIED:403,OzonErrorCode.RATE_LIMITED:429,
                  OzonErrorCode.UNAVAILABLE:503,OzonErrorCode.INVALID_REQUEST:400,
                  OzonErrorCode.INVALID_RESPONSE:502}
        return error(statuses.get(exc.code,502),exc.code.value,str(exc),None)
    except ShipmentPreparationError as exc:
        return error(exc.http_status,exc.code,exc.message,exc.field)
    return vault_response(status)

@router.post('/api/ozon/connection/diagnose')
def ozon_connection_diagnose():
    """Run the single fast preflight used by both manual checks and sync UX."""
    try:
        context=OZON_VAULT.capture_context()
        diagnostic=diagnose_connection(OZON_CLIENT.bind_context(context))
        if diagnostic.connection_valid:
            commit_active_credential_context(context,OZON_VAULT.record_connection_check)
        else:
            commit_active_credential_context(context,lambda:None)
        return wire(diagnostic)
    except OzonVaultError as exc:
        return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error()
        return error(503,exc.code.value,'Не удалось выполнить диагностику Ozon.',None)
    except ShipmentPreparationError as exc:
        return error(exc.http_status,exc.code,exc.message,exc.field)

@router.post('/api/ozon/connection/transport-compare')
def ozon_connection_transport_compare():
    """Compare transports directly; never run the raw DNS/TLS preflight."""
    try:
        context=OZON_VAULT.capture_context()
        comparison=asyncio.run(compare_transports(
            OZON_CLIENT.bind_context(context),context.credentials))
        return commit_active_credential_context(context,lambda:wire(comparison))
    except OzonVaultError as exc:
        return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error()
        return error(503,exc.code.value,'Не удалось сравнить HTTP-транспорты.',None)
    except ShipmentPreparationError as exc:
        return error(exc.http_status,exc.code,exc.message,exc.field)

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
        context=OZON_VAULT.capture_context()
        points=search_handoff_points(OZON_CLIENT.bind_context(context),query,ozon_supply_types)
        return commit_active_credential_context(
            context,lambda:(HANDOFF_STORE.put_all(points),
                            {'api_version':1,'items':wire(points)})[1])
    except OzonVaultError as exc:return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error()
        return error(503,exc.code.value,str(exc),None)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)

def _refresh_response(context, mode, progress_callback=None):
    base=OZON_SOURCE_STORE.latest()
    # Preserve the established injection seam used by transport/concurrency tests.
    if sync_ozon_source is not _ORIGINAL_SYNC_OZON_SOURCE:
        kwargs={'credential_context_id':context.context_id}
        if progress_callback is not None and 'progress_callback' in inspect.signature(sync_ozon_source).parameters:
            kwargs['progress_callback']=progress_callback
        candidate=sync_ozon_source(OZON_CLIENT.bind_context(context),**kwargs)
        report=OzonRefreshReport(mode,'full',getattr(base,'source_snapshot_id',None),
            tuple(x.name for x in candidate.endpoint_evidence),(),
            tuple(x.name for x in candidate.endpoint_evidence if not x.complete),None)
    else:
        candidate,report=refresh_ozon_source(
            OZON_CLIENT.bind_context(context),mode=mode,base_snapshot=base,
            credential_context_id=context.context_id,progress_callback=progress_callback)

    def commit():
        active=base
        activated=base is None or not source_refresh_regresses(base,candidate)
        if activated:
            save_source_snapshot_atomic(OZON_SOURCE_PATH,candidate)
            OZON_SOURCE_STORE.put(candidate)
            active=candidate
        authoritative_report=replace(report,activated=activated)
        result={'api_version':1,'source':source_status_view(active),
                'capabilities':capability_matrix(active),'refresh':wire(authoritative_report)}
        if not activated:
            result['attempt']=source_status_view(candidate)
        return result
    return commit_active_credential_context(context,commit)

@router.post('/api/ozon/sync')
def ozon_sync(mode:str='smart'):
    if mode not in {'smart','full'}:
        return error(400,'INVALID_REFRESH_MODE','Expected smart or full.','mode')
    try:
        context=OZON_VAULT.capture_context()
        return _refresh_response(context,mode)
    except OSError:return error(500,'OZON_SOURCE_WRITE_FAILED','Could not save Ozon source data.',None)
    except OzonVaultError as exc:return error(423,exc.code.value,'Unlock the Ozon credential vault first.',None)
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error()
        return error(503,exc.code.value,str(exc),None)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)

@router.post('/api/ozon/sync/stream')
def ozon_sync_stream(mode:str='smart'):
    """Stream sync observations while retaining the regular sync's commit path."""
    events=Queue()

    def worker():
        try:
            if mode not in {'smart','full'}:
                events.put({'type':'error','error':{'code':'INVALID_REFRESH_MODE','message':'Expected smart or full.'}});return
            context=OZON_VAULT.capture_context()
            data=_refresh_response(context,mode,events.put)
            events.put({'type':'result','data':data})
        except OzonVaultError as exc:
            events.put({'type':'error','error':{
                'code':exc.code.value,'message':'Unlock the Ozon credential vault first.'}})
        except OzonClientError as exc:
            code=('OZON_CREDENTIAL_CONTEXT_CHANGED'
                  if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED else exc.code.value)
            message=(CREDENTIAL_CONTEXT_MESSAGE
                     if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED else str(exc))
            events.put({'type':'error','error':{'code':code,'message':message}})
        except ShipmentPreparationError as exc:
            events.put({'type':'error','error':{'code':exc.code,'message':exc.message}})
        except Exception:
            logger.exception('Ozon source sync stream failed')
            events.put({'type':'error','error':{
                'code':'OZON_SYNC_FAILED','message':'Не удалось обновить данные Ozon.'}})
        finally:
            events.put(None)

    async def stream():
        thread=Thread(target=worker,name='ozon-sync');thread.start()
        try:
            while True:
                item=await asyncio.to_thread(events.get)
                if item is None:break
                yield json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n'
        finally:
            await asyncio.shield(asyncio.to_thread(thread.join))
    return StreamingResponse(stream(),media_type='application/x-ndjson')

@router.get('/api/ozon/source/latest')
def ozon_source_latest():
    snapshot=OZON_SOURCE_STORE.latest()
    if snapshot is None:
        return {'api_version':1,'source':None}
    return {'api_version':1,'source':source_status_view(snapshot),
            'capabilities':capability_matrix(snapshot)}

@router.get('/api/ozon/source/{source_snapshot_id}/status')
def ozon_source_status(source_snapshot_id:str):
    try:snapshot=current_source(source_snapshot_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    return {'api_version':1,'source_snapshot_id':source_snapshot_id,'source_as_of':snapshot.source_as_of.isoformat(),
            'source_timezone':snapshot.source_timezone,'capabilities':capability_matrix(snapshot),
            'endpoint_evidence':wire(snapshot.endpoint_evidence),'diagnostics':wire(snapshot.diagnostics)}

@router.post('/api/shipment/candidates')
async def shipment_candidates(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported_fields={'analysis_snapshot_id','shippable_plan_id','working_plan_id','scenario'}
    unsupported_fields=set(body)-supported_fields
    if unsupported_fields:
        field=sorted(unsupported_fields)[0]
        return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',field)
    analysis_id=body.get('analysis_snapshot_id')
    plan_id=body.get('shippable_plan_id')
    working_id=body.get('working_plan_id')
    if not isinstance(analysis_id,str) or not analysis_id.strip():
        return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():
        return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    if not isinstance(working_id,str) or not working_id.strip():
        return error(400,'WORKING_PLAN_ID_REQUIRED','Working Plan identity is required.','working_plan_id')
    try:snapshot,plan,working=require_current_working_plan(
        analysis_snapshot_id=analysis_id,shippable_plan_id=plan_id,
        working_plan_id=working_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try:shipment_input=build_shipment_input(plan,working)
    except WorkingPlanIdentityError:return error(409,'WORKING_PLAN_IDENTITY_MISMATCH',
        'Working Plan identities do not match the Shippable Plan.','working_plan_id')
    try:
        scenario=parse_shipment_scenario(body.get('scenario'))
    except ValueError:
        return error(400,'INVALID_SHIPMENT_SCENARIO','Shipment scenario is invalid.','scenario')
    seller_warehouses=()
    if plan.source_snapshot_id is not None:
        try:source=current_source(plan.source_snapshot_id,field='analysis_snapshot_id')
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
        if source.source_as_of != plan.analysis_as_of:
            return error(409,'SOURCE_PROVENANCE_MISMATCH','Analysis and source provenance do not match.','analysis_snapshot_id')
        seller_warehouses=source.seller_warehouses
    result=build_candidate_result(shipment_input=shipment_input,scenario=scenario,
        seller_warehouses=seller_warehouses,handoff_store=HANDOFF_STORE,
        max_candidates=DEFAULT_MAX_CANDIDATES)
    if any(item.code=='WORKING_PLAN_SCOPE_BLOCKED' for item in result.diagnostics):
        return error(409,'WORKING_PLAN_SCOPE_BLOCKED',
            'В выбранных кластерах есть позиции, которые требуют исправления перед поставкой.',
            'scenario.selected_cluster_ids')
    return {'api_version':1,'analysis_snapshot_id':analysis_id,
            'shippable_plan_id':plan_id,'working_plan_id':working_id,
            'candidates':wire(result.candidates),
            'diagnostics':wire(result.diagnostics)}

@router.post('/api/shipment/validate')
async def shipment_validate(request:Request):
    """Validate reconstructed backend candidates; client rows are never authoritative."""
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported={'analysis_snapshot_id','shippable_plan_id','working_plan_id','scenario','candidate_ids'}
    extra=set(body)-supported
    if extra:return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',sorted(extra)[0])
    analysis_id=body.get('analysis_snapshot_id'); plan_id=body.get('shippable_plan_id'); working_id=body.get('working_plan_id')
    candidate_ids=body.get('candidate_ids')
    if not isinstance(analysis_id,str) or not analysis_id.strip():
        return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():
        return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    if not isinstance(working_id,str) or not working_id.strip():
        return error(400,'WORKING_PLAN_ID_REQUIRED','Working Plan identity is required.','working_plan_id')
    if not isinstance(candidate_ids,list) or not candidate_ids or any(not isinstance(x,str) or not x.strip() for x in candidate_ids) or len(candidate_ids)!=len(set(candidate_ids)):
        return error(400,'INVALID_CANDIDATE_IDS','Candidate identities must be a nonempty unique list.','candidate_ids')
    try:_,_,working=require_current_working_plan(
        analysis_snapshot_id=analysis_id,shippable_plan_id=plan_id,
        working_plan_id=working_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    expected_context=OZON_VAULT.credential_context_id()
    try: prepared=prepare_shipment_validation(analysis_store=ANALYSIS_STORE,
        source_store=OZON_SOURCE_STORE,handoff_store=HANDOFF_STORE,
        analysis_id=analysis_id,plan_id=plan_id,working_plan=working,scenario_payload=body.get('scenario'),
        candidate_ids=candidate_ids,expected_credential_context_id=expected_context)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try:
        context=OZON_VAULT.capture_context()
        if context.context_id!=expected_context:return credential_context_error('analysis_snapshot_id')
    except OzonVaultError:return error(423,'OZON_VAULT_LOCKED','Unlock the Ozon credential vault first.',None)
    source_id=prepared.snapshot.source_snapshot_id
    try:options=await asyncio.to_thread(DRAFT_VALIDATION_SERVICE.validate,prepared.candidates,prepared.scenario,
                                    provenance=f'{context.context_id}:{analysis_id}:{plan_id}:{working_id}:{source_id}',
                                    source_clusters=prepared.source_snapshot.clusters,
                                    client=OZON_CLIENT.bind_context(context))
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error('analysis_snapshot_id')
        raise
    def commit_validation_result():
        require_current_working_plan(analysis_snapshot_id=analysis_id,
            shippable_plan_id=plan_id,working_plan_id=working_id)
        return {'api_version':1,'analysis_snapshot_id':analysis_id,
                'shippable_plan_id':plan_id,'working_plan_id':working_id,
                'options':wire(options)}
    try:return commit_active_credential_context(
        context,commit_validation_result,field='analysis_snapshot_id')
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)

@router.post('/api/shipment/plan')
async def shipment_plan(request:Request):
    body=await json_object(request)
    if body is None:return error(400,'INVALID_REQUEST','Expected a JSON object.',None)
    supported={'analysis_snapshot_id','shippable_plan_id','working_plan_id','scenario','candidate_ids'}
    extra=set(body)-supported
    if extra:return error(400,'UNSUPPORTED_FIELD','Request field is not supported.',sorted(extra)[0])
    analysis_id=body.get('analysis_snapshot_id');plan_id=body.get('shippable_plan_id');working_id=body.get('working_plan_id');ids=body.get('candidate_ids')
    if not isinstance(analysis_id,str) or not analysis_id.strip():return error(400,'ANALYSIS_SNAPSHOT_ID_REQUIRED','Analysis identity is required.','analysis_snapshot_id')
    if not isinstance(plan_id,str) or not plan_id.strip():return error(400,'SHIPPABLE_PLAN_ID_REQUIRED','Shippable Plan identity is required.','shippable_plan_id')
    if not isinstance(working_id,str) or not working_id.strip():return error(400,'WORKING_PLAN_ID_REQUIRED','Working Plan identity is required.','working_plan_id')
    if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x.strip() for x in ids) or len(ids)!=len(set(ids)):
        return error(400,'INVALID_CANDIDATE_IDS','Candidate identities must be a nonempty unique list.','candidate_ids')
    try:_,_,working=require_current_working_plan(
        analysis_snapshot_id=analysis_id,shippable_plan_id=plan_id,
        working_plan_id=working_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    expected_context=OZON_VAULT.credential_context_id()
    try: prepared=prepare_shipment_validation(analysis_store=ANALYSIS_STORE,
        source_store=OZON_SOURCE_STORE,handoff_store=HANDOFF_STORE,
        analysis_id=analysis_id,plan_id=plan_id,working_plan=working,scenario_payload=body.get('scenario'),
        candidate_ids=ids,expected_credential_context_id=expected_context)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try:
        expected_pack_fingerprint=capture_shipment_pack_fingerprint_if_current(
            expected_analysis_snapshot_id=analysis_id,
            expected_shippable_plan_id=plan_id,
            expected_working_plan_id=working_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
    try:
        context=OZON_VAULT.capture_context()
        if context.context_id!=expected_context:return credential_context_error('analysis_snapshot_id')
    except OzonVaultError:return error(423,'OZON_VAULT_LOCKED','Unlock the Ozon credential vault first.',None)
    source_id=prepared.snapshot.source_snapshot_id
    try:options=await asyncio.to_thread(DRAFT_VALIDATION_SERVICE.validate,prepared.candidates,prepared.scenario,provenance=f'{context.context_id}:{analysis_id}:{plan_id}:{working_id}:{source_id}',source_clusters=prepared.source_snapshot.clusters,client=OZON_CLIENT.bind_context(context))
    except OzonClientError as exc:
        if exc.code is OzonErrorCode.CREDENTIAL_CONTEXT_CHANGED:return credential_context_error('analysis_snapshot_id')
        raise
    if not OZON_VAULT.is_context_active(context):return credential_context_error('analysis_snapshot_id')
    try:shipment=build_shipment_plan(source_snapshot_id=source_id,analysis_snapshot_id=analysis_id,shippable_plan_id=plan_id,working_plan_id=working_id,analysis_as_of=prepared.snapshot.analysis_as_of,scenario=prepared.scenario,candidates=prepared.candidates,validations=options,diagnostics=tuple(x.code for x in prepared.diagnostics))
    except ShipmentOrchestrationError as exc:return error(502,exc.code,'Ozon validation returned inconsistent candidate evidence.',None)
    try:commit_shipment_plan_if_current(
        shipment,expected_analysis_snapshot_id=analysis_id,
        expected_shippable_plan_id=plan_id,
        expected_working_plan_id=working_id,
        expected_pack_fingerprint=expected_pack_fingerprint,
        credential_context=context)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
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
    with PROJECT_PERSISTENCE_LOCK:
        try:require_current_working_plan(
            analysis_snapshot_id=plan.analysis_snapshot_id,
            shippable_plan_id=plan.shippable_plan_id,
            working_plan_id=plan.working_plan_id)
        except ShipmentPreparationError:
            return error(409,'SHIPMENT_PLAN_STALE',
                'Рабочий план изменился. Проверьте варианты поставки повторно.',
                'shipment_plan_id')
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
    product_facts: tuple = ()


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
    demand_incomplete_skus = tuple(sorted({
        sku
        for evidence in snapshot.endpoint_evidence
        if evidence.name in {"orders_fbo", "orders_fbs"} and evidence.record_quality is not None
        for sku in evidence.record_quality.incomplete_skus
    }))
    inbound_incomplete_skus = tuple(sorted({
        sku
        for evidence in snapshot.endpoint_evidence
        if evidence.name == "inbound" and evidence.record_quality is not None
        for sku in evidence.record_quality.incomplete_skus
    }))
    fbo_stock_incomplete_skus = tuple(sorted({
        sku for evidence in snapshot.endpoint_evidence
        if evidence.name == "fbo_stock" and evidence.record_quality is not None
        for sku in evidence.record_quality.incomplete_skus
    }))
    seller_stock_incomplete_skus = tuple(sorted({
        sku for evidence in snapshot.endpoint_evidence
        if evidence.name == "seller_stock" and evidence.record_quality is not None
        for sku in evidence.record_quality.incomplete_skus
    }))
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
            orders_fbo_complete=completeness.get("orders_fbo", False),
            orders_fbs_complete=completeness.get("orders_fbs", False),
            fbo_stock_complete=completeness.get("fbo_stock", False),
            inbound_complete=completeness.get("inbound", False),
            demand_incomplete_skus=demand_incomplete_skus,
            inbound_incomplete_skus=inbound_incomplete_skus,
            fbo_stock_incomplete_skus=fbo_stock_incomplete_skus,
            seller_stock_complete=completeness.get("seller_stock", False),
            seller_stock_incomplete_skus=seller_stock_incomplete_skus,
        ),
        tuple(snapshot.product_facts),
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
    with PROJECT_PERSISTENCE_LOCK:
        project,_=_persist_unitka_baseline(load_project_if_exists(PROJECT_PATH),packs.records)
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
    snapshot=None; credential_context_id=None; order_coverage=None
    if source_mode is SourceMode.API:
        if any(form.get(field) is not None for field in common):
            return error(400,'MIXED_SOURCE_MODE','API source cannot be combined with Ozon report files.',None)
        source_snapshot_id=str(form.get('source_snapshot_id','')).strip()
        if not source_snapshot_id:return error(400,'MISSING_SOURCE_SNAPSHOT_ID','API source snapshot identity is required.','source_snapshot_id')
        snapshot=OZON_SOURCE_STORE.get(source_snapshot_id)
        if snapshot is None:return error(400,'OZON_SOURCE_SNAPSHOT_NOT_FOUND','Ozon source snapshot was not found.','source_snapshot_id')
        credential_context_id=OZON_VAULT.credential_context_id()
        try:require_source_credential_context(snapshot,credential_context_id,field='source_snapshot_id')
        except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)
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
        parsed_period = {}
        for field in ('orders_period_from', 'orders_period_to'):
            raw_period = str(form.get(field, '')).strip()
            if not raw_period:
                return error(400, 'ORDERS_PERIOD_REQUIRED',
                             'Orders report period is required.', field)
            try:
                parsed = date.fromisoformat(raw_period)
                if len(raw_period) != 10 or parsed.isoformat() != raw_period:
                    raise ValueError
            except ValueError:
                return error(400, 'INVALID_ORDERS_PERIOD',
                             'Expected YYYY-MM-DD.', field)
            parsed_period[field] = parsed
        try:
            order_coverage = ObservationCoverage(
                parsed_period['orders_period_from'], parsed_period['orders_period_to'])
        except ValueError:
            return error(400, 'INVALID_ORDERS_PERIOD',
                         'Report period start must not follow its end.',
                         'orders_period_to')
        if order_coverage.period_start > as_of:
            return error(400, 'ORDERS_PERIOD_AFTER_AS_OF',
                         'Orders report period begins after the analysis date.',
                         'orders_period_from')
        if not fully_covered_completed_iso_weeks(
            coverage=order_coverage, as_of=as_of
        ):
            return error(400, 'ORDERS_PERIOD_HAS_NO_COMPLETED_WEEKS',
                         'Orders report period contains no fully covered completed ISO week.',
                         'orders_period_from')
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
        order_coverage=ObservationCoverage(snapshot.history_from, snapshot.history_to)
        economic_files=(['unitka_file'] if unitka is not None else ['tariffs_file','product_economics_file'])
        for field in economic_files:
            try: raw.append((form[field],await read(form[field],field,request_id)))
            except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    else:
        for field in files:
            try: raw.append((form[field],await read(form[field],field,request_id)))
            except OverflowError:return error(413,'UPLOAD_TOO_LARGE','File exceeds 64 MiB.',field)
    provenance=(source_mode,snapshot.source_snapshot_id if snapshot else None,credential_context_id)
    return raw, unitka, files, values, tax, as_of, (explicit_horizon,raw_inbound=="true",objective), provenance, source_inputs, order_coverage

@router.post('/api/analysis')
async def analysis(request:Request):
    request_id=uuid4().hex[:8]
    prepared=await prepare_analysis(request,request_id)
    if isinstance(prepared,JSONResponse): return prepared
    try:return run_analysis_pipeline(*prepared,request_id=request_id)
    except ShipmentPreparationError as exc:return error(exc.http_status,exc.code,exc.message,exc.field)

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
        except ShipmentPreparationError as exc:
            events.put({"type":"error","request_id":request_id,"stage":last_stage["name"],
                        "error":{"code":exc.code,"message":exc.message,"field":exc.field}})
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


def run_analysis_pipeline(raw, unitka, files, values, tax, as_of, scenario_request=(None,True,AllocationObjective.MAX_MARGIN), provenance=(SourceMode.FILES,None,None), source_inputs=None, order_coverage=None, *, progress_callback=None, request_id="http"):
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
        orders=timed("orders_import",import_orders,raw[2][1],meta(raw[2][0], coverage=order_coverage))
        orders=scope_orders_to_coverage(orders, order_coverage)
        economics_offset=3
        operational_availability=availability.records
    else:
        availability=source_inputs.availability
        progress("reports",2,4,"restrictions")
        restrictions=source_inputs.restrictions
        progress("reports",3,4,"orders")
        orders=source_inputs.orders
        orders=scope_orders_to_coverage(orders, order_coverage)
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
        with PROJECT_PERSISTENCE_LOCK:
            project,_=_persist_unitka_baseline(load_project_if_exists(PROJECT_PATH),pack_evidence)
            pack_evidence=build_effective_pack_evidence(project,pack_evidence)
            pack_fingerprint_at_start=pack_multiplicity_fingerprint(project)
    else:
        tariffs=timed("tariffs_import",import_tariffs,raw[economics_offset][1],meta(raw[economics_offset][0])); products=timed("product_economics_import",import_product_economics,raw[economics_offset+1][1],meta(raw[economics_offset+1][0]))
        pack_evidence=()
        with PROJECT_PERSISTENCE_LOCK:
            project=load_project_if_exists(PROJECT_PATH)
            pack_evidence=build_effective_pack_evidence(project,pack_evidence)
            pack_fingerprint_at_start=pack_multiplicity_fingerprint(project)
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
    if source_inputs is not None:
        for item in source_inputs.product_facts:
            if item.article:current_article_skus.setdefault(item.article,set()).add(item.sku)
    primary={}; primary_conflicts=set()
    for item in analysis_availability:
        if not item.article: continue
        if item.article in primary and primary[item.article]!=item.sku: primary_conflicts.add(item.article)
        else: primary[item.article]=item.sku
    if source_inputs is not None:
        for item in source_inputs.product_facts:
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
    if source_inputs is not None:
        merged_products, merge_diagnostics = merge_api_product_economics(
            products.records, source_inputs.product_facts,
            tuple(row for row in source_inputs.operational_availability
                  if getattr(row, "fbs_quantity", None) is not None),
        )
        products = replace(products, records=merged_products,
                           diagnostics=products.diagnostics + merge_diagnostics)
    logger.info("[analysis %s] article_join done %.3fs rows=%d",request_id,perf_counter()-join_started,len(products.records))
    logger.info("[analysis %s] reports done %.3fs",request_id,perf_counter()-reports_started)
    imported=[availability,restrictions,orders,tariffs,products]
    settings=EconomicsSettings(*(values[n] for n in DECIMAL_NAMES[:4]),tax,*(values[n] for n in DECIMAL_NAMES[4:7])); thresholds=OptimizerThresholds(*(values[n] for n in DECIMAL_NAMES[7:]))
    explicit_horizon,include_inbound,objective=scenario_request
    scenario=ScenarioSettings(explicit_horizon or availability.meta.recommendation_horizon_days or 56,include_inbound,objective)
    order_coverage_valid = not any(
        diagnostic.code == "ORDER_OUTSIDE_DECLARED_PERIOD"
        and diagnostic.severity == "error"
        for diagnostic in orders.diagnostics
    )
    result=analyze(analysis_availability,analysis_restrictions,analysis_orders,analysis_tariffs,products.records,as_of=as_of,economics_settings=settings,optimizer_thresholds=thresholds,availability_fbs_authoritative=unitka is not None,operational_availability=operational_availability,ozon_horizon_days=availability.meta.recommendation_horizon_days,source_mode=provenance[0],source_coverage=(source_inputs.source_coverage if source_inputs is not None else None),order_coverage=order_coverage,order_coverage_valid=order_coverage_valid,progress_callback=progress_callback,scenario_settings=scenario)
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
    if not result.demand.window.coverage_current:
        warnings.append(
            f"История заказов подтверждена только по {order_coverage.period_end.isoformat()}. "
            "Более поздние недели не считаются нулевыми. "
            "Расчёт потребности заблокирован до актуального покрытия."
        )
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
        source_mode=provenance[0],source_snapshot_id=provenance[1],
        demand_window=result.demand.window)
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
    expected_context=provenance[2] if len(provenance)>2 else None
    commit_analysis_snapshot_if_current(
        snapshot,expected_pack_fingerprint=pack_fingerprint_at_start,
        expected_credential_context_id=expected_context,
        require_credential_context=snapshot.source_mode is SourceMode.API)
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
    try:
        with PROJECT_PERSISTENCE_LOCK:
            project=load_project_if_exists(PROJECT_PATH)
            project=replace(project,manual_cluster_mappings=mappings)
            save_project_atomic(PROJECT_PATH,project)
    except ProjectValidationError: return error(400,"INVALID_MAPPINGS","Mappings are invalid.","mappings")
    return {"api_version":1,"mappings":dict(sorted(mappings.items()))}


def _pack_items(project):
    catalog={}
    for product in project.product_economics:
        if not product.article: continue
        try: article=normalize_supplier_article(product.article)
        except ValueError: continue
        catalog.setdefault(article,set()).add(str(product.sku))
    articles=sorted(set(catalog)|set(project.pack_multiplicity))
    items=[]
    for article in articles:
        resolved=resolve_pack_multiplicity(project.pack_multiplicity.get(article))
        items.append({"article":article,"pack_multiple":resolved.pack_multiple,"source":resolved.source,
                      "unitka_pack_multiple":resolved.unitka_pack_multiple,
                      "rtp_price_pack_multiple":resolved.rtp_price_pack_multiple,
                      "override_pack_multiple":resolved.override_pack_multiple,
                      "updated_at":resolved.updated_at,"product_name":None,"skus":sorted(catalog.get(article,()))})
    return items


@router.get("/api/project/pack-multiplicity")
def get_pack_multiplicity():
    with PROJECT_PERSISTENCE_LOCK: project=load_project_if_exists(PROJECT_PATH)
    return {"api_version":1,"items":_pack_items(project)}


@router.put("/api/project/pack-multiplicity/{article}")
async def put_pack_multiplicity(article: str, request: Request):
    try: payload=await request.json()
    except Exception: return error(400,"INVALID_PACK_MULTIPLICITY","Expected a JSON object.","pack_multiple")
    if not isinstance(payload,dict) or set(payload)!={"pack_multiple"}:
        return error(400,"INVALID_PACK_MULTIPLICITY","Expected pack_multiple only.","pack_multiple")
    try:
        with PROJECT_PERSISTENCE_LOCK:
            project, normalized=set_override(load_project_if_exists(PROJECT_PATH),article,payload["pack_multiple"],"manual")
            save_project_atomic(PROJECT_PATH,project)
    except (ValueError,ProjectValidationError): return error(400,"INVALID_PACK_MULTIPLICITY","Кратность должна быть положительным целым числом.","pack_multiple")
    ANALYSIS_STORE.clear(); SHIPMENT_PLAN_STORE.clear()
    return {"api_version":1,"item":next(item for item in _pack_items(project) if item["article"]==normalized)}


@router.delete("/api/project/pack-multiplicity/{article}")
def delete_pack_multiplicity(article: str):
    try:
        with PROJECT_PERSISTENCE_LOCK:
            project, normalized=reset_override(load_project_if_exists(PROJECT_PATH),article)
            save_project_atomic(PROJECT_PATH,project)
    except (ValueError,ProjectValidationError): return error(400,"INVALID_ARTICLE","Некорректный артикул.","article")
    ANALYSIS_STORE.clear(); SHIPMENT_PLAN_STORE.clear()
    return {"api_version":1,"item":next(item for item in _pack_items(project) if item["article"]==normalized)}


@router.post("/api/project/pack-multiplicity/import")
async def import_pack_multiplicity(request: Request):
    form=await request.form(); upload=form.get("file")
    if upload is None:return error(400,"MISSING_FIELD","Required multipart field is missing.","file")
    try: parsed=parse_import_xlsx(await read(upload,"file"))
    except (ValueError,OverflowError) as exc:return error(400,"INVALID_PACK_MULTIPLICITY_FILE",str(exc),"file")
    with PROJECT_PERSISTENCE_LOCK:
        project=load_project_if_exists(PROJECT_PATH)
        old_fingerprint=pack_multiplicity_fingerprint(project)
        if parsed.source_format == "rtp_price":
            updated=apply_rtp_price_snapshot(project,parsed.values)
        else:
            updated=project
            for article,value in parsed.values.items():
                updated,_=set_override(updated,article,value,"import")
        new_fingerprint=pack_multiplicity_fingerprint(updated)
        changed=new_fingerprint!=old_fingerprint
        if changed: save_project_atomic(PROJECT_PATH,updated)
    if changed:
        ANALYSIS_STORE.clear(); SHIPMENT_PLAN_STORE.clear()
    return {"api_version":1,"source_format":parsed.source_format,
            "accepted":len(parsed.values),"rejected":len(parsed.diagnostics),
            "changed":changed,"diagnostics":wire(parsed.diagnostics)}


@router.get("/api/project/pack-multiplicity/export")
def export_pack_multiplicity():
    with PROJECT_PERSISTENCE_LOCK: items=_pack_items(load_project_if_exists(PROJECT_PATH))
    return Response(export_xlsx(items),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":"attachment; filename*=UTF-8''%D0%9A%D1%80%D0%B0%D1%82%D0%BD%D0%BE%D1%81%D1%82%D1%8C_%D1%83%D0%BF%D0%B0%D0%BA%D0%BE%D0%B2%D0%BA%D0%B8.xlsx"})
