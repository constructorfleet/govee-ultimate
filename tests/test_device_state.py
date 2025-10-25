"""Tests for the asyncio-based device state helpers."""

import asyncio
from typing import Any
from collections.abc import Callable

from custom_components.govee_ultimate.state.device_state import (
    DeviceOpState,
    DeviceState,
    ParseOption,
)


class DummyDevice:
    """Simple device stub that captures status listeners."""

    def __init__(self) -> None:
        """Set up listener storage."""

        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    def add_status_listener(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a listener for emitted payloads."""

        self._listeners.append(callback)

    def emit(self, payload: dict[str, Any]) -> None:
        """Invoke all listeners with the provided payload."""

        for listener in list(self._listeners):
            listener(payload)


class SampleState(DeviceState[dict[str, Any]]):
    """Concrete DeviceState used for tests."""

    def __init__(self, device: DummyDevice, initial: dict[str, Any]) -> None:
        """Initialize the sample state wrapper."""

        super().__init__(device=device, name="power", initial_value=initial)

    def parse_state(self, data: dict[str, Any]) -> None:
        """Update internal state from payload data."""

        state = data.get("state")
        if state is not None:
            self._update_state(state)


class CommandableState(DeviceState[dict[str, Any]]):
    """Concrete DeviceState with command mapping."""

    def __init__(
        self,
        device: DummyDevice,
        initial: dict[str, Any],
        *,
        state_to_command,
    ) -> None:
        """Initialize the commandable state wrapper."""

        super().__init__(
            device=device,
            name="power",
            initial_value=initial,
            state_to_command=state_to_command,
        )

    def parse_state(self, data: dict[str, Any]) -> None:
        """Update state using commandable payloads."""

        state = data.get("state")
        if state is not None:
            self._update_state(state)


class RecordingOpState(DeviceOpState[dict[str, Any]]):
    """DeviceOpState subclass that records parsing invocations."""

    def __init__(
        self,
        device: DummyDevice,
        initial: dict[str, Any],
        *,
        parse_option: ParseOption,
        op_type: int,
        identifier: list[int],
        state_to_command=None,
    ) -> None:
        """Initialize the recording op state wrapper."""

        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifier},
            device=device,
            name="power",
            initial_value=initial,
            parse_option=parse_option,
            state_to_command=state_to_command,
        )
        self.op_calls: list[list[int]] = []
        self.multi_calls: list[list[list[int]]] = []

    def parse_state(self, data: dict[str, Any]) -> None:
        """Record state payload updates."""

        state = data.get("state")
        if state is not None:
            self._update_state(state)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Record a parsed opcode command."""

        self.op_calls.append(op_command)

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Record a batch of opcode commands."""

        self.multi_calls.append(op_commands)


def test_previous_state_reverts_to_prior_value() -> None:
    """previous_state pops from the fixed-length history stack."""

    device = DummyDevice()
    state = SampleState(device, {"power": "off"})

    state._update_state({"power": "on"})
    state._update_state({"power": "dim"})
    state._update_state({"power": "boost"})

    assert state.value == {"power": "boost"}

    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))

    state.previous_state()

    assert state.value == {"power": "dim"}


def test_set_state_tracks_pending_and_clears_on_status_match() -> None:
    """set_state enqueues commands and clears them when the status matches."""

    device = DummyDevice()

    def to_command(value: dict[str, Any]):
        return {
            "command": {
                "name": "set_power",
                "payload": [0x01],
            },
            "status": {
                "state": value,
            },
        }

    state = CommandableState(device, {"power": "off"}, state_to_command=to_command)

    command_ids = state.set_state({"power": "on"})

    assert len(command_ids) == 1

    dispatched = state.command_queue.get_nowait()
    assert dispatched["command_id"] == command_ids[0]
    assert dispatched["name"] == "set_power"

    state.parse({"cmd": "status", "state": {"power": "on"}})

    cleared = state.clear_queue.get_nowait()
    assert cleared["command_id"] == command_ids[0]
    assert cleared["state"] == "power"


def test_op_state_state_only_skips_opcode_parsing() -> None:
    """When configured for state parsing, opcode data is ignored."""

    device = DummyDevice()
    state = RecordingOpState(
        device,
        {"power": "off"},
        parse_option=ParseOption.STATE,
        op_type=0x33,
        identifier=[0x01],
    )

    state.parse({"cmd": "status", "state": {"power": "on"}, "op": {"command": [[0x33, 0x01, 0x02]]}})

    assert state.value == {"power": "on"}
    assert state.op_calls == []
    assert state.multi_calls == []


def test_op_state_opcode_parsing_clears_matching_pending() -> None:
    """Opcode parsing emits clear events when commands match."""

    device = DummyDevice()

    def to_command(_: dict[str, Any]):
        return {
            "command": {"name": "set_mode", "payload": [0x33, 0x01, 0x02]},
            "status": {"op": {"command": [[0x33, 0x01, None]]}},
        }

    state = RecordingOpState(
        device,
        {"power": "off"},
        parse_option=ParseOption.OP_CODE,
        op_type=0x33,
        identifier=[0x01],
        state_to_command=to_command,
    )

    command_ids = state.set_state({"power": "on"})

    assert state.command_queue.get_nowait()["command_id"] == command_ids[0]

    state.parse({"op": {"command": [[0x33, 0x01, 0xFF]]}})

    assert state.op_calls == [[0x33, 0x01, 0xFF]]
    cleared = state.clear_queue.get_nowait()
    assert cleared["command_id"] == command_ids[0]


def test_op_state_multi_op_parsing_batches_commands() -> None:
    """Multi-op parsing groups commands when the flag is set."""

    device = DummyDevice()
    state = RecordingOpState(
        device,
        {"power": "off"},
        parse_option=ParseOption.MULTI_OP,
        op_type=0x40,
        identifier=[-1],
    )

    payload = {
        "op": {"command": [[0x40, 0x01, 0x02], [0x41, 0x03, 0x04]]}
    }

    state.parse(payload)

    assert state.multi_calls == [[[0x40, 0x01, 0x02], [0x41, 0x03, 0x04]]]
