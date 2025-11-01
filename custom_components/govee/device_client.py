"""Client for retrieving Govee devices from the REST API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from homeassistant.helpers.storage import Store

from .auth import GoveeAuthManager
from .storage import async_migrate_storage_file

DEVICE_LIST_URL = "https://app2.govee.com/device/rest/devices/v1/list"
DEVICE_STORE_KEY = "govee_devices"
LEGACY_DEVICE_STORE_KEY = "govee_ultimate_devices"
DEVICE_STORE_VERSION = 1


class DeviceListError(RuntimeError):
    """Raised when the REST API returns an invalid payload."""


@dataclass(frozen=True)
class Measurement:
    """Normalized measurement data from the device."""

    min: float | None = None
    max: float | None = None
    calibration: float | None = None
    warning: bool | None = None
    current: float | None = None


@dataclass(frozen=True)
class DeviceState:
    """Representation of current device state."""

    online: bool | None = None
    is_on: bool | None = None
    last_report_time: int | None = None
    water_shortage: bool | None = None
    boil_water_complete_notification: bool | None = None
    complete_notification: bool | None = None
    auto_shutdown: bool | None = None
    filter_expired: bool | None = None
    play_state: bool | None = None
    battery: int | None = None
    temperature: Measurement | None = None
    humidity: Measurement | None = None


@dataclass(frozen=True)
class WiFiInfo:
    """Wi-Fi metadata for a device."""

    name: str | None
    mac: str
    hardware_version: str
    software_version: str


@dataclass(frozen=True)
class BluetoothInfo:
    """Bluetooth metadata for a device."""

    name: str
    mac: str


@dataclass(frozen=True)
class GoveeDevice:
    """Normalized device representation."""

    id: str
    name: str
    model: str
    group_id: int
    pact_type: int
    pact_code: int
    goods_type: int
    ic: int
    hardware_version: str
    software_version: str
    iot_topic: str | None
    wifi: WiFiInfo | None
    bluetooth: BluetoothInfo | None
    state: DeviceState

    def as_storage(self) -> dict[str, Any]:
        """Serialize to a storage-friendly dictionary."""

        return asdict(self)

    @classmethod
    def from_storage(cls, data: dict[str, Any]) -> GoveeDevice:
        """Hydrate a device from stored JSON."""

        wifi = data.get("wifi")
        bluetooth = data.get("bluetooth")
        state = data.get("state") or {}
        return cls(
            id=data["id"],
            name=data["name"],
            model=data["model"],
            group_id=data["group_id"],
            pact_type=data["pact_type"],
            pact_code=data["pact_code"],
            goods_type=data["goods_type"],
            ic=data["ic"],
            hardware_version=data["hardware_version"],
            software_version=data["software_version"],
            iot_topic=data.get("iot_topic"),
            wifi=WiFiInfo(**wifi) if wifi else None,
            bluetooth=BluetoothInfo(**bluetooth) if bluetooth else None,
            state=DeviceState(
                online=state.get("online"),
                is_on=state.get("is_on"),
                last_report_time=state.get("last_report_time"),
                water_shortage=state.get("water_shortage"),
                boil_water_complete_notification=state.get(
                    "boil_water_complete_notification"
                ),
                complete_notification=state.get("complete_notification"),
                auto_shutdown=state.get("auto_shutdown"),
                filter_expired=state.get("filter_expired"),
                play_state=state.get("play_state"),
                battery=state.get("battery"),
                temperature=_measurement_from_storage(state.get("temperature")),
                humidity=_measurement_from_storage(state.get("humidity")),
            ),
        )


class DeviceListClient:
    """Retrieve and normalize devices from the REST API."""

    def __init__(
        self,
        hass: Any,
        client: httpx.AsyncClient,
        auth: GoveeAuthManager,
    ) -> None:
        """Bind Home Assistant context, HTTP client, and auth manager for REST operations."""

        self._hass = hass
        self._client = client
        self._auth = auth
        self._store = Store(hass, DEVICE_STORE_VERSION, DEVICE_STORE_KEY, private=True)

    async def async_fetch_devices(self) -> list[GoveeDevice]:
        """Fetch the device list, falling back to cached data when needed."""

        await self._migrate_legacy_storage()
        try:
            payload = await self._request_payload()
            devices = [
                self._normalize_device(item) for item in payload.get("devices", [])
            ]
            await self._store.async_save(
                {"devices": [device.as_storage() for device in devices]}
            )
            return devices
        except (httpx.HTTPError, DeviceListError):
            cached = await self._store.async_load()
            if not cached:
                raise
            return [
                GoveeDevice.from_storage(item) for item in cached.get("devices", [])
            ]

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return metadata payloads compatible with ``DeviceMetadata``."""

        devices = await self.async_fetch_devices()
        return [self._adapt_device(device) for device in devices]

    async def _migrate_legacy_storage(self) -> None:
        """Migrate persisted device storage files from the legacy namespace."""

        await async_migrate_storage_file(
            self._hass, LEGACY_DEVICE_STORE_KEY, DEVICE_STORE_KEY
        )

    async def _request_payload(self) -> dict[str, Any]:
        """Request the raw JSON payload from the REST API."""

        token = await self._auth.async_get_access_token()
        response = await self._client.post(
            DEVICE_LIST_URL,
            json={},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != 200:
            raise DeviceListError(f"Unexpected status {payload.get('status')}")
        return payload

    def _normalize_device(self, payload: dict[str, Any]) -> GoveeDevice:
        """Convert a raw payload entry into a dataclass."""

        ext = payload.get("deviceExt", {})
        settings = ext.get("deviceSettings", {})
        data = ext.get("deviceData", {})
        return GoveeDevice(
            id=payload["device"],
            name=payload.get("deviceName", ""),
            model=payload.get("sku", ""),
            group_id=payload.get("groupId", 0),
            pact_type=payload.get("pactType", 0),
            pact_code=payload.get("pactCode", 0),
            goods_type=payload.get("goodsType", 0),
            ic=settings.get("ic", 0),
            hardware_version=settings.get("versionHard", ""),
            software_version=settings.get("versionSoft", ""),
            iot_topic=settings.get("topic"),
            wifi=self._parse_wifi(settings),
            bluetooth=self._parse_bluetooth(settings),
            state=self._parse_state(settings, data),
        )

    def _adapt_device(self, device: GoveeDevice) -> dict[str, Any]:
        """Convert a ``GoveeDevice`` into coordinator metadata payload."""

        channels: dict[str, dict[str, Any]] = {}
        if isinstance(device.iot_topic, str) and device.iot_topic:
            channels["iot"] = {"topic": device.iot_topic}
        if device.bluetooth is not None:
            channels["ble"] = {"mac": device.bluetooth.mac}

        name = device.name or device.model

        payload = {
            "device_id": device.id,
            "model": device.model,
            "sku": device.model,
            "category": "",
            "category_group": "",
            "device_name": name,
            "manufacturer": "Govee",
            "channels": channels,
        }

        for alias, key in (
            ("deviceId", "device_id"),
            ("deviceModel", "model"),
            ("deviceSku", "sku"),
            ("categoryGroup", "category_group"),
            ("category_group_name", "category_group"),
            ("deviceName", "device_name"),
        ):
            payload[alias] = payload[key]

        return payload

    def _parse_wifi(self, settings: dict[str, Any]) -> WiFiInfo | None:
        if not (
            settings.get("wifiMac")
            and settings.get("wifiHardVersion")
            and settings.get("wifiSoftVersion")
        ):
            return None
        return WiFiInfo(
            name=settings.get("wifiName"),
            mac=settings["wifiMac"],
            hardware_version=settings["wifiHardVersion"],
            software_version=settings["wifiSoftVersion"],
        )

    def _parse_bluetooth(self, settings: dict[str, Any]) -> BluetoothInfo | None:
        if not (settings.get("address") and settings.get("bleName")):
            return None
        return BluetoothInfo(name=settings["bleName"], mac=settings["address"])

    def _parse_state(
        self, settings: dict[str, Any], data: dict[str, Any]
    ) -> DeviceState:
        return DeviceState(
            online=_coerce_bool(data.get("online")),
            is_on=_coerce_bool(data.get("isOnOff")),
            last_report_time=data.get("lastTime"),
            water_shortage=_coerce_bool(settings.get("waterShortageOnOff")),
            boil_water_complete_notification=_coerce_bool(
                settings.get("boilWaterCompletedNotiOnOff")
            ),
            complete_notification=_coerce_bool(settings.get("completionNotiOnOff")),
            auto_shutdown=_coerce_bool(settings.get("autoShutDownOnOff")),
            filter_expired=_coerce_bool(settings.get("filterExpireOnOff")),
            play_state=_coerce_bool(settings.get("playState")),
            battery=settings.get("battery"),
            temperature=_measurement_from_values(
                settings.get("temMin"),
                settings.get("temMax"),
                settings.get("temCali"),
                settings.get("temWarning"),
                data.get("tem"),
            ),
            humidity=_measurement_from_values(
                settings.get("humMin"),
                settings.get("humMax"),
                settings.get("humCali"),
                settings.get("humWarning"),
                data.get("hum"),
            ),
        )


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None


def _measurement_from_values(
    min_value: Any,
    max_value: Any,
    calibration: Any,
    warning: Any,
    current_value: Any,
) -> Measurement | None:
    if min_value is None or max_value is None:
        return None
    return Measurement(
        min=_safe_divide(min_value),
        max=_safe_divide(max_value),
        calibration=_coerce_float(calibration),
        warning=_coerce_bool(warning),
        current=_safe_divide(current_value),
    )


def _safe_divide(value: Any, divisor: float = 100.0) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _measurement_from_storage(data: dict[str, Any] | None) -> Measurement | None:
    if not data:
        return None
    return Measurement(**data)
