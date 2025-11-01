"""Integration tests for the coordinator/service layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Callable
from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest

if "homeassistant.helpers.update_coordinator" not in __import__("sys").modules:
    import sys

    homeassistant = ModuleType("homeassistant")
    helpers = ModuleType("homeassistant.helpers")
    update_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class _DataUpdateCoordinator:
        """Minimal stub replicating the HA coordinator API for tests."""

        def __init__(
            self,
            hass: Any,
            logger: Any,
            name: str | None = None,
            update_interval: timedelta | None = None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data: Any | None = None

        async def async_config_entry_first_refresh(self) -> None:
            update = getattr(self, "_async_update_data", None)
            if update is None:
                return
            self.data = await update()

        async def async_request_refresh(self) -> None:
            await self.async_config_entry_first_refresh()

    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    helpers.update_coordinator = update_coordinator
    homeassistant.helpers = helpers

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault(
        "homeassistant.helpers.update_coordinator", update_coordinator
    )

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from custom_components.govee import DOMAIN
from custom_components.govee.coordinator import (
    DeviceMetadata,
    GoveeDataUpdateCoordinator,
)
from custom_components.govee.state import DeviceOpState, ParseOption
from custom_components.govee.device_types.air_quality import AirQualityDevice
from custom_components.govee.device_types.humidifier import HumidifierDevice
from custom_components.govee.device_types.ice_maker import IceMakerDevice
from custom_components.govee.device_types.hygrometer import HygrometerDevice
from custom_components.govee.device_types.presence import PresenceDevice
from custom_components.govee.device_types.purifier import PurifierDevice
from custom_components.govee.device_types.meat_thermometer import (
    MeatThermometerDevice,
)


class FakeAPIClient:
    """Test double mimicking the upstream API client."""

    def __init__(self, devices: list[dict[str, str]]) -> None:
        """Store the static device metadata returned by the client."""

        self._devices = devices
        self.request_count = 0
        self.iot_commands: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self.ble_commands: list[tuple[str, dict[str, str], dict[str, str]]] = []

    async def async_get_devices(self) -> list[dict[str, str]]:
        """Return static metadata for coordinator discovery."""

        await asyncio.sleep(0)
        self.request_count += 1
        return list(self._devices)

    async def async_publish_iot_command(
        self, device_id: str, channel_info: dict[str, str], command: dict[str, str]
    ) -> None:
        """Record IoT commands issued by the coordinator."""

        self.iot_commands.append((device_id, dict(command), dict(channel_info)))

    async def async_publish_ble_command(
        self, device_id: str, channel_info: dict[str, str], command: dict[str, str]
    ) -> None:
        """Record BLE commands issued by the coordinator."""

        self.ble_commands.append((device_id, dict(command), dict(channel_info)))


def test_device_metadata_accepts_typescript_payload() -> None:
    """TypeScript-style payloads should normalise to DeviceMetadata."""

    payload = {
        "deviceId": "ts-device-1",
        "model": "H7141",
        "sku": "H7141",
        "category": "Home Appliances",
        "categoryGroup": "Air Treatment",
        "deviceName": "Bedroom Humidifier",
        "channels": {
            "iot": {
                "topic": "accounts/123/device/ts-device-1",
            }
        },
    }

    metadata = DeviceMetadata.from_dict(payload)

    assert metadata.device_id == "ts-device-1"
    assert metadata.model == "H7141"
    assert metadata.sku == "H7141"
    assert metadata.category == "Home Appliances"
    assert metadata.category_group == "Air Treatment"
    assert metadata.device_name == "Bedroom Humidifier"
    assert metadata.manufacturer == "Govee"
    assert metadata.channels["iot"]["topic"] == "accounts/123/device/ts-device-1"


@dataclass
class FakeDeviceEntry:
    """Representation of a created device registry entry."""

    id: str


class FakeDeviceRegistry:
    """Record device registry calls for verification."""

    def __init__(self) -> None:
        """Initialise storage for registered devices."""

        self.created: list[tuple[FakeDeviceEntry, dict[str, Any]]] = []
        self._counter = 0

    async def async_get_or_create(self, **kwargs: Any) -> FakeDeviceEntry:
        """Capture device registry registration requests."""

        self._counter += 1
        entry = FakeDeviceEntry(id=f"device-entry-{self._counter}")
        self.created.append((entry, dict(kwargs)))
        return entry


class FakeEntityRegistry:
    """Capture entity registry registrations for later assertions."""

    def __init__(self) -> None:
        """Initialise storage for registered entities."""

        self.created: list[dict[str, Any]] = []

    async def async_get_or_create(
        self, domain: str, platform: str, unique_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Capture entity registry registration requests."""

        entry = {
            "domain": domain,
            "platform": platform,
            "unique_id": unique_id,
            **kwargs,
        }
        self.created.append(entry)
        return entry


