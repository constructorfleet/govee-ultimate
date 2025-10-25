"""Tests for the auth manager."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from custom_components.govee_ultimate.auth import GoveeAuthManager, TokenDetails


class StubHass:
    """Minimal hass stub implementing storage API requirements."""

    def __init__(self, loop: asyncio.AbstractEventLoop, config_dir: str) -> None:
        self.loop = loop
        self.config = SimpleNamespace(config_dir=config_dir)

    async def async_add_executor_job(self, func, *args):  # type: ignore[no-untyped-def]
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


@pytest.mark.asyncio
async def test_auth_manager_login_saves_tokens(tmp_path_factory, request):
    """Login should persist tokens via the storage helper."""

    tmp_path = tmp_path_factory.mktemp("hass")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload == {"email": "user@example.com", "password": "secret"}
        return httpx.Response(
            200,
            json={
                "client": {"clientType": "app", "clientId": "abc"},
                "login": {
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "expiresIn": 120,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app2.govee.com")

    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    tokens = await manager.async_login("user@example.com", "secret")

    assert tokens.access_token == "access-token"
    assert tokens.refresh_token == "refresh-token"
    assert tokens.expires_at > datetime.now(timezone.utc)

    storage_file = tmp_path / ".storage" / "govee_ultimate_auth"
    assert json.loads(storage_file.read_text()) == {
        "email": "user@example.com",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": tokens.expires_at.isoformat(),
    }

    reload_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    reload_manager = GoveeAuthManager(hass, reload_client)
    await reload_manager.async_initialize()

    assert reload_manager.tokens == tokens

    await client.aclose()
    await reload_client.aclose()


@pytest.mark.asyncio
async def test_auth_manager_refreshes_tokens(tmp_path_factory, request):
    """Stored tokens nearing expiry should be refreshed and persisted."""

    tmp_path = tmp_path_factory.mktemp("hass_refresh")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    expiring = TokenDetails(
        email="user@example.com",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
    )

    storage_file = tmp_path / ".storage" / "govee_ultimate_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text(
        json.dumps(
            {
                "email": expiring.email,
                "access_token": expiring.access_token,
                "refresh_token": expiring.refresh_token,
                "expires_at": expiring.expires_at.isoformat(),
            }
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/account/refresh-token"
        payload = json.loads(request.content.decode())
        assert payload == {"refreshToken": "old-refresh"}
        return httpx.Response(
            200,
            json={
                "login": {
                    "accessToken": "new-access",
                    "refreshToken": "new-refresh",
                    "expiresIn": 3600,
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app2.govee.com")
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    token = await manager.async_get_access_token()

    assert token == "new-access"
    assert manager.tokens is not None
    assert manager.tokens.access_token == "new-access"

    updated = json.loads(storage_file.read_text())
    assert updated["access_token"] == "new-access"
    assert updated["refresh_token"] == "new-refresh"

    await client.aclose()


@pytest.mark.asyncio
async def test_auth_manager_login_failure(tmp_path_factory, request):
    """A login failure should bubble up and not persist credentials."""

    tmp_path = tmp_path_factory.mktemp("hass_login_fail")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    existing = TokenDetails(
        email="user@example.com",
        access_token="cached-access",
        refresh_token="cached-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    storage_file = tmp_path / ".storage" / "govee_ultimate_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text(
        json.dumps(
            {
                "email": existing.email,
                "access_token": existing.access_token,
                "refresh_token": existing.refresh_token,
                "expires_at": existing.expires_at.isoformat(),
            }
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app2.govee.com")
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    assert manager.tokens is not None  # loaded cached tokens

    with pytest.raises(httpx.HTTPStatusError):
        await manager.async_login("user@example.com", "bad")

    assert manager.tokens is None
    assert not storage_file.exists()


@pytest.mark.asyncio
async def test_auth_manager_refresh_failure_clears_state(tmp_path_factory, request):
    """A refresh error should clear stored credentials."""

    tmp_path = tmp_path_factory.mktemp("hass_refresh_fail")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))

    expiring = TokenDetails(
        email="user@example.com",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=10),
    )

    storage_file = tmp_path / ".storage" / "govee_ultimate_auth"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_text(json.dumps(expiring.as_storage()))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "expired"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app2.govee.com")
    manager = GoveeAuthManager(hass, client)
    await manager.async_initialize()

    with pytest.raises(httpx.HTTPStatusError):
        await manager.async_get_access_token()

    assert manager.tokens is None
    assert not storage_file.exists()

    await client.aclose()

    await client.aclose()
