"""Tests for additional state implementations."""

from __future__ import annotations

import pytest

from custom_components.govee_ultimate.state.states import (
    ConnectedState,
    ControlLockState,
    DisplayScheduleState,
    HumidifierUVCState,
    NightLightState,
    TemperatureState,
    UnknownState,
)


class DummyDevice:
    """Minimal device stub for state tests."""

    def add_status_listener(self, _callback):
        """Compatibility hook for state classes."""


@pytest.fixture
def device() -> DummyDevice:
    """Return a dummy device instance for tests."""

    return DummyDevice()


@pytest.fixture
def connected_state(device: DummyDevice) -> ConnectedState:
    """Return a connected state bound to a dummy device."""

    return ConnectedState(device=device)


@pytest.fixture
def temperature_state(device: DummyDevice) -> TemperatureState:
    """Return a temperature state bound to a dummy device."""

    return TemperatureState(device=device)


def _next_command(state) -> dict:
    """Return the next queued command payload for assertions."""

    queued = state.command_queue.get_nowait()
    assert isinstance(queued, dict)
    return queued


def _schedule_payload(
    identifier: int, *, on: bool, start: tuple[int, int], end: tuple[int, int]
) -> list[int]:
    """Construct an opcode payload for display schedule assertions."""

    return [
        0xAA,
        identifier,
        0x01 if on else 0x00,
        start[0],
        start[1],
        end[0],
        end[1],
    ]


def _night_light_payload(identifier: int, *, on: bool, brightness: int) -> list[int]:
    """Build a night light opcode payload."""

    return [0xAA, identifier, 0x01 if on else 0x00, brightness]


def test_connected_state_parses_multiple_boolean_keys(
    connected_state: ConnectedState,
) -> None:
    """Connected state accepts any supported boolean flag from payloads."""

    connected_state.parse({"state": {"isConnected": True}})
    assert connected_state.value is True

    connected_state.parse({"state": {"isOnline": False}})
    assert connected_state.value is False

    connected_state.parse({"state": {"connected": True}})
    assert connected_state.value is True

    connected_state.parse({"state": {"online": False}})
    assert connected_state.value is False


def test_connected_state_is_not_commandable_and_history(
    connected_state: ConnectedState,
) -> None:
    """Connected state does not emit commands and supports history rewind."""

    assert connected_state.set_state(True) == []
    assert connected_state.command_queue.empty()

    connected_state.parse({"state": {"isConnected": True}})
    connected_state.parse({"state": {"isConnected": False}})

    assert connected_state.value is False

    connected_state.previous_state()
    assert connected_state.value is True


@pytest.fixture
def control_lock_state(device: DummyDevice) -> ControlLockState:
    """Return a control lock state bound to a dummy device."""

    return ControlLockState(device=device, identifier=[0x0A])


@pytest.fixture
def humidifier_uvc_state(device: DummyDevice) -> HumidifierUVCState:
    """Return a humidifier UVC state bound to a dummy device."""

    return HumidifierUVCState(device=device, identifier=[0x1A])


@pytest.fixture
def unknown_state(device: DummyDevice) -> UnknownState:
    """Return an unknown state bound to a dummy device."""

    return UnknownState(device=device, op_type=0xAA, identifier=[0x0B])


def test_control_lock_state_parses_opcode_payload(
    control_lock_state: ControlLockState,
) -> None:
    """Control lock state interprets opcode payload values as booleans."""

    control_lock_state.parse({"op": {"command": [[0xAA, 0x0A, 0x00]]}})
    assert control_lock_state.value is False

    control_lock_state.parse({"op": {"command": [[0xAA, 0x0A, 0x01]]}})
    assert control_lock_state.value is True