@pytest.mark.asyncio
async def test_update_data_discovers_devices_from_typescript_payload() -> None:
    """Coordinator refresh should discover devices and expose snapshot data."""

    api_client = FakeAPIClient(
        [
            {
                "deviceId": "ts-device-1",
                "model": "H7141",
                "categoryGroup": "Air Treatment",
                "category": "Humidifier",
                "deviceName": "Bedroom Humidifier",
                "channels": {
                    "iot": {
                        "stateTopic": "state/ts-device-1",
                        "commandTopic": "command/ts-device-1",
                        "refreshTopic": "refresh/ts-device-1",
                    }
                },
            }
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )

    data = await coordinator._async_update_data()

    assert api_client.request_count == 1
    assert coordinator.device_metadata.keys() == {"ts-device-1"}
    assert coordinator.devices.keys() == {"ts-device-1"}
    assert data["device_metadata"] is coordinator.device_metadata
    assert data["devices"] is coordinator.devices

    [(entry, payload)] = device_registry.created
    assert payload["identifiers"] == {(DOMAIN, "ts-device-1")}
    assert payload["manufacturer"] == "Govee"
    assert payload["model"] == "H7141"


def test_resolve_factory_selects_air_quality_by_category() -> None:
    """Air quality category group should map to the AirQualityDevice factory."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="aq-1",
        model="H6601",
        sku="H6601",
        category="Air Quality Monitor",
        category_group="Air Quality",
        device_name="Air Quality Monitor",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is AirQualityDevice


def test_resolve_factory_matches_ice_maker_category() -> None:
    """Kitchen appliances matching ice maker naming should use IceMakerDevice."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="ice-1",
        model="H8000",
        sku="H8000",
        category="Home Appliances",
        category_group="Kitchen",
        device_name="Smart Countertop Ice Maker",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is IceMakerDevice


def test_resolve_factory_matches_meat_thermometer_category() -> None:
    """Kitchen devices named like WiFi meat thermometers should map correctly."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="meat-1",
        model="H7480",
        sku="H7480",
        category="Home Improvement",
        category_group="Kitchen",
        device_name="WiFi Meat Thermometer",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is MeatThermometerDevice


def test_resolve_factory_matches_air_quality_model_prefix() -> None:
    """Specific air quality model prefixes should map to AirQualityDevice."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="aq-2",
        model="H6609",
        sku="H6609",
        category="Unknown",
        category_group="",
        device_name="AQ Sensor",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is AirQualityDevice


def test_resolve_factory_matches_ice_maker_model_prefix() -> None:
    """Ice maker model prefixes should map directly to IceMakerDevice."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="ice-2",
        model="H7172",
        sku="H7172",
        category="Unknown",
        category_group="",
        device_name="Countertop Ice Maker",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is IceMakerDevice


def test_resolve_factory_matches_meat_thermometer_model_prefix() -> None:
    """Meat thermometer model prefixes should map to MeatThermometerDevice."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="meat-2",
        model="H7481",
        sku="H7481",
        category="Unknown",
        category_group="",
        device_name="Smart Thermometer",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is MeatThermometerDevice


def test_resolve_factory_matches_hygrometer_model_prefix() -> None:
    """Hygrometer model prefixes should map to HygrometerDevice."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="hg-1",
        model="H5075",
        sku="H5075",
        category="Thermo-Hygrometer",
        category_group="Thermo-Hygrometers",
        device_name="Smart Hygrometer",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is HygrometerDevice


def test_resolve_factory_detects_presence_category() -> None:
    """Presence sensors should resolve to the PresenceDevice factory."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    metadata = DeviceMetadata(
        device_id="presence-1",
        model="H5109",
        sku="H5109",
        category="Presence Sensor",
        category_group="Presence Sensors",
        device_name="Presence Detector",
        manufacturer="Govee",
        channels={},
    )

    factory = coordinator._resolve_factory(metadata)

    assert factory is PresenceDevice


