from dataclasses import FrozenInstanceError

import pytest

from backend.ozon.contracts import OzonCredentials, OzonErrorCode, VaultStatus


@pytest.mark.parametrize("client_id,api_key", [("", "key"), ("  ", "key"), ("id", ""), ("id", "\t")])
def test_credentials_require_nonblank_values(client_id, api_key):
    with pytest.raises(ValueError, match="nonblank"):
        OzonCredentials(client_id, api_key)


def test_credentials_are_immutable_and_repr_is_redacted():
    credentials = OzonCredentials("client-secret-id", "api-super-secret")
    rendered = repr(credentials)
    assert "client-secret-id" not in rendered
    assert "api-super-secret" not in rendered
    assert "***" in rendered
    with pytest.raises(FrozenInstanceError):
        credentials.api_key = "replacement"


def test_vault_status_is_immutable_and_contains_only_safe_metadata():
    status = VaultStatus(configured=True, locked=False, masked_client_id_suffix="…1234", last_connection_check=None,
                         credential_context_id="opaque")
    assert status.masked_client_id_suffix == "…1234"
    assert set(status.__dataclass_fields__) == {
        "configured", "locked", "masked_client_id_suffix", "last_connection_check",
        "credential_context_id"
    }
    with pytest.raises(FrozenInstanceError):
        status.locked = True


def test_error_codes_are_stable():
    assert {code.value for code in OzonErrorCode} == {
        "OZON_VAULT_LOCKED", "OZON_AUTH_FAILED", "OZON_RATE_LIMITED",
        "OZON_UNAVAILABLE", "OZON_INVALID_RESPONSE", "OZON_CREDENTIAL_CONTEXT_CHANGED",
    }


@pytest.mark.parametrize(
    "client_id,expected", [("1", "…1"), ("1234", "…1234"), (" 123456 ", "…3456")]
)
def test_masked_client_id_exposes_at_most_four_trailing_characters(client_id, expected):
    assert OzonCredentials(client_id, "key").masked_client_id_suffix == expected
