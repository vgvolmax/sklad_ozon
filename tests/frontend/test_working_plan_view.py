from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_working_plan_ui_uses_one_server_authoritative_state():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    core = (ROOT / 'frontend/assets/js/core.js').read_text()
    for text in ('/api/working-plan', 'Рекомендация', 'К поставке', 'data-working-step',
                 'data-working-input', 'data-working-reset', 'Сбросить все ручные изменения'):
        assert text in app
    assert 'workingLine(row)' in app
    assert "workingPlan:{plan:null,busy:false,error:null" in core
    assert 'workingPlan.plan?.lines' in app
    assert 'localStorage' not in app[app.index('async function loadWorkingPlan'):app.index('function sellerWarehouses')]


def test_working_plan_failure_and_legacy_shipment_guard_are_explicit():
    app = (ROOT / 'frontend/assets/js/app.js').read_text()
    core = (ROOT / 'frontend/assets/js/core.js').read_text()
    assert 'Рабочий план недоступен' in app
    assert 'Для создания поставки требуется рабочий план поставки' in core
    assert "workingPlan?.plan?.active_override_count>0" in core
    assert 'expectedRunId===state.workingPlan.runId' in app
    assert 'runId:state.shipmentView.runId+1,candidates:null,plan:null' in app
