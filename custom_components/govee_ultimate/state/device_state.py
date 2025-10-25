"""Async device state management primitives for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Flag, auto
from typing import Any, Callable, Deque, Dict, Generic, List, Optional, Sequence, TypeVar, Union

StateNameT = TypeVar("StateNameT", bound=str)
StateValueT = TypeVar("StateValueT")


class ParseOption(Flag):
    """Bit flags mirroring the TypeScript ParseOption enum."""

    OP_CODE = auto()
    MULTI_OP = auto()
    STATE = auto()
    NONE = auto()

    def has_flag(self, other: "ParseOption") -> bool:
        return bool(self & other)


CommandDict = Dict[str, Any]
StatusDict = Dict[str, Any]


def _normalize_status(status: Union[StatusDict, Sequence[StatusDict]]) -> List[StatusDict]:
    if isinstance(status, Sequence) and not isinstance(status, (dict, str, bytes, bytearray)):
        return [dict(item) for item in status]  # type: ignore[arg-type]
    return [dict(status)]  # type: ignore[list-item]


def _normalize_commands(command: Union[CommandDict, Sequence[CommandDict]]) -> List[CommandDict]:
    if isinstance(command, Sequence) and not isinstance(command, (dict, str, bytes, bytearray)):
        return [dict(cmd) for cmd in command]  # copy each command mapping
    return [dict(command)]  # type: ignore[list-item]


class FixedLengthStack(Generic[StateValueT]):
    """A LIFO stack with a fixed capacity, mirroring the TS implementation."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be greater than 0")
        self._items: Deque[StateValueT] = deque(maxlen=max_size)

    def enstack(self, item: StateValueT) -> None:
        self._items.appendleft(item)

    def destack(self) -> Optional[StateValueT]:
        if not self._items:
            return None
        return self._items.popleft()

    def peek(self) -> Optional[StateValueT]:
        return self._items[0] if self._items else None

    def peek_all(self) -> List[StateValueT]:
        return list(self._items)

    def size(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


@dataclass
class _Subscription:
    callback: Callable[[StateValueT], None]
    listeners: List[Callable[[StateValueT], None]]

    def unsubscribe(self) -> None:
        try:
            self.listeners.remove(self.callback)
        except ValueError:
            pass


def deep_partial_compare(expected: Any, actual: Any) -> bool:
    """Recursively compare partial structures."""

    if expected is None:
        # None mirrors the JS undefined wildcard in this context.
        return True
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, value in expected.items():
            if key not in actual:
                return False
            if not deep_partial_compare(value, actual[key]):
                return False
        return True
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes, bytearray)):
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes, bytearray)):
            return False
        if len(actual) < len(expected):
            return False
        return all(deep_partial_compare(exp_item, actual[idx]) for idx, exp_item in enumerate(expected))
    return expected == actual


def filter_commands(
    commands: Sequence[Sequence[int]],
    *,
    type: Optional[int] = None,
    identifier: Optional[Union[int, Sequence[int]]] = None,
) -> List[List[int]]:
    """Filter commands according to op type and identifier rules."""

    results: List[List[int]] = []
    for command in commands:
        if type is None:
            results.append(list(command))
            continue
        identifiers: Optional[List[int]]
        if identifier is None:
            identifiers = None
        elif isinstance(identifier, Sequence) and not isinstance(identifier, (str, bytes, bytearray)):
            identifiers = list(identifier)
        else:
            identifiers = [int(identifier)]
        expected_slice_length = 1 + (len(identifiers) if identifiers is not None else 0)
        segment = list(command[:expected_slice_length])
        if not segment:
            continue
        cmd_type, *cmd_identifiers = segment
        if cmd_type != type:
            continue
        if identifiers is None:
            continue
        if not all(
            idx < len(cmd_identifiers) and (identifiers[idx] < 0 or cmd_identifiers[idx] == identifiers[idx])
            for idx in range(len(identifiers))
        ):
            continue
        drop = 1 + (1 if isinstance(identifier, int) else len(identifiers))
        results.append(list(command[drop:]))
    return results


ClearCallback = Callable[[Dict[str, Any]], None]