@pytest.mark.asyncio
async def test_first_refresh_populates_coordinator_data_snapshot() -> None:
    """Initial refresh should store metadata snapshot for entities."""

    api_client = FakeAPIClient(
        [
            {
                "deviceId": "ts-device-1",
                "model": "H7141",
                "categoryGroup": "Air Treatment",
                "category": "Humidifier",
                "deviceName": "Bedroom Humidifier",
            }
        ]
    )
    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data == {
        "devices": coordinator.devices,
        "device_metadata": coordinator.device_metadata,
    }
    assert "ts-device-1" in coordinator.device_metadata


class FakeTimerHandle:
    """Minimal timer handle tracking cancellation state."""

    def __init__(self, callback: Callable[[], None]) -> None:
        """Bind the handle to a callback."""

        self._callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        """Mark the handle as cancelled."""

        self.cancelled = True

    def fire(self) -> None:
        """Invoke the stored callback when not cancelled."""

        if not self.cancelled:
            self._callback()


class FakeLoop:
    """Event loop double that records scheduled callbacks."""

    def __init__(self) -> None:
        """Set up storage for scheduled timer handles."""

        self.calls: list[tuple[float, FakeTimerHandle]] = []

    def call_later(self, delay: float, callback: Callable[[], None]) -> FakeTimerHandle:
        """Record timer registrations with the requested delay."""

        handle = FakeTimerHandle(callback)
        self.calls.append((delay, handle))
        return handle


class FakeIoTClient:
    """Test double for the IoT MQTT client."""

    def __init__(self) -> None:
        """Initialise storage for commands and subscriptions."""

        self.started: int = 0
        self.commands: list[tuple[str, dict[str, Any]]] = []
        self.refreshes: list[str] = []
        self.update_callback: Callable[[tuple[str, dict[str, Any]]], Any] | None = None
        self.expiry_batches: list[list[str]] = []
        self.pending_commands: dict[str, float] = {}

    async def async_start(self) -> None:
        """Record a start request."""

        self.started += 1

    async def async_publish_command(self, topic: str, payload: dict[str, Any]) -> str:
        """Capture an IoT command publication."""

        self.commands.append((topic, dict(payload)))
        return "cmd-1"

    async def async_request_refresh(self, topic: str) -> None:
        """Record a refresh request for ``topic``."""

        self.refreshes.append(topic)

    def set_update_callback(
        self, callback: Callable[[tuple[str, dict[str, Any]]], Any]
    ) -> None:
        """Register the update callback invoked by state messages."""

        self.update_callback = callback

    def expire_pending_commands(self) -> list[str]:
        """Return the next batch of expired command identifiers."""

        if self.expiry_batches:
            return self.expiry_batches.pop(0)
        return []