def test_control_lock_state_emits_commands_and_tracks_history(
    control_lock_state: ControlLockState,
) -> None:
    """Control lock state emits multi-sync commands and maintains history."""

    assert control_lock_state.set_state(None) == []
    assert control_lock_state.command_queue.empty()

    command_ids = control_lock_state.set_state(True)
    assert len(command_ids) == 1

    queued = _next_command(control_lock_state)
    assert queued["command"] == "multi_sync"
    frame = queued["data"]["command"][0]
    assert frame[0] == 0x33
    assert frame[1] == 0x0A
    assert frame[2] == 0x01

    control_lock_state.parse({"op": {"command": [[0xAA, 0x0A, 0x01]]}})
    assert control_lock_state.value is True

    control_lock_state.parse({"op": {"command": [[0xAA, 0x0A, 0x00]]}})
    assert control_lock_state.value is False

    control_lock_state.previous_state()
    assert control_lock_state.value is True


def test_humidifier_uvc_state_parses_opcode_payload(
    humidifier_uvc_state: HumidifierUVCState,
) -> None:
    """Humidifier UVC payloads map opcode values to booleans."""

    humidifier_uvc_state.parse({"op": {"command": [[0xAA, 0x1A, 0x01]]}})
    assert humidifier_uvc_state.value is True

    humidifier_uvc_state.parse({"op": {"command": [[0xAA, 0x1A, 0x00]]}})
    assert humidifier_uvc_state.value is False


def test_humidifier_uvc_state_emits_multi_sync_command(
    humidifier_uvc_state: HumidifierUVCState,
) -> None:
    """Humidifier UVC commands mirror the TypeScript multi-sync payload."""

    command_ids = humidifier_uvc_state.set_state(True)

    assert len(command_ids) == 1

    queued = _next_command(humidifier_uvc_state)
    assert queued["command"] == "multi_sync"
    frame = queued["data"]["command"][0]

    expected = [0x33, 0x1A, 0x01] + [0x00] * 16
    checksum = 0
    for byte in expected:
        checksum ^= byte
    expected.append(checksum)

    assert frame == expected

    humidifier_uvc_state.parse({"op": {"command": [[0xAA, 0x1A, 0x01]]}})

    cleared = humidifier_uvc_state.clear_queue.get_nowait()
    assert cleared["command_id"] == command_ids[0]
    assert cleared["state"] == "isUVCActive"
    assert cleared["value"] is True


@pytest.fixture
def display_schedule_state(device: DummyDevice) -> DisplayScheduleState:
    """Return a display schedule state bound to a dummy device."""

    return DisplayScheduleState(device=device, identifier=[0x18])


def test_display_schedule_state_parses_payload(
    display_schedule_state: DisplayScheduleState,
) -> None:
    """Display schedule payloads map to structured from/to fields."""

    payload = _schedule_payload(0x18, on=True, start=(0x06, 0x2D), end=(0x07, 0x3C))
    display_schedule_state.parse({"op": {"command": [payload]}})

    assert display_schedule_state.value == {
        "on": True,
        "from": {"hour": 0x06, "minute": 0x2D},
        "to": {"hour": 0x07, "minute": 0x3C},
    }


def test_display_schedule_state_emits_command_and_history(
    display_schedule_state: DisplayScheduleState,
) -> None:
    """Display schedule emits structured commands and maintains history."""

    command_ids = display_schedule_state.set_state(
        {
            "on": True,
            "from": {"hour": 8, "minute": 15},
            "to": {"hour": 20, "minute": 45},
        }
    )

    assert len(command_ids) == 1

    queued = _next_command(display_schedule_state)
    frame = queued["data"]["command"][0]
    assert frame[:4] == [0x33, 0xAA, 0x18, 0x01]
    assert frame[4:8] == [8, 15, 20, 45]

    display_schedule_state.parse(
        {
            "op": {
                "command": [
                    _schedule_payload(0x18, on=True, start=(8, 15), end=(20, 45))
                ]
            }
        }
    )
    assert display_schedule_state.value["on"] is True

    display_schedule_state.parse(
        {
            "op": {
                "command": [_schedule_payload(0x18, on=False, start=(0, 0), end=(0, 0))]
            }
        }
    )
    assert display_schedule_state.value["on"] is False

    display_schedule_state.previous_state()
    assert display_schedule_state.value["on"] is True


