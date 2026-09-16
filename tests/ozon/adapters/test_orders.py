from datetime import date
import pytest
from backend.ozon.adapters.orders import fetch_postings, normalize_fbo_posting, normalize_fbs_posting
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH


def fbo(number="1", destination="Москва", status="delivered"):
    financial = {"cluster_from": "Казань"}
    if destination is not None: financial["cluster_to"] = destination
    return {"posting_number": number, "status": status, "in_process_at": "2026-08-01T10:00:00Z",
            "financial_data": financial,
            "analytics_data": {"warehouse_name": "W-1", "region": "WRONG", "city": "WRONG"},
            "products": [{"sku": 123, "offer_id": "ART", "name": "Product", "quantity": 2, "price": "100"}],
            "legal_info": {"company_name": "PII"}, "customer": {"phone": "PII"}}


def fbs(number="2", destination="Сибирь"):
    financial = {"cluster_from": "Урал", "cluster_to": destination} if destination is not None else {"cluster_from": "Урал"}
    return {"posting_number": number, "status_alias": "delivered",
            "in_process_at": "2026-08-01T10:00:00Z", "financial_data": financial,
            "analytics_data": {"region": "WRONG", "city": "WRONG"},
            "products": [{"product_id": 456, "product_offer_id": "FBS-ART", "product_name": "FBS product", "quantity": 1, "price": "55"}]}


class Client:
    def __init__(self, responses): self.responses=iter(responses); self.calls=[]
    def post_json(self,path,payload,**kwargs): self.calls.append((path,payload)); return next(self.responses)


@pytest.mark.parametrize(("path", "factory"), [(FBO_POSTINGS_PATH, fbo), (FBS_POSTINGS_PATH, fbs)])
def test_real_cursor_contract_and_financial_data_request(path, factory):
    client=Client([{"result":{"postings":[factory("1")],"has_next":True,"cursor":"next"}},
                   {"result":{"postings":[factory("2")],"has_next":False,"cursor":"done"}}])
    records, diagnostics, quality=fetch_postings(client,path,date(2026,7,1),date(2026,8,1))
    assert len(records)==2 and not diagnostics
    assert client.calls[0][1]["with"]=={"analytics_data":True,"financial_data":True}
    assert "legal_info" not in client.calls[0][1]["with"]
    assert client.calls[1][1]["cursor"]=="next"


def test_endpoint_specific_wire_fields_and_pii_are_discarded():
    fbo_rows,_,_=normalize_fbo_posting(fbo()); fbs_rows,_,_=normalize_fbs_posting(fbs())
    assert (fbo_rows[0].origin_cluster,fbo_rows[0].destination_cluster)==("Казань","Москва")
    assert (fbs_rows[0].origin_cluster,fbs_rows[0].destination_cluster)==("Урал","Сибирь")
    assert (fbs_rows[0].sku,fbs_rows[0].article,fbs_rows[0].product_name)==("456","FBS-ART","FBS product")
    assert fbs_rows[0].raw_status=="delivered" and "PII" not in repr(fbo_rows)


@pytest.mark.parametrize(("normalizer", "value"), [(normalize_fbo_posting, fbo(destination=None)), (normalize_fbs_posting, fbs(destination=None))])
def test_region_and_city_never_substitute_destination(normalizer,value):
    rows, diagnostics, quality=normalizer(value)
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert {d.code for d in diagnostics}=={"UNRESOLVED_DESTINATION_CLUSTER"}


def test_unknown_lifecycle_quarantines_affected_sku():
    rows, diagnostics, quality = normalize_fbo_posting(fbo(status="future"))
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == ("123",)
    assert any(item.code == "UNKNOWN_ORDER_STATUS" and item.severity == "warning"
               for item in diagnostics)


def test_repeated_cursor_stops():
    client=Client([{"result":{"postings":[fbo()],"has_next":True,"cursor":"same"}}]*2)
    rows, diagnostics, quality=fetch_postings(client,FBO_POSTINGS_PATH,date(2026,7,1),date(2026,8,1))
    assert len(rows)==2 and len(client.calls)==2 and diagnostics[-1].code=="NON_PROGRESSING_POSTINGS_CURSOR"


def test_business_calendar_normalizes_event_instants_across_sunday_boundary():
    after = fbo()
    after["in_process_at"] = "2026-09-06T22:30:00Z"
    before = fbo()
    before["in_process_at"] = "2026-09-06T20:30:00Z"

    after_rows, _, _ = normalize_fbo_posting(after)
    before_rows, _, _ = normalize_fbo_posting(before)

    assert after_rows[0].accepted_at == "2026-09-07T01:30:00+03:00"
    assert before_rows[0].accepted_at == "2026-09-06T23:30:00+03:00"


def test_history_business_dates_are_converted_to_utc_request_instants():
    client = Client([{"result": {"postings": [], "has_next": False}}])

    fetch_postings(client, FBO_POSTINGS_PATH, date(2026, 9, 7), date(2026, 9, 13))

    assert client.calls[0][1]["filter"] == {
        "since": "2026-09-06T21:00:00Z",
        "to": "2026-09-13T20:59:59.999999Z",
    }


def test_invalid_nonblank_event_timestamp_is_diagnostic_and_unknown():
    posting = fbo()
    posting["in_process_at"] = "not-a-timestamp"

    rows, diagnostics, _ = normalize_fbo_posting(posting)

    assert rows[0].accepted_at == ""
    assert any(item.code == "INVALID_ORDER_TIMESTAMP" for item in diagnostics)