class DeviceState(Generic[StateNameT, StateValueT]):
    """Mirror of the TypeScript DeviceState using asyncio primitives."""

    def __init__(
        self,
        *,
        name: StateNameT,
        initial_value: StateValueT,
        parse_option: ParseOption = ParseOption.STATE,
        state_to_command: Optional[
            Callable[[StateValueT], Optional[Dict[str, Any]]]
        ] = None,
        history_size: int = 5,
    ) -> None:
        self.name = name
        self._parse_option = parse_option
        self._state_to_command = state_to_command
        self.history: FixedLengthStack[StateValueT] = FixedLengthStack(history_size)
        self.history.enstack(initial_value)
        self._value = initial_value
        self._listeners: List[Callable[[StateValueT], None]] = []
        self.command_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self.pending_commands: Dict[str, List[Dict[str, Any]]] = {}
        self._clear_callbacks: List[ClearCallback] = []
        # Immediately record initial state in history for parity with TS behaviour.
        self._notify_listeners(initial_value)

    @property
    def value(self) -> StateValueT:
        return self._value

    @property
    def is_commandable(self) -> bool:
        return self._state_to_command is not None

    def subscribe(self, callback: Callable[[StateValueT], None]) -> _Subscription:
        self._listeners.append(callback)
        callback(self._value)
        return _Subscription(callback, self._listeners)

    def add_clear_command_callback(self, callback: ClearCallback) -> None:
        self._clear_callbacks.append(callback)

    def _notify_listeners(self, value: StateValueT) -> None:
        for listener in list(self._listeners):
            try:
                listener(value)
            except Exception:
                # Align with RxJS behaviour where subscriber errors do not break the stream.
                continue

    def _update_value(self, value: StateValueT) -> None:
        if self.history.peek() != self._value:
            self.history.enstack(self._value)
        self._value = value
        self._notify_listeners(value)

    def _status_matches(self, expected: Dict[str, Any], message: Dict[str, Any]) -> bool:
        if "state" in expected and "state" in message:
            if deep_partial_compare(expected["state"], message["state"]):
                return True
        if "op" in expected and "op" in message:
            expected_command = _extract_expected_op_command(expected)
            message_commands = message.get("op", {}).get("command")
            if expected_command is not None and isinstance(message_commands, Sequence):
                for command in message_commands:
                    if isinstance(command, Sequence) and _op_command_matches(expected_command, command):
                        return True
        return False

    def _find_matching_command_id(self, message: Dict[str, Any]) -> Optional[str]:
        for command_id, statuses in self.pending_commands.items():
            if any(self._status_matches(status, message) for status in statuses):
                return command_id
        return None

    def _clear_pending(self, command_id: str) -> None:
        if command_id in self.pending_commands:
            del self.pending_commands[command_id]
        result = {"commandId": command_id, "state": self.name, "value": self.value}
        for callback in list(self._clear_callbacks):
            callback(result)

    def parse_state(self, data: Dict[str, Any]) -> None:  # pragma: no cover - meant for overrides
        return

    def parse(self, data: Dict[str, Any]) -> None:
        if data.get("cmd") and data.get("cmd") != "status":
            return
        command_id = self._find_matching_command_id(data)
        self.parse_state(data)
        if command_id is not None:
            self._clear_pending(command_id)

    def set_state(self, next_state: StateValueT) -> List[str]:
        if self._state_to_command is None:
            return []
        mapping = self._state_to_command(next_state)
        if not mapping:
            return []
        command_payload = mapping.get("command")
        status_payload = mapping.get("status")
        if command_payload is None or status_payload is None:
            return []
        command_id = str(uuid.uuid4())
        commands = _normalize_commands(command_payload)
        statuses = _normalize_status(status_payload)
        self.pending_commands[command_id] = statuses
        command_ids: List[str] = []
        for command in commands:
            enriched = dict(command)
            enriched["commandId"] = command_id
            self.command_queue.put_nowait(enriched)
            command_ids.append(command_id)
        return command_ids

    def previous_state(self, last: int = 1) -> List[str]:
        state: Optional[StateValueT] = None
        remaining = max(last, 0)
        while remaining > 0:
            state = self.history.destack()
            remaining -= 1
        if state is None:
            return []
        return self.set_state(state)


