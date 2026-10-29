"""Persistent storage for OAuth clients and issued tokens."""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from ..const import (
    ACCESS_TOKEN_TTL,
    AUTH_CODE_TTL,
    REFRESH_TOKEN_TTL,
    STORAGE_KEY,
    STORAGE_VERSION,
)


def random_token(length: int = 48) -> str:
    """A URL-safe high-entropy secret."""
    return secrets.token_urlsafe(length)


def hash_token(token: str) -> str:
    """Hash a bearer token for storage.

    Tokens are 48 random bytes, so a single SHA-256 pass is enough — there is no
    low-entropy secret to brute force.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_pkce(verifier: str, challenge: str) -> bool:
    """Check an S256 PKCE verifier against its challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, challenge)


@dataclass(slots=True)
class OAuthClient:
    """A registered or discovered MCP client."""

    client_id: str
    client_name: str
    redirect_uris: list[str]
    created_at: float = field(default_factory=time.time)
    #: True when created through dynamic client registration (RFC 7591).
    dynamic: bool = False
    client_uri: str | None = None
    logo_uri: str | None = None
    scope: str | None = None

    def allows(self, redirect_uri: str) -> bool:
        """Whether `redirect_uri` was registered for this client."""
        return redirect_uri in self.redirect_uris

    def as_registration_response(self) -> dict[str, Any]:
        """RFC 7591 registration response body."""
        payload = {
            "client_id": self.client_id,
            "client_id_issued_at": int(self.created_at),
            "client_name": self.client_name,
            "redirect_uris": self.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        if self.client_uri:
            payload["client_uri"] = self.client_uri
        if self.logo_uri:
            payload["logo_uri"] = self.logo_uri
        if self.scope:
            payload["scope"] = self.scope
        return payload


@dataclass(slots=True)
class TokenRecord:
    """An issued access/refresh token pair, backed by a Home Assistant refresh token."""

    token_id: str
    access_hash: str
    refresh_hash: str
    client_id: str
    client_name: str
    user_id: str
    ha_refresh_token_id: str
    scopes: list[str]
    created_at: float
    expires_at: float
    refresh_expires_at: float
    last_used: float | None = None

    @property
    def access_expired(self) -> bool:
        """Whether the access token is past its lifetime."""
        return time.time() >= self.expires_at

    @property
    def refresh_expired(self) -> bool:
        """Whether the refresh token is past its lifetime."""
        return time.time() >= self.refresh_expires_at


@dataclass(slots=True)
class AuthCode:
    """A short-lived authorization code (held in memory only)."""

    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    user_id: str
    ha_refresh_token_id: str
    resource: str | None
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        """Whether the code is no longer usable."""
        return time.time() - self.created_at > AUTH_CODE_TTL


@dataclass(slots=True)
class PendingAuthorization:
    """An authorization request parked while the user logs in to Home Assistant."""

    state_key: str
    client_id: str
    client_name: str
    redirect_uri: str
    client_state: str | None
    code_challenge: str
    scopes: list[str]
    resource: str | None
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        """Whether the login took too long."""
        return time.time() - self.created_at > 900


class AuthStore:
    """Keeps clients and tokens, persisting them across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise."""
        self.hass = hass
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY, private=True)
        self.clients: dict[str, OAuthClient] = {}
        self.tokens: dict[str, TokenRecord] = {}
        self._by_access: dict[str, str] = {}
        self._by_refresh: dict[str, str] = {}
        self.codes: dict[str, AuthCode] = {}
        self.pending: dict[str, PendingAuthorization] = {}

    async def async_load(self) -> None:
        """Load from disk."""
        data = await self._store.async_load() or {}
        for raw in data.get("clients", []):
            client = OAuthClient(**raw)
            self.clients[client.client_id] = client
        for raw in data.get("tokens", []):
            record = TokenRecord(**raw)
            self.tokens[record.token_id] = record
        self._reindex()
        await self.async_purge()

    async def async_save(self) -> None:
        """Persist to disk."""
        await self._store.async_save(
            {
                "clients": [asdict(client) for client in self.clients.values()],
                "tokens": [asdict(token) for token in self.tokens.values()],
            }
        )

    @callback
    def _reindex(self) -> None:
        """Rebuild the token lookup indexes."""
        self._by_access = {t.access_hash: t.token_id for t in self.tokens.values()}
        self._by_refresh = {t.refresh_hash: t.token_id for t in self.tokens.values()}

    # Clients -----------------------------------------------------------------
    async def async_add_client(self, client: OAuthClient) -> OAuthClient:
        """Store a client."""
        self.clients[client.client_id] = client
        await self.async_save()
        return client

    @callback
    def get_client(self, client_id: str) -> OAuthClient | None:
        """Look up a client."""
        return self.clients.get(client_id)

    # Tokens ------------------------------------------------------------------
    async def async_issue_tokens(
        self,
        *,
        client: OAuthClient,
        user_id: str,
        ha_refresh_token_id: str,
        scopes: list[str],
    ) -> tuple[str, str, TokenRecord]:
        """Mint a new access/refresh token pair."""
        access_token = random_token()
        refresh_token = random_token()
        now = time.time()
        record = TokenRecord(
            token_id=secrets.token_hex(16),
            access_hash=hash_token(access_token),
            refresh_hash=hash_token(refresh_token),
            client_id=client.client_id,
            client_name=client.client_name,
            user_id=user_id,
            ha_refresh_token_id=ha_refresh_token_id,
            scopes=scopes,
            created_at=now,
            expires_at=now + ACCESS_TOKEN_TTL,
            refresh_expires_at=now + REFRESH_TOKEN_TTL,
        )
        self.tokens[record.token_id] = record
        self._reindex()
        await self.async_save()
        return access_token, refresh_token, record

    async def async_rotate(self, record: TokenRecord) -> tuple[str, str]:
        """Issue a fresh pair for an existing grant, invalidating the old one."""
        access_token = random_token()
        refresh_token = random_token()
        now = time.time()
        record.access_hash = hash_token(access_token)
        record.refresh_hash = hash_token(refresh_token)
        record.expires_at = now + ACCESS_TOKEN_TTL
        record.refresh_expires_at = now + REFRESH_TOKEN_TTL
        self._reindex()
        await self.async_save()
        return access_token, refresh_token

    @callback
    def resolve_access_token(self, token: str) -> TokenRecord | None:
        """Find the record for a bearer token."""
        token_id = self._by_access.get(hash_token(token))
        return self.tokens.get(token_id) if token_id else None

    @callback
    def resolve_refresh_token(self, token: str) -> TokenRecord | None:
        """Find the record for a refresh token."""
        token_id = self._by_refresh.get(hash_token(token))
        return self.tokens.get(token_id) if token_id else None

    async def async_revoke(self, token_id: str, *, revoke_ha: bool = True) -> bool:
        """Drop a token, and the Home Assistant refresh token behind it."""
        record = self.tokens.pop(token_id, None)
        if record is None:
            return False
        if revoke_ha:
            ha_token = self.hass.auth.async_get_refresh_token(record.ha_refresh_token_id)
            if ha_token is not None:
                self.hass.auth.async_remove_refresh_token(ha_token)
        self._reindex()
        await self.async_save()
        return True

    async def async_purge(self) -> None:
        """Remove expired tokens and codes, and tokens whose HA grant is gone."""
        changed = False
        for token_id, record in list(self.tokens.items()):
            if record.refresh_expired or (
                self.hass.auth.async_get_refresh_token(record.ha_refresh_token_id) is None
            ):
                del self.tokens[token_id]
                changed = True
        for code, record in list(self.codes.items()):
            if record.expired:
                del self.codes[code]
        for key, pending in list(self.pending.items()):
            if pending.expired:
                del self.pending[key]
        if changed:
            self._reindex()
            await self.async_save()

    @callback
    def touch(self, record: TokenRecord) -> None:
        """Record that a token was just used (persisted lazily)."""
        record.last_used = time.time()

    @callback
    def connected_clients(self) -> list[dict[str, Any]]:
        """A summary of live grants, for the options UI and diagnostics."""
        return [
            {
                "token_id": record.token_id,
                "client_id": record.client_id,
                "client_name": record.client_name,
                "user_id": record.user_id,
                "scopes": record.scopes,
                "created_at": record.created_at,
                "last_used": record.last_used,
                "expires_at": record.expires_at,
            }
            for record in sorted(
                self.tokens.values(), key=lambda r: r.created_at, reverse=True
            )
        ]
