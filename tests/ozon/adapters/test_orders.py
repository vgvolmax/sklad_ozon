from datetime import date
import pytest
from backend.domain.contracts import OrderLifecycle
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
    return {"posting_number": number, "status_alias": "delivered", "financial_data": financial,
            "analytics_data": {"region": "WRONG", "city": "WRONG"},
            "products": [{"product_id": 456, "product_offer_id": "FBS-ART", "product_name": "FBS product", "quantity": 1, "price": "55"}]}


class Client:
    def __init__(self, responses): self.responses=iter(responses); self.calls=[]
    def post_json(self,path,payload,**kwargs): self.calls.append((path,payload)); return next(self.responses)


@pytest.mark.parametrize(("path", "factory"), [(FBO_POSTINGS_PATH, fbo), (FBS_POSTINGS_PATH, fbs)])
def test_real_cursor_contract_and_financial_data_request(path, factory):
    client=Client([{"result":{"postings":[factory("1")],"has_next":True,"cursor":"next"}},
                   {"result":{"postings":[factory("2")],"has_next":False,"cursor":"done"}}])
    records, diagnostics=fetch_postings(client,path,date(2026,7,1),date(2026,8,1))
    assert len(records)==2 and not diagnostics
    assert client.calls[0][1]["with"]=={"analytics_data":True,"financial_data":True}
    assert "legal_info" not in client.calls[0][1]["with"]
    assert client.calls[1][1]["cursor"]=="next"


def test_endpoint_specific_wire_fields_and_pii_are_discarded():
    fbo_rows,_=normalize_fbo_posting(fbo()); fbs_rows,_=normalize_fbs_posting(fbs())
    assert (fbo_rows[0].origin_cluster,fbo_rows[0].destination_cluster)==("Казань","Москва")
    assert (fbs_rows[0].origin_cluster,fbs_rows[0].destination_cluster)==("Урал","Сибирь")
    assert (fbs_rows[0].sku,fbs_rows[0].article,fbs_rows[0].product_name)==("456","FBS-ART","FBS product")
    assert fbs_rows[0].raw_status=="delivered" and "PII" not in repr(fbo_rows)


@pytest.mark.parametrize(("normalizer", "value"), [(normalize_fbo_posting, fbo(destination=None)), (normalize_fbs_posting, fbs(destination=None))])
def test_region_and_city_never_substitute_destination(normalizer,value):
    rows, diagnostics=normalizer(value)
    assert rows[0].destination_cluster==""
    assert {d.code for d in diagnostics}=={"UNRESOLVED_DESTINATION_CLUSTER"}


def test_unknown_lifecycle_remains_unknown():
    rows, diagnostics=normalize_fbo_posting(fbo(status="future"))
    assert rows[0].lifecycle is OrderLifecycle.UNKNOWN and diagnostics[-1].code=="UNKNOWN_ORDER_STATUS"


def test_repeated_cursor_stops():
    client=Client([{"result":{"postings":[fbo()],"has_next":True,"cursor":"same"}}]*2)
    rows, diagnostics=fetch_postings(client,FBO_POSTINGS_PATH,date(2026,7,1),date(2026,8,1))
    assert len(rows)==2 and len(client.calls)==2 and diagnostics[-1].code=="NON_PROGRESSING_POSTINGS_CURSOR"
