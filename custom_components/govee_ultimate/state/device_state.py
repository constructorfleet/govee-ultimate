"""Async-friendly device state helpers."""

from __future__ import annotations

import asyncio
from enum import IntFlag, auto
from typing import Any, Generic, TypeVar
from collections.abc import Callable
from collections.abc import Sequence

from uuid import uuid4
from collections.abc import Mapping

T = TypeVar("T")


class ParseOption(IntFlag):
    """Bit flags describing which parts of a status payload should be parsed."""

    OP_CODE = auto()
    MULTI_OP = auto()
    STATE = auto()
    NONE = auto()

    def has_flag(self, option: ParseOption) -> bool:
        """Return True when the provided option is present."""

        return bool(self & option)


class FixedLengthHistory(Generic[T]):
    """Maintain a bounded history of state values for backtracking."""

    def __init__(self, capacity: int) -> None:
        """Initialize the history storage."""

        self._capacity = capacity
        self._items: list[T] = []

    def enstack(self, value: T) -> None:
        """Push a new value onto the history stack, trimming as needed."""

        self._items.append(value)
        if len(self._items) > self._capacity:
            self._items.pop(0)

    def destack(self) -> T | None:
        """Drop the most recent value and return the next newest entry."""

        if not self._items:
            return None
        self._items.pop()
        if not self._items:
            return None
        return self._items[-1]


CommandPayload = dict[str, Any]
StatusSnapshot = dict[str, Any]
StateCommand = CommandPayload | Sequence[CommandPayload]
StateStatus = StatusSnapshot | Sequence[StatusSnapshot]
StateCommandAndStatus = dict[str, StateCommand | StateStatus]
OpIdentifier = dict[str, Any]


class DeviceState(Generic[T]):
    """Base class for device state handling."""

    history_size = 5

    def __init__(
        self,
        *,
        device: object,
        name: str,
        initial_value: T,
        parse_option: ParseOption = ParseOption.STATE,
        state_to_command: Callable[[T], StateCommandAndStatus | None] | None = None,
    ) -> None:
        """Initialize the device state wrapper."""

        self.device = device
        self.name = name
        self._value = initial_value
        self.parse_option = parse_option
        self._history: FixedLengthHistory[T] = FixedLengthHistory(self.history_size)
        self._history.enstack(initial_value)
        self.command_queue: asyncio.Queue[CommandPayload] = asyncio.Queue()
        self.clear_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending_commands: dict[str, list[StatusSnapshot]] = {}
        self._state_to_command = state_to_command

    @property
    def value(self) -> T:
        """Return the latest state value."""

        return self._value

    @property
    def is_commandable(self) -> bool:
        """Return True when the state exposes a command mapping."""

        return self._state_to_command is not None

    def _update_state(self, value: T) -> None:
        """Update the stored value and record the new history entry."""

        self._value = value
        self._history.enstack(value)

    def _rewind_history(self, count: int) -> T | None:
        """Remove ``count`` entries and return the latest remaining value."""

        state: T | None = None
        while count > 0:
            state = self._history.destack()
            count -= 1
        return state

    def previous_state(self, last: int = 1) -> list[str]:
        """Re-emit a previous state value from history."""

        state = self._rewind_history(last)
        if state is None:
            return []
        self._update_state(state)
        return []

    def set_state(self, next_state: T) -> list[str]:
        """Translate ``next_state`` into commands and enqueue them."""

        if self._state_to_command is None:
            return []
        command_and_status = self._state_to_command(next_state)
        if not command_and_status:
            return []
        command_spec = command_and_status.get("command")
        status_spec = command_and_status.get("status")
        if command_spec is None or status_spec is None:
            return []
        commands = self._as_list(command_spec)
        statuses = self._as_list(status_spec)
        command_id = str(uuid4())
        self._pending_commands[command_id] = statuses
        command_ids: list[str] = []
        for payload in commands:
            command = dict(payload)
            command["command_id"] = command_id
            self.command_queue.put_nowait(command)
            command_ids.append(command_id)
        return command_ids

    def _as_list(self, value: StateCommand | StateStatus) -> list[Any]:
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | Mapping):
            return list(value)
        return [value]

    def _match_partial(self, expected: Any, actual: Any) -> bool:
        if expected is None:
            return True
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                return False
            for key, value in expected.items():
                if key not in actual:
                    return False
                if not self._match_partial(value, actual[key]):
                    return False
            return True
        if isinstance(expected, Sequence) and not isinstance(
            expected, str | bytes | Mapping
        ):
            if not isinstance(actual, Sequence) or isinstance(actual, str | bytes):
                return False
            actual_list = list(actual)
            if len(actual_list) < len(expected):
                return False
            return all(
                self._match_partial(exp, actual_list[idx])
                for idx, exp in enumerate(expected)
            )
        return expected == actual

    def _find_matching_command(self, data: dict[str, Any]) -> str | None:
        state_payload = data.get("state")
        for command_id, statuses in list(self._pending_commands.items()):
            for status in statuses:
                expected_state = status.get("state")
                if expected_state is not None and self._match_partial(
                    expected_state, state_payload
                ):
                    return command_id
        return None

    def _emit_clear_event(self, command_id: str) -> None:
        self.clear_queue.put_nowait(
            {"command_id": command_id, "state": self.name, "value": self.value}
        )

    def _clear_pending(self, command_id: str) -> None:
        self._pending_commands.pop(command_id, None)
        self._emit_clear_event(command_id)

    def expire_pending_commands(self, command_ids: Sequence[str]) -> None:
        """Remove ``command_ids`` from pending tracking and emit clear events."""

        for command_id in command_ids:
            if command_id in self._pending_commands:
                self._clear_pending(command_id)

    def parse_state(
        self, data: dict[str, object]
    ) -> None:  # pragma: no cover - override hook
        """Parse state payloads for subclasses."""

    def parse(self, data: dict[str, object]) -> None:
        """Entry point for processing status messages."""

        if data.get("cmd") and data.get("cmd") != "status":
            return
        command_id = (
            self._find_matching_command(data) if self._pending_commands else None
        )
        if self.parse_option.has_flag(ParseOption.STATE):
            self.parse_state(data)
        if command_id is not None:
            self._clear_pending(command_id)