def test_temperature_state_parses_measurement_payload(
    temperature_state: TemperatureState,
) -> None:
    """Temperature state normalises calibration and current measurements."""

    temperature_state.parse(
        {
            "state": {
                "temperature": {
                    "calibration": 150,
                    "current": 235,
                    "min": 0,
                    "max": 50,
                }
            }
        }
    )

    assert temperature_state.value["calibration"] == pytest.approx(1.5)
    assert temperature_state.value["current"] == pytest.approx(2.35)
    assert temperature_state.value["raw"] == pytest.approx(0.85)
    assert temperature_state.value["range"] == {"min": 0, "max": 50}


def test_temperature_state_reuses_previous_values_when_missing_fields(
    temperature_state: TemperatureState,
) -> None:
    """Temperature state falls back to previous calibration and range data."""

    temperature_state.parse(
        {
            "state": {
                "temperature": {
                    "calibration": 1.5,
                    "current": 23.5,
                    "min": 0,
                    "max": 50,
                }
            }
        }
    )

    temperature_state.parse({"state": {"temperature": {"current": 280}}})

    assert temperature_state.value["calibration"] == pytest.approx(1.5)
    assert temperature_state.value["current"] == pytest.approx(2.8)
    assert temperature_state.value["raw"] == pytest.approx(1.3)
    assert temperature_state.value["range"] == {"min": 0, "max": 50}


def test_temperature_state_rejects_values_outside_range(
    temperature_state: TemperatureState,
) -> None:
    """Temperature state ignores updates that violate configured ranges."""

    temperature_state.parse(
        {
            "state": {
                "temperature": {
                    "calibration": 1.0,
                    "current": 25.0,
                    "min": 0,
                    "max": 40,
                }
            }
        }
    )

    previous_value = dict(temperature_state.value)

    temperature_state.parse(
        {
            "state": {
                "temperature": {
                    "current": 6000,
                    "min": 0,
                    "max": 40,
                }
            }
        }
    )

    assert temperature_state.value == previous_value


def test_temperature_state_is_not_commandable(
    temperature_state: TemperatureState,
) -> None:
    """Temperature state does not emit commands when set manually."""

    assert temperature_state.set_state({}) == []


def test_unknown_state_parses_opcode_payload(
    unknown_state: UnknownState,
) -> None:
    """Unknown state records the raw opcode payload it receives."""

    unknown_state.parse({"op": {"command": [[0xAA, 0x0B, 0x01, 0x02]]}})

    assert unknown_state.value == {"codes": [0xAA, 0x0B, 0x01, 0x02]}


def test_unknown_state_is_not_commandable(unknown_state: UnknownState) -> None:
    """Unknown state ignores manual set requests."""

    assert unknown_state.set_state({}) == []


@pytest.fixture
def night_light_state(device: DummyDevice) -> NightLightState:
    """Return a night light state bound to a dummy device."""

    return NightLightState(device=device, identifier=[0x18])


def test_night_light_state_parses_payload(night_light_state: NightLightState) -> None:
    """Night light payloads expose on flag and brightness."""

    night_light_state.parse(
        {"op": {"command": [_night_light_payload(0x18, on=True, brightness=0x20)]}}
    )

    assert night_light_state.value == {"on": True, "brightness": 0x20}


def test_night_light_state_emits_command_and_history(
    night_light_state: NightLightState,
) -> None:
    """Night light commands emit proper frames and track history."""

    assert night_light_state.set_state({"on": True}) == []

    command_ids = night_light_state.set_state({"on": True, "brightness": 64})
    assert len(command_ids) == 1

    queued = _next_command(night_light_state)
    frame = queued["data"]["command"][0]
    assert frame[:5] == [0x33, 0xAA, 0x18, 0x01, 0x40]

    night_light_state.parse(
        {"op": {"command": [_night_light_payload(0x18, on=True, brightness=0x40)]}}
    )
    assert night_light_state.value == {"on": True, "brightness": 0x40}

    night_light_state.parse(
        {"op": {"command": [_night_light_payload(0x18, on=False, brightness=0x10)]}}
    )
    assert night_light_state.value["on"] is False

    night_light_state.previous_state()
    assert night_light_state.value["on"] is True
