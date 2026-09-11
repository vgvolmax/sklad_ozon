"""Immutable, public-safe contracts for Ozon infrastructure."""

from dataclasses import dataclass, field
from enum import Enum


class OzonErrorCode(str, Enum):
    LOCKED = "OZON_VAULT_LOCKED"
    AUTH_FAILED = "OZON_AUTH_FAILED"
    RATE_LIMITED = "OZON_RATE_LIMITED"
    UNAVAILABLE = "OZON_UNAVAILABLE"
    INVALID_RESPONSE = "OZON_INVALID_RESPONSE"
    CREDENTIAL_CONTEXT_CHANGED = "OZON_CREDENTIAL_CONTEXT_CHANGED"


@dataclass(frozen=True, slots=True)
class OzonCredentials:
    client_id: str = field(repr=False)
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        client_id = self.client_id.strip()
        api_key = self.api_key.strip()
        if not client_id or not api_key:
            raise ValueError("Ozon credentials must be nonblank")
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "api_key", api_key)

    @property
    def masked_client_id_suffix(self) -> str:
        return f"…{self.client_id[-4:]}"

    def __repr__(self) -> str:
        return "OzonCredentials(client_id='***', api_key='***')"


@dataclass(frozen=True, slots=True)
class OzonCredentialContext:
    context_id: str
    credentials: OzonCredentials = field(repr=False)


@dataclass(frozen=True, slots=True)
class VaultStatus:
    configured: bool
    locked: bool
    masked_client_id_suffix: str | None
    last_connection_check: str | None
    credential_context_id: str | None
