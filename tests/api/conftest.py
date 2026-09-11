"""Shared isolated Ozon credential context for API-boundary tests."""

from dataclasses import replace

import pytest

import backend.api as api_module
from backend.ozon.client import OzonClient
from backend.ozon.contracts import OzonCredentials
from backend.ozon.draft_validation import DraftValidationService
from backend.ozon.vault import CredentialVault


TEST_CLIENT_ID = "api-test-client"
TEST_API_KEY = "api-test-key"
TEST_VAULT_PASSWORD = "api-test-password"


@pytest.fixture(autouse=True)
def isolated_api_credential_context(tmp_path, monkeypatch):
    """Make legacy API fixtures represent the currently configured Ozon account.

    Hand-built snapshots that predate credential provenance intentionally omit
    ``credential_context_id``. At the HTTP boundary those fixtures should mean
    "snapshot from the current test account", so the test store fills only a
    missing context id. Explicit foreign ids remain untouched and still test
    mismatch rejection.

    The shared harness vault lives in a dedicated subdirectory so tests that
    intentionally create an initially-unconfigured vault at ``tmp_path`` stay
    independent.
    """
    vault = CredentialVault(tmp_path / "_credential_context" / "ozon-credentials.json")
    vault.setup(
        OzonCredentials(TEST_CLIENT_ID, TEST_API_KEY),
        TEST_VAULT_PASSWORD,
    )
    client = OzonClient(vault)

    monkeypatch.setattr(api_module, "OZON_VAULT", vault)
    monkeypatch.setattr(api_module, "OZON_CLIENT", client)
    monkeypatch.setattr(
        api_module,
        "DRAFT_VALIDATION_SERVICE",
        DraftValidationService(client),
    )

    api_module.OZON_SOURCE_STORE.clear()
    api_module.HANDOFF_STORE.clear()
    api_module.ANALYSIS_STORE.clear()
    api_module.SHIPMENT_PLAN_STORE.clear()

    original_put = api_module.OZON_SOURCE_STORE.put

    def put_current_context(snapshot):
        if snapshot.credential_context_id is None:
            snapshot = replace(
                snapshot,
                credential_context_id=vault.credential_context_id(),
            )
        return original_put(snapshot)

    monkeypatch.setattr(api_module.OZON_SOURCE_STORE, "put", put_current_context)

    yield vault

    api_module.OZON_SOURCE_STORE.clear()
    api_module.HANDOFF_STORE.clear()
    api_module.ANALYSIS_STORE.clear()
    api_module.SHIPMENT_PLAN_STORE.clear()
