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
