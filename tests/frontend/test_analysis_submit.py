import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
CORE_JS = ROOT / "frontend/assets/js/core.js"
APP_JS = ROOT / "frontend/assets/js/app.js"


def node(expression):
    script = f"require({json.dumps(str(CORE_JS))}); console.log(JSON.stringify({expression}))"
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def test_request_body_captures_all_controls_and_appends_only_supported_scenario():
    result = node("""(()=>{class FakeFormData{constructor(form){this.entries={...form.snapshot};}set(key,value){this.entries[key]=value;}get(key){return this.entries[key];}}const form={snapshot:{availability_file:'availability.xlsx',restrictions_file:'restrictions.xlsx',orders_file:'orders.csv',unitka_file:'unitka.xlsx',as_of:'2026-09-03',acquiring_rate:'0.01',advertising_rate:'0',buyout_rate:'1',tax_system:'usn_income'}};return SkladOzon.buildAnalysisRequestBody(form,{horizonDays:56,includeInbound:true},FakeFormData).entries;})()""")
    assert result == {
        "availability_file": "availability.xlsx",
        "restrictions_file": "restrictions.xlsx",
        "orders_file": "orders.csv",
        "unitka_file": "unitka.xlsx",
        "as_of": "2026-09-03",
        "acquiring_rate": "0.01",
        "advertising_rate": "0",
        "buyout_rate": "1",
        "tax_system": "usn_income",
        "horizon_days": "56",
        "include_inbound": "true",
        "source_mode": "files",
    }
    assert "optimization_objective" not in result


def test_submit_captures_body_then_enters_busy_state_renders_and_fetches():
    source = APP_JS.read_text()
    start = source.index("async function runAnalysis")
    end = source.index("function scenarioEquals", start)
    lifecycle = source[start:end]
    capture = lifecycle.index("S.buildAnalysisRequestBody(")
    busy = lifecycle.index("analysisActive=true")
    render = lifecycle.index("render();", busy)
    fetch = lifecycle.index("fetch('/api/analysis/stream", render)
    assert capture < busy < render < fetch
    assert lifecycle.startswith("async function runAnalysis(form=document.querySelector('#analysis-form')){if(analysisActive)return;")
    assert "finally{clearInterval(timer);if(id===runSequence){analysisActive=false;render();}}" in lifecycle


def test_runtime_scenario_guard_prevents_request_capture_and_busy_state():
    source = APP_JS.read_text()
    lifecycle = source[source.index("async function runAnalysis"):source.index("function scenarioEquals")]
    guard = lifecycle.index("S.validateScenarioDraft(state.scenario.horizonDays)")
    invalid_return = lifecycle.index("return;", guard)
    capture = lifecycle.index("S.buildAnalysisRequestBody(")
    busy = lifecycle.index("analysisActive=true")
    assert guard < invalid_return < capture < busy
    assert "analysisError:checked.error" in lifecycle


def test_analysis_file_form_has_stable_dom_owner_across_unrelated_renders():
    source = APP_JS.read_text()
    render_data = source[source.index("let renderedAnalysisMode"):source.index("function validate", source.index("let renderedAnalysisMode"))]
    assert "#analysis-region" in render_data
    assert "renderedAnalysisMode!==state.source.mode" in render_data
    assert "analysisRegion.innerHTML=analysisFormMarkup()" in render_data
    assert "root.innerHTML=`<div class=\"stack\">${connectionMarkup()}" not in render_data


def test_analysis_form_dynamic_state_updates_without_replacing_file_inputs():
    source = APP_JS.read_text()
    updater = source[
        source.index("function updateAnalysisFormState"):
        source.index("let renderedAnalysisMode")
    ]
    render_data = source[
        source.index("let renderedAnalysisMode"):
        source.index("function validate", source.index("let renderedAnalysisMode"))
    ]
    assert 'id="analysis-source-basis"' in source
    assert 'id="analysis-submit"' in source
    assert 'id="analysis-source-required"' in source
    assert "submit.disabled=analysisActive||missingSource" in updater
    assert "state.source.sourceAsOf" in updater
    assert "Сначала обновите данные Ozon." in updater
    assert "innerHTML" not in updater
    assert "updateAnalysisFormState(root)" in render_data
    assert render_data.index("analysisRegion.innerHTML=analysisFormMarkup()") < render_data.index(
        "updateAnalysisFormState(root)"
    )


def test_credential_payloads_use_named_elements_not_form_data():
    source = APP_JS.read_text()
    assert "new FormData" not in source
    for field in ("client_id", "api_key", "password", "password_confirmation"):
        assert f"form.elements.{field}.value" in source