@pytest.mark.parametrize("response", [
    {},
    {"result": {}},
    {"result": {"postings": None}},
    {"result": {"postings": {}}},
    {"result": {"postings": "bad"}},
    {"result": {"postings": [None]}},
    {"result": {"postings": [[]]}},
    {"result": {"postings": ["bad"]}},
    {"result": {"postings": [123]}},
])
def test_invalid_postings_envelope_fails_endpoint(response):
    client = Client([response])
    with pytest.raises(ValueError):
        fetch_postings(client, FBO_POSTINGS_PATH, date(2026, 7, 1), date(2026, 8, 1))


@pytest.mark.parametrize("path", [FBO_POSTINGS_PATH, FBS_POSTINGS_PATH])
def test_explicit_empty_postings_is_valid(path):
    rows, diagnostics, quality = fetch_postings(
        Client([{"result": {"postings": [], "has_next": False}}]),
        path, date(2026, 7, 1), date(2026, 8, 1))
    assert rows == () and diagnostics == ()
    assert quality.rejected_record_count == 0 and quality.incomplete_skus == ()


@pytest.mark.parametrize("normalizer,factory", [
    (normalize_fbo_posting, fbo),
    (normalize_fbs_posting, fbs),
])
@pytest.mark.parametrize("products", [None, {}, "bad", [], [None], [[]], ["bad"], [123]])
def test_invalid_products_collection_fails_endpoint(normalizer, factory, products):
    posting = factory()
    posting["products"] = products
    with pytest.raises(ValueError):
        normalizer(posting)


@pytest.mark.parametrize("normalizer,factory", [
    (normalize_fbo_posting, fbo),
    (normalize_fbs_posting, fbs),
])
def test_missing_products_collection_fails_endpoint(normalizer, factory):
    posting = factory()
    del posting["products"]
    with pytest.raises(ValueError):
        normalizer(posting)


@pytest.mark.parametrize("normalizer,factory,sku_field", [
    (normalize_fbo_posting, fbo, "sku"),
    (normalize_fbs_posting, fbs, "product_id"),
])
@pytest.mark.parametrize("sku", [None, "", "   "])
def test_missing_product_identity_fails_endpoint(normalizer, factory, sku_field, sku):
    posting = factory()
    posting["products"][0][sku_field] = sku
    with pytest.raises(ValueError):
        normalizer(posting)


@pytest.mark.parametrize("normalizer,factory,sku_field", [
    (normalize_fbo_posting, fbo, "sku"),
    (normalize_fbs_posting, fbs, "product_id"),
])
def test_invalid_quantity_is_scoped_to_known_sku(normalizer, factory, sku_field):
    posting = factory()
    posting["products"] = [
        {sku_field: "SKU-A", "quantity": 2},
        {sku_field: "SKU-B", "quantity": None},
    ]
    rows, diagnostics, quality = normalizer(posting)
    assert [row.sku for row in rows] == ["SKU-A"]
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == ("SKU-B",)
    assert any(item.code == "INVALID_ORDER_PRODUCT" and item.severity == "warning"
               for item in diagnostics)


@pytest.mark.parametrize("normalizer,factory", [
    (normalize_fbo_posting, fbo),
    (normalize_fbs_posting, fbs),
])
def test_missing_demand_event_date_quarantines_affected_sku(normalizer, factory):
    posting = factory()
    posting.pop("in_process_at", None)
    posting.pop("created_at", None)
    rows, diagnostics, quality = normalizer(posting)
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus in {("123",), ("456",)}
    assert any(item.code == "MISSING_ORDER_EVENT_DATE" and
               item.field == "accepted_at" and item.severity == "warning"
               for item in diagnostics)


def test_cancelled_missing_event_date_is_not_a_demand_blocker():
    posting = fbo(status="cancelled")
    posting.pop("in_process_at")
    rows, diagnostics, quality = normalize_fbo_posting(posting)
    assert len(rows) == 1
    assert diagnostics == ()
    assert quality.rejected_record_count == 0
    assert quality.incomplete_skus == ()


def test_one_product_with_multiple_rejection_reasons_counts_once():
    posting = fbo(destination=None, status="future")
    posting["products"][0]["quantity"] = None
    rows, diagnostics, quality = normalize_fbo_posting(posting)
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == ("123",)
    assert {item.code for item in diagnostics} >= {
        "UNKNOWN_ORDER_STATUS", "INVALID_ORDER_PRODUCT"}

@pytest.mark.parametrize(("normalizer", "value", "sku"), [
    (normalize_fbo_posting, fbo(destination=None), "123"),
    (normalize_fbs_posting, fbs(destination=None), "456"),
])
def test_missing_destination_quarantines_affected_sku(normalizer, value, sku):
    rows, diagnostics, quality = normalizer(value)
    assert rows == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == (sku,)
    assert any(item.code == "UNRESOLVED_DESTINATION_CLUSTER" and item.severity == "warning"
               for item in diagnostics)


def test_missing_destination_quality_is_unique_sorted_and_counts_rows():
    posting = fbo(destination=None)
    posting["products"] = [
        {"sku": "SKU-B", "quantity": 1},
        {"sku": "SKU-A", "quantity": 2},
        {"sku": "SKU-B", "quantity": 3},
    ]
    rows, _, quality = normalize_fbo_posting(posting)
    assert rows == ()
    assert quality.rejected_record_count == 3
    assert quality.incomplete_skus == ("SKU-A", "SKU-B")


def test_cancelled_missing_destination_is_quarantined_without_demand_blocker():
    rows, diagnostics, quality = normalize_fbo_posting(
        fbo(destination=None, status="cancelled"))
    assert rows == () and diagnostics == ()
    assert quality.rejected_record_count == 1
    assert quality.incomplete_skus == ()


def test_unscoped_missing_destination_remains_blocking():
    posting = fbo(destination=None)
    posting["products"] = [{"sku": "", "quantity": 1}]
    with pytest.raises(ValueError):
        normalize_fbo_posting(posting)