class StubOpState(DeviceOpState[bool | None]):
    """Capture opcode payloads processed during tests."""

    def __init__(self, device: object) -> None:
        """Initialise the stub state with permissive opcode filtering."""

        super().__init__(
            op_identifier={"op_type": 0xAA, "identifier": []},
            device=device,
            name="stubOp",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
        )
        self.commands: list[list[int]] = []

    def parse_op_command(self, op_command: list[int]) -> None:
        """Record opcode commands forwarded by the coordinator."""

        self.commands.append(list(op_command))


def test_coordinator_inherits_home_assistant_data_update_coordinator() -> None:
    """The integration coordinator must extend Home Assistant's base class."""

    coordinator = GoveeDataUpdateCoordinator(
        hass=object(),
        api_client=None,
        device_registry=None,
        entity_registry=None,
    )

    assert isinstance(coordinator, DataUpdateCoordinator)


@pytest.mark.asyncio
async def test_discovery_creates_devices_and_registers_entries() -> None:
    """Coordinator should materialise devices and register them with HA."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-1",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Living Room Humidifier",
            },
            {
                "device_id": "device-2",
                "model": "H7126",
                "sku": "H7126",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Office Purifier",
            },
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )

    await coordinator.async_discover_devices()

    assert api_client.request_count == 1
    assert set(coordinator.devices) == {"device-1", "device-2"}
    assert isinstance(coordinator.devices["device-1"], HumidifierDevice)
    assert isinstance(coordinator.devices["device-2"], PurifierDevice)

    assert len(device_registry.created) == 2
    identifiers = {
        next(iter(data["identifiers"])) for _, data in device_registry.created
    }
    assert identifiers == {
        ("govee", "device-1"),
        ("govee", "device-2"),
    }


@pytest.mark.asyncio
async def test_discovery_registers_home_assistant_entities() -> None:
    """All exposed states should be registered with the entity registry."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-1",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Living Room Humidifier",
            },
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )

    await coordinator.async_discover_devices()

    assert len(device_registry.created) == 1
    device_entry, _ = device_registry.created[0]

    unique_ids = {entry["unique_id"] for entry in entity_registry.created}
    assert {"device-1-power", "device-1-mistLevel"} <= unique_ids

    power_entry = next(
        entry
        for entry in entity_registry.created
        if entry["unique_id"] == "device-1-power"
    )
    assert power_entry["domain"] == "humidifier"
    assert power_entry["platform"] == "govee"
    assert power_entry["device_id"] == device_entry.id
    assert power_entry["entity_category"] is None

    diagnostic_entry = next(
        entry
        for entry in entity_registry.created
        if entry["unique_id"] == "device-1-active"
    )
    assert diagnostic_entry["entity_category"] == "diagnostic"


@pytest.mark.asyncio
async def test_presence_discovery_registers_presence_entities() -> None:
    """Presence devices should expose detection and tuning entities."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "presence-1",
                "model": "H5109",
                "sku": "H5109",
                "category": "Presence Sensor",
                "category_group": "Presence Sensors",
                "device_name": "Office Presence Sensor",
            }
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )

    await coordinator.async_discover_devices()

    unique_ids = {entry["unique_id"] for entry in entity_registry.created}
    assert {
        "presence-1-presence-mmWave",
        "presence-1-presence-biological",
        "presence-1-presenceEnable-mmWave",
        "presence-1-presenceEnable-biological",
        "presence-1-detectionDistance",
    } <= unique_ids

    mmwave_entry = next(
        entry
        for entry in entity_registry.created
        if entry["unique_id"] == "presence-1-presence-mmWave"
    )
    assert mmwave_entry["domain"] == "binary_sensor"
    assert mmwave_entry["translation_key"] == "presence_mmwave"

    distance_entry = next(
        entry
        for entry in entity_registry.created
        if entry["unique_id"] == "presence-1-detectionDistance"
    )
    assert distance_entry["domain"] == "number"
    assert distance_entry["entity_category"] == "config"


@pytest.mark.asyncio
async def test_command_dispatch_defaults_to_iot_channel() -> None:
    """Command publishers should select the default IoT channel when available."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-1",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Living Room Humidifier",
                "channels": {
                    "iot": {"topic": "govee/device-1"},
                    "ble": {"mac": "00:11:22:33:44:55"},
                },
            }
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )

    await coordinator.async_discover_devices()

    publisher = coordinator.get_command_publisher("device-1")
    await publisher({"opcode": "0x01", "payload": "01"})

    assert api_client.iot_commands == [
        (
            "device-1",
            {"opcode": "0x01", "payload": "01"},
            {"topic": "govee/device-1"},
        )
    ]
    assert api_client.ble_commands == []


