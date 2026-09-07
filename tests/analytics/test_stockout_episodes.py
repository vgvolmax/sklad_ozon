from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from decimal import Decimal

import pytest

from backend.analytics.daily import (DailyDemandCell, DailyDemandResult,
    DailyFulfillmentCell, DailyFulfillmentResult, DailyOrderFacts)
from backend.analytics.stockout_episodes import (DailyStockoutThresholds,
    StockoutEpisodeScope, build_daily_locality_series, detect_stockout_episodes)
from backend.domain.signals import AvailabilityCorroboration, SignalConfidence
from backend.ingestion.availability import AvailabilityRecord


def facts(patterns, *, sku="SKU", destination="Москва"):
    demands=[]; fulfillment=[]
    for day, demand, origins in patterns:
        demands.append(DailyDemandCell(sku, day, destination, demand, 1))
        for origin, qty in origins.items():
            if qty:
                fulfillment.append(DailyFulfillmentCell(sku, day, origin, destination, qty, 1))
    return DailyOrderFacts(DailyDemandResult(tuple(demands),0,0),
                           DailyFulfillmentResult(tuple(fulfillment),0,0))


def series(local=(9,1), collapse=None, *, start=date(2026,1,1), demand=10):
    rows=[]
    for index in range(21):
        origins={"Москва":local[0], "Казань":local[1]}
        if collapse and index in collapse:
            origins={"Москва":2, "Казань":8}
        rows.append((start+timedelta(days=index), demand, origins))
    return rows


def test_daily_locality_materializes_calendar_gaps_and_unknown_routing():
    start=date(2026,1,1)
    locality=build_daily_locality_series(facts([
        (start,10,{"Москва":9,"Казань":1}),
        (start+timedelta(days=2),5,{}),
    ]), start+timedelta(days=2))
    assert len(locality)==3
    assert locality[0].local_share == Decimal("0.9")
    assert locality[0].external_share == Decimal("0.1")
    assert locality[1].destination_demand_qty == locality[1].fulfilled_qty == 0
    assert locality[2].local_share is None and locality[2].origin_shares == ()
    with pytest.raises(FrozenInstanceError):
        locality[0].sku="x"


@pytest.mark.parametrize("field,value", [
    ("rolling_window_days", True), ("min_contaminated_days",0),
    ("prior_local_share_min", Decimal("NaN")),
    ("local_share_drop_min", Decimal("1.1")),
    ("demand_retention_min", .6),
])
def test_daily_thresholds_validate(field,value):
    with pytest.raises(ValueError):
        DailyStockoutThresholds(**{field:value})


def detect(rows, as_of=date(2026,1,26), availability=()):
    return detect_stockout_episodes(build_daily_locality_series(facts(rows),as_of), availability, as_of)


def test_stable_local_and_one_day_spike_are_suppressed():
    assert detect(series()) == ()
    assert detect(series(collapse={10})) == ()


def test_sustained_collapse_creates_one_merged_historical_episode():
    episodes=detect(series(collapse=set(range(7,14))))
    assert len(episodes)==1
    episode=episodes[0]
    assert (episode.sku,episode.destination_cluster_id)==("SKU","Москва")
    assert episode.affected_dates == tuple(date(2026,1,8)+timedelta(days=i) for i in range(7))
    assert (episode.start_date,episode.end_date)==(date(2026,1,8),date(2026,1,14))
    assert episode.baseline_local_share == Decimal("0.9")
    assert episode.representative_local_share == Decimal("0.2")
    assert episode.destination_demand_retention == Decimal(1)
    assert episode.replacement_origins[0].origin_cluster_id == "Казань"
    assert episode.replacement_origins[0].fulfilled_quantity_during_episode == 56
    assert episode.historical_evidence_strength is SignalConfidence.HIGH
    assert episode.route_cleaning_eligible
    assert episode.evidence_scope is StockoutEpisodeScope.HISTORICAL_COMPLETE


def test_demand_collapse_does_not_create_episode_even_with_availability():
    rows=series(collapse=set(range(7,14)))
    rows=[(day, 1 if 7<=i<14 else demand, origins) for i,(day,demand,origins) in enumerate(rows)]
    availability=(AvailabilityRecord("SKU","WH","Москва",1, fbo_quantity=0, days_without_stock=2),)
    assert detect(rows,availability=availability)==()


def test_donor_switch_merges_and_is_input_order_deterministic():
    rows=series()
    for i in range(7,14):
        day,demand,_=rows[i]
        rows[i]=(day,demand,{"Москва":2,"Казань":8} if i<11 else {"Москва":2,"Тверь":8})
    locality=build_daily_locality_series(facts(rows),date(2026,1,26))
    left=detect_stockout_episodes(locality,(),date(2026,1,26))
    right=detect_stockout_episodes(reversed(locality),(),date(2026,1,26))
    assert left==right and len(left)==1
    assert {x.origin_cluster_id for x in left[0].replacement_origins}=={"Казань","Тверь"}
    assert len(left[0].reason_codes)==len(set(left[0].reason_codes))


def test_sku_mix_change_does_not_create_identity_level_false_positive():
    start=date(2026,1,1); combined=[]
    for sku,local in (("A",(9,1)),("B",(1,9))):
        amount_before,amount_after=((10,100) if sku=="A" else (100,10))
        rows=[]
        for i in range(21):
            scale=amount_before if i<7 else amount_after
            rows.append((start+timedelta(days=i),scale,{"Москва":local[0]*scale,"Казань":local[1]*scale}))
        combined.extend(build_daily_locality_series(facts(rows,sku=sku),date(2026,1,21)))
    assert detect_stockout_episodes(combined,(),date(2026,1,21))==()


def test_current_availability_only_corroborates_operational_episode():
    as_of=date(2026,1,14)
    locality=build_daily_locality_series(facts(series(collapse=set(range(7,14)))[:14]),as_of)
    supporting=(AvailabilityRecord("SKU","WH","Москва",0,fbo_quantity=0,days_without_stock=2),)
    episode=detect_stockout_episodes(locality,supporting,as_of)[0]
    assert episode.evidence_scope is StockoutEpisodeScope.OPERATIONAL_CURRENT_WEEK
    assert episode.availability_corroboration is AvailabilityCorroboration.SUPPORTS
    assert episode.confidence is SignalConfidence.HIGH
    assert not episode.route_cleaning_eligible


def test_current_availability_cannot_cancel_historical_episode():
    contradiction=(AvailabilityRecord("SKU","WH","Москва",5,fbo_quantity=5,days_without_stock=0),)
    episode=detect(series(collapse=set(range(7,14))),availability=contradiction)[0]
    assert episode.availability_corroboration is AvailabilityCorroboration.CONTRADICTS
    assert episode.historical_evidence_strength is SignalConfidence.HIGH
    assert episode.confidence is SignalConfidence.HIGH and episode.route_cleaning_eligible
