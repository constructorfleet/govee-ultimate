import asyncio
from typing import Any, Dict, List

import pytest

from custom_components.govee_ultimate.state.device_state import (
    DeviceOpState,
    DeviceState,
    ParseOption,
    filter_commands,
)


class SimpleState(DeviceState[str, Dict[str, Any]]):
    def __init__(self, initial: Dict[str, Any]):
        super().__init__(
            name="power",
            initial_value=initial,
            history_size=3,
            state_to_command=self._state_to_command,
        )

    def set_current(self, value: Dict[str, Any]) -> None:
        self._update_value(value)

    def _state_to_command(self, value: Dict[str, Any]):
        return {
            "command": {
                "cmd": "setPower",
                "payload": value,
            },
            "status": {"state": value},
        }


@pytest.mark.asyncio
async def test_device_state_previous_state_uses_history_and_returns_command_ids():
    state = SimpleState({"power": "off"})
    state.set_current({"power": "dim"})
    state.set_current({"power": "on"})
    state.set_current({"power": "max"})

    command_ids = state.previous_state(last=2)
    assert len(command_ids) == 1

    command = state.command_queue.get_nowait()
    assert command["commandId"] == command_ids[0]
    assert command["cmd"] == "setPower"
    assert command["payload"] == {"power": "dim"}

    pending = state.pending_commands[command_ids[0]]
    assert pending == [{"state": {"power": "dim"}}]
    # history should retain at most the configured size
    assert state.history.size() <= 3


@pytest.mark.asyncio
async def test_pending_command_cleared_when_matching_status_received():
    state = SimpleState({"power": "off"})
    cleared: List[Dict[str, Any]] = []
    state.add_clear_command_callback(lambda result: cleared.append(result))

    command_ids = state.set_state({"power": "on"})
    assert command_ids
    command_id = command_ids[0]

    state.parse({"cmd": "status", "state": {"power": "on"}})

    assert command_id not in state.pending_commands
    assert cleared == [
        {"commandId": command_id, "state": "power", "value": state.value}
    ]


def test_device_op_state_parse_option_state_only():
    class RecordingState(DeviceOpState[str, Dict[str, Any]]):
        def __init__(self):
            super().__init__(
                {"opType": 7, "identifier": [1]},
                name="mode",
                initial_value={"mode": "auto"},
                parse_option=ParseOption.STATE,
            )
            self.state_calls: List[Dict[str, Any]] = []
            self.op_calls: List[List[int]] = []
            self.multi_calls: List[List[List[int]]] = []

        def parse_state(self, data: Dict[str, Any]) -> None:
            self.state_calls.append(data)

        def parse_op_command(self, op_command: List[int]) -> None:
            self.op_calls.append(op_command)

        def parse_multi_op_command(self, op_commands: List[List[int]]) -> None:
            self.multi_calls.append(op_commands)

    recording = RecordingState()
    recording.parse(
        {
            "cmd": "status",
            "state": {"mode": "manual"},
            "op": {"command": [[7, 1, 2]]},
        }
    )

    assert recording.state_calls == [
        {"cmd": "status", "state": {"mode": "manual"}, "op": {"command": [[7, 1, 2]]}}
    ]
    assert recording.op_calls == []
    assert recording.multi_calls == []


def test_device_op_state_parse_option_op_code():
    class RecordingState(DeviceOpState[str, Dict[str, Any]]):
        def __init__(self):
            super().__init__(
                {"opType": 7, "identifier": [1]},
                name="mode",
                initial_value={"mode": "auto"},
                parse_option=ParseOption.OP_CODE,
            )
            self.op_calls: List[List[int]] = []

        def parse_op_command(self, op_command: List[int]) -> None:
            self.op_calls.append(op_command)

    recording = RecordingState()
    recording.parse({"op": {"command": [[7, 1, 2], [6, 1, 3]]}})

    assert recording.op_calls == [[7, 1, 2]]


def test_device_op_state_parse_option_multi_op():
    class RecordingState(DeviceOpState[str, Dict[str, Any]]):
        def __init__(self):
            super().__init__(
                {"opType": 7, "identifier": [1]},
                name="mode",
                initial_value={"mode": "auto"},
                parse_option=ParseOption.MULTI_OP,
            )
            self.multi_calls: List[List[List[int]]] = []

        def parse_multi_op_command(self, op_commands: List[List[int]]) -> None:
            self.multi_calls.append(op_commands)

    recording = RecordingState()
    recording.parse({"op": {"command": [[7, 1, 2], [7, 1, 4], [6, 1, 3]]}})

    assert recording.multi_calls == [[[7, 1, 2], [7, 1, 4]]]


def test_filter_commands_strips_op_headers():
    commands = [[7, 1, 2], [7, 1, 4], [6, 1, 3]]
    assert filter_commands(commands, type=7, identifier=[1]) == [[2], [4]]
    assert filter_commands(commands, type=None) == commands
