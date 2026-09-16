"""Vault regressions for failed unlock attempts revoking stale authority."""

import pytest

from backend.ozon.contracts import OzonCredentials, OzonErrorCode
from backend.ozon.vault import CredentialVault, OzonVaultError


def test_missing_vault_file_unlock_revokes_existing_session(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.setup(OzonCredentials("client", "key"), "password")
    captured = vault.capture_context()

    path.unlink()

    with pytest.raises(OzonVaultError) as error:
        vault.unlock("password")

    assert error.value.code is OzonErrorCode.AUTH_FAILED
    assert vault.is_context_active(captured) is False
    with pytest.raises(OzonVaultError) as locked:
        vault.require_credentials()
    assert locked.value.code is OzonErrorCode.LOCKED