def _op_command_matches(expected: Sequence[Optional[int]], actual: Sequence[int]) -> bool:
    for index, expected_value in enumerate(expected):
        if index >= len(actual):
            return False
        if expected_value is None:
            continue
        if expected_value < 0:
            continue
        if actual[index] != expected_value:
            return False
    return True


def _extract_expected_op_command(status: Dict[str, Any]) -> Optional[Sequence[Optional[int]]]:
    op = status.get("op")
    if not isinstance(op, dict):
        return None
    commands = op.get("command")
    if not isinstance(commands, Sequence) or not commands:
        return None
    first_command = commands[0]
    if not isinstance(first_command, Sequence):
        return None
    return first_command  # type: ignore[return-value]


class DeviceOpState(DeviceState[StateNameT, StateValueT]):
    """State variant that can parse op-code responses."""

    def __init__(
        self,
        identifiers: Dict[str, Any],
        *,
        name: StateNameT,
        initial_value: StateValueT,
        parse_option: ParseOption = ParseOption.OP_CODE,
        state_to_command: Optional[
            Callable[[StateValueT], Optional[Dict[str, Any]]]
        ] = None,
        history_size: int = 5,
    ) -> None:
        super().__init__(
            name=name,
            initial_value=initial_value,
            parse_option=parse_option,
            state_to_command=state_to_command,
            history_size=history_size,
        )
        self.op_type: Optional[int] = identifiers.get("opType")
        identifier_value = identifiers.get("identifier")
        if identifier_value is None:
            self.identifier: Optional[List[int]] = None
        elif isinstance(identifier_value, Sequence) and not isinstance(identifier_value, (str, bytes, bytearray)):
            self.identifier = list(identifier_value)
        else:
            self.identifier = [int(identifier_value)]

    def parse_op_command(self, op_command: Sequence[int]) -> None:  # pragma: no cover - override hook
        return

    def parse_multi_op_command(self, op_commands: Sequence[Sequence[int]]) -> None:  # pragma: no cover - override hook
        return

    def filter_op_commands(self, commands: Sequence[Sequence[int]]) -> List[List[int]]:
        if self.op_type is None:
            return [list(command) for command in commands]
        return filter_commands(commands, type=self.op_type, identifier=self.identifier)

    def _augment_command(self, command: Sequence[int]) -> List[int]:
        if self.op_type is None:
            return list(command)
        header: List[int] = [self.op_type]
        if self.identifier is not None:
            header.extend(self.identifier)
        return header + list(command)

    def _matching_op_command_ids(self, commands: Sequence[Sequence[int]]) -> List[str]:
        matches: List[str] = []
        for command_id, statuses in self.pending_commands.items():
            for status in statuses:
                if not isinstance(status, dict):
                    continue
                expected_command = _extract_expected_op_command(status)
                if expected_command is None:
                    continue
                if any(_op_command_matches(expected_command, cmd) for cmd in commands):
                    matches.append(command_id)
                    break
        return matches

    def parse(self, data: Dict[str, Any]) -> None:
        if self._parse_option.has_flag(ParseOption.NONE):
            return
        commands = data.get("op", {}).get("command") or []
        filtered_commands = self.filter_op_commands(commands)
        callback_commands = [
            self._augment_command(command) for command in filtered_commands
        ] if filtered_commands else []
        if commands:
            if self._parse_option.has_flag(ParseOption.OP_CODE):
                for original, command in zip(callback_commands, filtered_commands):
                    command_ids = self._matching_op_command_ids([command])
                    self.parse_op_command(original)
                    for command_id in command_ids:
                        self._clear_pending(command_id)
            elif self._parse_option.has_flag(ParseOption.MULTI_OP):
                if filtered_commands:
                    command_ids = self._matching_op_command_ids(filtered_commands)
                    self.parse_multi_op_command(callback_commands)
                    for command_id in command_ids:
                        self._clear_pending(command_id)
        if self._parse_option.has_flag(ParseOption.STATE):
            super().parse(data)
