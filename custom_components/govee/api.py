"""High-level API client for the Govee Ultimate integration.

This module provides a small facade, `GoveeAPIClient`, which centralises
API-facing operations and composes the existing `DeviceListClient`.

The implementation intentionally proxies device-list related calls to the
existing `DeviceListClient` when available and will delegate publish
operations to the underlying client if it exposes the expected methods.
This keeps the refactor low-risk while providing a single place to add
REST/command implementations later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import httpx

from homeassistant.core import HomeAssistant
import homeassistant.helpers.httpx_client as httpx_client

from . import device_client

API_BASE_URL = "https://app2.govee.com"


def _create_http_client() -> Any:
    """Return an httpx async client configured for the REST API."""

    if httpx is None:
        msg = "httpx is required for the Govee Ultimate integration"
        raise RuntimeError(msg)
    return httpx.AsyncClient(base_url=API_BASE_URL)


class _BaseUrlAsyncClient(httpx.AsyncClient):
    """Wrap an async client to ensure relative URLs resolve against the base URL."""

    def __init__(self, client: httpx.AsyncClient, base_url: httpx.URL | str) -> None:
        self._client = client
        self._base_url = httpx.URL(base_url) if httpx is not None else base_url

    @property
    def base_url(self) -> Any:
        return self._base_url

    def _prepare_url(self, url: httpx.URL | str) -> httpx.URL | str:
        if httpx is None:
            if isinstance(url, str) and url.startswith("/"):
                return f"{self._base_url}{url}"
            return url
        return httpx.URL(url, base_url=self._base_url)

    async def request(
        self, method: str, url: httpx.URL | str, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._client.request(
            method, self._prepare_url(url), *args, **kwargs
        )

    async def post(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        return await self.request("POST", url, *args, **kwargs)

    async def get(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        return await self.request("GET", url, *args, **kwargs)

    async def aclose(self) -> Any:
        return await self._client.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


async def _async_get_http_client(hass: HomeAssistant) -> _BaseUrlAsyncClient:
    """Return an HTTP client, preferring the Home Assistant helper when available."""

    if httpx_client is not None:
        getter = getattr(httpx_client, "get_async_client", None)
        if callable(getter):
            client = getter(hass, verify_ssl=True)
            if asyncio.iscoroutine(client):
                client = await client
            if isinstance(client, _BaseUrlAsyncClient):
                return client
            if httpx is not None:
                base_url = getattr(client, "base_url", None)
                if not base_url or str(base_url) in {"", "/"}:
                    return _BaseUrlAsyncClient(client, API_BASE_URL)
            return client

    return _create_http_client()


class GoveeAPIClient:
    """Facade for API operations used by the integration.

    Currently this is a thin wrapper around `DeviceListClient` to centralise
    the surface the rest of the integration depends upon. It will call
    into the composed device client for device discovery and, when present,
    defer publish operations to methods implemented by that client.
    """

    def __init__(self, hass: Any, auth: Any) -> None:
        """Create the API facade and delay HTTP client construction.

        The HTTP client and underlying DeviceListClient are created lazily on
        first use so the API module owns the creation logic via
        :func:`_async_get_http_client`.
        """

        self._hass = hass
        self._auth = auth
        self._device_client: Any | None = None
        self._http_client: Any | None = None

    @property
    def http_client(self) -> Any | None:
        """Expose the underlying HTTP client when available (tests expect this)."""

        return self._http_client

    async def _ensure_client(self) -> None:
        """Ensure the HTTP client and device client are constructed."""

        if self._device_client is not None:
            return
        # Acquire an http client using the integration-level helper so the
        # logic for preference (Home Assistant helper vs direct httpx) lives
        # in one place.
        self._http_client = await _async_get_http_client(self._hass)
        # Resolve DeviceListClient from the device_client module so tests can
        # monkeypatch `device_client.DeviceListClient` before creating the
        # facade. This mirrors how callers import the module in tests.
        # Allow tests to override which device client class is used by
        # monkeypatching `_get_device_client_class` in the integration
        # module. This mirrors test usage in the suite.
        device_client_cls = (
            getattr(__import__("custom_components.govee"), "_get_device_client_class", None)
            or getattr(device_client, "DeviceListClient")
        )
        self._device_client = device_client_cls(self._hass, self._http_client, self._auth)

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return the device metadata payloads expected by the coordinator.

        This proxies to `DeviceListClient.async_get_devices`.
        """

        await self._ensure_client()
        assert self._device_client is not None
        return await self._device_client.async_get_devices()

    async def async_fetch_devices(self) -> list[Any]:
        """Proxy fetch operation to underlying device client."""
        await self._ensure_client()
        assert self._device_client is not None
        return await self._device_client.async_fetch_devices()

    async def async_publish_iot_command(
        self, device_id: str, channel_info: dict[str, Any], command: dict[str, Any]
    ) -> None:
        """Attempt to publish an IoT command via the underlying client.

        If the composed device client implements `async_publish_iot_command`,
        delegate to it. Otherwise raise NotImplementedError to make the
        missing behaviour explicit for future implementation.
        """

        await self._ensure_client()
        assert self._device_client is not None
        impl = getattr(self._device_client, "async_publish_iot_command", None)
        if callable(impl):
            result = impl(device_id, channel_info, command)
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result  # type: ignore[arg-type]
            return None
        raise NotImplementedError("IoT publish not implemented for this client")

    async def async_publish_ble_command(
        self, device_id: str, channel_info: dict[str, Any], command: dict[str, Any]
    ) -> None:
        """Attempt to publish a BLE command via the underlying client.

        Behaviour mirrors `async_publish_iot_command`.
        """

        await self._ensure_client()
        assert self._device_client is not None
        impl = getattr(self._device_client, "async_publish_ble_command", None)
        if callable(impl):
            result = impl(device_id, channel_info, command)
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result  # type: ignore[arg-type]
            return None
        raise NotImplementedError("BLE publish not implemented for this client")

    async def async_close(self) -> None:
        """Close any owned resources such as the HTTP client."""

        if self._http_client is not None:
            close = getattr(self._http_client, "aclose", None)
            if close is not None:
                result = close()
                if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                    await result  # type: ignore[arg-type]
            self._http_client = None
        self._device_client = None
