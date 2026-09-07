import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    prefix=f"require({json.dumps(str(ROOT/'frontend/assets/js/core.js'))})"
    return json.loads(subprocess.check_output(['node','-e',f"{prefix};console.log(JSON.stringify({expr}))"],text=True))

def test_entity_and_raw_pages_are_bounded_to_one_hundred_and_search_all_rows():
    assert node("SkladOzon.paginateQualityRows(Array.from({length:384},(_,i)=>({label:'SKU '+i})),1,100)")['rows'].__len__()==100
    assert node("SkladOzon.paginateQualityRows(Array.from({length:384},(_,i)=>i),2,500).rows.length")==100
    assert node("SkladOzon.filterQualityRows(Array.from({length:384},(_,i)=>({label:'SKU '+i})),'SKU 383').length")==1

def test_quality_ui_uses_backend_copy_and_collapsed_accessible_details():
    app=(ROOT/'frontend/assets/js/app.js').read_text(); components=(ROOT/'frontend/assets/js/components.js').read_text()
    assert 'snap.data_quality' in app and 'snap.diagnostics' in app
    assert '<summary>Техническая диагностика' in components
    assert 'data-quality-search' in components and 'type="search"' in components
    assert 'user_title' in components and 'user_explanation' in components and 'action_hint' in components
    assert "querySelector('#diagnostics')" not in app
    assert 'Math.min(100' in (ROOT/'frontend/assets/js/core.js').read_text()