@pytest.mark.asyncio
async def test_iot_state_subscription_is_started_for_iot_devices() -> None:
    """Discovery should start the IoT client with IoT-capable devices."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {
                    "iot": {
                        "topic": "accounts/123/devices/device-iot",
                    }
                },
            },
            {
                "device_id": "device-ble",
                "model": "H7126",
                "sku": "H7126",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Purifier",
                "channels": {"ble": {"mac": "AA:BB:CC:DD:EE:FF"}},
            },
        ]
    )
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        iot_client=iot_client,
        iot_state_enabled=True,
    )

    await coordinator.async_discover_devices()

    assert iot_client.started == 1


@pytest.mark.asyncio
async def test_iot_state_updates_flow_to_devices() -> None:
    """IoT updates should update device state via the coordinator."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {"iot": {"topic": "accounts/123/devices/device-iot"}},
            }
        ]
    )
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        iot_client=iot_client,
        iot_state_enabled=True,
    )

    await coordinator.async_discover_devices()
    await coordinator._handle_iot_update(("device-iot", {"power": True}))

    device = coordinator.devices["device-iot"]
    assert device.states["power"].value is True


@pytest.mark.asyncio
async def test_account_topic_payload_updates_connected_and_opcode_state() -> None:
    """Account topic payloads should update connected/opcode states immediately."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {"iot": {"topic": "accounts/123/devices/device-iot"}},
            }
        ]
    )
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        iot_client=iot_client,
        iot_state_enabled=True,
    )

    await coordinator.async_discover_devices()
    device = coordinator.devices["device-iot"]
    stub_state = device.add_state(StubOpState(device=device.device))

    payload = {
        "device": "device-iot",
        "msg": {
            "data": {
                "state": {"connected": True},
                "op": {"command": [[0xAA, 0x01, 0x01]]},
            }
        },
    }

    await coordinator._handle_iot_update(("device-iot", payload))

    connected_state = device.states["isConnected"]
    assert connected_state.value is True
    assert stub_state.commands == [[0xAA, 0x01, 0x01]]


@pytest.mark.asyncio
async def test_expire_pending_commands_clears_state_operations() -> None:
    """Expired IoT commands should clear pending operations on device states."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {"iot": {"topic": "accounts/123/devices/device-iot"}},
            }
        ]
    )
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        iot_client=iot_client,
        iot_state_enabled=True,
        iot_command_enabled=True,
    )

    await coordinator.async_discover_devices()
    device = coordinator.devices["device-iot"]
    power_state = device.states["power"]
    command_ids = power_state.set_state(True)
    assert command_ids
    expired_id = command_ids[0]
    iot_client.expiry_batches.append([expired_id])

    await coordinator._handle_iot_update(("device-iot", {"power": True}))
    # simulate expiry routine invocation
    coordinator._expire_pending_commands()

    cleared = power_state.clear_queue.get_nowait()
    assert cleared["command_id"] == expired_id


