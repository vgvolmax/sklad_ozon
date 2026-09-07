import json, subprocess
from pathlib import Path
ROOT=Path(__file__).parents[2]
def node(expr):
    files=('core.js','components.js','flow_timeline.js','flow.js')
    prefix=';'.join(f"require({json.dumps(str(ROOT/'frontend/assets/js'/f))})" for f in files)
    return json.loads(subprocess.check_output(['node','-e',f'{prefix};console.log(JSON.stringify({expr}))'],text=True))

def test_bounds_timeline_gaps_and_signed_copy():
    assert node("SkladOzon.FlowView.paginate(Array.from({length:250}),1,100).rows.length")==100
    assert node("[SkladOzon.FlowView.paginate(Array.from({length:180}),1,100).rows.length,SkladOzon.FlowView.paginate(Array.from({length:180}),2,100).rows.length]")==[100,80]
    assert node("SkladOzon.FlowTimeline.HEIGHT")==260
    assert node("SkladOzon.FlowTimeline.paginate(Array.from({length:90}),1,50).rows.length")==50
    assert node("SkladOzon.FlowTimeline.segments([{local_share:'1'},{local_share:null},{local_share:'0'}]).length")==2
    assert 'Локальное размещение хуже' in node("SkladOzon.FlowTimeline.impact({complete:true,profit_loss_or_opportunity_rub:'-10',extra_logistics_rub:'-2',margin_delta_pp:'-1'})")
    assert node("SkladOzon.FlowTimeline.impact({complete:false})")=='Экономика: Не рассчитано'

def test_production_has_no_route_count_canvas_height_or_pii():
    source=(ROOT/'frontend/assets/js/flow.js').read_text()+(ROOT/'frontend/assets/js/flow_timeline.js').read_text()
    assert 'links.length*90' not in source and 'length * 90' not in source
    assert 'raw_orders' not in source and 'buyer' not in source.lower()
    assert 'stockout_impact?.destination_daily_series' in source
