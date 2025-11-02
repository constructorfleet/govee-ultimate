"""Authentication management for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    load_key_and_certificates,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .storage import async_migrate_storage_file

STORAGE_VERSION = 1
STORAGE_KEY = "govee_auth"
LEGACY_STORAGE_KEY = "govee_ultimate_auth"
REFRESH_OFFSET = timedelta(seconds=60)
LOGIN_ENDPOINT = "https://app2.govee.com/account/rest/account/v1/login"
REFRESH_ENDPOINT = "https://app2.govee.com/account/rest/v1/first/refresh-tokens"
IOT_KEY_ENDPOINT = "https://app2.govee.com/app/v1/account/iot/key"
COMMUNITY_LOGIN_ENDPOINT = "https://community-api.govee.com/os/v1/login"
APP_VERSION = "5.6.01"
USER_AGENT = (
    "GoveeHome/"
    f"{APP_VERSION}"
    " (com.ihoment.GoVeeSensor; build:2; iOS 16.5.0) Alamofire/5.6.4"
)
CLIENT_TYPE = "1"


@dataclass(frozen=True)
class IoTBundle:
    """Persisted IoT connection metadata."""

    account_id: str
    client_id: str
    topic: str
    endpoint: str
    certificate: str
    private_key: str


@dataclass(frozen=True)
class BffBundle:
    """Persisted community (BFF) authentication metadata."""

    access_token: str
    client_id: str
    expires_at: datetime


@dataclass(frozen=True)
class AccountAuthDetails:
    """Complete account authentication state."""

    email: str
    account_id: str
    client_id: str
    topic: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    iot_endpoint: str | None = None
    iot_certificate: str | None = None
    iot_private_key: str | None = None
    bff_access_token: str | None = None
    bff_client_id: str | None = None
    bff_expires_at: datetime | None = None

    @classmethod
    def from_login_payload(
        cls, email: str, payload: dict[str, Any]
    ) -> AccountAuthDetails:
        """Create auth details from the login payload."""

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(payload["tokenExpireCycle"])
        )
        return cls(
            email=email,
            account_id=str(payload["accountId"]),
            client_id=payload["client"],
            topic=payload.get("topic", ""),
            access_token=payload["token"],
            refresh_token=payload["refreshToken"],
            expires_at=expires_at,
        )

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> AccountAuthDetails:
        """Create auth details from persisted storage."""

        return cls(
            email=data["email"],
            account_id=data["account_id"],
            client_id=data["client_id"],
            topic=data["topic"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            iot_endpoint=data.get("iot_endpoint"),
            iot_certificate=data.get("iot_certificate"),
            iot_private_key=data.get("iot_private_key"),
            bff_access_token=data.get("bff_access_token"),
            bff_client_id=data.get("bff_client_id"),
            bff_expires_at=(
                datetime.fromisoformat(data["bff_expires_at"])
                if data.get("bff_expires_at")
                else None
            ),
        )

    def as_storage(self) -> dict[str, Any]:
        """Serialize the auth details for storage."""

        return {
            "email": self.email,
            "account_id": self.account_id,
            "client_id": self.client_id,
            "topic": self.topic,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "iot_endpoint": self.iot_endpoint,
            "iot_certificate": self.iot_certificate,
            "iot_private_key": self.iot_private_key,
            "bff_access_token": self.bff_access_token,
            "bff_client_id": self.bff_client_id,
            "bff_expires_at": (
                self.bff_expires_at.isoformat()
                if self.bff_expires_at is not None
                else None
            ),
        }

    def should_refresh(self, now: datetime | None = None) -> bool:
        """Return True if the token should be refreshed."""

        if now is None:
            now = datetime.now(timezone.utc)
        return now >= (self.expires_at - REFRESH_OFFSET)

    def with_tokens(
        self, *, access_token: str, refresh_token: str, expires_in: int
    ) -> AccountAuthDetails:
        """Return a copy with updated token fields."""

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return replace(
            self,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

    def with_iot_data(
        self, *, endpoint: str, certificate: str, private_key: str
    ) -> AccountAuthDetails:
        """Return a copy populated with IoT credential data."""

        return replace(
            self,
            iot_endpoint=endpoint,
            iot_certificate=certificate,
            iot_private_key=private_key,
        )

    def with_bff_data(
        self,
        *,
        access_token: str,
        client_id: str,
        expires_in: int,
    ) -> AccountAuthDetails:
        """Return a copy populated with BFF credential data."""

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return replace(
            self,
            bff_access_token=access_token,
            bff_client_id=client_id,
            bff_expires_at=expires_at,
        )

    def as_iot_bundle(self) -> IoTBundle | None:
        """Expose an IoT bundle if certificate data is available."""

        if (
            self.iot_endpoint is None
            or self.iot_certificate is None
            or self.iot_private_key is None
        ):
            return None
        return IoTBundle(
            account_id=self.account_id,
            client_id=self.client_id,
            topic=self.topic,
            endpoint=self.iot_endpoint,
            certificate=self.iot_certificate,
            private_key=self.iot_private_key,
        )

    def as_bff_bundle(self) -> BffBundle | None:
        """Expose persisted BFF credentials if available."""

        if (
            self.bff_access_token is None
            or self.bff_client_id is None
            or self.bff_expires_at is None
        ):
            return None
        return BffBundle(
            access_token=self.bff_access_token,
            client_id=self.bff_client_id,
            expires_at=self.bff_expires_at,
        )

    def valid_bff_bundle(self, now: datetime | None = None) -> BffBundle | None:
        """Return the BFF bundle when it has not yet expired."""

        bundle = self.as_bff_bundle()
        if bundle is None:
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        if bundle.expires_at <= now:
            return None
        return bundle


def _generate_client_id() -> str:
    """Generate a Govee client identifier matching the upstream service."""

    millis = datetime.now(timezone.utc).microsecond // 1000
    seed = f"{uuid.uuid4()}{millis}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def _base_headers(client_id: str, client_type: str = CLIENT_TYPE) -> dict[str, str]:
    """Return the baseline headers expected by the Govee API."""

    return {
        "clientType": client_type,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "iotVersion": "0",
        "clientId": client_id,
        "User-Agent": USER_AGENT,
        "appVersion": APP_VERSION,
        "AppVersion": APP_VERSION,
    }


def _authenticated_headers(*, access_token: str, client_id: str) -> dict[str, str]:
    """Return headers for authenticated requests."""

    headers = _base_headers(client_id)
    headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _decode_p12_bundle(certificate_b64: str, password: str) -> tuple[str, str]:
    """Decode a P12 bundle into PEM certificate and private key."""

    data = base64.b64decode(certificate_b64)
    private_key, certificate, _extra = load_key_and_certificates(
        data, password.encode("utf-8")
    )
    if private_key is None or certificate is None:
        msg = "P12 bundle missing required certificate components"
        raise ValueError(msg)
    certificate_pem = certificate.public_bytes(Encoding.PEM).decode("utf-8").strip()
    private_key_pem = (
        private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        .decode("utf-8")
        .strip()
    )
    return certificate_pem, private_key_pem


async def _extract_response_payload(response: object) -> dict[str, Any]:
    """Coerce various test-friendly response shapes into a dict.

    Tests sometimes provide bare dicts or fake response objects instead of
    an ``httpx.Response``. This helper attempts to extract JSON-like payloads
    from common shapes and will await coroutine-returning helpers when
    encountered.
    """
    # Direct dict passthrough
    if isinstance(response, dict):
        return response

    # If the object exposes a .json() method, prefer to call it. It may
    # return a coroutine or a dict-like value.
    json_attr = getattr(response, "json", None)
    if callable(json_attr):
        try:
            result = json_attr()
        except TypeError:
            # Some test doubles implement async json() signature
            result = (
                await json_attr()
                if asyncio.iscoroutinefunction(json_attr)
                else json_attr()
            )
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, dict) else {}

    # Some fakes expose a .data attribute with the payload
    data_attr = getattr(response, "data", None)
    if isinstance(data_attr, dict):
        return data_attr
    if asyncio.iscoroutine(data_attr):
        data_attr = await data_attr
        if isinstance(data_attr, dict):
            return data_attr

    # Fallback: try to read .content (bytes/str) and parse JSON
    content = getattr(response, "content", None)
    if content is not None:
        if asyncio.iscoroutine(content):
            content = await content
        try:
            if isinstance(content, bytes | bytearray):
                import json as _json

                return _json.loads(content.decode())
            if isinstance(content, str):
                import json as _json

                return _json.loads(content)
        except Exception:
            return {}

    # Nothing we recognise — return empty dict so callers raise an appropriate
    # error when required keys are missing.
    return {}


async def _maybe_raise_for_status(response: object) -> None:
    """Invoke ``raise_for_status`` when provided by ``response``."""

    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        maybe = raise_for_status()
        if asyncio.iscoroutine(maybe):
            await maybe


class GoveeAuthManager:
    """Manage authentication lifecycle for the Govee Ultimate integration."""

    def __init__(
        self, hass: HomeAssistant, client: httpx.AsyncClient | None = None
    ) -> None:
        """Initialize the auth manager with Home Assistant and optional HTTP client.

        When `client` is None the manager will lazily obtain the helper client
        from `custom_components.govee.api._async_get_http_client` when a network
        operation is first performed. This keeps HTTP client creation logic in
        the API module while allowing tests to inject mock clients.
        """

        self._hass = hass
        self._client = client
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY, private=True)
        self._tokens: AccountAuthDetails | None = None
        self._store_lock = asyncio.Lock()

    async def _ensure_client(self) -> None:
        """Lazily obtain the HTTP client if not already provided."""

        if self._client is not None:
            return
        # Use the integration-level helper so tests that monkeypatch
        # `custom_components.govee._async_get_http_client` or inject a
        # runtime helper into the integration module are respected.
        from custom_components.govee import _async_get_http_client  # type: ignore

        self._client = await _async_get_http_client(self._hass)

    @property
    def tokens(self) -> AccountAuthDetails | None:
        """Return the current token details."""

        return self._tokens

    async def async_initialize(self) -> None:
        """Load persisted tokens from disk."""

        await self._migrate_legacy_storage()
        data = await self._store.async_load()
        if not data:
            return
        self._tokens = AccountAuthDetails.from_storage(data)

    async def async_login(self, email: str, password: str) -> AccountAuthDetails:
        """Login with the provided credentials and persist the resulting tokens."""
        await self._ensure_client()
        assert self._client is not None
        client_id = _generate_client_id()
        try:
            response = await self._client.post(
                LOGIN_ENDPOINT,
                json={"email": email, "password": password, "client": client_id},
                headers=_base_headers(client_id),
            )
            # Some test doubles don't implement raise_for_status; guard it.
            await _maybe_raise_for_status(response)
        except httpx.HTTPError:
            await self._clear_tokens()
            raise

        payload = await _extract_response_payload(response)
        login_data = payload.get("client")
        if not isinstance(login_data, dict):
            msg = "Invalid login response"
            raise TypeError(msg)
        tokens = AccountAuthDetails.from_login_payload(email, login_data)
        tokens = await self._fetch_bff_credentials(tokens, email, password)
        tokens = await self._fetch_iot_credentials(tokens)
        return await self._store_tokens(tokens)

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""

        if self._tokens is None:
            raise RuntimeError("No credentials loaded")

        if self._tokens.should_refresh():
            await self._refresh_tokens()

        return self._tokens.access_token

    async def async_get_iot_bundle(self) -> IoTBundle | None:
        """Expose persisted IoT credentials, if available."""

        if self._tokens is None:
            return None
        return self._tokens.as_iot_bundle()

    async def async_get_bff_bundle(self) -> BffBundle | None:
        """Expose persisted community (BFF) credentials."""

        if self._tokens is None:
            return None
        return self._tokens.valid_bff_bundle()

    async def _refresh_tokens(self) -> AccountAuthDetails:
        """Refresh the stored token using the refresh token."""

        if self._tokens is None:
            raise RuntimeError("No credentials to refresh")
        await self._ensure_client()
        assert self._client is not None
        try:
            response = await self._client.post(
                REFRESH_ENDPOINT,
                json={"refreshToken": self._tokens.refresh_token},
                headers=self._headers_for_tokens(self._tokens),
            )
            await _maybe_raise_for_status(response)
        except httpx.HTTPError:
            await self._clear_tokens()
            raise
        payload = await _extract_response_payload(response)
        refresh_data = payload.get("data")
        if not isinstance(refresh_data, dict):
            msg = "Invalid refresh response"
            raise TypeError(msg)
        tokens = self._tokens.with_tokens(
            access_token=refresh_data["token"],
            refresh_token=refresh_data["refreshToken"],
            expires_in=int(refresh_data["tokenExpireCycle"]),
        )
        tokens = await self._fetch_iot_credentials(tokens)
        return await self._store_tokens(tokens)

    async def _fetch_iot_credentials(
        self, tokens: AccountAuthDetails
    ) -> AccountAuthDetails:
        """Retrieve and decode IoT credentials for the account."""
        await self._ensure_client()
        assert self._client is not None
        response = await self._client.get(
            IOT_KEY_ENDPOINT,
            headers=self._headers_for_tokens(tokens),
        )
        await _maybe_raise_for_status(response)
        payload = await _extract_response_payload(response)
        data = payload.get("data")
        if not isinstance(data, dict):
            msg = "Invalid IoT credential payload"
            raise TypeError(msg)
        certificate_b64 = data.get("p12")
        password = data.get("p12Pass")
        endpoint = data.get("endpoint") or data.get("brokerUrl")
        if not certificate_b64 or not password or not endpoint:
            msg = "Incomplete IoT credential payload"
            raise TypeError(msg)
        certificate, private_key = _decode_p12_bundle(certificate_b64, password)
        return tokens.with_iot_data(
            endpoint=endpoint,
            certificate=certificate,
            private_key=private_key,
        )

    async def _fetch_bff_credentials(
        self, tokens: AccountAuthDetails, email: str, password: str
    ) -> AccountAuthDetails:
        """Retrieve BFF OAuth credentials for the community API."""

        await self._ensure_client()
        assert self._client is not None
        try:
            response = await self._client.post(
                COMMUNITY_LOGIN_ENDPOINT,
                json={"email": email, "password": password},
                headers=_base_headers(tokens.client_id),
            )
            await _maybe_raise_for_status(response)
        except httpx.HTTPError:
            return tokens

        payload = await _extract_response_payload(response)
        data = payload.get("data")
        if not isinstance(data, dict):
            return tokens

        access_token = data.get("accessToken")
        client_id = data.get("clientId")
        expires_in = data.get("expiresIn")
        if (
            not isinstance(access_token, str)
            or not isinstance(client_id, str)
            or expires_in is None
        ):
            return tokens
        try:
            expires = int(expires_in)
        except (TypeError, ValueError):
            return tokens

        return tokens.with_bff_data(
            access_token=access_token,
            client_id=client_id,
            expires_in=expires,
        )

    async def _persist_tokens(self, tokens: AccountAuthDetails) -> None:
        """Persist tokens via the storage helper."""

        async with self._store_lock:
            await self._store.async_save(tokens.as_storage())

    async def _store_tokens(self, tokens: AccountAuthDetails) -> AccountAuthDetails:
        """Persist and cache the provided tokens."""

        await self._persist_tokens(tokens)
        self._tokens = tokens
        return tokens

    @staticmethod
    def _headers_for_tokens(tokens: AccountAuthDetails) -> dict[str, str]:
        """Return authenticated headers for ``tokens``."""

        return _authenticated_headers(
            access_token=tokens.access_token, client_id=tokens.client_id
        )

    async def _clear_tokens(self) -> None:
        """Remove any cached tokens from memory and disk."""

        self._tokens = None
        async with self._store_lock:
            await self._store.async_remove()

    async def _migrate_legacy_storage(self) -> None:
        """Migrate legacy storage files written under the previous domain name."""

        await async_migrate_storage_file(self._hass, LEGACY_STORAGE_KEY, STORAGE_KEY)
