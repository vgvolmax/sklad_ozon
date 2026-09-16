import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
CORE_JS = ROOT / "frontend/assets/js/core.js"
APP_JS = ROOT / "frontend/assets/js/app.js"


def node(expression):
    script = f"require({json.dumps(str(CORE_JS))}); console.log(JSON.stringify({expression}))"
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def view(capability, endpoints, key):
    return node(
        f"SkladOzon.buildSourceStatusRows({json.dumps({'capabilities': capability, 'endpointStates': endpoints})})"
        f".find(row=>row.key==={json.dumps(key)})"
    )


def test_permission_denied_exposes_safe_causal_evidence():
    row = view(
        {"operational_allocation": {"complete": False}},
        [{"name": "seller_stock", "complete": False, "record_count": 0,
          "diagnostics": [{"severity": "error", "code": "OZON_SELLER_STOCK_FAILED", "message": "failed"}],
          "api_error": {"code": "OZON_PERMISSION_DENIED", "endpoint": "/v2/product/info/stocks-by-warehouse/fbs",
                        "http_status": 403, "vendor_code": "PERMISSION_DENIED", "vendor_message": "Access denied",
                        "request_id": "trace-123"}}],
        "operational_allocation",
    )
    assert row["status"] == "incomplete" and row["statusText"] == "Неполные данные"
    assert "Недостаточно прав API" in row["cause"]
    technical = row["endpoints"][0]["technical"]
    assert technical["endpoint"] == "/v2/product/info/stocks-by-warehouse/fbs"
    assert technical["httpStatus"] == 403 and technical["requestId"] == "trace-123"


def test_rejected_request_and_unavailable_have_distinct_causes():
    rejected = view(
        {"operational_allocation": {"complete": False}},
        [{"name": "seller_stock", "complete": False, "api_error": {
            "code": "OZON_INVALID_REQUEST", "http_status": 400,
            "vendor_message": "sku or offer_id is required"}}],
        "operational_allocation",
    )
    assert "Ozon отклонил запрос (HTTP 400)." in rejected["cause"]
    assert rejected["endpoints"][0]["technical"]["vendorMessage"] == "sku or offer_id is required"
    unavailable = view(
        {"operational_allocation": {"complete": False}},
        [{"name": "seller_stock", "complete": False,
          "api_error": {"code": "OZON_UNAVAILABLE", "http_status": 503}}],
        "operational_allocation",
    )
    assert unavailable["cause"] == "Ozon API временно недоступен."
    assert "прав" not in unavailable["cause"].lower()


def test_scoped_quality_is_partial_and_keeps_endpoint_counts():
    orders = view(
        {"demand_flow": {"complete": True}},
        [{"name": "orders_fbo", "complete": True, "record_count": 120,
          "record_quality": {"rejected_record_count": 2, "incomplete_skus": ["SKU-B"]}}],
        "demand_flow",
    )
    assert orders["status"] == "partial" and orders["statusText"] == "Частично"
    endpoint = orders["endpoints"][0]
    assert endpoint["accepted"] == 120 and endpoint["rejected"] == 2
    assert endpoint["affectedSkuCount"] == 1
    inbound = view(
        {"need_inbound": {"complete": True}},
        [{"name": "inbound", "complete": True, "record_count": 8,
          "diagnostics": [{"severity": "warning", "code": "REPORT_REJECTED_SUPPLY_STATE", "message": "rejected"}],
          "record_quality": {"rejected_record_count": 3, "incomplete_skus": ["B", "A"]}}],
        "need_inbound",
    )
    assert inbound["status"] == "partial" and inbound["endpoints"][0]["label"] == "Поставки в пути"
    assert inbound["endpoints"][0]["affectedSkus"] == ["A", "B"]


def test_clean_source_is_available_and_warning_is_not_clean():
    clean = view(
        {"need_fbo": {"complete": True}},
        [{"name": "products", "complete": True, "record_count": 10},
         {"name": "fbo_stock", "complete": True, "record_count": 10,
          "record_quality": {"rejected_record_count": 0, "incomplete_skus": []}}],
        "need_fbo",
    )
    assert clean["status"] == "available" and clean["statusText"] == "Доступно"
    warning = view(
        {"need_inbound": {"complete": True}},
        [{"name": "inbound", "complete": True,
          "diagnostics": [{"severity": "warning", "code": "OTHER", "message": "Проверьте источник"}]}],
        "need_inbound",
    )
    assert warning["status"] == "warning" and warning["statusText"] == "Доступно с предупреждениями"


