from datetime import date

import pytest

from backend.domain.contracts import OrderLifecycle
from backend.ozon.adapters.orders import fetch_postings, normalize_posting
from backend.ozon.endpoints import FBO_POSTINGS_PATH, FBS_POSTINGS_PATH


def posting(*, number="100-1", status="delivered", destination="Москва"):
    analytics = {"cluster_from": "Казань", "warehouse_name": "W-1", "region": "НЕ DESTINATION"}
    if destination is not None:
        analytics["cluster_to"] = destination
    return {
        "posting_number": number, "status": status, "in_process_at": "2026-08-01T10:00:00Z",
        "analytics_data": analytics,
        "products": [{"sku": 123, "offer_id": "ART", "name": "Product", "quantity": 2, "price": "100"}],
        "customer": {"name": "PII"}, "addressee": {"phone": "PII"},
    }


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return next(self.responses)


@pytest.mark.parametrize("path", [FBO_POSTINGS_PATH, FBS_POSTINGS_PATH])
def test_real_cursor_contract_fetches_two_pages(path):
    client = Client([
        {"result": {"postings": [posting(number="1")], "has_next": True, "cursor": "next"}},
        {"result": {"postings": [posting(number="2")], "has_next": False, "cursor": "done"}},
    ])
    records, diagnostics = fetch_postings(client, path, date(2026, 7, 1), date(2026, 8, 1))
    assert len(records) == 2 and not diagnostics
    assert client.calls[0][1]["sort_dir"] == "ASC"
    assert "cursor" not in client.calls[0][1]
    assert client.calls[1][1]["cursor"] == "next"
    assert not ({"offset", "dir", "last_id"} & client.calls[1][1].keys())


def test_exact_destination_and_origin_are_preserved_and_pii_is_discarded():
    records, diagnostics = normalize_posting(posting())
    assert not diagnostics
    assert records[0].destination_cluster == "Москва"
    assert records[0].origin_cluster == "Казань"
    assert records[0].origin_warehouse == "W-1"
    assert "PII" not in repr(records)


def test_region_never_substitutes_for_missing_destination():
    records, diagnostics = normalize_posting(posting(destination=None))
    assert records[0].destination_cluster == ""
    assert {item.code for item in diagnostics} == {"UNRESOLVED_DESTINATION_CLUSTER"}


def test_unknown_lifecycle_remains_unknown_and_is_diagnostic():
    records, diagnostics = normalize_posting(posting(status="future_new_state"))
    assert records[0].lifecycle is OrderLifecycle.UNKNOWN
    assert "UNKNOWN_ORDER_STATUS" in {item.code for item in diagnostics}


def test_repeated_cursor_stops_deterministically():
    client = Client([
        {"result": {"postings": [posting()], "has_next": True, "cursor": "same"}},
        {"result": {"postings": [posting()], "has_next": True, "cursor": "same"}},
    ])
    records, diagnostics = fetch_postings(client, FBO_POSTINGS_PATH, date(2026, 7, 1), date(2026, 8, 1))
    assert len(records) == 2 and len(client.calls) == 2
    assert diagnostics[-1].code == "NON_PROGRESSING_POSTINGS_CURSOR"
