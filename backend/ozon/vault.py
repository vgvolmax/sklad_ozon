"""Password-encrypted, process-unlocked Ozon credential vault."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .contracts import OzonCredentialContext, OzonCredentials, OzonErrorCode, VaultStatus


_AAD = b"sklad_ozon:ozon-vault:v1"
_KDF = {"name": "scrypt", "n": 32768, "r": 8, "p": 1, "dklen": 32}
_CIPHER = {"name": "AES-256-GCM"}
_CONTEXT_DOMAIN = b"sklad_ozon:credential-context:v1\0"


class OzonVaultError(Exception):
    """A normalized vault failure whose message never includes secret input."""

    def __init__(self, code: OzonErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class CredentialVault:
    """Keep encrypted credentials on disk and plaintext only by process reference."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._credentials: OzonCredentials | None = None
        self._last_connection_check: str | None = None
        self._lock = RLock()

    def setup(self, credentials: OzonCredentials, password: str) -> VaultStatus:
        password_bytes = self._password_bytes(password)
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = self._derive_key(password_bytes, salt)
        plaintext = json.dumps(
            {"client_id": credentials.client_id, "api_key": credentials.api_key},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, _AAD)
        document = {
            "version": 1,
            "kdf": _KDF,
            "salt_b64": base64.b64encode(salt).decode("ascii"),
            "cipher": _CIPHER,
            "nonce_b64": base64.b64encode(nonce).decode("ascii"),
            "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
            "masked_client_id_suffix": credentials.masked_client_id_suffix,
        }
        with self._lock:
            self._write_atomic(json.dumps(document, separators=(",", ":")).encode("utf-8"))
            self._credentials = credentials
            self._last_connection_check = None
            return self.status()

    def unlock(self, password: str) -> VaultStatus:
        with self._lock:
            return self._unlock(password)

    def _unlock(self, password: str) -> VaultStatus:
        if not self._path.is_file():
            raise OzonVaultError(OzonErrorCode.AUTH_FAILED, "Ozon credential vault is not configured")
        try:
            document = json.loads(self._path.read_bytes())
            self._validate_document(document)
            salt = self._decode(document["salt_b64"], 16)
            nonce = self._decode(document["nonce_b64"], 12)
            ciphertext = self._decode(document["ciphertext_b64"])
            key = self._derive_key(self._password_bytes(password), salt)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
            decoded = json.loads(plaintext)
            credentials = OzonCredentials(decoded["client_id"], decoded["api_key"])
        except (InvalidTag, KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            self._credentials = None
            raise OzonVaultError(OzonErrorCode.AUTH_FAILED, "Vault password or encrypted data is invalid") from None
        self._credentials = credentials
        return self.status()

    def lock(self) -> VaultStatus:
        # Python cannot promise secure memory zeroization; dropping this reference
        # only makes credentials unavailable to subsequent backend operations.
        with self._lock:
            self._credentials = None
            return self.status()

    def status(self) -> VaultStatus:
        with self._lock:
            configured = self._path.is_file()
            suffix = None
            if configured:
                try:
                    value = json.loads(self._path.read_bytes()).get("masked_client_id_suffix")
                    suffix = value if isinstance(value, str) else None
                except (OSError, json.JSONDecodeError, UnicodeError):
                    suffix = None
            return VaultStatus(
                configured=configured,
                locked=self._credentials is None,
                masked_client_id_suffix=suffix,
                last_connection_check=self._last_connection_check,
                credential_context_id=self.credential_context_id(),
            )

    def credential_context_id(self) -> str | None:
        """Return an opaque identity derived only from the encrypted document."""
        with self._lock:
            try:
                document = self._path.read_bytes()
            except FileNotFoundError:
                return None
            return hashlib.sha256(_CONTEXT_DOMAIN + document).hexdigest()

    def capture_context(self) -> OzonCredentialContext:
        """Atomically capture matching credentials and encrypted-vault identity."""
        with self._lock:
            credentials = self.require_credentials()
            context_id = self.credential_context_id()
            if context_id is None:
                raise OzonVaultError(OzonErrorCode.LOCKED, "Ozon credential vault is locked")
            return OzonCredentialContext(context_id, credentials)

    def require_credentials(self) -> OzonCredentials:
        if self._credentials is None:
            raise OzonVaultError(OzonErrorCode.LOCKED, "Ozon credential vault is locked")
        return self._credentials

    def record_connection_check(self, checked_at: datetime | None = None) -> VaultStatus:
        checked_at = checked_at or datetime.now(timezone.utc)
        with self._lock:
            self._last_connection_check = checked_at.astimezone(timezone.utc).isoformat()
            return self.status()

    def reset(self) -> None:
        with self._lock:
            self._credentials = None
            self._last_connection_check = None
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _password_bytes(password: str) -> bytes:
        if not isinstance(password, str) or not password.strip():
            raise ValueError("Vault password must be nonblank")
        return password.encode("utf-8")

    @staticmethod
    def _derive_key(password: bytes, salt: bytes) -> bytes:
        return hashlib.scrypt(password, salt=salt, n=32768, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)

    @staticmethod
    def _decode(value: object, expected_length: int | None = None) -> bytes:
        if not isinstance(value, str):
            raise ValueError("invalid encoded value")
        decoded = base64.b64decode(value, validate=True)
        if expected_length is not None and len(decoded) != expected_length:
            raise ValueError("invalid encoded length")
        return decoded

    @staticmethod
    def _validate_document(document: object) -> None:
        if not isinstance(document, dict):
            raise ValueError("invalid vault document")
        if document.get("version") != 1 or document.get("kdf") != _KDF or document.get("cipher") != _CIPHER:
            raise ValueError("unsupported vault format")

    def _write_atomic(self, data: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
