"""Integration tests for the coordinator/service layer."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from datetime import timedelta

import pytest

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


class FakeDeviceRegistry:
    """Record device registry calls for verification."""

    def __init__(self) -> None:
        """Initialise storage for registered devices."""

        self.created: list[dict[str, str]] = []

    async def async_get_or_create(self, **kwargs: str) -> dict[str, str]:
        """Capture device registry registration requests."""

        self.created.append(kwargs)
        return kwargs


class FakeEntityRegistry:
    """Capture entity registry registrations for later assertions."""

    def __init__(self) -> None:
        """Initialise storage for registered entities."""

        self.created: list[dict[str, str]] = []

    async def async_get_or_create(self, **kwargs: str) -> dict[str, str]:
        """Capture entity registry registration requests."""

        self.created.append(kwargs)
        return kwargs


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

    created_ids = {entry["id"] for entry in device_registry.created}
    assert created_ids == {"device-1", "device-2"}


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

    unique_ids = {entry["unique_id"] for entry in entity_registry.created}
    assert {"device-1-power", "device-1-mist_level"} <= unique_ids

    power_entry = next(entry for entry in entity_registry.created if entry["unique_id"] == "device-1-power")
    assert power_entry["domain"] == "humidifier"
    assert power_entry["device_id"] == "device-1"
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
