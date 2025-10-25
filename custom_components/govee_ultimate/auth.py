"""Authentication management for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from homeassistant.helpers.storage import Store

STORAGE_VERSION = 1
STORAGE_KEY = "govee_ultimate_auth"
REFRESH_OFFSET = timedelta(seconds=60)
LOGIN_ENDPOINT = "/v1/account/login"
REFRESH_ENDPOINT = "/v1/account/refresh-token"


@dataclass(frozen=True)
class TokenDetails:
    """Details about issued access tokens."""

    email: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    @classmethod
    def from_login_payload(cls, email: str, payload: dict[str, Any]) -> "TokenDetails":
        """Create token details from a login payload."""

        return cls(
            email=email,
            access_token=payload["accessToken"],
            refresh_token=payload["refreshToken"],
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=payload["expiresIn"]),
        )

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> "TokenDetails":
        """Create token details from persisted storage."""

        return cls(
            email=data["email"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )

    def as_storage(self) -> dict[str, Any]:
        """Serialize the token details for storage."""

        return {
            "email": self.email,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
        }

    def should_refresh(self, now: datetime | None = None) -> bool:
        """Return True if the token should be refreshed."""

        if now is None:
            now = datetime.now(timezone.utc)
        return now >= (self.expires_at - REFRESH_OFFSET)


class GoveeAuthManager:
    """Manage authentication lifecycle for the Govee Ultimate integration."""

    def __init__(self, hass: Any, client: httpx.AsyncClient) -> None:
        self._hass = hass
        self._client = client
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY, private=True)
        self._tokens: TokenDetails | None = None
        self._store_lock = asyncio.Lock()

    @property
    def tokens(self) -> TokenDetails | None:
        """Return the current token details."""

        return self._tokens

    async def async_initialize(self) -> None:
        """Load persisted tokens from disk."""

        data = await self._store.async_load()
        if not data:
            return
        self._tokens = TokenDetails.from_storage(data)

    async def async_login(self, email: str, password: str) -> TokenDetails:
        """Login with the provided credentials and persist the resulting tokens."""

        try:
            response = await self._client.post(
                LOGIN_ENDPOINT,
                json={"email": email, "password": password},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            await self._clear_tokens()
            raise

        payload = response.json()
        login_data = payload.get("login", {})
        tokens = TokenDetails.from_login_payload(email, login_data)
        return await self._store_tokens(tokens)

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""

        if self._tokens is None:
            raise RuntimeError("No credentials loaded")

        if self._tokens.should_refresh():
            await self._refresh_tokens()

        return self._tokens.access_token

    async def _refresh_tokens(self) -> TokenDetails:
        """Refresh the stored token using the refresh token."""

        if self._tokens is None:
            raise RuntimeError("No credentials to refresh")

        try:
            response = await self._client.post(
                REFRESH_ENDPOINT,
                json={"refreshToken": self._tokens.refresh_token},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            await self._clear_tokens()
            raise
        payload = response.json()
        login_data = payload.get("login", {})
        tokens = TokenDetails.from_login_payload(self._tokens.email, login_data)
        return await self._store_tokens(tokens)

    async def _persist_tokens(self, tokens: TokenDetails) -> None:
        """Persist tokens via the storage helper."""

        async with self._store_lock:
            await self._store.async_save(tokens.as_storage())

    async def _store_tokens(self, tokens: TokenDetails) -> TokenDetails:
        """Persist and cache the provided tokens."""

        await self._persist_tokens(tokens)
        self._tokens = tokens
        return tokens

    async def _clear_tokens(self) -> None:
        """Remove any cached tokens from memory and disk."""

        self._tokens = None
        async with self._store_lock:
            await self._store.async_remove()