@pytest.mark.asyncio
async def test_command_dispatch_supports_explicit_ble_channel() -> None:
    """Publishers should honour an explicit BLE channel request."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-1",
                "model": "H7126",
                "sku": "H7126",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Office Purifier",
                "channels": {"ble": {"mac": "AA:BB:CC:DD:EE:FF"}},
            }
        ]
    )
    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    await coordinator.async_discover_devices()

    publisher = coordinator.get_command_publisher("device-1", channel="ble")
    await publisher({"opcode": "0x10"})

    assert api_client.ble_commands == [
        (
            "device-1",
            {"opcode": "0x10"},
            {"mac": "AA:BB:CC:DD:EE:FF"},
        )
    ]
    assert api_client.iot_commands == []


@pytest.mark.asyncio
async def test_iot_commands_use_mqtt_client_when_enabled() -> None:
    """When configured the coordinator should send commands via the IoT client."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {"iot": {"topic": "accounts/123/devices/device-iot"}},
            }
        ]
    )
    device_registry = FakeDeviceRegistry()
    entity_registry = FakeEntityRegistry()
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
        iot_client=iot_client,
        iot_state_enabled=True,
        iot_command_enabled=True,
        iot_refresh_enabled=True,
    )

    await coordinator.async_discover_devices()

    publisher = coordinator.get_command_publisher("device-iot", channel="iot")
    await publisher({"opcode": "0x20"})

    assert iot_client.commands == [
        ("accounts/123/devices/device-iot", {"opcode": "0x20"})
    ]
    assert api_client.iot_commands == []


@pytest.mark.asyncio
async def test_iot_refresh_requests_use_mqtt_client() -> None:
    """Refresh requests should be forwarded to the IoT client when enabled."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-iot",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Humidifier",
                "channels": {"iot": {"topic": "accounts/123/devices/device-iot"}},
            }
        ]
    )
    iot_client = FakeIoTClient()

    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        iot_client=iot_client,
        iot_state_enabled=False,
        iot_command_enabled=False,
        iot_refresh_enabled=True,
    )

    await coordinator.async_discover_devices()
    await coordinator.async_request_device_refresh("device-iot")

    assert iot_client.refreshes == ["accounts/123/devices/device-iot"]


@pytest.mark.asyncio
async def test_event_processing_updates_device_state() -> None:
    """Incoming state updates should fan out to device state objects."""

    api_client = FakeAPIClient(
        [
            {
                "device_id": "device-1",
                "model": "H7142",
                "sku": "H7142",
                "category": "Home Appliances",
                "category_group": "Air Treatment",
                "device_name": "Living Room Humidifier",
            }
        ]
    )
    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=api_client,
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
    )

    await coordinator.async_discover_devices()

    updated = await coordinator.async_process_state_update(
        "device-1", {"power": True, "water_shortage": False}
    )

    device = coordinator.devices["device-1"]
    assert device.states["power"].value is True
    assert device.states["waterShortage"].value is False
    assert set(updated) >= {"power", "water_shortage"}


def test_refresh_scheduler_reschedules_callback() -> None:
    """Refresh scheduling should reschedule callbacks at the configured interval."""

    loop = FakeLoop()
    coordinator = GoveeDataUpdateCoordinator(
        hass=None,
        api_client=FakeAPIClient([]),
        device_registry=FakeDeviceRegistry(),
        entity_registry=FakeEntityRegistry(),
        refresh_interval=timedelta(seconds=30),
        loop=loop,
    )

    invocations: list[int] = []

    def refresh_callback() -> None:
        invocations.append(len(invocations))

    first_handle = coordinator.async_schedule_refresh(refresh_callback)

    assert len(loop.calls) == 1
    delay, handle = loop.calls[0]
    assert delay == 30
    assert not handle.cancelled
    assert first_handle is handle

    handle.fire()
    assert invocations == [0]
    assert len(loop.calls) == 2
    assert loop.calls[1][0] == 30

    second_handle = coordinator.async_schedule_refresh(refresh_callback)
    assert loop.calls[1][1].cancelled is True
    assert second_handle is loop.calls[2][1]
