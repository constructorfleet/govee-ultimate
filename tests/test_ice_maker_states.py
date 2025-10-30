"""Tests for Govee ice maker specific state handlers."""

from __future__ import annotations

import datetime as dt

import pytest

from custom_components.govee_ultimate import opcodes
from custom_components.govee_ultimate.state.states import (
    IceMakerBasketFullState,
    IceMakerMakingIceState,
    IceMakerNuggetSizeState,
    IceMakerScheduledStartState,
    IceMakerStatusState,
    IceMakerTemperatureState,
    IceMakerWaterEmptyState,
)


class DummyDevice:
    """Minimal device stub compatible with device states."""

    def add_status_listener(self, _callback):  # pragma: no cover - compatibility shim
        """Device states expect a listener hook."""


@pytest.fixture
def device() -> DummyDevice:
    """Return a dummy device instance."""

    return DummyDevice()


def _drain(queue) -> list[dict]:
    """Drain an asyncio queue synchronously for inspection."""

    items: list[dict] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


@pytest.mark.parametrize(
    "payload,value",
    [
        ([0xAA, 0x05, 0x03], "SMALL"),
        ([0xAA, 0x05, 0x02], "MEDIUM"),
        ([0xAA, 0x05, 0x01], "LARGE"),
    ],
)
def test_nugget_size_state_parses_and_emits_command(
    device: DummyDevice, payload: list[int], value: str
) -> None:
    """Nugget size state should parse opcode payloads and emit commands."""

    state = IceMakerNuggetSizeState(device=device)
    assert state.options == ("SMALL", "MEDIUM", "LARGE")

    state.parse({"op": {"command": [payload]}})
    assert state.value == value

    command_ids = state.set_state("LARGE")
    assert command_ids

    [command] = _drain(state.command_queue)
    assert command["payload_hex"] == "0501"
    assert command["ble_base64"] == opcodes.ble_command_to_base64([0x33], [0x05, 0x01])


@pytest.mark.parametrize(
    "state_cls,payload",
    [
        (IceMakerBasketFullState, [0xAA, 0x17, 0x01, 0x01]),
        (IceMakerWaterEmptyState, [0xAA, 0x17, 0x02, 0x01]),
    ],
)
def test_boolean_alarms_parse_identifier_payloads(
    device: DummyDevice, state_cls, payload: list[int]
) -> None:
    """Boolean ice maker alarms should parse opcode payloads from identifier frames."""

    state = state_cls(device=device)
    state.parse({"op": {"command": [payload]}})
    assert state.value is True

    cleared_payload = payload[:-1] + [0x00]
    state.parse({"op": {"command": [cleared_payload]}})
    assert state.value is False


@pytest.mark.parametrize(
    "payload,value",
    [
        ([0xAA, 0x19, 0x00], "STANDBY"),
        ([0xAA, 0x19, 0x01], "MAKING_ICE"),
        ([0xAA, 0x19, 0x02], "FULL"),
        ([0xAA, 0x19, 0x03], "WASHING"),
        ([0xAA, 0x19, 0x04], "FINISHED_WASHING"),
        ([0xAA, 0x19, 0x05], "SCHEDULED"),
    ],
)
def test_status_state_maps_numeric_codes(
    device: DummyDevice, payload: list[int], value: str
) -> None:
    """Status state should map opcode payloads to descriptive values."""

    state = IceMakerStatusState(device=device)
    state.parse({"op": {"command": [payload]}})
    assert state.value == value

    command_ids = state.set_state("WASHING")
    assert command_ids
    [command] = _drain(state.command_queue)
    assert command["payload_hex"] == "1903"
    assert command["ble_base64"] == opcodes.ble_command_to_base64([0x33], [0x19, 0x03])


def test_making_ice_state_reflects_status(device: DummyDevice) -> None:
    """Derived making-ice state should follow the status state updates."""

    status = IceMakerStatusState(device=device)
    state = IceMakerMakingIceState(device=device, status_state=status)

    status.parse({"op": {"command": [[0xAA, 0x19, 0x01]]}})
    assert state.value is True

    status.parse({"op": {"command": [[0xAA, 0x19, 0x00]]}})
    assert state.value is False

    command_ids = state.set_state(True)
    assert command_ids
    [command] = _drain(status.command_queue)
    assert command["payload_hex"] == "1901"


def test_scheduled_start_state_parses_and_emits_commands(
    device: DummyDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scheduled start state should parse opcode payloads and emit commands."""

    state = IceMakerScheduledStartState(device=device)
    reference_now = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(state, "_now", lambda: reference_now)

    command_ids = state.set_state(
        {
            "enabled": True,
            "hourStart": 13,
            "minuteStart": 0,
            "nuggetSize": "MEDIUM",
        }
    )
    assert command_ids
    [command] = _drain(state.command_queue)

    expected_payload_hex = "2301003C6592B75002"
    assert command["payload_hex"] == expected_payload_hex
    assert command["ble_base64"] == opcodes.ble_command_to_base64(
        [0x33], bytes.fromhex(expected_payload_hex)
    )

    status_payload = [0xAA, 0x23, 0x01, 0x00, 0x3C, 0x65, 0x92, 0xB7, 0x50, 0x02]
    state.parse({"op": {"command": [status_payload]}})
    assert state.value == {
        "enabled": True,
        "hourStart": 13,
        "minuteStart": 0,
        "nuggetSize": "MEDIUM",
    }

    disable_ids = state.set_state({"enabled": False})
    assert disable_ids
    [disable_command] = _drain(state.command_queue)
    assert disable_command["payload_hex"] == "2300"


def test_temperature_state_parses_signed_value(device: DummyDevice) -> None:
    """Temperature state should parse signed payloads with scaling."""

    state = IceMakerTemperatureState(device=device)

    state.parse({"op": {"command": [[0xAA, 0x10, 0x00, 0xC3, 0x50]]}})
    assert state.value == {
        "current": pytest.approx(5.0),
        "range": {"min": -20, "max": 60},
        "unit": "C",
    }

    state.parse({"op": {"command": [[0xAA, 0x10, 0x80, 0xC3, 0x50]]}})
    assert state.value["current"] == pytest.approx(-5.0)
