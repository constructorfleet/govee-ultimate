"""Translation-focused tests for newly ported device states."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from custom_components.govee_ultimate.state.states import (
    BatteryLevelState,
    ControlLockState,
    TimerState,
    WaterShortageState,
)


class DummyDevice:
    """Minimal device stub for state testing."""

    def add_status_listener(self, _callback):  # pragma: no cover - compatibility shim
        """Provide the listener registration hook expected by states."""


@pytest.fixture
def device() -> DummyDevice:
    """Return a dummy device for state instances."""

    return DummyDevice()


def _next_command(state) -> Mapping[str, object]:
    """Return the next queued command payload for assertions."""

    queued = state.command_queue.get_nowait()
    assert isinstance(queued, Mapping)
    return queued


def test_battery_level_state_parses_top_level_and_nested(device: DummyDevice) -> None:
    """Battery level should accept top-level or nested percentages."""

    state = BatteryLevelState(device=device)

    state.parse({"battery": 58})
    assert state.value == 58

    state.parse({"state": {"battery": 17}})
    assert state.value == 17


def test_water_shortage_state_parses_boolean_and_opcode(device: DummyDevice) -> None:
    """Water shortage state maps booleans and opcode payloads to flags."""

    state = WaterShortageState(device=device)

    state.parse({"state": {"waterShortage": True}})
    assert state.value is True

    state.parse({"state": {"sta": {"stc": [0x06, 0x00]}}})
    assert state.value is False

    state.parse({"op": {"command": [[0xAA, 0x23, 0x00, 0x01]]}})
    assert state.value is True


def test_timer_state_tracks_boolean_and_duration(device: DummyDevice) -> None:
    """Timer state should expose a boolean value while tracking duration."""

    state = TimerState(device=device, identifier=[0x0A, 0x0B])

    state.parse({"op": {"command": [[0xAA, 0x0A, 0x0B, 0x01, 0x01, 0x2C]]}})
    assert state.value is True
    assert state.duration == 300

    command_ids = state.set_state(False)
    assert command_ids

    queued = _next_command(state)
    frame = queued["data"]["command"][0]
    assert frame[:6] == [0x33, 0x0A, 0x0B, 0x00, 0x01, 0x2C]


def test_timer_state_parses_disabled_payload(device: DummyDevice) -> None:
    """Timer payloads with disabled flag should update state and duration."""

    state = TimerState(device=device, identifier=[0x0A, 0x0B])

    state.parse({"op": {"command": [[0xAA, 0x0A, 0x0B, 0x00, 0x00, 0x3C]]}})
    assert state.value is False
    assert state.duration == 60


def test_control_lock_state_parses_and_emits_command(device: DummyDevice) -> None:
    """Control lock state should parse booleans and emit toggle commands."""

    state = ControlLockState(device=device, identifier=[0x0A])

    state.parse({"state": {"controlLock": True}})
    assert state.value is True

    command_ids = state.set_state(False)
    assert command_ids

    queued = _next_command(state)
    assert queued["command"] == "multi_sync"
    frame = queued["data"]["command"][0]
    assert frame[:3] == [0x33, 0x0A, 0x00]
