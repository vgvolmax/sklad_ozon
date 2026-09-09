import pytest

from backend.ozon.handoff import HandoffPointStore, search_handoff_points


class Client:
    def __init__(self): self.calls = []
    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return {"search": [{"warehouse_id": 7, "name": "Тверь", "address": "address",
                            "warehouse_type": "CROSS_DOCK", "point_type": "PVZ",
                            "phone": "PII"}]}


def test_exact_request_response_contract_and_type_preservation():
    client = Client()
    result = search_handoff_points(client, "  Тверь ", ("CROSS_DOCK",))
    assert client.calls[0][1] == {"filter_by_supply_type": ["CROSS_DOCK"], "search": "Тверь"}
    assert (result[0].warehouse_type, result[0].point_type) == ("CROSS_DOCK", "PVZ")
    assert "PII" not in repr(result)


def test_short_trimmed_query_performs_no_network_call():
    client = Client()
    assert search_handoff_points(client, " abc ", ()) == ()
    assert client.calls == []


def test_store_is_memory_only_and_stale_identity_fails():
    first = HandoffPointStore()
    second = HandoffPointStore()
    point = search_handoff_points(Client(), "Тверь", ())[0]
    first.put_all((point,))
    assert first.require(7) == point
    with pytest.raises(KeyError): second.require(7)
