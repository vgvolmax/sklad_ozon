import json, subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def node(expression):
    script = f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))}); console.log(JSON.stringify({expression}))"
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def test_route_state_and_page_behaviors():
    assert node("SkladOzon.parseRoute('#plan')")['section'] == 'plan'
    assert node("SkladOzon.parseRoute('#data')")['section'] == 'data'
    parsed = node("SkladOzon.parseRoute('#plan?q=abc&filter=disagreement&page=3')")
    assert (parsed['search'], parsed['quickFilter'], parsed['page']) == ('abc', 'disagreement', 3)
    assert node("SkladOzon.serializeRoute({...SkladOzon.createInitialState(),section:'plan',planView:{...SkladOzon.createInitialState().planView,search:'abc',quickFilter:'disagreement',page:3}})") == '#plan?q=abc&filter=disagreement&page=3'
    assert node("SkladOzon.setPlanSearch({...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,page:7}},'x').planView.page") == 1
    assert node("SkladOzon.setQuickFilter({...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,page:7}},'blocked').planView.page") == 1
    assert node("SkladOzon.clearPlanFilters({...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,search:'x',page:4}}).planView")['search'] == ''
    assert node("SkladOzon.clampPage(9,51,25)") == 3


def test_scenario_dirty_keeps_snapshot_identity_and_route_preserves_flow_state():
    result = node("(()=>{const snap=SkladOzon.deepFreezeSnapshot({scenario:{horizon_days:56,include_inbound:true,optimization_objective:'max_profit'}});const s={...SkladOzon.createInitialState(),snapshot:snap};const n=SkladOzon.updateScenario(s,{horizonDays:28});return {stale:n.staleSnapshot,same:n.snapshot===snap,frozen:Object.isFrozen(snap.scenario)}})()")
    assert result == {'stale': True, 'same': True, 'frozen': True}
    assert node("(()=>{const s={...SkladOzon.createInitialState(),flowView:{mode:'sku',metric:'units',selectedKey:'1',selectedRoute:null}};return SkladOzon.applyRoute(s,SkladOzon.parseRoute('#data')).flowView})()")['selectedKey'] == '1'


def test_local_date_uses_calendar_parts():
    assert node("SkladOzon.localDate({getFullYear:()=>2026,getMonth:()=>0,getDate:()=>2})") == '2026-01-02'


def test_navigation_preserves_plan_state_and_url_only_overrides_present_values():
    expression="""(()=>{let s={...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,search:'39439',quickFilter:'blocked',pageSize:100,page:2}};s=SkladOzon.resolveNavigation(s,'#data');s=SkladOzon.resolveNavigation(s,'#plan');return s.planView})()"""
    view=node(expression)
    assert (view['search'],view['quickFilter'],view['pageSize'],view['page']) == ('39439','blocked',100,2)
    explicit=node("SkladOzon.resolveNavigation({...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,quickFilter:'blocked',pageSize:100}},'#plan?filter=disagreement').planView")
    assert explicit['quickFilter'] == 'disagreement'
    assert explicit['pageSize'] == 100


def test_scenario_draft_input_revision_and_date_only_format():
    for draft in ('0','-1','1.5',''):
        assert node(f"SkladOzon.validateScenarioDraft({json.dumps(draft)}).valid") is False
    assert node("SkladOzon.validateScenarioDraft('67')") == {'valid':True,'value':67,'error':None}
    assert node("SkladOzon.isSnapshotStale({runInputRevision:4,currentInputRevision:5,currentScenario:{horizonDays:56,includeInbound:true,objective:'max_profit'},resultScenario:{horizon_days:56,include_inbound:true,optimization_objective:'max_profit'}})") is True
    assert node("SkladOzon.presentIsoDate('2026-09-01')") == '01.09.2026'