class DeviceOpState(DeviceState[T]):
    """Device state that also processes opcode responses."""

    def __init__(
        self,
        *,
        op_identifier: OpIdentifier,
        device: object,
        name: str,
        initial_value: T,
        parse_option: ParseOption = ParseOption.OP_CODE,
        state_to_command: Callable[[T], StateCommandAndStatus | None] | None = None,
    ) -> None:
        """Initialize the opcode-aware state wrapper."""

        super().__init__(
            device=device,
            name=name,
            initial_value=initial_value,
            parse_option=parse_option,
            state_to_command=state_to_command,
        )
        self._op_type: int | None = op_identifier.get("op_type")
        identifier = op_identifier.get("identifier")
        self._identifier: list[int] | None = (
            list(identifier) if identifier is not None else None
        )

    def parse_op_command(
        self, op_command: list[int]
    ) -> None:  # pragma: no cover - hook
        """Handle a single opcode command."""

    def parse_multi_op_command(
        self, op_commands: list[list[int]]
    ) -> None:  # pragma: no cover
        """Handle multiple opcode commands."""

    def parse(self, data: dict[str, Any]) -> None:
        """Process opcode and state payloads according to parse options."""

        if self.parse_option.has_flag(ParseOption.NONE):
            return
        commands = data.get("op", {}).get("command") or []
        filtered_commands = self._filter_op_commands(commands)
        if commands:
            if self.parse_option.has_flag(ParseOption.OP_CODE):
                for command in filtered_commands:
                    command_id = self._match_pending_op(command)
                    self.parse_op_command(command)
                    if command_id is not None:
                        self._clear_pending(command_id)
            elif self.parse_option.has_flag(ParseOption.MULTI_OP):
                command_list = [list(command) for command in commands]
                if command_list:
                    matching_ids = self._match_pending_multi_op(command_list)
                    self.parse_multi_op_command(command_list)
                    for command_id in matching_ids:
                        self._clear_pending(command_id)
        super().parse(data)

    def _filter_op_commands(self, commands: Sequence[Sequence[int]]) -> list[list[int]]:
        if self._op_type is None:
            return [list(command) for command in commands]
        filtered: list[list[int]] = []
        for command in commands:
            sequence = list(command)
            if not sequence:
                continue
            if sequence[0] != self._op_type:
                continue
            if self._identifier is None:
                filtered.append(sequence)
                continue
            if all(
                idx + 1 < len(sequence)
                and (identifier < 0 or sequence[idx + 1] == identifier)
                for idx, identifier in enumerate(self._identifier)
            ):
                filtered.append(sequence)
        return filtered

    def _match_pending_op(self, command: Sequence[int]) -> str | None:
        for command_id, statuses in list(self._pending_commands.items()):
            for status in statuses:
                expected = status.get("op", {}).get("command")
                if expected and self._match_op_sequence(expected[0], command):
                    return command_id
        return None

    def _match_pending_multi_op(self, commands: list[list[int]]) -> list[str]:
        matched: list[str] = []
        for command_id, statuses in list(self._pending_commands.items()):
            for status in statuses:
                expected = status.get("op", {}).get("command")
                if expected and any(
                    self._match_op_sequence(expected[0], command)
                    for command in commands
                ):
                    matched.append(command_id)
                    break
        return matched

    def _match_op_sequence(
        self, expected: Sequence[int | None], actual: Sequence[int]
    ) -> bool:
        if len(actual) < len(expected):
            return False
        for idx, expected_value in enumerate(expected):
            if expected_value is None or (
                isinstance(expected_value, int) and expected_value < 0
            ):
                continue
            if actual[idx] != expected_value:
                return False
        return True
