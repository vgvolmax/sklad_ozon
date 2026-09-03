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


def test_initial_and_history_route_hydration_have_distinct_missing_parameter_semantics():
    preferred = "({...SkladOzon.createInitialState(),planView:{...SkladOzon.createInitialState().planView,search:'39439',quickFilter:'blocked',sort:{key:'profit',direction:'desc'},page:3,pageSize:100}})"
    initial = node(f"SkladOzon.applyInitialRoute({preferred},SkladOzon.parseRoute('#plan')).planView")
    assert (initial['search'], initial['quickFilter'], initial['sort'], initial['page'], initial['pageSize']) == ('39439', 'blocked', {'key':'profit','direction':'desc'}, 3, 100)
    history = node(f"SkladOzon.applyHistoryRoute({preferred},SkladOzon.parseRoute('#plan')).planView")
    assert (history['search'], history['quickFilter'], history['sort'], history['page'], history['pageSize']) == ('', 'all', None, 1, 50)
    forward = node(f"SkladOzon.applyHistoryRoute({preferred},SkladOzon.parseRoute('#plan?q=39439&filter=blocked&sort=profit:desc&page=3&size=100')).planView")
    assert (forward['search'], forward['quickFilter'], forward['sort'], forward['page'], forward['pageSize']) == ('39439', 'blocked', {'key':'profit','direction':'desc'}, 3, 100)


def test_section_route_serializes_the_current_plan_view_for_history_restoration():
    route = node("SkladOzon.serializeRoute({...SkladOzon.createInitialState(),section:'data',planView:{...SkladOzon.createInitialState().planView,search:'39439',quickFilter:'blocked',pageSize:100}})")
    assert route == '#data?q=39439&filter=blocked&size=100'


def test_mapping_draft_rows_are_independent_and_only_saved_changes_revision():
    result = node("(()=>{let s=SkladOzon.initializeMappings(SkladOzon.createInitialState(),{});s=SkladOzon.addMappingDraft(SkladOzon.addMappingDraft(s));const ids=s.mappingDraftRows.map(x=>x.id);s=SkladOzon.updateMappingDraft(s,ids[0],{source:' Alias ',target:' Canonical '});const revision=s.inputRevision;const completed=SkladOzon.commitMappings(s,{Alias:'Canonical'});return {count:s.mappingDraftRows.length,ids,dirty:s.mappingDirty,draft:s.mappingDraftRows[0],revision,committedRevision:completed.inputRevision,committedDirty:completed.mappingDirty,stale:completed.staleSnapshot};})()")
    assert result['count'] == 2
    assert len(set(result['ids'])) == 2
    assert result['dirty'] is True
    assert result['draft']['source'] == ' Alias '
    assert result['revision'] == 0
    assert result['committedRevision'] == 1
    assert result['committedDirty'] is False
    assert result['stale'] is False  # no snapshot exists yet


def test_mapping_validation_rejects_blank_and_duplicate_sources_without_mutating_draft():
    invalid = node("SkladOzon.validateMappingDraft([{id:'1',source:' A ',target:' X '},{id:'2',source:'A',target:'Y'}])")
    assert invalid['valid'] is False
    assert 'повторяется' in invalid['error']


def test_scenario_draft_input_revision_and_date_only_format():
    for draft in ('0','-1','1.5',''):
        assert node(f"SkladOzon.validateScenarioDraft({json.dumps(draft)}).valid") is False
    assert node("SkladOzon.validateScenarioDraft('67')") == {'valid':True,'value':67,'error':None}
    assert node("SkladOzon.isSnapshotStale({runInputRevision:4,currentInputRevision:5,currentScenario:{horizonDays:56,includeInbound:true,objective:'max_profit'},resultScenario:{horizon_days:56,include_inbound:true,optimization_objective:'max_profit'}})") is True
    assert node("SkladOzon.canApplyRunInputStatuses(4,5)") is False
    assert node("SkladOzon.canApplyRunInputStatuses(5,5)") is True
    assert node("SkladOzon.presentIsoDate('2026-09-01')") == '01.09.2026'
