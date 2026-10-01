from backend.ozon.adapters.orders import normalize_fbo_posting, normalize_fbs_posting
from tests.ozon.adapters.test_orders import fbo, fbs
from decimal import Decimal
import pytest


@pytest.mark.parametrize('normalizer,factory',[(normalize_fbo_posting,fbo),(normalize_fbs_posting,fbs)])
def test_buyer_price_money_is_kept_without_pii(normalizer,factory):
    posting=factory()
    posting['products'][0]['customer_price']={'amount':'40','currency':'RUB'}
    rows,diagnostics,quality=normalizer(posting)
    assert rows[0].buyer_price == 40
    assert diagnostics == () and quality.rejected_record_count == 0


def test_financial_buyer_price_matches_sku_not_row_position():
    posting=fbo()
    posting['financial_data']['products']=[{'product_id':999,'customer_price':99},
        {'product_id':123,'customer_price':40,'customer_currency_code':'RUB'}]
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price == 40


@pytest.mark.parametrize('blank',[None,'',{'amount':'','currency':'RUB'}])
def test_blank_product_customer_price_uses_matching_financial_evidence(blank):
    posting=fbo()
    posting['products'][0]['customer_price']=blank
    posting['financial_data']['products']=[{'product_id':999,'customer_price':99},
        {'product_id':123,'customer_price':{'amount':'40','currency':'RUB'}}]
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price == 40


def test_financial_explicit_seller_base_is_matched_by_sku():
    posting=fbo()
    posting['products'][0]['price']={'amount':'60','currency':'RUB'}
    posting['financial_data']['products']=[{'product_id':999,'seller_price':200},
        {'product_id':123,'seller_price':{'amount':'100','currency':'RUB'},
         'customer_price':{'amount':'40','currency':'RUB'}}]
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].seller_price == 60
    assert rows[0].spp_base_price == 100 and rows[0].buyer_price == 40


def test_explicit_foreign_customer_price_is_not_replaced_with_other_evidence():
    posting=fbo()
    posting['products'][0]['customer_price']={'amount':'10','currency':'USD'}
    posting['financial_data']['products']=[{'product_id':123,'customer_price':40}]
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price is None


def test_wrong_currency_and_missing_buyer_prices_are_unknown():
    posting=fbo()
    posting['products'][0]['customer_price']={'amount':'10','currency':'USD'}
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price is None


def test_legacy_client_price_and_ambiguous_financial_rows():
    posting=fbo()
    posting['financial_data']['products']=[{'product_id':123,'client_price':'40.25'}]
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price==40.25
    posting['financial_data']['products'].append({'product_id':123,'client_price':'20'})
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].buyer_price is None


@pytest.mark.parametrize('value',[None,[],True,'NaN',-10])
def test_invalid_customer_price_keeps_order_and_existing_quality(value):
    posting=fbo();posting['products'][0]['customer_price']=value
    rows,diagnostics,quality=normalize_fbo_posting(posting)
    assert len(rows)==1 and rows[0].buyer_price is None
    assert diagnostics==() and quality.rejected_record_count==0


def test_modern_spp_seller_base_does_not_change_existing_route_or_revenue_price():
    from datetime import date
    from backend.analytics._weeks import ObservationCoverage
    from backend.economics.daily_series import build_daily_evidence,daily_series
    posting=fbo()
    posting['products'][0]['price']={'amount':'60','currency':'RUB'}
    posting['products'][0]['seller_price']={'amount':'100','currency':'RUB'}
    posting['products'][0]['customer_price']={'amount':'40','currency':'RUB'}
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].seller_price==60 and rows[0].spp_base_price==100
    day=rows[0].accepted_at[:10]
    series=daily_series(build_daily_evidence(rows,ObservationCoverage(date.fromisoformat(day),date.fromisoformat(day))),'123')
    assert series['days'][0]['spp']==Decimal('.6')


def test_malformed_explicit_spp_base_does_not_fall_back():
    posting=fbo();posting['products'][0]['seller_price']={'amount':'100','currency':'USD'}
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].spp_base_price==0


def test_legacy_base_currency_cannot_be_mixed_with_buyer_rubles():
    posting=fbo()
    posting['products'][0]['price']={'amount':'100','currency':'USD'}
    posting['products'][0]['customer_price']={'amount':'40','currency':'RUB'}
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].spp_base_price==0 and rows[0].buyer_price==40


def test_legacy_scalar_base_checks_sibling_currency_code():
    posting=fbo()
    posting['products'][0].update(price='100',currency_code='USD',customer_price={'amount':'40','currency':'RUB'})
    rows,_,_=normalize_fbo_posting(posting)
    assert rows[0].spp_base_price==0 and rows[0].buyer_price==40
