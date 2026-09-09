import base64
import json

import pytest

from backend.ozon.contracts import OzonCredentials, OzonErrorCode
from backend.ozon.vault import CredentialVault, OzonVaultError


CREDS = OzonCredentials("client-123456", "api-key-sensitive")


def test_setup_lock_unlock_roundtrip_and_reset(tmp_path):
    path = tmp_path / "ozon-credentials.json"
    vault = CredentialVault(path)
    status = vault.setup(CREDS, "vault-password")
    assert status.configured and not status.locked
    assert status.masked_client_id_suffix == "…3456"
    assert vault.require_credentials() == CREDS

    assert vault.lock().locked
    with pytest.raises(OzonVaultError) as error:
        vault.require_credentials()
    assert error.value.code is OzonErrorCode.LOCKED
    assert vault.unlock("vault-password").locked is False
    assert vault.require_credentials() == CREDS

    vault.reset()
    assert vault.status().configured is False
    assert not path.exists()


def test_wrong_password_and_tampering_fail_without_secret_details(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.setup(CREDS, "correct-password")
    vault.lock()

    with pytest.raises(OzonVaultError) as wrong:
        vault.unlock("wrong-password")
    assert wrong.value.code is OzonErrorCode.AUTH_FAILED
    assert "wrong-password" not in str(wrong.value)

    document = json.loads(path.read_text())
    ciphertext = bytearray(base64.b64decode(document["ciphertext_b64"]))
    ciphertext[-1] ^= 1
    document["ciphertext_b64"] = base64.b64encode(ciphertext).decode("ascii")
    path.write_text(json.dumps(document))
    with pytest.raises(OzonVaultError) as tampered:
        vault.unlock("correct-password")
    assert tampered.value.code is OzonErrorCode.AUTH_FAILED
    assert CREDS.api_key not in str(tampered.value)


def test_setup_uses_random_salt_and_nonce_and_exact_crypto_metadata(tmp_path):
    first_path, second_path = tmp_path / "first.json", tmp_path / "second.json"
    CredentialVault(first_path).setup(CREDS, "password")
    CredentialVault(second_path).setup(CREDS, "password")
    first, second = json.loads(first_path.read_text()), json.loads(second_path.read_text())
    assert first["version"] == 1
    assert first["kdf"] == {"name": "scrypt", "n": 32768, "r": 8, "p": 1, "dklen": 32}
    assert first["cipher"] == {"name": "AES-256-GCM"}
    assert len(base64.b64decode(first["salt_b64"])) == 16
    assert len(base64.b64decode(first["nonce_b64"])) == 12
    assert first["salt_b64"] != second["salt_b64"]
    assert first["nonce_b64"] != second["nonce_b64"]


def test_vault_json_contains_no_plaintext_secrets_or_password(tmp_path):
    path = tmp_path / "vault.json"
    CredentialVault(path).setup(CREDS, "vault-password-sensitive")
    raw = path.read_bytes()
    assert CREDS.client_id.encode() not in raw
    assert CREDS.api_key.encode() not in raw
    assert b"vault-password-sensitive" not in raw
    assert set(json.loads(raw)) == {
        "version", "kdf", "salt_b64", "cipher", "nonce_b64",
        "ciphertext_b64", "masked_client_id_suffix",
    }


def test_failed_atomic_replace_preserves_previous_valid_vault(tmp_path, monkeypatch):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.setup(CREDS, "old-password")
    original = path.read_bytes()

    def fail_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("backend.ozon.vault.os.replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        vault.setup(OzonCredentials("other-client", "other-key"), "new-password")
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".vault.json.*.tmp"))

    recovered = CredentialVault(path)
    recovered.unlock("old-password")
    assert recovered.require_credentials() == CREDS


def test_status_survives_process_restart_without_decrypting(tmp_path):
    path = tmp_path / "vault.json"
    CredentialVault(path).setup(CREDS, "password")
    restarted = CredentialVault(path)
    assert restarted.status().configured
    assert restarted.status().locked
    assert restarted.status().masked_client_id_suffix == "…3456"


@pytest.mark.parametrize("password", ["   ", "\t\n"])
def test_setup_rejects_whitespace_only_password_without_creating_vault(tmp_path, password):
    path = tmp_path / "vault.json"

    with pytest.raises(ValueError, match="nonblank"):
        CredentialVault(path).setup(CREDS, password)

    assert not path.exists()


def test_password_surrounding_whitespace_is_preserved_as_cryptographic_input(tmp_path):
    path = tmp_path / "vault.json"
    vault = CredentialVault(path)
    vault.setup(CREDS, " abc ")
    vault.lock()

    assert vault.unlock(" abc ").locked is False
    vault.lock()
    with pytest.raises(OzonVaultError) as error:
        vault.unlock("abc")
    assert error.value.code is OzonErrorCode.AUTH_FAILED
