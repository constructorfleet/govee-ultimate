"""Standalone test runner for the GoveeAPIClient tests.

This script mirrors the logic in tests/test_api_client.py but runs without pytest
so we can reproduce failures and tracebacks while debugging the refactor.
"""

import asyncio
import sys
from typing import Any

from custom_components.govee.api import GoveeAPIClient


class DummyDeviceClient:
    def __init__(self) -> None:
        self.iot_called = []
        self.ble_called = []

    async def async_get_devices(self) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return [{"device_id": "d1", "model": "H7141", "channels": {}}]

    async def async_fetch_devices(self) -> list[Any]:
        await asyncio.sleep(0)
        return [object()]

    async def async_publish_iot_command(
        self, device_id: str, channel_info: dict, command: dict
    ) -> None:
        self.iot_called.append((device_id, dict(channel_info), dict(command)))

    def async_publish_ble_command(
        self, device_id: str, channel_info: dict, command: dict
    ) -> None:
        self.ble_called.append((device_id, dict(channel_info), dict(command)))


class MinimalDeviceClient:
    async def async_get_devices(self) -> list[dict[str, Any]]:
        await asyncio.sleep(0)
        return []


async def run_tests() -> int:
    failures = 0

    # Test 1: proxying get/fetch
    try:
        dummy = DummyDeviceClient()
        import custom_components.govee.device_client as device_client_mod

        device_client_mod.DeviceListClient = lambda hass, client, auth: dummy

        client = GoveeAPIClient(hass=None, auth=None)

        devices = await client.async_get_devices()
        assert isinstance(devices, list), "async_get_devices did not return a list"
        fetched = await client.async_fetch_devices()
        assert isinstance(fetched, list), "async_fetch_devices did not return a list"

    except Exception as exc:  # pragma: no cover - expose failures
        failures += 1

    # Test 2: publish delegation
    try:
        dummy = DummyDeviceClient()
        import custom_components.govee.device_client as device_client_mod

        device_client_mod.DeviceListClient = lambda hass, client, auth: dummy

        client = GoveeAPIClient(hass=None, auth=None)

        await client.async_publish_iot_command("d1", {"topic": "t"}, {"cmd": "v"})
        await client.async_publish_ble_command("d1", {"mac": "m"}, {"cmd": "v2"})

        assert dummy.iot_called == [
            ("d1", {"topic": "t"}, {"cmd": "v"})
        ], f"iot_called unexpected: {dummy.iot_called}"
        assert dummy.ble_called == [
            ("d1", {"mac": "m"}, {"cmd": "v2"})
        ], f"ble_called unexpected: {dummy.ble_called}"

    except Exception as exc:
        failures += 1

    # Test 3: missing publish raises
    try:
        minimal = MinimalDeviceClient()
        import custom_components.govee.device_client as device_client_mod

        device_client_mod.DeviceListClient = lambda hass, client, auth: minimal

        client = GoveeAPIClient(hass=None, auth=None)

        try:
            await client.async_publish_iot_command("d1", {}, {})
        except NotImplementedError:
            pass
        else:
            raise AssertionError("Expected NotImplementedError for missing iot publish")
    except Exception as exc:
        failures += 1

    return failures


if __name__ == "__main__":
    fail_count = asyncio.run(run_tests())
    if fail_count:
        sys.exit(1)
    sys.exit(0)
