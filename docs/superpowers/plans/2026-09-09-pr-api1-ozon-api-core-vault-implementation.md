# PR-API1 Ozon API Core & Encrypted Credentials Vault Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only Ozon Seller API client and password-encrypted local credential vault without exposing secrets to the frontend or changing Product Completion analytics.

**Architecture:** `data/ozon-credentials.json` stores only versioned AES-256-GCM ciphertext and scrypt metadata. Unlock decrypts Client-Id/API-Key into backend memory for the current process session. A synchronous fixed-host stdlib HTTP client owns headers, timeouts, redaction, pagination/retry primitives and normalized errors; frontend only calls localhost FastAPI credential/connection endpoints.

**Tech Stack:** Python 3.13.14, FastAPI, `hashlib.scrypt`, `cryptography==50.0.1` AESGCM, stdlib `urllib.request`, pytest; no frontend framework and no external secret store.

**Spec:** `docs/superpowers/specs/2026-09-09-ozon-api-first-shipment-planner-design.md`

## Global Constraints

- Never send stored Client-Id/API-Key back to frontend.
- Never persist password/plaintext credentials in Project JSON, logs, URLs, snapshots or test artifacts.
- Vault password is session input only; no recovery flow and no inactivity timeout.
- Fixed Ozon host is `https://api-seller.ozon.ru`; reject arbitrary hosts.
- Draft-creation retry semantics are not implemented in this PR, but the client API must allow later call policies to disable retries.
- Existing analysis/file workflows stay regression-identical.
- The only new runtime dependency in this roadmap is exactly `cryptography==50.0.1`, verified on PyPI to support Python 3.13 and provide a Windows CPython 3.11+ abi3 wheel; Windows portable smoke remains the repository-level acceptance proof.

---

### Task 1: Pin cryptography and prove portable import

**Files:**
- Modify: `requirements.txt`
- Modify: `.github/workflows/ci.yml` only if the existing Windows portable smoke needs an explicit cryptography import assertion.
- Test: existing portable/bootstrap tests and Windows smoke.

**Interfaces:**
- Produces: importable `cryptography.hazmat.primitives.ciphers.aead.AESGCM` in project-local runtime.

- [ ] **Step 1: Add exactly `cryptography==50.0.1` to `requirements.txt`; do not use a version range.**

- [ ] **Step 2: Run the local dependency/bootstrap test path available in the repo and add an explicit `from cryptography.hazmat.primitives.ciphers.aead import AESGCM` smoke assertion if current tests would not catch a missing wheel.**

- [ ] **Step 3: Run focused runtime/bootstrap tests.**

```bash
python -m pytest tests -q
```

If the repository has a narrower bootstrap suite, run it first, then the full suite before merge.

- [ ] **Step 4: Commit.**

```bash
git add requirements.txt .github/workflows/ci.yml
git commit -m "build: add vault encryption dependency"
```

---

### Task 2: Define immutable Ozon credential/client contracts

**Files:**
- Create: `backend/ozon/__init__.py`
- Create: `backend/ozon/contracts.py`
- Create: `tests/ozon/test_contracts.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OzonCredentials:
    client_id: str
    api_key: str

@dataclass(frozen=True, slots=True)
class VaultStatus:
    configured: bool
    locked: bool
    masked_client_id_suffix: str | None
    last_connection_check: str | None

class OzonErrorCode(str, Enum):
    LOCKED = "OZON_VAULT_LOCKED"
    AUTH_FAILED = "OZON_AUTH_FAILED"
    RATE_LIMITED = "OZON_RATE_LIMITED"
    UNAVAILABLE = "OZON_UNAVAILABLE"
    INVALID_RESPONSE = "OZON_INVALID_RESPONSE"
```

- [ ] **Step 1: Write contract tests for nonblank Client-Id/API-Key, stable enum values and masked suffix behavior.**
- [ ] **Step 2: Run RED.**

```bash
python -m pytest tests/ozon/test_contracts.py -q
```

- [ ] **Step 3: Implement frozen contracts and validation.**
- [ ] **Step 4: Run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_contracts.py -q
git add backend/ozon tests/ozon/test_contracts.py
git commit -m "feat: define Ozon API contracts"
```

---

### Task 3: Implement the encrypted JSON vault

**Files:**
- Create: `backend/ozon/vault.py`
- Create: `tests/ozon/test_vault.py`

**Interfaces:**

```python
class CredentialVault:
    def __init__(self, path: Path): ...
    def setup(self, credentials: OzonCredentials, password: str) -> VaultStatus: ...
    def unlock(self, password: str) -> VaultStatus: ...
    def lock(self) -> VaultStatus: ...
    def status(self) -> VaultStatus: ...
    def require_credentials(self) -> OzonCredentials: ...
    def reset(self) -> None: ...
