"""Tests for the device list client."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from custom_components.govee_ultimate.device_client import DeviceListClient


class StubHass:
    """Minimal hass stub implementing storage API requirements."""

    def __init__(self, loop: asyncio.AbstractEventLoop, config_dir: str) -> None:
        self.loop = loop
        self.config = SimpleNamespace(config_dir=config_dir)

    async def async_add_executor_job(self, func, *args):  # type: ignore[no-untyped-def]
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)


class StubAuthManager:
    """Auth stub returning a static access token."""

    def __init__(self, token: str = "access-token") -> None:
        self.token = token

    async def async_get_access_token(self) -> str:
        return self.token


@pytest.mark.asyncio
async def test_device_list_client_fetches_and_persists(tmp_path_factory, request):
    """Successful fetch should normalize devices and persist them for reuse."""

    tmp_path = tmp_path_factory.mktemp("devices")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))
    auth = StubAuthManager()

    response_payload = {
        "status": 200,
        "message": "ok",
        "devices": [
            {
                "device": "AA:BB:CC",
                "deviceName": "Test Device",
                "sku": "H1234",
                "pactCode": 1,
                "pactType": 2,
                "goodsType": 3,
                "groupId": 4,
                "iotServer": "us",
                "deviceExt": {
                    "deviceSettings": {
                        "device": "AA:BB:CC",
                        "deviceName": "Test Device",
                        "sku": "H1234",
                        "versionSoft": "1.2.3",
                        "versionHard": "2.3.4",
                        "wifiName": "MyWiFi",
                        "wifiMac": "11:22:33",
                        "wifiSoftVersion": "1.0.0",
                        "wifiHardVersion": "1.0.1",
                        "address": "AA:BB:CC:DD",
                        "bleName": "BLE Device",
                        "ic": 42,
                        "pactType": 2,
                        "pactCode": 1,
                        "waterShortageOnOff": 1,
                        "boilWaterCompletedNotiOnOff": 0,
                        "completionNotiOnOff": 1,
                        "autoShutDownOnOff": 0,
                        "filterExpireOnOff": 0,
                        "playState": 1,
                        "battery": 80,
                        "temMin": 1500,
                        "temMax": 2800,
                        "temCali": 5,
                        "temWarning": 1,
                        "humMin": 3000,
                        "humMax": 5000,
                        "humCali": 2,
                        "humWarning": 0,
                        "topic": "iot/topic",
                    },
                    "deviceData": {
                        "online": 1,
                        "isOnOff": 1,
                        "lastTime": 1700000000,
                        "tem": 2000,
                        "hum": 4500,
                    },
                    "deviceResources": {
                        "skuImageUrl": "https://example.com/image.png",
                    },
                },
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer access-token"
        return httpx.Response(200, json=response_payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app2.govee.com")
    device_client = DeviceListClient(hass, client, auth)

    devices = await device_client.async_fetch_devices()

    assert len(devices) == 1
    device = devices[0]
    assert device.id == "AA:BB:CC"
    assert device.name == "Test Device"
    assert device.model == "H1234"
    assert device.hardware_version == "2.3.4"
    assert device.software_version == "1.2.3"
    assert device.wifi is not None and device.wifi.mac == "11:22:33"
    assert device.bluetooth is not None and device.bluetooth.mac == "AA:BB:CC:DD"
    assert device.state.online is True
    assert device.state.temperature is not None
    assert device.state.temperature.min == pytest.approx(15.0)
    assert device.state.temperature.max == pytest.approx(28.0)

    storage_file = tmp_path / ".storage" / "govee_ultimate_devices"
    saved = json.loads(storage_file.read_text())
    assert saved["devices"][0]["id"] == "AA:BB:CC"
    assert saved["devices"][0]["state"]["online"] is True

    await client.aclose()


@pytest.mark.asyncio
async def test_device_list_client_uses_fallback(tmp_path_factory, request):
    """If the REST call fails the client should fall back to cached data."""

    tmp_path = tmp_path_factory.mktemp("devices_fallback")
    loop = asyncio.get_running_loop()
    hass = StubHass(loop, str(tmp_path))
    auth = StubAuthManager()

    payload = {
        "status": 200,
        "message": "ok",
        "devices": [
            {
                "device": "AA:BB:CC",
                "deviceName": "Cached Device",
                "sku": "H1234",
                "pactCode": 1,
                "pactType": 2,
                "goodsType": 3,
                "groupId": 4,
                "deviceExt": {
                    "deviceSettings": {
                        "versionSoft": "1.0.0",
                        "versionHard": "1.0.1",
                        "ic": 1,
                    },
                    "deviceData": {},
                },
            }
        ],
    }

    success_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        base_url="https://app2.govee.com",
    )
    priming_client = DeviceListClient(hass, success_client, auth)
    await priming_client.async_fetch_devices()
    await success_client.aclose()

    failure_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500, json={"status": 500})),
        base_url="https://app2.govee.com",
    )
    device_client = DeviceListClient(hass, failure_client, auth)

    devices = await device_client.async_fetch_devices()

    assert len(devices) == 1
    assert devices[0].name == "Cached Device"

    await failure_client.aclose()
