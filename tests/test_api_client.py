"""Unit tests for the GoveeAPIClient facade."""

from __future__ import annotations

import asyncio
from typing import Any

from custom_components.govee.api import GoveeAPIClient


class DummyDeviceClient:
    """A device client implementing sync and async publish methods for testing."""

    def __init__(self) -> None:
        """Initialise storage for captured calls."""
        self.iot_called = []
        self.ble_called = []

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return a single mocked device payload asynchronously."""
        await asyncio.sleep(0)
        return [{"device_id": "d1", "model": "H7141", "channels": {}}]

    async def async_fetch_devices(self) -> list[Any]:
        """Return a mocked fetch result asynchronously."""
        await asyncio.sleep(0)
        return [object()]

    async def async_publish_iot_command(
        self, device_id: str, channel_info: dict, command: dict
    ) -> None:
        """Capture IoT publish calls for assertions."""
        self.iot_called.append((device_id, dict(channel_info), dict(command)))

    def async_publish_ble_command(
        self, device_id: str, channel_info: dict, command: dict
    ) -> None:
        """Publish BLE command synchronously."""
        # Intentionally synchronous to verify facade handles non-coroutine delegates
        self.ble_called.append((device_id, dict(channel_info), dict(command)))


class MinimalDeviceClient:
    """A device client that only supports discovery, no publish methods."""

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return an empty list of devices for minimal client tests."""
        await asyncio.sleep(0)
        return []


async def test_async_get_devices_and_fetch_devices_proxied(monkeypatch) -> None:
    """async_get_devices and async_fetch_devices should proxy to the underlying client."""
    dummy = DummyDeviceClient()

    # Monkeypatch DeviceListClient used in GoveeAPIClient to our dummy
    import custom_components.govee.device_client as device_client_mod

    monkeypatch.setattr(
        device_client_mod, "DeviceListClient", lambda hass, client, auth: dummy
    )

    client = GoveeAPIClient(hass=None, auth=None)

    devices = await client.async_get_devices()
    assert isinstance(devices, list)
    fetched = await client.async_fetch_devices()
    assert isinstance(fetched, list)


async def test_publish_delegation_async_and_sync(monkeypatch) -> None:
    """Verify async and sync publish delegates are executed by the facade."""
    dummy = DummyDeviceClient()
    import custom_components.govee.device_client as device_client_mod

    monkeypatch.setattr(
        device_client_mod, "DeviceListClient", lambda hass, client, auth: dummy
    )

    client = GoveeAPIClient(hass=None, auth=None)

    await client.async_publish_iot_command("d1", {"topic": "t"}, {"cmd": "v"})
    # BLE delegate is synchronous; facade should still accept and execute it
    await client.async_publish_ble_command("d1", {"mac": "m"}, {"cmd": "v2"})

    assert dummy.iot_called == [("d1", {"topic": "t"}, {"cmd": "v"})]
    assert dummy.ble_called == [("d1", {"mac": "m"}, {"cmd": "v2"})]


async def test_publish_not_implemented_raises(monkeypatch) -> None:
    """When the underlying client lacks publish methods, NotImplementedError is raised."""
    minimal = MinimalDeviceClient()
    import custom_components.govee.device_client as device_client_mod

    monkeypatch.setattr(
        device_client_mod, "DeviceListClient", lambda hass, client, auth: minimal
    )

    client = GoveeAPIClient(hass=None, auth=None)

    try:
        await client.async_publish_iot_command("d1", {}, {})
    except NotImplementedError:
        pass
    else:
        raise AssertionError("Expected NotImplementedError for missing iot publish")