def test_api_error_model_has_a_strict_allow_list():
    hostile = {"name": "seller_stock", "complete": False, "api_error": {
        "code": "OZON_INVALID_RESPONSE", "endpoint": "/v1/test", "http_status": 400,
        "vendor_message": "safe", "request_id": "req", "raw_body": "SECRET_RAW_BODY",
        "details": {"password": "SECRET_PASSWORD"}, "headers": {"Authorization": "SECRET_HEADER"},
        "api_key": "SECRET_API_KEY"}}
    row = view({"operational_allocation": {"complete": False}}, [hostile], "operational_allocation")
    serialized = json.dumps(row)
    for forbidden in ("SECRET_RAW_BODY", "SECRET_PASSWORD", "SECRET_HEADER", "SECRET_API_KEY",
                      "raw_body", "details", "headers", "api_key"):
        assert forbidden not in serialized


def test_dependency_endpoint_error_is_primary_and_all_dependencies_remain_visible():
    row = view(
        {"need_fbo": {"complete": False}},
        [{"name": "products", "complete": False, "api_error": {
            "code": "OZON_PERMISSION_DENIED", "endpoint": "/v3/product/info/list", "http_status": 403}},
         {"name": "fbo_stock", "complete": False, "diagnostics": [{
             "severity": "error", "code": "FBO_STOCK_UNAVAILABLE", "message": "SKU universe unavailable"}]}],
        "need_fbo",
    )
    assert [endpoint["name"] for endpoint in row["endpoints"]] == ["products", "fbo_stock"]
    assert "Недостаточно прав API" in row["cause"]


def test_diagnostics_are_grouped_and_affected_skus_are_bounded():
    diagnostics = [{"severity": "warning", "code": "UNRESOLVED_DESTINATION_CLUSTER", "message": "one"}] * 14
    skus = [f"SKU-{i:03}" for i in range(25, -1, -1)]
    row = view({"demand_flow": {"complete": True}}, [{"name": "orders_fbo", "complete": True,
        "diagnostics": diagnostics, "record_quality": {"rejected_record_count": 14, "incomplete_skus": skus}}], "demand_flow")
    endpoint = row["endpoints"][0]
    assert endpoint["diagnostics"][0]["count"] == 14
    assert len(endpoint["affectedSkus"]) == 20 and endpoint["moreAffectedSkuCount"] == 6


def test_degraded_refresh_preserves_active_source_and_can_use_same_view_model():
    result = node("""(()=>{let s=SkladOzon.createInitialState();s={...s,source:{...s.source,snapshotId:'old',syncedAt:'2026-09-14T12:50:00Z',source:{source_snapshot_id:'old',endpoint_evidence:[{name:'seller_stock',complete:true}]},capabilities:{operational_allocation:{complete:true}},endpointStates:[{name:'seller_stock',complete:true}]}};s=SkladOzon.beginSourceRun(s);s=SkladOzon.applySourceSuccess(s,s.source.runId,{source:{source_snapshot_id:'new',synced_at_utc:'2026-09-14T13:20:00Z',endpoint_evidence:[{name:'seller_stock',complete:false,api_error:{code:'OZON_PERMISSION_DENIED',http_status:403}}]},capabilities:{operational_allocation:{complete:false}}});return {active:s.source.snapshotId,degraded:s.source.lastDegradedRefresh,view:SkladOzon.buildSourceStatusRows(s.source.lastDegradedRefresh).find(x=>x.key==='operational_allocation')};})()""")
    assert result["active"] == "old"
    assert result["degraded"]["endpointStates"][0]["name"] == "seller_stock"
    assert result["view"]["status"] == "incomplete"
    assert "Недостаточно прав API" in result["view"]["cause"]


def test_data_screen_has_one_stable_owner_and_mapping_editor():
    source = APP_JS.read_text()
    assert len(re.findall(r"\bfunction\s+renderData\s*\(", source)) == 1
    assert "dataInitialized" not in source and "function dataMarkup" not in source
    for marker in ("mapping-region", "mappingMarkup", "mapping-rows", "mapping-notice", "add-mapping", "save-mappings"):
        assert marker in source
    render_data = source[source.index("let renderedAnalysisMode"):source.index("function validate", source.index("let renderedAnalysisMode"))]
    assert "renderMappings()" in render_data
    assert "if(!mappingRegion.firstElementChild)" in render_data
    assert "S.commitMappings" in source[source.index("async function saveMappings"):]
