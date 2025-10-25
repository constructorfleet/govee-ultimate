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

    update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinator
    helpers.update_coordinator = update_coordinator
    homeassistant.helpers = helpers

    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault(
        "homeassistant.helpers.update_coordinator", update_coordinator
    )

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from custom_components.govee_ultimate.coordinator import GoveeDataUpdateCoordinator
from custom_components.govee_ultimate.device_types.humidifier import HumidifierDevice
from custom_components.govee_ultimate.device_types.purifier import PurifierDevice


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
        ("govee_ultimate", "device-1"),
        ("govee_ultimate", "device-2"),
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
    assert {"device-1-power", "device-1-mist_level"} <= unique_ids

    power_entry = next(entry for entry in entity_registry.created if entry["unique_id"] == "device-1-power")
    assert power_entry["domain"] == "humidifier"
    assert power_entry["platform"] == "govee_ultimate"
    assert power_entry["device_id"] == device_entry.id
    assert power_entry["entity_category"] is None

    diagnostic_entry = next(
        entry
        for entry in entity_registry.created
        if entry["unique_id"] == "device-1-active"
    )
    assert diagnostic_entry["entity_category"] == "diagnostic"


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
    assert device.states["water_shortage"].value is False
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
