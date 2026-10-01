import json
from pathlib import Path
import subprocess

MODULE = Path(__file__).parents[2] / 'frontend/assets/js/economics_daily.js'


def geometry(days, expanded=False):
    script = f"globalThis.SkladOzon={{escapeHtml:String}};require({json.dumps(str(MODULE))});console.log(JSON.stringify(SkladOzon.EconomicsDaily.geometry({json.dumps(days)}, {str(expanded).lower()})));"
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def test_spp_uses_observed_range_and_shared_calendar_for_bars():
    chart = geometry([{'day':'2026-09-01','spp':'.6','orders':10},
                      {'day':'2026-09-02','spp':'.65','orders':20}], True)
    assert chart['minimum'] == .6 and chart['maximum'] == .65
    assert chart['points'][0]['y'] == chart['lineBottom']
    assert chart['points'][1]['y'] == chart['lineTop']
    assert [p['x'] for p in chart['points']] == [bar['x'] for bar in chart['bars']]


def test_constant_spp_has_finite_centerline_and_unknown_days_break_path():
    chart = geometry([{'spp':'.6','orders':10},{'spp':None,'orders':0},{'spp':'.6','orders':4}])
    assert chart['minimum'] == chart['maximum'] == .6
    assert chart['points'][0]['y'] == (chart['lineBottom'] + chart['lineTop']) / 2
    assert len(chart['segments']) == 2
    assert all('NaN' not in path and 'Infinity' not in path for path in chart['segments'])


def test_single_day_zero_and_unknown_order_values_are_distinct():
    chart = geometry([{'spp':0,'orders':0}])
    assert chart['points'][0]['x'] == 524
    assert chart['bars'][0]['height'] == 0
    unknown = geometry([{'spp':None,'orders':None}])
    assert unknown['segments'] == [] and unknown['bars'] == []


def test_buyer_price_uses_independent_observed_range_on_same_dates():
    chart = geometry([{'spp':'.6','orders':2,'buyer_price_mean':'200'},
        {'spp':'.5','orders':1,'buyer_price_mean':'1500'}],True)
    assert chart['buyerMinimum']==200 and chart['buyerMaximum']==1500
    assert chart['buyerPoints'][0]['y']==chart['buyerBottom']
    assert chart['buyerPoints'][1]['y']==chart['buyerTop']
    assert [p['x'] for p in chart['buyerPoints']]==[p['x'] for p in chart['points']]


def test_constant_buyer_price_zero_and_missing_days_do_not_make_false_lines():
    chart=geometry([{'spp':None,'orders':1,'buyer_price_mean':0},
        {'spp':None,'orders':0,'buyer_price_mean':None},
        {'spp':None,'orders':1,'buyer_price_mean':0}])
    assert chart['buyerMinimum']==chart['buyerMaximum']==0
    assert chart['buyerPoints'][0]['y']==(chart['buyerTop']+chart['buyerBottom'])/2
    assert len(chart['buyerSegments'])==2 and chart['segments']==[]