```

Vault v1 exact primitives:

```text
scrypt(n=32768, r=8, p=1, dklen=32, salt=16 random bytes)
AES-256-GCM(nonce=12 random bytes)
AAD = b"sklad_ozon:ozon-vault:v1"
```

Persist JSON keys:

```text
version
kdf.name / n / r / p / dklen
salt_b64
cipher.name
nonce_b64
ciphertext_b64
masked_client_id_suffix
```

- [ ] **Step 1: Add tests proving round-trip setup→lock→unlock, wrong-password failure, tamper/auth-tag failure, random salt/nonce, and no plaintext Client-Id/API-Key/password bytes in the written file.**
- [ ] **Step 2: Add atomic-write recovery test: a failed temp write must not destroy the previous valid vault.**
- [ ] **Step 3: Run RED.**

```bash
python -m pytest tests/ozon/test_vault.py -q
```

- [ ] **Step 4: Implement scrypt + AESGCM and atomic replace.**

Do not claim secure zeroization. `lock()` only drops backend references and forces future `require_credentials()` to fail.

- [ ] **Step 5: Run GREEN and commit.**

```bash
python -m pytest tests/ozon/test_vault.py -q
git add backend/ozon/vault.py tests/ozon/test_vault.py
git commit -m "feat: add encrypted Ozon credential vault"
```

---

### Task 4: Implement fixed-host Ozon HTTP client primitives

**Files:**
- Create: `backend/ozon/endpoints.py`
- Create: `backend/ozon/client.py`
- Create: `tests/ozon/test_client.py`

**Interfaces:**

```python
OZON_API_BASE = "https://api-seller.ozon.ru"

@dataclass(frozen=True, slots=True)
class OzonRequestPolicy:
    retry_safe: bool
    max_attempts: int = 3

class OzonClient:
    def post_json(self, path: str, payload: dict, *, policy: OzonRequestPolicy) -> dict: ...
```

The client pulls credentials through `CredentialVault.require_credentials()`; callers never pass headers/secrets.

- [ ] **Step 1: Add fake-transport tests for exact fixed host, Client-Id/Api-Key header injection, finite timeout, JSON response decoding and malformed JSON normalization.**
- [ ] **Step 2: Add retry tests: safe call retries boundedly on 429/selected 5xx and respects numeric `Retry-After`; `retry_safe=False` performs one attempt only.**
- [ ] **Step 3: Add redaction tests proving secret values do not appear in exception strings or logger records.**
- [ ] **Step 4: Run RED, implement client, run GREEN.**

```bash
python -m pytest tests/ozon/test_client.py -q
```

- [ ] **Step 5: Commit.**

```bash
git add backend/ozon/endpoints.py backend/ozon/client.py tests/ozon/test_client.py
git commit -m "feat: add backend Ozon API client"
```

---

### Task 5: Add localhost credential and connection endpoints

**Files:**
- Modify: `backend/api.py`
- Create: `tests/api/test_ozon_credentials.py`

**Interfaces:**

```text
GET  /api/ozon/credentials/status
POST /api/ozon/credentials/setup
POST /api/ozon/credentials/unlock
POST /api/ozon/credentials/lock
POST /api/ozon/connection/test
```

`setup` request contains Client-Id, API-Key, password, password_confirmation. `unlock` contains password only. Responses expose `VaultStatus` only.

- [ ] **Step 1: Write API tests for first setup, mismatch password confirmation, locked restart state, unlock, wrong password, lock and status. Assert response bodies never contain the API key/password.**
- [ ] **Step 2: Add connection-test fake-client test proving locked vault is rejected before network and successful check updates only `last_connection_check`.**
- [ ] **Step 3: Run RED, wire one process-owned vault/client into the FastAPI app, run GREEN.**

```bash
python -m pytest tests/api/test_ozon_credentials.py -q
```

- [ ] **Step 4: Commit.**

```bash
git add backend/api.py tests/api/test_ozon_credentials.py
git commit -m "feat: expose local Ozon credential controls"
```

---

### Task 6: PR-API1 security and regression gate

- [ ] **Step 1: Run all Ozon/vault/API focused tests.**

```bash
python -m pytest tests/ozon tests/api/test_ozon_credentials.py -q
```

- [ ] **Step 2: Run existing analysis API tests unchanged.**

```bash
python -m pytest tests/api/test_analysis.py tests/api/test_product_completion_acceptance.py -q
```

- [ ] **Step 3: Run full suite.**

```bash
python -m pytest -q
```

- [ ] **Step 4: Run/inspect authoritative Windows portable smoke and verify `cryptography==50.0.1` installs/imports in project-local Python 3.13.14.**

- [ ] **Step 5: Search repository/test artifacts for fixture secrets and verify no new production secret logging or frontend credential serialization exists.**

Acceptance: vault is encrypted at rest, unlock lasts one process session, API client is backend-only, fixed-host and redact-safe, and no existing analytical behavior changed.
