"""Presence detection state translation tests."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


if "homeassistant.components.binary_sensor" not in sys.modules:
    binary_sensor_module = ModuleType("homeassistant.components.binary_sensor")

    class _BinarySensorEntity:
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

    binary_sensor_module.BinarySensorEntity = _BinarySensorEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_module


from custom_components.govee_ultimate.binary_sensor import GoveeBinarySensorEntity
from custom_components.govee_ultimate.device_types.base import HomeAssistantEntity
from custom_components.govee_ultimate.state.states import (
    BiologicalPresenceState,
    DetectionSettingsState,
    EnablePresenceState,
    MMWavePresenceState,
)


class DummyDevice:
    """Stub device supporting the listener API used by DeviceOpState."""

    def add_status_listener(self, _callback):  # type: ignore[no-untyped-def]
        """Accept a listener without storing it."""
        return None


def test_presence_binary_sensor_uses_detected_flag() -> None:
    """Binary sensor entities expose the detected flag from mapping states."""

    device = DummyDevice()
    state = MMWavePresenceState(device)
    entity = HomeAssistantEntity(platform="binary_sensor", state=state)
    coordinator = SimpleNamespace()
    binary_sensor = GoveeBinarySensorEntity(coordinator, "device-id", entity)

    state._update_state({"detected": False})
    assert binary_sensor.is_on is False

    state._update_state({"detected": True})
    assert binary_sensor.is_on is True


def test_presence_binary_sensor_reads_enabled_flag() -> None:
    """Binary sensor entities continue scanning mapping flags until they match."""

    device = DummyDevice()
    state = EnablePresenceState(device)
    entity = HomeAssistantEntity(platform="binary_sensor", state=state)
    coordinator = SimpleNamespace()
    binary_sensor = GoveeBinarySensorEntity(coordinator, "device-id", entity)

    state._update_state({"enabled": False})
    assert binary_sensor.is_on is False

    state._update_state({"enabled": True})
    assert binary_sensor.is_on is True


def test_mmwave_presence_parses_detection_distance_and_duration() -> None:
    """MMWave presence decoding yields detection, distance, and duration."""

    device = DummyDevice()
    state = MMWavePresenceState(device)

    payload = [
        0xAA,
        0x01,
        0x01,
        0x00,
        0x5B,
        0x00,
        0x00,
        0x5D,
        0x00,
        0x00,
        0x02,
        0xC3,
        0x00,
        0x00,
        0x00,
        0x00,
        0x01,
        0x00,
        0x00,
        0x6C,
    ]

    state.parse({"op": {"command": [payload]}})

    assert state.value == {
        "type": "mmWave",
        "detected": True,
        "distance": {"value": 91, "unit": "cm"},
        "duration": {"value": 707, "unit": "s"},
    }


def test_enable_presence_generates_multi_sync_commands() -> None:
    """Enable presence commands emit multi-sync payloads with flags."""

    device = DummyDevice()
    state = EnablePresenceState(device)

    payload = [
        0xAA,
        0x1F,
        0x01,
        0x01,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0xB5,
    ]

    state.parse({"op": {"command": [payload]}})

    assert state.value == {"biologicalEnabled": True, "mmWaveEnabled": True}

    command_ids = state.set_state({"biologicalEnabled": False, "mmWaveEnabled": True})

    assert len(command_ids) == 1

    queued = state.command_queue.get_nowait()
    assert queued["command_id"] == command_ids[0]
    assert queued["command"] == "multi_sync"
    command_frame = queued["data"]["command"][0]
    assert command_frame[0] == 0x33
    assert command_frame[1] == 0x1F
    assert command_frame[2] == 0x00
    assert command_frame[3] == 0x01


def test_detection_settings_parse_and_emit_commands() -> None:
    """Detection settings decode status and emit compound commands."""

    device = DummyDevice()
    state = DetectionSettingsState(device)

    payload = [
        0xAA,
        0x05,
        0x01,
        0x00,
        0x64,
        0x00,
        0x0A,
        0x00,
        0x14,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0xAF,
    ]

    state.parse({"op": {"command": [payload]}})

    assert state.value == {
        "detectionDistance": {"value": 100, "unit": "cm"},
        "absenceDuration": {"value": 10, "unit": "s"},
        "reportDetection": {"value": 20, "unit": "s"},
    }

    command_ids = state.set_state(
        {
            "detectionDistance": {"value": 150, "unit": "cm"},
            "absenceDuration": {"value": 12, "unit": "s"},
            "reportDetection": {"value": 25, "unit": "s"},
        }
    )

    assert len(command_ids) == 1
    queued = state.command_queue.get_nowait()
    assert queued["data"]["command"][0][0] == 0x33
    assert queued["data"]["command"][1][0] == 0x33
    assert len(queued["data"]["command"]) == 2


def test_biological_presence_handles_longer_payloads() -> None:
    """Biological presence state produces expected detection metadata."""

    device = DummyDevice()
    state = BiologicalPresenceState(device)

    payload = [
        0xAA,
        0x01,
        0x01,
        0x00,
        0xA3,
        0x01,
        0x01,
        0x39,
        0x00,
        0x00,
        0x02,
        0x87,
        0x00,
        0x00,
        0x00,
        0x00,
        0x01,
        0x00,
        0x00,
        0xB5,
    ]

    state.parse({"op": {"command": [payload]}})

    assert state.value == {
        "type": "biological",
        "detected": True,
        "distance": {"value": 313, "unit": "cm"},
        "duration": {"value": 647, "unit": "s"},
    }
