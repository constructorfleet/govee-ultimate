"""Concrete device state implementations backed by the catalog."""

from __future__ import annotations

import base64
import datetime as dt
import itertools
import json
import logging

from collections.abc import Callable, Mapping, Sequence
from enum import Enum, IntEnum
from functools import cache
from typing import Any

from .. import opcodes

from ..state_catalog import CommandTemplate, StateEntry, load_state_catalog
from .device_state import (
    DeviceOpState,
    DeviceState,
    ParseOption,
    StateCommandAndStatus,
)


_LOGGER = logging.getLogger(__name__)


def _chunk(values: Sequence[int], size: int) -> list[list[int]]:
    """Return ``values`` split into ``size`` sized chunks."""

    return [list(values[idx : idx + size]) for idx in range(0, len(values), size)]


def _total(bytes_: Sequence[int]) -> int:
    """Interpret ``bytes_`` as a big endian integer."""

    result = 0
    for value in bytes_:
        result = (result << 8) | (value & 0xFF)
    return result


def _flatten_commands(commands: Sequence[Sequence[int]]) -> list[int]:
    """Return a flattened copy of the opcode command sequences."""

    return list(itertools.chain.from_iterable(commands))


def _probe_readings(commands: Sequence[Sequence[int]]) -> list[list[int]]:
    """Return probe readings extracted from ``commands``."""

    flattened = _flatten_commands(commands)
    if len(flattened) <= 10:
        return []
    payload = flattened[10:]
    readings = _chunk(payload, 9)
    return [reading for reading in readings if len(reading) == 9]


def _get_probe_reading(
    commands: Sequence[Sequence[int]], probe: int
) -> list[int] | None:
    """Return the reading for ``probe`` from ``commands`` when available."""

    readings = _probe_readings(commands)
    index = probe - 1
    if index < 0 or index >= len(readings):
        return None
    return readings[index]


def _first_command(op_commands: Sequence[Sequence[int]]) -> list[int]:
    """Return the first opcode command when present."""

    if not op_commands:
        return []
    return list(op_commands[0])


class ProbeTempState(DeviceOpState[float | None]):
    """Expose probe temperature readings for meat thermometers."""

    def __init__(
        self,
        *,
        device: object,
        probe: int,
        default_state: float | None = None,
    ) -> None:
        """Track temperatures for ``probe`` using aggregated opcode payloads."""

        super().__init__(
            op_identifier={"op_type": None},
            device=device,
            name=f"probeTemp{probe}",
            initial_value=default_state,
            parse_option=ParseOption.MULTI_OP,
        )
        self._probe = probe

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Convert multi-op payloads into a float temperature reading."""

        reading = _get_probe_reading(op_commands, self._probe)
        if reading is None:
            return
        if len(reading) < 2:
            return
        temperature = _total(reading[:2]) / 100
        self._update_state(temperature)


class BuzzerState(DeviceOpState[bool | None]):
    """Expose the hardware buzzer enable flag."""

    def __init__(
        self,
        *,
        device: object,
        default_state: bool | None = None,
    ) -> None:
        """Initialise the buzzer state wrapper."""

        super().__init__(
            op_identifier={"op_type": None},
            device=device,
            name="buzzer",
            initial_value=default_state,
            parse_option=ParseOption.MULTI_OP,
        )

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Map header byte to a boolean buzzer flag."""

        op_command = _first_command(op_commands)
        if len(op_command) <= 6:
            return
        flag = op_command[6]
        if flag in (0, 1):
            self._update_state(flag == 1)


class TemperatureUnitState(DeviceOpState[str | None]):
    """Report the preferred temperature unit for the device."""

    def __init__(
        self,
        *,
        device: object,
        default_state: str | None = None,
    ) -> None:
        """Initialise the temperature unit tracker."""

        super().__init__(
            op_identifier={"op_type": None},
            device=device,
            name="temperatureUnit",
            initial_value=default_state,
            parse_option=ParseOption.MULTI_OP,
        )

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Decode the Fahrenheit/Celsius flag from the header."""

        op_command = _first_command(op_commands)
        if len(op_command) <= 2:
            return
        self._update_state("F" if op_command[2] == 1 else "C")


class EarlyWarningOffset(str, Enum):
    """Enumeration of supported early warning offsets."""

    OFF = "OFF"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EarlyWarningState(DeviceOpState[dict[str, Any] | None]):
    """Decode early warning enablement and offset configuration."""

    _VALID_FLAGS = {0, 1, 3, 5}
    _OFFSET_MAP = {
        0: EarlyWarningOffset.OFF,
        1: EarlyWarningOffset.LOW,
        3: EarlyWarningOffset.MEDIUM,
        5: EarlyWarningOffset.HIGH,
    }

    def __init__(
        self,
        *,
        device: object,
        default_state: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the early warning configuration tracker."""

        super().__init__(
            op_identifier={"op_type": None},
            device=device,
            name="earlyWarning",
            initial_value=default_state,
            parse_option=ParseOption.MULTI_OP,
        )

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Map header bytes to structured early warning metadata."""

        op_command = _first_command(op_commands)
        if len(op_command) <= 4:
            return
        enabled_flag = op_command[3]
        if enabled_flag not in self._VALID_FLAGS:
            return
        setting = self._OFFSET_MAP.get(op_command[4], EarlyWarningOffset.OFF)
        self._update_state(
            {
                "enabled": enabled_flag != 0,
                "setting": setting,
            }
        )


_FOOD_MAP: dict[int, str] = {
    0: "BEEF",
    1: "LAMB",
    2: "PORK",
    3: "POULTRY",
    4: "TURKEY",
    5: "FISH",
    6: "DIY",
    7: "VEAL",
    8: "SAUSAGE",
    9: "HAM",
    10: "SHRIMP",
    11: "POTATO",
    12: "CUPCAKE",
    13: "EGG",
}

_DIY_DONE_LEVEL = {1: "LOW", 2: "HIGH", 3: "RANGE"}
_SAUSAGE_HAM_DONE_LEVEL = {1: "RAW", 2: "PRE_COOKER"}
_PORK_DONE_LEVEL = {1: "MEDIUM", 2: "WELL_DONE"}
_MEAT_DONE_LEVEL = {
    1: "RARE",
    2: "MEDIUM_RARE",
    3: "MEDIUM",
    4: "MEDIUM_WELL",
    5: "WELL_DONE",
}
_REFERENCE_DONE_LEVEL = {1: "REFERENCE"}

_DONE_LEVEL_MAP: dict[str, dict[int, str]] = {
    "DIY": _DIY_DONE_LEVEL,
    "SAUSAGE": _SAUSAGE_HAM_DONE_LEVEL,
    "HAM": _SAUSAGE_HAM_DONE_LEVEL,
    "PORK": _PORK_DONE_LEVEL,
    "BEEF": _MEAT_DONE_LEVEL,
    "LAMB": _MEAT_DONE_LEVEL,
    "VEAL": _MEAT_DONE_LEVEL,
}


class PresetState(DeviceOpState[dict[str, Any] | None]):
    """Represent preset alarm and doneness configuration per probe."""

    options: tuple[str, ...] = tuple(
        _FOOD_MAP[key] for key in sorted(_FOOD_MAP)  # type: ignore[index]
    )

    def __init__(
        self,
        *,
        device: object,
        probe: int,
        default_state: dict[str, Any] | None = None,
    ) -> None:
        """Initialise preset decoding for ``probe``."""

        super().__init__(
            op_identifier={"op_type": None},
            device=device,
            name=f"preset{probe}",
            initial_value=default_state,
            parse_option=ParseOption.MULTI_OP,
        )
        self._probe = probe

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Decode preset metadata from the aggregated payload."""

        reading = _get_probe_reading(op_commands, self._probe)
        if reading is None:
            return
        if len(reading) < 9:
            return
        alarm_high = _total(reading[2:4]) / 100
        alarm_low = _total(reading[4:6]) / 100
        food = _FOOD_MAP.get(reading[6])
        done_lookup = _REFERENCE_DONE_LEVEL
        if food is not None and food in _DONE_LEVEL_MAP:
            done_lookup = _DONE_LEVEL_MAP[food]
        done_level = done_lookup.get(reading[8])
        state: dict[str, Any] = {
            "food": food,
            "alarm": {"high": alarm_high, "low": alarm_low},
            "doneLevel": done_level,
        }
        self._update_state(state)


_REPORT_OPCODE = 0xAA


def _match_identifier_tail(identifier: Sequence[int], active: Sequence[int]) -> bool:
    """Return True when ``active`` matches the trailing portion of ``identifier``."""

    if not active:
        return False
    if len(identifier) < len(active):
        return False
    tail = identifier[-len(active) :]
    return all(candidate == value for candidate, value in zip(tail, active))


def _default_mode_identifier(state: ModeState) -> DeviceState[str] | None:
    """Locate the active sub-state using identifier comparison."""

    active_identifier = state.active_identifier
    if not active_identifier:
        return None
    for mode in state.modes:
        identifier = getattr(mode, "_identifier", None)
        if not identifier:
            continue
        if _match_identifier_tail(identifier, active_identifier):
            return mode
    return None


def _normalise_mode_name(value: str) -> str:
    """Return a canonical uppercase token for mode comparisons."""

    token = value.strip().replace("-", "_").replace(" ", "_")
    if token.lower().endswith("_mode"):
        token = token[: -len("_mode")]
    return token.upper()


class ModeState(DeviceOpState[DeviceState[str] | None]):
    """Manage a collection of mode states keyed by identifier sequences."""

    def __init__(
        self,
        *,
        device: object,
        modes: list[DeviceState[str] | None],
        op_type: int = _REPORT_OPCODE,
        identifier: list[int] | None = None,
        inline: bool = False,
        identifier_map=_default_mode_identifier,
        catalog_name: str | None = None,
    ) -> None:
        """Initialise the composite mode state handler."""

        entry = _state_entry(catalog_name) if catalog_name else None
        command_template = entry.command_templates[0] if entry else None
        status_opcode = (
            int(entry.identifiers["status"]["opcode"], 16) if entry else None
        )
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifier},
            device=device,
            name="mode",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command if entry else None,
        )
        self._identifier_map = identifier_map
        self._inline = inline
        self._active_identifier: list[int] | None = None
        self._modes: list[DeviceState[str]] = []
        self._mode_aliases: dict[str, str] = {}
        self._mode_lookup: dict[str, DeviceState[str]] = {}
        self._command_template = command_template
        self._status_opcode = status_opcode
        self._mode_payloads: dict[str, str] = {}
        if entry is not None:
            command_identifiers = entry.identifiers.get("command", {})
            payloads = command_identifiers.get("payloads", {})
            for label, payload in payloads.items():
                normalised = _normalise_mode_name(str(label))
                self._mode_payloads[normalised] = str(payload).upper()
                if normalised not in self._mode_aliases:
                    suffix = "_mode" if not str(label).endswith("_mode") else ""
                    self._mode_aliases[normalised] = f"{label}{suffix}".strip()
        for mode in modes:
            self.register_mode(mode)

    @property
    def active_identifier(self) -> list[int] | None:
        """Return the currently tracked mode identifier sequence."""

        return list(self._active_identifier) if self._active_identifier else None

    @property
    def modes(self) -> list[DeviceState[str]]:
        """Return the registered sub-states."""

        return list(self._modes)

    @property
    def active_mode(self) -> DeviceState[str] | None:
        """Return the mode matching the active identifier."""

        return self.value

    def register_mode(self, mode: DeviceState[str] | None) -> None:
        """Register a sub-state for identifier tracking."""

        if mode is None:
            return
        if mode not in self._modes:
            self._modes.append(mode)
        name = getattr(mode, "name", None)
        if isinstance(name, str):
            self._mode_aliases.setdefault(_normalise_mode_name(name), name)
            self._mode_lookup.setdefault(_normalise_mode_name(name), mode)
        value = getattr(mode, "value", None)
        if isinstance(value, str):
            self._mode_aliases.setdefault(_normalise_mode_name(value), value)
            self._mode_lookup.setdefault(_normalise_mode_name(value), mode)

    def parse_state(self, data: dict[str, Any]) -> None:
        """Capture active mode identifiers from structured state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        identifier = _int_from_value(state_section.get("mode"))
        if identifier is None:
            return
        self._set_active_identifier([identifier])

    def parse_op_command(self, op_command: list[int]) -> None:
        """Interpret opcode responses carrying active mode identifiers."""

        if not op_command:
            return
        if self._inline:
            self._set_active_identifier(list(op_command))
            return
        leading, *values = op_command
        if leading != 0x00:
            return
        if not values:
            return
        self._set_active_identifier(values)

    def _set_active_identifier(self, identifier: list[int]) -> None:
        self._active_identifier = identifier
        active_mode = self._identifier_map(self)
        self._update_state(active_mode)

    def _resolve_mode_token(self, next_state: Any) -> str | None:
        if isinstance(next_state, DeviceState):
            name = getattr(next_state, "name", None)
            if isinstance(name, str):
                return _normalise_mode_name(name)
            value = getattr(next_state, "value", None)
            if isinstance(value, str):
                return _normalise_mode_name(value)
            return None
        if isinstance(next_state, str):
            if not next_state.strip():
                return None
            return _normalise_mode_name(next_state)
        return None

    def _state_to_command(self, next_state: Any):
        if self._command_template is None or self._status_opcode is None:
            return None
        token = self._resolve_mode_token(next_state)
        if token is None:
            return None
        payload_hex = self._mode_payloads.get(token)
        if payload_hex is None:
            return None
        mode_code = payload_hex[2:] if len(payload_hex) > 2 else payload_hex
        command, payload_bytes = _command_payload(
            self._command_template, {"mode_code": mode_code}
        )
        status_sequence = [_REPORT_OPCODE, self._status_opcode, *payload_bytes[1:]]
        state_value = self._mode_aliases.get(token, token.lower())
        return {
            "command": command,
            "status": _status_payload(self.name, state_value, status_sequence),
        }

    def resolve_mode(self, option: Any) -> DeviceState[str] | None:
        """Return the registered mode matching ``option`` when available."""

        token = self._resolve_mode_token(option)
        if token is None:
            return None
        return self._mode_lookup.get(token)


class _PurifierMode(Enum):
    MANUAL = 0x01
    PROGRAM = 0x02
    AUTO = 0x03


class PurifierManualModeState(DeviceOpState[int | None]):
    """Represent purifier manual mode fan speed slots."""

    def __init__(
        self,
        device: object,
        *,
        op_type: int = _REPORT_OPCODE,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the purifier manual mode tracker."""
        identifiers = list(identifier) if identifier is not None else [0x05]
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="manual_mode",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._mode_identifier = [_PurifierMode.MANUAL.value]
        self._speed_index = 0

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode report payloads to capture manual fan speeds."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        mode_code, *command = payload
        if mode_code != _PurifierMode.MANUAL.value:
            return
        if not command:
            return
        try:
            sentinel_index = command.index(0x00)
        except ValueError:
            return
        speed_index = sentinel_index - 1
        if speed_index < 0 or speed_index >= len(command):
            return
        self._speed_index = speed_index
        self._update_state(command[speed_index])

    def _state_to_command(self, next_state: Any):
        """Translate a manual fan speed into a command payload."""
        speed = _int_from_value(next_state)
        if speed is None:
            return None
        filler = [0x00] * max(self._speed_index, 0)
        frame = _opcode_frame(
            0x33,
            0x05,
            _PurifierMode.MANUAL.value,
            *filler,
            speed,
        )
        status_sequence = [
            _REPORT_OPCODE,
            0x05,
            _PurifierMode.MANUAL.value,
            0x00,
            speed,
        ]
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {"op": {"command": [status_sequence]}},
        }


class PurifierCustomModeState(DeviceOpState[dict[str, Any] | None]):
    """Track purifier custom program slots and durations."""

    def __init__(
        self,
        device: object,
        *,
        op_type: int = _REPORT_OPCODE,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the custom program handler."""
        identifiers = list(identifier) if identifier is not None else [0x05]
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="custom_mode",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._mode_identifier = [_PurifierMode.PROGRAM.value]
        self._custom_modes: dict[str, Any] = {}

    def parse_op_command(self, op_command: list[int]) -> None:
        """Parse custom program slot data from opcode payloads."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        mode_code, *command = payload
        if mode_code != _PurifierMode.PROGRAM.value:
            return
        if not command:
            return
        current_program_id = command[0]
        programs: dict[int, dict[str, int]] = {}
        for slot in range(3):
            offset = 1 + slot * 5
            if len(command) < offset + 5:
                continue
            fan_speed = command[offset]
            duration = (command[offset + 1] << 8) | command[offset + 2]
            remaining = (command[offset + 3] << 8) | command[offset + 4]
            programs[slot] = {
                "id": slot,
                "fan_speed": fan_speed,
                "duration": duration,
                "remaining": remaining,
            }
        current_program = programs.get(current_program_id)
        self._custom_modes = {
            "current_program_id": current_program_id,
            "programs": programs,
            "current_program": current_program,
        }
        self._update_state(current_program)

    def _state_to_command(self, next_state: Any):
        """Generate a command sequence for a custom program update."""
        program = self._resolve_program(next_state)
        if program is None:
            return None
        programs = self._merged_programs(program)
        frame = _opcode_frame(
            0x33,
            0x05,
            _PurifierMode.PROGRAM.value,
            program["id"],
            *self._flatten_programs(programs, include_remaining=True),
        )
        status_sequence = [
            _REPORT_OPCODE,
            0x05,
            _PurifierMode.PROGRAM.value,
            program["id"],
            *self._flatten_programs(programs, include_remaining=False),
        ]
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {"op": {"command": [status_sequence]}},
        }

    def _resolve_program(self, next_state: Any) -> dict[str, int] | None:
        """Normalise mapping inputs into a program dictionary."""
        if not isinstance(next_state, Mapping):
            return None
        id_candidate = _int_from_value(
            next_state.get("id") or next_state.get("program")
        )
        fan_speed = _int_from_value(
            next_state.get("fan_speed") or next_state.get("fanSpeed")
        )
        duration = _int_from_value(next_state.get("duration"))
        remaining = _int_from_value(next_state.get("remaining"))
        current_program: Mapping[str, Any] | None = self._custom_modes.get(
            "current_program"
        )
        program_id = (
            id_candidate
            if id_candidate is not None
            else _int_from_value(current_program.get("id") if current_program else None)
        )
        if program_id is None:
            program_id = 0
        resolved_duration = (
            duration
            if duration is not None
            else _int_from_value(
                current_program.get("duration") if current_program else None
            )
        )
        resolved_remaining = (
            remaining
            if remaining is not None
            else _int_from_value(
                current_program.get("duration") if current_program else None
            )
        )
        resolved_fan_speed = (
            fan_speed
            if fan_speed is not None
            else _int_from_value(
                current_program.get("fan_speed") if current_program else None
            )
        )
        if resolved_fan_speed is None:
            return None
        return {
            "id": program_id,
            "fan_speed": resolved_fan_speed,
            "duration": resolved_duration or 100,
            "remaining": resolved_remaining or 100,
        }

    def _merged_programs(self, program: Mapping[str, int]) -> dict[int, dict[str, int]]:
        """Merge incoming program changes with stored slot metadata."""
        base_programs: Mapping[int, Mapping[str, Any]] = self._custom_modes.get(
            "programs", {}
        )
        merged: dict[int, dict[str, int]] = {
            idx: {
                "id": idx,
                "fan_speed": _int_from_value(value.get("fan_speed")) or 0,
                "duration": _int_from_value(value.get("duration")) or 100,
                "remaining": _int_from_value(value.get("remaining"))
                or (0 if idx != 2 else 32640),
            }
            for idx, value in base_programs.items()
        }
        defaults = {
            0: {"id": 0, "duration": 100, "remaining": 100, "fan_speed": 0},
            1: {"id": 1, "duration": 100, "remaining": 100, "fan_speed": 0},
            2: {
                "id": 2,
                "duration": 32640,
                "remaining": 32640,
                "fan_speed": 0,
            },
        }
        for idx, value in defaults.items():
            merged.setdefault(idx, dict(value))
        slot = program["id"]
        merged[slot] = {
            "id": slot,
            "fan_speed": program["fan_speed"],
            "duration": program["duration"],
            "remaining": program["remaining"],
        }
        return merged

    def _flatten_programs(
        self, programs: Mapping[int, Mapping[str, int]], *, include_remaining: bool
    ) -> list[int | None]:
        """Flatten structured program data into opcode payload fields."""
        flattened: list[int | None] = []
        for slot in range(3):
            program = programs.get(slot)
            if not program:
                flattened.extend([0, 0, 0, None, None])
                continue
            duration = int(program.get("duration", 0))
            remaining = int(program.get("remaining", 0))
            flattened.extend(
                [
                    int(program.get("fan_speed", 0)),
                    (duration >> 8) & 0xFF,
                    duration & 0xFF,
                ]
            )
            if include_remaining:
                flattened.extend(
                    [
                        (remaining >> 8) & 0xFF,
                        remaining & 0xFF,
                    ]
                )
            else:
                flattened.extend([None, None])
        return flattened


class PurifierActiveMode(ModeState):
    """Active mode selector delegating commands to sub-states."""

    def __init__(
        self,
        device: object,
        modes: list[DeviceState[str] | None],
    ) -> None:
        """Initialise the purifier active mode delegator."""
        filtered_modes = [mode for mode in modes if mode is not None]
        report_identifier: list[int] | None = None
        for mode in filtered_modes:
            identifier = getattr(mode, "_identifier", None)
            if not isinstance(identifier, Sequence):
                continue
            candidate = [int(value) for value in identifier if isinstance(value, int)]
            if candidate:
                report_identifier = candidate
                break
        super().__init__(device=device, modes=filtered_modes, inline=True)
        self._report_identifier = report_identifier
        self._mode_by_code: dict[int, DeviceState[str]] = {}
        for mode in filtered_modes:
            identifier = getattr(mode, "_mode_identifier", None)
            if isinstance(identifier, Sequence) and identifier:
                self._mode_by_code[int(identifier[0])] = mode

    def parse_op_command(self, op_command: list[int]) -> None:
        """Update the active mode using inline opcode payloads."""
        sequence = list(op_command)
        if self._op_type is not None and sequence and sequence[0] == self._op_type:
            sequence = _strip_op_header(sequence, self._op_type, self._identifier)
        if (
            self._report_identifier
            and len(sequence) > len(self._report_identifier)
            and sequence[: len(self._report_identifier)] == self._report_identifier
        ):
            sequence = sequence[len(self._report_identifier) :]
        if not sequence:
            return
        self._set_active_from_sequence(sequence)

    def _normalise_sequence(self, op_command: Sequence[int]) -> list[int]:
        """Return ``op_command`` without opcode headers or identifiers."""

        sequence = list(op_command)
        if not sequence:
            return []
        if self._op_type is not None and sequence[0] == self._op_type:
            stripped = _strip_op_header(sequence, self._op_type, self._identifier)
            if not stripped:
                return []
            sequence = stripped
        if (
            self._report_identifier
            and len(sequence) > len(self._report_identifier)
            and sequence[: len(self._report_identifier)] == self._report_identifier
        ):
            sequence = sequence[len(self._report_identifier) :]
        return sequence

    def activate(self, mode_name: str) -> None:
        """Select the active mode using a human readable name."""
        mode = self.resolve_mode(mode_name)
        if mode is None:
            raise KeyError(mode_name)
        identifier = getattr(mode, "_mode_identifier", None)
        if isinstance(identifier, Sequence) and identifier:
            self._set_active_from_sequence([int(identifier[0])])

    def set_state(self, next_state: Any) -> list[str]:
        """Delegate commands to the currently resolved sub-state."""
        mode: DeviceState[str] | None
        if isinstance(next_state, DeviceState):
            mode = next_state
        else:
            mode = self.resolve_mode(next_state)
        if mode is None:
            return []
        value = getattr(mode, "value", None)
        if value is None:
            return []
        return mode.set_state(value)

    def _set_active_from_sequence(self, sequence: Sequence[int]) -> None:
        """Persist ``sequence`` as the active identifier and update state."""
        self._active_identifier = list(sequence)
        if not sequence:
            self._update_state(None)
            return
        mode = self._mode_by_code.get(sequence[0])
        self._update_state(mode)


class ConnectedState(DeviceState[bool | None]):
    """Track whether a device reports itself as connected."""

    def __init__(self, device: object) -> None:
        """Initialise the connection state tracker."""

        super().__init__(device=device, name="isConnected", initial_value=None)

    def parse_state(self, data: dict[str, Any]) -> None:
        """Update connectivity using any known boolean flag."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        for key in ("isConnected", "isOnline", "connected", "online"):
            value = state_section.get(key)
            if isinstance(value, bool):
                self._update_state(value)
                return


class BatteryLevelState(DeviceState[int | None]):
    """Expose battery percentages reported by supported devices."""

    def __init__(self, *, device: object) -> None:
        """Initialise the battery state wrapper."""

        super().__init__(device=device, name="batteryLevel", initial_value=None)

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse battery values from top-level or nested payloads."""

        for mapping in self._candidate_mappings(data):
            value = mapping.get("battery")
            percentage = _int_from_value(value)
            if percentage is None:
                continue
            if 0 <= percentage <= 100:
                self._update_state(percentage)
                return

    def _candidate_mappings(self, data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        candidates: list[Mapping[str, Any]] = []
        if isinstance(data, Mapping):
            candidates.append(data)
            state_section = data.get("state")
            if isinstance(state_section, Mapping):
                candidates.append(state_section)
        return candidates


class ControlLockState(DeviceOpState[bool | None]):
    """Enable or disable on-device control buttons."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the control lock handler."""

        identifiers = list(identifier) if identifier is not None else []
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="controlLock",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command,
        )
        self._state_keys = ("controlLock", "control_lock")

    def parse_state(self, data: dict[str, Any]) -> None:
        """Capture control lock flags from nested state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        for key in self._state_keys:
            value = state_section.get(key)
            boolean = _bool_from_value(value)
            if boolean is not None:
                self._update_state(boolean)
                return

    def parse_op_command(self, op_command: list[int]) -> None:
        """Interpret opcode payloads as boolean lock flags."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        value = payload[0]
        self._update_state(value == 0x01)

    def _state_to_command(self, next_state: bool | None):
        """Translate desired lock state into a multi-sync command."""

        value = _bool_from_value(next_state)
        if value is None:
            return None
        if not self._identifier:
            return None
        byte_value = 0x01 if value else 0x00
        frame = _opcode_frame(0x33, *self._identifier, byte_value)
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {
                "op": {
                    "command": [
                        [_REPORT_OPCODE, *self._identifier, byte_value],
                    ]
                }
            },
        }


class HumidifierUVCState(DeviceOpState[bool | None]):
    """Toggle the built-in UVC sanitisation feature."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the UVC state handler with identifier defaults."""

        identifiers = list(identifier) if identifier is not None else [0x1A]
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="isUVCActive",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Map opcode payloads to a boolean UVC state."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        value = payload[0]
        if value in (0x00, 0x01):
            self._update_state(value == 0x01)

    def _state_to_command(self, next_state: bool | None):
        """Translate boolean requests into multi-sync opcode frames."""

        value = _bool_from_value(next_state)
        if value is None:
            return None
        if not self._identifier:
            return None
        byte_value = 0x01 if value else 0x00
        frame = _opcode_frame(0x33, *self._identifier, byte_value)
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {
                "op": {
                    "command": [
                        [_REPORT_OPCODE, *self._identifier, byte_value],
                    ]
                }
            },
        }


class HumidityState(DeviceState[dict[str, Any] | None]):
    """Report the current ambient humidity percentage with calibration data."""

    def __init__(self, *, device: object) -> None:
        """Initialise the humidity sensor state handler."""

        super().__init__(device=device, name="humidity", initial_value=None)

    def parse(self, data: dict[str, Any]) -> None:
        """Parse humidity readings from nested state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return

        measurement = state_section.get("humidity")
        parsed = self._parse_measurement(measurement)
        if parsed is not None:
            self._update_state(parsed)

        status_section = state_section.get("status")
        if isinstance(status_section, Mapping):
            self._parse_status_code(status_section.get("code"))

    def _parse_measurement(self, measurement: Any) -> dict[str, Any] | None:
        previous = self.value if isinstance(self.value, Mapping) else {}
        previous_range = previous.get("range")
        prev_min = (
            previous_range.get("min") if isinstance(previous_range, Mapping) else None
        )
        prev_max = (
            previous_range.get("max") if isinstance(previous_range, Mapping) else None
        )
        prev_calibration = previous.get("calibration")
        prev_current = previous.get("current")

        if isinstance(measurement, Mapping):
            calibration = self._scaled_value(
                measurement.get("calibration"), prev_calibration
            )
            current = self._scaled_value(measurement.get("current"), prev_current)
            min_value = self._numeric_value(measurement.get("min"))
            max_value = self._numeric_value(measurement.get("max"))
        else:
            calibration = self._scaled_value(None, prev_calibration)
            current = self._scaled_value(measurement, prev_current)
            min_value = self._numeric_value(prev_min)
            max_value = self._numeric_value(prev_max)

        if current is None:
            return None

        minimum = self._coalesce_bound(min_value, prev_min)
        maximum = self._coalesce_bound(max_value, prev_max)

        if minimum is not None and current < minimum:
            return None
        if maximum is not None and current > maximum:
            return None

        payload: dict[str, Any] = {"current": current}
        raw = current - calibration if calibration is not None else current
        payload["raw"] = raw
        if calibration is not None:
            payload["calibration"] = calibration

        range_payload = self._range_payload(minimum, maximum)
        if range_payload is not None:
            payload["range"] = range_payload

        return payload

    def _parse_status_code(self, code: Any) -> None:
        if not isinstance(code, str) or not code.strip():
            return
        try:
            codes = list(_hex_to_bytes(code))
        except ValueError:
            return
        if len(codes) < 3:
            return

        raw = codes[2]
        previous = self.value if isinstance(self.value, Mapping) else {}
        calibration = previous.get("calibration")
        if calibration is None:
            calibration = 0
        current = raw + calibration

        payload: dict[str, Any] = {
            "current": current,
            "raw": raw,
        }
        payload["calibration"] = calibration
        range_value = previous.get("range")
        if isinstance(range_value, Mapping):
            payload["range"] = range_value
        self._update_state(payload)

    def _scaled_value(
        self, candidate: Any, previous: float | int | None
    ) -> float | int | None:
        numeric = _float_from_value(candidate)
        if numeric is None:
            if isinstance(previous, int | float):
                return previous
            return None
        if numeric > 100:
            numeric /= 100
        if float(numeric).is_integer():
            return int(numeric)
        return numeric

    def _numeric_value(self, candidate: Any) -> float | int | None:
        numeric = _float_from_value(candidate)
        if numeric is None:
            return None
        if float(numeric).is_integer():
            return int(numeric)
        return numeric

    def _coalesce_bound(
        self, candidate: float | int | None, fallback: Any
    ) -> float | int | None:
        if candidate is not None:
            return candidate
        if isinstance(fallback, int | float):
            return fallback
        return None

    @staticmethod
    def _range_payload(
        minimum: float | int | None, maximum: float | int | None
    ) -> dict[str, float | int] | None:
        if minimum is None and maximum is None:
            return None
        payload: dict[str, float | int] = {}
        if minimum is not None:
            payload["min"] = minimum
        if maximum is not None:
            payload["max"] = maximum
        return payload or None


_HUMIDIFIER_MODE_PREFIX = 0x05
_HUMIDIFIER_MODE_MANUAL = 0x01
_HUMIDIFIER_MODE_CUSTOM = 0x02
_HUMIDIFIER_MODE_AUTO = 0x03


class _HumidifierModeState(DeviceOpState[Any]):
    """Shared helpers for humidifier mode opcode-backed states."""

    _command_opcode = 0x33

    def __init__(
        self,
        *,
        device: object,
        name: str,
        identifier: Sequence[int],
        delegate: Any | None = None,
        state_to_command: Callable[[Any], StateCommandAndStatus | None] | None,
    ) -> None:
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": list(identifier)},
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=state_to_command,
        )
        self._identifier = [identifier[-1]] if identifier else []
        self._listeners: list[Callable[[Any], None]] = []
        self._delegate = delegate
        self._pending_value: Any | None = None

    @property
    def delegate_state(self) -> Any | None:
        """Expose the optional delegate backing this mode."""

        return self._delegate

    def register_listener(self, callback: Callable[[Any], None]) -> None:
        """Register a listener invoked when the mode payload changes."""

        self._listeners.append(callback)

    def _notify_listeners(self, value: Any) -> None:
        for listener in list(self._listeners):
            listener(value)

    def _update_state(self, value: Any) -> None:  # type: ignore[override]
        super()._update_state(value)
        self._notify_listeners(value)

    def set_state(self, next_state: Any) -> list[str]:  # type: ignore[override]
        command_ids = super().set_state(next_state)
        if command_ids and self._pending_value is not None:
            self._update_state(self._pending_value)
            self._pending_value = None
        return command_ids

    def _command_payload(self, payload: Sequence[int]) -> dict[str, Any]:
        return {
            "data": {
                "command": [[self._command_opcode, *payload]],
            }
        }


class ManualModeState(_HumidifierModeState):
    """Track humidifier manual mode output levels."""

    def __init__(
        self,
        *,
        device: object,
        delegate: Any | None = None,
    ) -> None:
        """Initialise the manual mode opcode-backed state."""
        super().__init__(
            device=device,
            name="manual_mode",
            identifier=[_HUMIDIFIER_MODE_PREFIX, _HUMIDIFIER_MODE_MANUAL],
            delegate=delegate,
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode the manual mist level from the opcode payload."""
        payload = op_command[1:]
        if not payload:
            return
        try:
            sentinel_index = payload.index(0x00)
        except ValueError:
            return
        if sentinel_index <= 0:
            return
        level = _int_from_value(payload[sentinel_index - 1])
        if level is None:
            return
        self._update_state(self._clamp_level(level))

    def _clamp_level(self, value: int) -> int:
        if value < 0:
            return 0
        if value > 9:
            return 9
        return value

    def _state_to_command(self, next_state: Any) -> StateCommandAndStatus | None:
        value = _int_from_value(next_state)
        if value is None:
            return None
        clamped = self._clamp_level(value)
        if clamped != value:
            _LOGGER.warning(
                "Manual mode level %s outside supported range, clamping to %s",
                value,
                clamped,
            )
        payload = [_HUMIDIFIER_MODE_PREFIX, _HUMIDIFIER_MODE_MANUAL, clamped]
        self._pending_value = clamped
        return {
            "command": self._command_payload(payload),
            "status": {"op": {"command": [[clamped]]}},
        }


class CustomModeState(_HumidifierModeState):
    """Track and update humidifier custom programs."""

    def __init__(
        self,
        *,
        device: object,
        delegate: Any | None = None,
    ) -> None:
        """Initialise the custom mode program tracker."""
        super().__init__(
            device=device,
            name="custom_mode",
            identifier=[_HUMIDIFIER_MODE_PREFIX, _HUMIDIFIER_MODE_CUSTOM],
            delegate=delegate,
            state_to_command=self._state_to_command,
        )
        self._programs: dict[int, dict[str, int]] = {}
        self._current_program_id: int | None = None

    def parse_op_command(self, op_command: list[int]) -> None:
        """Parse the program slots and active program identifier."""
        payload = op_command[1:]
        if not payload:
            return
        program_id = _int_from_value(payload[0])
        if program_id is None:
            return
        programs: dict[int, dict[str, int]] = {}
        for index in range(3):
            base = 1 + 5 * index
            if len(payload) < base + 5:
                return
            mist_level = _int_from_value(payload[base])
            duration_hi = _int_from_value(payload[base + 1])
            duration_lo = _int_from_value(payload[base + 2])
            remaining_hi = _int_from_value(payload[base + 3])
            remaining_lo = _int_from_value(payload[base + 4])
            if None in (
                mist_level,
                duration_hi,
                duration_lo,
                remaining_hi,
                remaining_lo,
            ):
                return
            duration = duration_hi * 255 + duration_lo
            remaining = remaining_hi * 255 + remaining_lo
            programs[index] = {
                "id": index,
                "mistLevel": mist_level,
                "duration": duration,
                "remaining": remaining,
            }
        self._programs = programs
        self._current_program_id = program_id if program_id in programs else None
        current = (
            programs.get(self._current_program_id)
            if self._current_program_id is not None
            else None
        )
        self._update_state(current)

    def _default_programs(self, selected: int) -> dict[int, dict[str, int]]:
        defaults = {
            0: {"id": 0, "duration": 100, "remaining": 100, "mistLevel": 0},
            1: {
                "id": 1,
                "duration": 100,
                "remaining": 0 if selected > 1 else 100,
                "mistLevel": 0,
            },
            2: {"id": 2, "duration": 32640, "remaining": 32640, "mistLevel": 0},
        }
        if selected == 1:
            defaults[0]["remaining"] = 0
        if selected == 2:
            defaults[0]["remaining"] = 0
            defaults[1]["remaining"] = 0
        return defaults

    @staticmethod
    def _encode_program(program: Mapping[str, int]) -> list[int]:
        duration = max(0, int(program.get("duration", 0)))
        remaining = max(0, int(program.get("remaining", 0)))
        mist_level = _int_from_value(program.get("mistLevel")) or 0
        return [
            mist_level,
            duration // 255,
            duration % 255,
            remaining // 255,
            remaining % 255,
        ]

    def _state_to_command(self, next_state: Any) -> StateCommandAndStatus | None:
        if not isinstance(next_state, Mapping):
            return None
        program_id = _int_from_value(next_state.get("id"))
        if program_id is None:
            program_id = self._current_program_id or 0
        if program_id not in (0, 1, 2):
            program_id = max(0, min(2, program_id))
        source = self._programs.get(program_id, {"id": program_id})
        mist_level = _int_from_value(next_state.get("mistLevel"))
        duration = _int_from_value(next_state.get("duration"))
        remaining = _int_from_value(next_state.get("remaining"))
        program: dict[str, int] = {
            "id": program_id,
            "mistLevel": (
                mist_level if mist_level is not None else source.get("mistLevel", 0)
            ),
            "duration": duration if duration is not None else source.get("duration", 0),
            "remaining": (
                remaining
                if remaining is not None
                else source.get("remaining", 100 if program_id == 0 else 0)
            ),
        }
        programs = {
            **self._default_programs(program_id),
            **self._programs,
            program_id: program,
        }
        payload: list[int] = [
            _HUMIDIFIER_MODE_PREFIX,
            _HUMIDIFIER_MODE_CUSTOM,
            program_id,
        ]
        status_payload: list[int | None] = [program_id]
        for index in range(3):
            encoded = self._encode_program(programs[index])
            payload.extend(encoded)
            status_payload.extend(encoded[:3] + [None, None])
        self._pending_value = program
        return {
            "command": self._command_payload(payload),
            "status": {"op": {"command": [status_payload]}},
        }


class AutoModeState(_HumidifierModeState):
    """Track target humidity for humidifier auto mode."""

    def __init__(
        self,
        *,
        device: object,
        humidity_state: HumidityState | None = None,
        delegate: Any | None = None,
    ) -> None:
        """Initialise the auto mode state with optional humidity binding."""
        super().__init__(
            device=device,
            name="auto_mode",
            identifier=[_HUMIDIFIER_MODE_PREFIX, _HUMIDIFIER_MODE_AUTO],
            delegate=delegate,
            state_to_command=self._state_to_command,
        )
        self._humidity_state = humidity_state

    def bind_humidity_state(self, humidity_state: HumidityState) -> None:
        """Bind the humidity state for range clamping."""

        self._humidity_state = humidity_state

    def parse_op_command(self, op_command: list[int]) -> None:
        """Extract the target humidity from the opcode payload."""
        if not op_command:
            return
        target = _int_from_value(op_command[0])
        if target is None:
            return
        self._update_state({"targetHumidity": target})

    def _clamp_target(self, target: int) -> int:
        state = self._humidity_state.value if self._humidity_state is not None else None
        if isinstance(state, Mapping):
            range_value = state.get("range")
            if isinstance(range_value, Mapping):
                minimum = _int_from_value(range_value.get("min"))
                maximum = _int_from_value(range_value.get("max"))
                if minimum is not None and target < minimum:
                    _LOGGER.warning(
                        "Target humidity %s below minimum %s, clamping",
                        target,
                        minimum,
                    )
                    target = minimum
                if maximum is not None and target > maximum:
                    _LOGGER.warning(
                        "Target humidity %s above maximum %s, clamping",
                        target,
                        maximum,
                    )
                    target = maximum
        return target

    def _state_to_command(self, next_state: Any) -> StateCommandAndStatus | None:
        if not isinstance(next_state, Mapping):
            return None
        target = _int_from_value(next_state.get("targetHumidity"))
        if target is None:
            return None
        clamped = self._clamp_target(target)
        self._pending_value = {"targetHumidity": clamped}
        payload = [_HUMIDIFIER_MODE_PREFIX, _HUMIDIFIER_MODE_AUTO, clamped]
        return {
            "command": self._command_payload(payload),
            "status": {"op": {"command": [[clamped]]}},
        }


class TemperatureState(DeviceOpState[dict[str, Any]]):
    """Expose ambient temperature measurements with calibration details."""

    def __init__(
        self,
        *,
        device: object,
        op_type: int | None = None,
        identifier: Sequence[int] | None = None,
        parse_option: ParseOption = ParseOption.STATE,
    ) -> None:
        """Initialise the temperature state handler."""

        identifiers = list(identifier or [])
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="temperature",
            initial_value={},
            parse_option=parse_option,
        )

    def parse_state(self, data: dict[str, Any]) -> None:
        """Normalise measurement payloads into calibrated readings."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        measurement = state_section.get("temperature")
        previous = self.value if isinstance(self.value, Mapping) else {}
        previous_range = previous.get("range")
        if not isinstance(previous_range, Mapping):
            previous_range = {}
        prev_min = previous_range.get("min")
        prev_max = previous_range.get("max")

        if isinstance(measurement, Mapping):
            calibration = self._measurement_value(
                measurement.get("calibration"), previous.get("calibration")
            )
            current = self._measurement_value(
                measurement.get("current"), previous.get("current")
            )
            if current is None:
                return
            min_value = self._range_value(measurement.get("min"), prev_min)
            max_value = self._range_value(measurement.get("max"), prev_max)
        else:
            calibration = previous.get("calibration")
            current = self._measurement_value(measurement, previous.get("current"))
            if current is None:
                return
            min_value = prev_min
            max_value = prev_max

        if min_value is not None and current < min_value:
            return
        if max_value is not None and current > max_value:
            return

        range_value = None
        if min_value is not None and max_value is not None:
            range_value = {"min": min_value, "max": max_value}
        elif previous_range:
            range_value = previous_range

        raw = current - calibration if calibration is not None else current
        next_state: dict[str, Any] = {"current": current, "raw": raw}
        if calibration is not None:
            next_state["calibration"] = calibration
        if range_value is not None:
            next_state["range"] = range_value
        self._update_state(next_state)

    def _measurement_value(
        self, candidate: Any, previous: float | None
    ) -> float | None:
        numeric = _float_from_value(candidate)
        if numeric is None:
            return previous
        if numeric > 100:
            numeric /= 100
        return numeric

    def _range_value(
        self, candidate: Any, previous: float | int | None
    ) -> float | int | None:
        numeric = _float_from_value(candidate)
        if numeric is None:
            return previous
        if numeric.is_integer():
            return int(numeric)
        return numeric


class _AirQualityMeasurementState(DeviceOpState[dict[str, Any] | None]):
    """Base class for air quality measurement parsing."""

    def __init__(
        self,
        *,
        device: object,
        name: str,
        state_key: str | None = None,
    ) -> None:
        """Initialise the measurement state."""

        super().__init__(
            op_identifier={"op_type": None, "identifier": None},
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.STATE | ParseOption.MULTI_OP,
        )
        self._state_key = state_key or name

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse structured measurement payloads."""

        measurement = self._extract_measurement(data)
        if measurement is None:
            return
        parsed = self._normalise_measurement(measurement)
        if parsed is not None:
            self._update_state(parsed)

    def _extract_measurement(self, data: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return the measurement mapping from ``data`` when present."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return None
        measurement = state_section.get(self._state_key)
        if not isinstance(measurement, Mapping):
            return None
        return measurement

    def _normalise_measurement(
        self, measurement: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Normalise the measurement payload."""

        raise NotImplementedError

    @staticmethod
    def _range_mapping(
        minimum: float | int | None, maximum: float | int | None
    ) -> dict[str, float | int] | None:
        """Build a range mapping when either bound is present."""

        range_payload: dict[str, float | int] = {}
        if minimum is not None:
            range_payload["min"] = minimum
        if maximum is not None:
            range_payload["max"] = maximum
        return range_payload or None

    @staticmethod
    def _numeric_value(value: Any) -> float | int | None:
        """Return numeric values preserving integers when possible."""

        numeric = _float_from_value(value)
        if numeric is None:
            return None
        if numeric.is_integer():
            return int(numeric)
        return numeric

    @staticmethod
    def _word(command: Sequence[int], start: int) -> int | None:
        """Return the 16-bit value at ``start`` when available."""

        if start < 0 or start + 1 >= len(command):
            return None
        return ((command[start] & 0xFF) << 8) | (command[start + 1] & 0xFF)

    @staticmethod
    def _signed_hundredths(word: int) -> float:
        """Return a signed float represented as hundredths in ``word``."""

        return ((word & 0x7FFF) - (word & 0x8000)) / 100


class AirQualityTemperatureState(_AirQualityMeasurementState):
    """Expose calibrated air quality temperature readings."""

    def __init__(self, *, device: object) -> None:
        """Initialise the air quality temperature state."""

        super().__init__(device=device, name="temperature")

    def _normalise_measurement(
        self, measurement: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        current = self._scaled_value(measurement.get("current"))
        if current is None:
            return None

        calibration = self._scaled_value(
            measurement.get("calibration"), scale_small=True
        )
        minimum = self._scaled_value(measurement.get("min"), scale_small=True)
        maximum = self._scaled_value(measurement.get("max"), scale_small=True)

        raw = current - calibration if calibration is not None else current
        payload: dict[str, Any] = {"current": current, "raw": raw}
        if calibration is not None:
            payload["calibration"] = calibration

        range_mapping = self._range_mapping(minimum, maximum)
        if range_mapping is not None:
            payload["range"] = range_mapping

        return payload

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Decode temperature readings from multi-op payloads."""

        if not op_commands:
            return
        op_command = op_commands[0]
        raw_word = self._word(op_command, 0)
        calibration_word = self._word(op_command, 2)
        if raw_word is None or calibration_word is None:
            return

        raw = raw_word / 100
        calibration = self._signed_hundredths(calibration_word)
        current = raw + calibration

        payload: dict[str, Any] = {"current": current, "raw": raw}
        payload["calibration"] = calibration
        self._update_state(payload)

    def _scaled_value(self, value: Any, *, scale_small: bool = False) -> float | None:
        numeric = _float_from_value(value)
        if numeric is None:
            return None
        if scale_small or abs(numeric) >= 100:
            numeric /= 100
        return numeric


class AirQualityHumidityState(_AirQualityMeasurementState):
    """Expose relative humidity measurements for air quality sensors."""

    def __init__(self, *, device: object) -> None:
        """Initialise the humidity state."""

        super().__init__(device=device, name="humidity")

    def _normalise_measurement(
        self, measurement: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        current = self._numeric_value(measurement.get("current"))
        if current is None:
            return None

        minimum = self._numeric_value(measurement.get("min"))
        maximum = self._numeric_value(measurement.get("max"))

        payload: dict[str, Any] = {"current": current}
        range_mapping = self._range_mapping(minimum, maximum)
        if range_mapping is not None:
            payload["range"] = range_mapping

        return payload

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Extract humidity readings from multi-op payloads."""

        if not op_commands:
            return
        op_command = op_commands[0]
        raw_word = self._word(op_command, 9)
        calibration_word = self._word(op_command, 11)
        if raw_word is None or calibration_word is None:
            return

        raw = raw_word / 100
        calibration = self._signed_hundredths(calibration_word)
        current = raw + calibration

        payload: dict[str, Any] = {
            "current": current,
            "raw": raw,
            "calibration": calibration,
        }
        self._update_state(payload)


class AirQualityPM25State(_AirQualityMeasurementState):
    """Expose particulate matter readings with warning flags."""

    def __init__(self, *, device: object) -> None:
        """Initialise the PM2.5 state."""

        super().__init__(device=device, name="pm25")

    def _normalise_measurement(
        self, measurement: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        current = self._numeric_value(measurement.get("current"))
        if current is None:
            return None

        warning = measurement.get("warning")
        if warning is not None:
            warning = bool(warning)

        minimum = self._numeric_value(measurement.get("min"))
        maximum = self._numeric_value(measurement.get("max"))

        payload: dict[str, Any] = {"current": current}
        if warning is not None:
            payload["warning"] = warning

        range_mapping = self._range_mapping(minimum, maximum)
        if range_mapping is not None:
            payload["range"] = range_mapping

        return payload

    def parse_multi_op_command(self, op_commands: list[list[int]]) -> None:
        """Parse PM2.5 data from aggregated opcode payloads."""

        if not op_commands:
            return
        op_command = op_commands[0]
        current_word = self._word(op_command, 18)
        if current_word is None:
            return

        payload: dict[str, Any] = {
            "current": current_word,
            "range": {"min": 0, "max": 1000},
        }
        self._update_state(payload)


class TimerState(DeviceOpState[bool | None]):
    """Represent the configured countdown timer for supported devices."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the timer handler using catalogue metadata."""

        entry = _state_entry("timer")
        default_identifier = list(
            _hex_to_bytes(entry.identifiers["status"].get("payload", ""))
        )
        identifiers = list(identifier) if identifier is not None else default_identifier
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="timer",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._status_identifier = list(identifiers)
        options = entry.parse_options or {}
        self._enabled_index = int(options.get("byte_index", 0))
        duration_indexes = options.get("duration_bytes", [1, 2])
        self._duration_indexes = (
            int(duration_indexes[0]),
            (
                int(duration_indexes[1])
                if len(duration_indexes) > 1
                else int(duration_indexes[0]) + 1
            ),
        )
        self._duration: int | None = None

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode opcode payloads into enabled flag and remaining seconds."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        required_index = max(self._enabled_index, *self._duration_indexes)
        if len(payload) <= required_index:
            return
        enabled_flag = payload[self._enabled_index] == 0x01
        hi_index, lo_index = self._duration_indexes
        duration = (payload[hi_index] << 8) | payload[lo_index]
        self._duration = duration
        self._update_state(enabled_flag)

    @property
    def duration(self) -> int | None:
        """Return the last known timer duration in seconds."""

        return self._duration

    def _state_to_command(self, next_state: Mapping[str, Any] | bool | None):
        """Translate timer requests into multi-sync commands."""

        if not self._status_identifier:
            return None
        enabled, duration = self._normalise_request(next_state)
        if enabled is None:
            return None
        if duration is None:
            duration = self._duration
        if duration is None:
            duration = 0
        if duration < 0 or duration > 0xFFFF:
            return None
        self._duration = duration
        enabled_byte = 0x01 if enabled else 0x00
        duration_high = (duration >> 8) & 0xFF
        duration_low = duration & 0xFF
        frame = _opcode_frame(
            0x33,
            *self._status_identifier,
            enabled_byte,
            duration_high,
            duration_low,
        )
        status_sequence = [
            _REPORT_OPCODE,
            *self._status_identifier,
            enabled_byte,
            duration_high,
            duration_low,
        ]
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": [
                {"op": {"command": [status_sequence]}},
                {"state": {"timer": {"enabled": enabled, "duration": duration}}},
            ],
        }

    def _normalise_request(
        self, next_state: Mapping[str, Any] | bool | None
    ) -> tuple[bool | None, int | None]:
        if isinstance(next_state, Mapping):
            return (
                _bool_from_value(next_state.get("enabled")),
                _int_from_value(next_state.get("duration")),
            )
        return _bool_from_value(next_state), None


class FilterLifeState(DeviceState[int | None]):
    """Expose purifier filter life remaining as a percentage."""

    def __init__(self, *, device: object) -> None:
        """Initialise the filter life sensor wrapper."""

        super().__init__(device=device, name="filterLife", initial_value=None)

    def parse(self, data: dict[str, Any]) -> None:
        """Parse numeric filter life values from state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        value = state_section.get("filterLife")
        if value is None:
            value = state_section.get("filter_life")
        life = _int_from_value(value)
        if life is None:
            return
        if 0 <= life <= 100:
            self._update_state(life)


class FilterExpiredState(DeviceState[bool | None]):
    """Report whether the purifier filter has expired."""

    def __init__(self, *, device: object) -> None:
        """Initialise the filter expiration status sensor."""

        super().__init__(device=device, name="filterExpired", initial_value=None)

    def parse(self, data: dict[str, Any]) -> None:
        """Parse expiration flags from state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        value = state_section.get("filterExpired")
        if value is None:
            value = state_section.get("filter_expired")
        flag = _bool_from_value(value)
        if flag is not None:
            self._update_state(flag)


class WaterShortageState(DeviceOpState[bool | None]):
    """Report low-water status from humidifiers."""

    def __init__(self, *, device: object) -> None:
        """Initialise the shortage tracker using catalogue metadata."""

        entry = _state_entry("water_shortage")
        payload_hex = entry.identifiers["status"].get("payload", "")
        identifier = list(_hex_to_bytes(payload_hex))
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": identifier},
            device=device,
            name="waterShortage",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
        )
        value_map = entry.parse_options.get("value_map", {})
        self._value_map = self._normalise_value_map(value_map)

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse boolean shortage flags from structured payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        shortage = state_section.get("waterShortage")
        flag = _bool_from_value(shortage)
        if flag is not None:
            self._update_state(flag)
            return
        sta_section = state_section.get("sta")
        if not isinstance(sta_section, Mapping):
            return
        stc = sta_section.get("stc")
        if not isinstance(stc, Sequence) or len(stc) < 2:
            return
        try:
            code = int(stc[0])
            value = int(stc[1])
        except (TypeError, ValueError):
            return
        if code == 0x06:
            self._update_state(value != 0)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Interpret opcode payloads describing water shortage state."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        key = f"{payload[0]:02X}"
        mapped = self._value_map.get(key)
        if mapped is not None:
            self._update_state(mapped)
            return
        self._update_state(payload[0] != 0x00)

    @staticmethod
    def _normalise_value_map(value_map: Mapping[str, Any]) -> dict[str, bool]:
        normalised: dict[str, bool] = {}
        for key, value in value_map.items():
            if isinstance(value, str):
                lowered = value.lower()
                normalised[key.upper()] = lowered not in {
                    "ok",
                    "clear",
                    "normal",
                    "off",
                }
            else:
                normalised[key.upper()] = bool(value)
        return normalised


_NUGGET_SIZE_CODES = {
    "SMALL": 0x03,
    "MEDIUM": 0x02,
    "LARGE": 0x01,
}
_NUGGET_SIZE_OPTIONS = tuple(_NUGGET_SIZE_CODES)
_NUGGET_SIZE_NAMES = {code: name for name, code in _NUGGET_SIZE_CODES.items()}

_ICE_MAKER_STATUS_CODES = {
    "STANDBY": 0x00,
    "MAKING_ICE": 0x01,
    "FULL": 0x02,
    "WASHING": 0x03,
    "FINISHED_WASHING": 0x04,
    "SCHEDULED": 0x05,
}
_ICE_MAKER_STATUS_NAMES = {code: name for name, code in _ICE_MAKER_STATUS_CODES.items()}


def _normalise_choice(value: Any, mapping: Mapping[str, int]) -> tuple[str, int] | None:
    if isinstance(value, str):
        key = value.strip().upper()
    else:
        key = str(value).strip().upper()
    code = mapping.get(key)
    if code is None:
        return None
    return key, code


class IceMakerNuggetSizeState(DeviceOpState[str | None]):
    """Track the selected nugget size reported by an ice maker."""

    def __init__(self, *, device: object) -> None:
        """Initialise the nugget size state."""
        entry = _state_entry("ice_maker_nugget_size")
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x05]},
            device=device,
            name="nuggetSize",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._default = entry.parse_options.get("default", "SMALL")
        self.options: tuple[str, ...] = _NUGGET_SIZE_OPTIONS

    def parse_op_command(self, op_command: list[int]) -> None:
        """Update the stored nugget size based on opcode payloads."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        value = _NUGGET_SIZE_NAMES.get(payload[0], self._default)
        self._update_state(value)

    def _state_to_command(self, next_state: Any):
        choice = _normalise_choice(next_state, _NUGGET_SIZE_CODES)
        if choice is None:
            return None
        name, code = choice
        command, payload_bytes = _command_payload(
            self._command_template, {"code": code}
        )
        status_sequence = [_REPORT_OPCODE, 0x05, payload_bytes[-1]]
        return {
            "command": command,
            "status": _status_payload("nuggetSize", name, status_sequence),
        }


class _IceMakerBinaryAlarmState(DeviceOpState[bool | None]):
    """Base helper for boolean ice maker alarms keyed by payload id."""

    def __init__(
        self,
        *,
        device: object,
        name: str,
        identifier: int,
        property_id: int,
    ) -> None:
        """Initialise a boolean alarm state for the ice maker."""
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [identifier]},
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
        )
        self._property_id = property_id

    def parse_op_command(self, op_command: list[int]) -> None:
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) <= 1:
            return
        if payload[0] != self._property_id:
            return
        self._update_state(payload[1] == 0x01)


class IceMakerBasketFullState(_IceMakerBinaryAlarmState):
    """Expose the basket full alarm reported by the ice maker."""

    def __init__(self, *, device: object) -> None:
        """Initialise the basket full alarm state."""
        super().__init__(
            device=device, name="basketFull", identifier=0x17, property_id=0x01
        )


class IceMakerWaterEmptyState(_IceMakerBinaryAlarmState):
    """Expose the water shortage alarm reported by the ice maker."""

    def __init__(self, *, device: object) -> None:
        """Initialise the water shortage alarm state."""
        super().__init__(
            device=device, name="waterShortage", identifier=0x17, property_id=0x02
        )


class IceMakerStatusState(DeviceOpState[str | None]):
    """Track the operational status of the ice maker."""

    def __init__(self, *, device: object) -> None:
        """Initialise the status tracker for the ice maker."""
        entry = _state_entry("ice_maker_status")
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x19]},
            device=device,
            name="iceMakerStatus",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._default = entry.parse_options.get("default", "STANDBY")
        self._listeners: list[Callable[[str | None], None]] = []

    def parse_op_command(self, op_command: list[int]) -> None:
        """Update the stored status using an opcode payload."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        value = _ICE_MAKER_STATUS_NAMES.get(payload[0], self._default)
        self._update_state(value)

    def register_listener(self, callback: Callable[[str | None], None]) -> None:
        """Register a listener for status updates."""
        self._listeners.append(callback)

    def _notify_listeners(self, value: str | None) -> None:
        for listener in list(self._listeners):
            listener(value)

    def _update_state(self, value: str | None) -> None:  # type: ignore[override]
        super()._update_state(value)
        self._notify_listeners(value)

    def _state_to_command(self, next_state: Any):
        choice = _normalise_choice(next_state, _ICE_MAKER_STATUS_CODES)
        if choice is None:
            return None
        name, code = choice
        command, payload_bytes = _command_payload(
            self._command_template, {"code": code}
        )
        status_sequence = [_REPORT_OPCODE, 0x19, payload_bytes[-1]]
        return {
            "command": command,
            "status": _status_payload("iceMakerStatus", name, status_sequence),
        }


class IceMakerScheduledStartState(DeviceOpState[dict[str, Any]]):
    """Manage scheduled start configuration for an ice maker."""

    def __init__(self, *, device: object) -> None:
        """Initialise the scheduled start state."""
        entry = _state_entry("ice_maker_scheduled_start")
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x23]},
            device=device,
            name="scheduledStart",
            initial_value={},
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]

    def parse_op_command(self, op_command: list[int]) -> None:
        """Parse a scheduled start payload emitted by the device."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        if payload[0] == 0x00:
            self._update_state(
                {
                    "enabled": False,
                    "hourStart": None,
                    "minuteStart": None,
                    "nuggetSize": None,
                }
            )
            return
        if len(payload) < 8:
            return
        timestamp = int.from_bytes(payload[3:7], "big")
        start_time = dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        nugget = _NUGGET_SIZE_NAMES.get(payload[7], "SMALL")
        self._update_state(
            {
                "enabled": payload[0] == 0x01,
                "hourStart": start_time.hour,
                "minuteStart": start_time.minute,
                "nuggetSize": nugget,
            }
        )

    def _state_to_command(self, next_state: dict[str, Any]) -> dict[str, Any] | None:
        enabled = next_state.get("enabled")
        if enabled is None:
            return None
        if not enabled:
            command, payload_bytes = _command_payload(
                self._command_template, {"payload": "00"}
            )
            status_sequence = [_REPORT_OPCODE, 0x23, payload_bytes[-1]]
            state_value = {
                "enabled": False,
                "hourStart": None,
                "minuteStart": None,
                "nuggetSize": None,
            }
            return {
                "command": command,
                "status": _status_payload(
                    "scheduledStart", state_value, status_sequence
                ),
            }

        hour = next_state.get("hourStart")
        minute = next_state.get("minuteStart")
        choice = _normalise_choice(next_state.get("nuggetSize"), _NUGGET_SIZE_CODES)
        if not isinstance(hour, int) or not isinstance(minute, int) or choice is None:
            return None
        name, code = choice
        start_time = self._resolve_start_time(hour, minute)
        minutes_delta = round((start_time - self._now()).total_seconds() / 60)
        if minutes_delta < 0:
            minutes_delta = 0
        minutes_bytes = minutes_delta.to_bytes(2, "big", signed=False)
        timestamp_bytes = int(start_time.timestamp()).to_bytes(4, "big", signed=False)
        payload_bytes = [0x01, *minutes_bytes, *timestamp_bytes, code]
        payload_hex = "".join(f"{byte:02X}" for byte in payload_bytes)
        command, _ = _command_payload(self._command_template, {"payload": payload_hex})
        status_sequence = [_REPORT_OPCODE, 0x23, *payload_bytes]
        state_value = {
            "enabled": True,
            "hourStart": start_time.hour,
            "minuteStart": start_time.minute,
            "nuggetSize": name,
        }
        return {
            "command": command,
            "status": _status_payload("scheduledStart", state_value, status_sequence),
        }

    def _resolve_start_time(self, hour: int, minute: int) -> dt.datetime:
        now = self._now()
        target = now.replace(
            hour=hour % 24, minute=minute % 60, second=0, microsecond=0
        )
        if target <= now:
            target += dt.timedelta(days=1)
        return target

    def _now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class IceMakerMakingIceState(DeviceOpState[bool | None]):
    """Boolean view of whether the ice maker is actively producing ice."""

    def __init__(
        self,
        *,
        device: object,
        status_state: IceMakerStatusState,
    ) -> None:
        """Initialise the derived making-ice state."""
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x19]},
            device=device,
            name="makeIce",
            initial_value=None,
            parse_option=ParseOption.OP_CODE,
        )
        self._status_state = status_state
        status_state.register_listener(self._handle_status_update)
        self._handle_status_update(status_state.value)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Mirror status opcode payloads to update the derived state."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if not payload:
            return
        status = _ICE_MAKER_STATUS_NAMES.get(payload[0])
        self._handle_status_update(status)

    def set_state(self, next_state: bool | None) -> list[str]:
        """Proxy state changes to the underlying status handler."""
        if next_state is None:
            return []
        target = "MAKING_ICE" if next_state else "STANDBY"
        return self._status_state.set_state(target)

    def _handle_status_update(self, status: str | None) -> None:
        """Apply ``status`` updates to the boolean representation."""
        if status is None:
            return
        self._update_state(status == "MAKING_ICE")


class IceMakerTemperatureState(TemperatureState):
    """Temperature state using the ice maker specific opcode payload."""

    def __init__(self, *, device: object) -> None:
        """Initialise the ice maker temperature state."""
        super().__init__(
            device=device,
            op_type=_REPORT_OPCODE,
            identifier=[0x10],
            parse_option=ParseOption.OP_CODE,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode temperature readings encoded in opcode payloads."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 3:
            return
        raw_value = int.from_bytes(payload[:3], "big", signed=False)
        sign_bit = 1 << 23
        magnitude = raw_value & (sign_bit - 1)
        current = magnitude / 10000.0
        if raw_value & sign_bit:
            current = -current
        self._update_state(
            {
                "current": current,
                "range": {"min": -20, "max": 60},
                "unit": "C",
            }
        )


class DisplayScheduleState(DeviceOpState[dict[str, Any]]):
    """Handle scheduling for device display panels."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the display schedule handler."""

        identifiers = list(identifier) if identifier is not None else []
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="displaySchedule",
            initial_value={},
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Convert opcode payloads into structured schedule dictionaries."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 5:
            return
        on_flag, from_hour, from_minute, to_hour, to_minute = payload[:5]
        self._update_state(
            {
                "on": on_flag == 0x01,
                "from": {"hour": from_hour, "minute": from_minute},
                "to": {"hour": to_hour, "minute": to_minute},
            }
        )

    def _state_to_command(self, next_state: dict[str, Any]):
        """Translate structured schedules into multi-sync commands."""

        if not self._identifier:
            return None
        if not isinstance(next_state, Mapping):
            return None
        on_flag = next_state.get("on")
        if not isinstance(on_flag, bool):
            return None

        def _extract_time(key: str) -> tuple[int, int] | None:
            section = next_state.get(key)
            if not isinstance(section, Mapping):
                return None
            hour = section.get("hour")
            minute = section.get("minute")
            if not isinstance(hour, int) or not isinstance(minute, int):
                return None
            return hour, minute

        segments: list[int] = []
        if on_flag:
            start = _extract_time("from")
            end = _extract_time("to")
            if start is None or end is None:
                return None
            segments.extend([start[0], start[1], end[0], end[1]])
        prefix: list[int] = []
        if self._op_type is not None:
            prefix.append(self._op_type)
        prefix.extend(self._identifier)
        frame = _opcode_frame(0x33, *prefix, 0x01 if on_flag else 0x00, *segments)
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {
                "op": {
                    "command": [
                        [
                            _REPORT_OPCODE,
                            *self._identifier,
                            0x01 if on_flag else 0x00,
                        ]
                    ]
                }
            },
        }


class NightLightState(DeviceOpState[dict[str, Any]]):
    """Toggle and configure the night-light brightness."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the night light handler."""

        identifiers = list(identifier) if identifier is not None else []
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="nightLight",
            initial_value={"on": None, "brightness": None},
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Convert opcode payloads into night-light state dictionaries."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 2:
            return
        on_flag, brightness = payload[:2]
        self._update_state({"on": on_flag == 0x01, "brightness": brightness})

    def _state_to_command(self, next_state: dict[str, Any]):
        """Translate state requests into multi-sync night light commands."""

        if not self._identifier:
            return None
        if not isinstance(next_state, Mapping):
            return None
        on_flag = next_state.get("on")
        brightness = next_state.get("brightness")
        if not isinstance(on_flag, bool):
            return None
        if not isinstance(brightness, int) or not (0 <= brightness <= 100):
            return None
        prefix: list[int] = []
        if self._op_type is not None:
            prefix.append(self._op_type)
        prefix.extend(self._identifier)
        frame = _opcode_frame(0x33, *prefix, 0x01 if on_flag else 0x00, brightness)
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {
                "op": {
                    "command": [
                        [
                            _REPORT_OPCODE,
                            *self._identifier,
                            0x01 if on_flag else 0x00,
                            brightness,
                        ]
                    ]
                }
            },
        }


def _strip_op_header(
    sequence: Sequence[int],
    op_type: int | None,
    identifier: Sequence[int] | None,
) -> list[int]:
    payload = list(sequence)
    offset = 0
    if op_type is not None:
        offset += 1
    if identifier:
        offset += len(identifier)
    return payload[offset:]


class PresenceState(DeviceOpState[dict[str, Any] | None]):
    """Decode presence sensor opcode payloads into structured values."""

    def __init__(
        self,
        device: object,
        presence_type: str,
        op_type: int = _REPORT_OPCODE,
        *identifier: int,
    ) -> None:
        """Initialise the presence state with identifier metadata."""
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": list(identifier)},
            device=device,
            name=f"presence-{presence_type}",
            initial_value=None,
        )
        self._presence_type = presence_type

    def parse_op_command(self, op_command: list[int]) -> None:
        """Translate opcode payloads into detection metadata."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 3:
            return
        detected = payload[0] == 0x01
        distance = int.from_bytes(payload[1:3], "big")
        duration = self._extract_duration(payload)
        value: dict[str, Any] = {
            "type": self._presence_type,
            "detected": detected,
            "distance": {"value": distance, "unit": "cm"},
        }
        if duration is not None:
            value["duration"] = {"value": duration, "unit": "s"}
        self._update_state(value)

    def _extract_duration(self, payload: list[int]) -> int | None:
        if len(payload) <= 14:
            return None
        duration_bytes = payload[-12:-8]
        if len(duration_bytes) != 4:
            return None
        return int.from_bytes(duration_bytes, "big")


class MMWavePresenceState(PresenceState):
    """Presence state dedicated to mmWave detection hardware."""

    def __init__(self, device: object) -> None:
        """Initialise the mmWave-specific presence handler."""
        super().__init__(device, "mmWave", _REPORT_OPCODE, 0x01)


class BiologicalPresenceState(PresenceState):
    """Presence state dedicated to biological detection sensors."""

    def __init__(self, device: object) -> None:
        """Initialise the biological presence handler."""
        super().__init__(device, "biological", _REPORT_OPCODE, 0x01, -1, -1, -1)


def _opcode_frame(op_type: int, *values: int) -> list[int]:
    """Construct an opcode frame padded to 19 bytes with checksum."""

    frame = [op_type, *values]
    if len(frame) < 19:
        frame.extend([0x00] * (19 - len(frame)))
    checksum = 0
    for byte in frame:
        checksum ^= byte
    frame.append(checksum)
    return frame


def _int_to_bytes(value: int) -> list[int]:
    return [value >> 8 & 0xFF, value & 0xFF]


class EnablePresenceState(DeviceOpState[dict[str, bool | None]]):
    """Toggle mmWave and biological presence detection sensors."""

    def __init__(self, device: object) -> None:
        """Initialise the enable-state wrapper with identifiers."""
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x1F]},
            device=device,
            name="enablePresence",
            initial_value={},
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Parse opcode responses carrying enable flags."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 2:
            return
        self._update_state(
            {
                "biologicalEnabled": payload[0] == 0x01,
                "mmWaveEnabled": payload[1] == 0x01,
            }
        )

    def _state_to_command(self, next_state: dict[str, bool | None]):
        biological = next_state.get("biologicalEnabled")
        if biological is None:
            biological = self.value.get("biologicalEnabled")
        mmwave = next_state.get("mmWaveEnabled")
        if mmwave is None:
            mmwave = self.value.get("mmWaveEnabled")
        if biological is None or mmwave is None:
            return None
        bio_flag = 0x01 if biological else 0x00
        mm_flag = 0x01 if mmwave else 0x00
        frame = _opcode_frame(0x33, 0x1F, bio_flag, mm_flag)
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {
                "op": {
                    "command": [[_REPORT_OPCODE, *self._identifier, bio_flag, mm_flag]]
                },
            },
        }


def _to_seconds(value: Any, unit: str) -> int | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    normalised = unit.lower()
    if normalised in {"s", "sec", "second", "seconds"}:
        return int(round(numeric))
    if normalised in {"m", "min", "minute", "minutes"}:
        return int(round(numeric * 60))
    if normalised in {"h", "hr", "hour", "hours"}:
        return int(round(numeric * 3600))
    return int(round(numeric))


class DetectionSettingsState(DeviceOpState[dict[str, Any]]):
    """Configure detection distance and reporting intervals."""

    def __init__(self, device: object) -> None:
        """Initialise the detection settings controller."""
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [0x05, 0x01]},
            device=device,
            name="detectionSettings",
            initial_value={},
            state_to_command=self._state_to_command,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode detection distance and durations from payloads."""
        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 6:
            return
        distance = int.from_bytes(payload[0:2], "big")
        absence = int.from_bytes(payload[2:4], "big")
        report = int.from_bytes(payload[4:6], "big")
        self._update_state(
            {
                "detectionDistance": {"value": distance, "unit": "cm"},
                "absenceDuration": {"value": absence, "unit": "s"},
                "reportDetection": {"value": report, "unit": "s"},
            }
        )

    def _state_to_command(self, next_state: dict[str, Any]):
        distance = self._resolve_distance(next_state)
        absence = self._resolve_duration(next_state, "absenceDuration")
        report = self._resolve_duration(next_state, "reportDetection")
        if None in (distance, absence, report):
            return None
        distance_bytes = _int_to_bytes(distance)
        absence_bytes = _int_to_bytes(absence)
        report_bytes = _int_to_bytes(report)
        command_frames = [
            _opcode_frame(0x33, 0x05, 0x00, 0x01),
            _opcode_frame(
                0x33, 0x05, 0x01, *distance_bytes, *absence_bytes, *report_bytes
            ),
        ]
        status_payload = distance_bytes + absence_bytes + report_bytes
        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": command_frames},
            },
            "status": {
                "op": {
                    "command": [[_REPORT_OPCODE, *self._identifier, *status_payload]]
                }
            },
        }

    def _resolve_distance(self, next_state: dict[str, Any]) -> int | None:
        candidate = self._select_field(next_state, "detectionDistance")
        if candidate is None:
            return None
        value = candidate.get("value")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _resolve_duration(self, next_state: dict[str, Any], key: str) -> int | None:
        candidate = self._select_field(next_state, key)
        if candidate is None:
            return None
        value = candidate.get("value")
        unit = candidate.get("unit", "s")
        return _to_seconds(value, unit)

    def _select_field(
        self, next_state: dict[str, Any], key: str
    ) -> Mapping[str, Any] | None:
        candidate = next_state.get(key)
        if isinstance(candidate, Mapping):
            return candidate
        existing = self.value.get(key)
        if isinstance(existing, Mapping):
            return existing
        return None


@cache
def _state_entry(name: str) -> StateEntry:
    """Load and cache a state entry from the catalogue."""

    catalog = load_state_catalog()
    return catalog.get_state(name)


def _render_payload(template: CommandTemplate, context: Mapping[str, Any]) -> str:
    """Render a payload template with the provided context."""

    template_text = template.payload_template.replace("\n", "")
    result: list[str] = []
    idx = 0
    while idx < len(template_text):
        start = template_text.find("{{", idx)
        if start == -1:
            result.append(template_text[idx:])
            break
        if start > idx:
            result.append(template_text[idx:start])
        end = template_text.find("}}", start)
        if end == -1:
            raise ValueError("Unterminated template expression")
        expression = template_text[start + 2 : end].strip()
        result.append(_evaluate_expression(expression, context))
        idx = end + 2
    payload = "".join(result)
    return payload.strip().replace(" ", "").upper()


def _evaluate_expression(expression: str, context: Mapping[str, Any]) -> str:
    if " if " in expression and " else " in expression:
        true_part, remainder = expression.split(" if ", 1)
        condition_part, false_part = remainder.split(" else ", 1)
        condition_value = _resolve_token(condition_part.strip(), context)
        chosen = true_part if bool(condition_value) else false_part
        return str(_resolve_token(chosen.strip(), context))

    parts = [segment.strip() for segment in expression.split("|")]
    value = _resolve_token(parts[0], context)
    for part in parts[1:]:
        if part == "int":
            value = int(value)
            continue
        if part.startswith("format"):
            start = part.find("(")
            end = part.rfind(")")
            if start == -1 or end == -1:
                raise ValueError(f"Invalid format expression: {part}")
            fmt_token = part[start + 1 : end].strip()
            fmt = str(_resolve_token(fmt_token, context))
            value = format(value, fmt)
            continue
        raise ValueError(f"Unsupported template filter: {part}")
    return str(value)


def _resolve_token(token: str, context: Mapping[str, Any]) -> Any:
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    if token in context:
        return context[token]
    if token.isdigit():
        return int(token)
    raise ValueError(f"Unknown token in template: {token}")


def _hex_to_bytes(hex_string: str) -> bytes:
    """Convert hexadecimal text into a byte string."""

    text = hex_string.strip().replace(" ", "")
    if len(text) % 2:
        text = f"0{text}"
    return bytes.fromhex(text)


def _command_payload(
    template: CommandTemplate, context: Mapping[str, Any]
) -> tuple[dict[str, Any], list[int]]:
    """Render a command payload and assemble transport metadata."""

    payload_hex = _render_payload(template, context)
    payload_bytes = list(_hex_to_bytes(payload_hex))
    opcode_int = int(template.opcode, 16)
    ble_frame = opcodes.ble_command_to_base64([opcode_int], payload_bytes)
    iot_payload = opcodes.iot_payload_to_base64(payload_bytes)
    return (
        {
            "name": template.name,
            "opcode": template.opcode,
            "payload_hex": payload_hex,
            "ble_base64": ble_frame,
            "iot_base64": iot_payload,
        },
        payload_bytes,
    )


def _status_payload(
    state_key: str, value: Any, status_sequence: list[int]
) -> list[dict[str, Any]]:
    return [
        {"state": {state_key: value}},
        {"op": {"command": [status_sequence]}},
    ]


def _bool_from_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "on"}:
            return True
        if lowered in {"0", "false", "off"}:
            return False
    return None


def _int_from_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_from_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PowerState(DeviceOpState[bool | None]):
    """Boolean power state that uses catalogue metadata."""

    def __init__(self, device: Any) -> None:
        """Initialise the power state wrapper."""
        entry = _state_entry("power")
        status_opcode = int(entry.identifiers["status"]["opcode"], 16)
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [status_opcode]},
            device=device,
            name="power",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._status_opcode = status_opcode
        value_map = entry.parse_options.get("value_map", {})
        self._value_map = {key.upper(): bool(value) for key, value in value_map.items()}

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse boolean flags from state payloads."""
        power = data.get("isOn")
        if isinstance(power, bool):
            self._update_state(power)
            return
        state_section = data.get("state", {})
        mappings: list[Mapping[str, Any]] = []
        if isinstance(state_section, Mapping):
            mappings.append(state_section)
            inner_state = state_section.get("state")
            if isinstance(inner_state, Mapping):
                mappings.append(inner_state)
        for mapping in mappings:
            for key in ("power", "onOff", "isOn"):
                nested_value = mapping.get(key)
                if isinstance(nested_value, bool):
                    self._update_state(nested_value)
                    return

    def parse_op_command(self, op_command: list[int]) -> None:
        """Update power state from opcode responses."""
        if len(op_command) < 3:
            return
        hex_value = "".join(f"{value:02X}" for value in op_command[1:3])
        mapped = self._value_map.get(hex_value)
        if mapped is not None:
            self._update_state(mapped)

    def _state_to_command(self, next_state: bool | None):
        """Translate boolean requests into command payloads."""
        value = _bool_from_value(next_state)
        if value is None:
            return None
        command, payload_bytes = _command_payload(
            self._command_template, {"value": value}
        )
        status_sequence = [_REPORT_OPCODE, self._status_opcode, payload_bytes[-1]]
        return {
            "command": command,
            "status": _status_payload("power", value, status_sequence),
        }


class ActiveState(DeviceOpState[bool | None]):
    """Derived active/inactive state that consumes opcode payloads."""

    def __init__(self, device: Any) -> None:
        """Initialise the active state handler."""
        entry = _state_entry("active")
        status_opcode = int(entry.identifiers["status"]["opcode"], 16)
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [status_opcode]},
            device=device,
            name="active",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._status_opcode = status_opcode

    def parse_state(self, data: dict[str, Any]) -> None:
        """Extract active flag from state payloads."""
        state_payload = data.get("state", {})
        active = state_payload.get("active")
        if not isinstance(active, bool):
            active = state_payload.get("isOn")
        if isinstance(active, bool):
            self._update_state(active)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Consume opcode payloads representing active state."""
        if len(op_command) < 3:
            return
        value = op_command[2]
        if value in (0x00, 0x01):
            self._update_state(value == 0x01)

    def _state_to_command(self, next_state: bool | None):
        """Translate active state requests into command payloads."""
        value = _bool_from_value(next_state)
        if value is None:
            return None
        command, payload_bytes = _command_payload(
            self._command_template, {"value": value}
        )
        status_sequence = [_REPORT_OPCODE, self._status_opcode, payload_bytes[-1]]
        return {
            "command": command,
            "status": _status_payload("active", value, status_sequence),
        }


class BrightnessState(DeviceOpState[int | None]):
    """Brightness percentage state with range validation."""

    def __init__(self, device: Any) -> None:
        """Initialise the brightness handler with range metadata."""
        entry = _state_entry("brightness")
        status_opcode = int(entry.identifiers["status"]["opcode"], 16)
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [status_opcode]},
            device=device,
            name="brightness",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._status_opcode = status_opcode
        scaling = entry.parse_options.get("scaling", {})
        self._min = scaling.get("min", 0)
        self._max = scaling.get("max", 100)

    def _in_range(self, value: int | None) -> bool:
        return value is not None and self._min <= value <= self._max

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse brightness percentages from state payloads."""
        brightness = data.get("state", {}).get("brightness")
        brightness_int = _int_from_value(brightness)
        if self._in_range(brightness_int):
            self._update_state(brightness_int)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Interpret opcode payloads carrying brightness values."""
        if len(op_command) < 3:
            return
        brightness = op_command[2]
        if self._in_range(brightness):
            self._update_state(brightness)

    def _state_to_command(self, next_state: int | None):
        """Convert brightness requests into command payloads."""
        value = _int_from_value(next_state)
        if not self._in_range(value):
            return None
        command, _payload = _command_payload(self._command_template, {"value": value})
        status_sequence = [_REPORT_OPCODE, self._status_opcode, value]
        return {
            "command": command,
            "status": _status_payload("brightness", value, status_sequence),
        }


class ColorRGBState(DeviceOpState[dict[str, int] | None]):
    """RGB colour state that validates individual channels."""

    def __init__(self, device: Any) -> None:
        """Initialise the RGB state handler."""
        entry = _state_entry("color_rgb")
        status_opcode = int(entry.identifiers["status"]["opcode"], 16)
        super().__init__(
            op_identifier={"op_type": _REPORT_OPCODE, "identifier": [status_opcode]},
            device=device,
            name="color",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
            state_to_command=self._state_to_command,
        )
        self._command_template = entry.command_templates[0]
        self._status_opcode = status_opcode

    def _validate_channels(
        self, channels: Mapping[str, Any] | None
    ) -> dict[str, int] | None:
        if channels is None:
            return None
        red = _int_from_value(channels.get("red"))
        green = _int_from_value(channels.get("green"))
        blue = _int_from_value(channels.get("blue"))
        if None in (red, green, blue):
            return None
        if not all(0 <= channel <= 255 for channel in (red, green, blue)):
            return None
        return {"red": red, "green": green, "blue": blue}

    def parse_state(self, data: dict[str, Any]) -> None:
        """Parse colour channel data from structured payloads."""
        colour = data.get("state", {}).get("color")
        validated = self._validate_channels(colour)
        if validated is not None:
            self._update_state(validated)

    def parse_op_command(self, op_command: list[int]) -> None:
        """Interpret opcode payloads representing colour channels."""
        if len(op_command) < 5:
            return
        channels = {"red": op_command[2], "green": op_command[3], "blue": op_command[4]}
        validated = self._validate_channels(channels)
        if validated is not None:
            self._update_state(validated)

    def _state_to_command(self, next_state: Mapping[str, Any] | None):
        """Convert RGB mappings into command payloads."""
        channels = self._validate_channels(
            next_state if isinstance(next_state, Mapping) else None
        )
        if channels is None:
            return None
        command, payload_bytes = _command_payload(self._command_template, channels)
        status_sequence = [
            _REPORT_OPCODE,
            self._status_opcode,
            channels["red"],
            channels["green"],
            channels["blue"],
        ]
        return {
            "command": command,
            "status": _status_payload("color", channels, status_sequence),
        }


class ColorTemperatureState(DeviceState[int | None]):
    """Represent the color temperature setting for supported lights."""

    def __init__(
        self,
        *,
        device: object,
        minimum: int = 2000,
        maximum: int = 9000,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the color temperature state wrapper."""

        super().__init__(
            device=device,
            name="colorTemperature",
            initial_value=None,
            parse_option=ParseOption.NONE,
        )
        self._minimum = minimum
        self._maximum = maximum
        self._identifier = list(identifier) if identifier is not None else []

    def set_state(self, next_state: Any) -> list[str]:
        """Update the stored color temperature when ``next_state`` is valid."""

        value = _int_from_value(next_state)
        if value is None:
            return []
        if value < self._minimum or value > self._maximum:
            return []
        self._update_state(value)
        return [self.name]


class SegmentColorState(DeviceState[list[int] | None]):
    """Expose segment-based RGB values for RGBIC devices."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the segment colour tracker."""

        super().__init__(
            device=device,
            name="segmentColor",
            initial_value=None,
            parse_option=ParseOption.NONE,
        )
        self._identifier = list(identifier) if identifier is not None else []

    def set_state(self, next_state: Any) -> list[str]:
        """Update segment colours when the payload is well-formed."""

        if not isinstance(next_state, list | tuple):
            return []
        values: list[int] = []
        for value in next_state:
            numeric = _int_from_value(value)
            if numeric is None or not 0 <= numeric <= 255:
                return []
            values.append(numeric)
        if len(values) % 3 != 0:
            return []
        self._update_state(values)
        return [self.name]


class SceneModeState(DeviceOpState[dict[str, int]]):
    """Track the currently active scene identifiers for RGB lights."""

    def __init__(
        self,
        *,
        device: object,
        op_type: int = _REPORT_OPCODE,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the scene mode opcode state handler."""

        identifiers = [0x05, 0x04] if identifier is None else list(identifier)
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="sceneMode",
            initial_value={"sceneId": None, "sceneParamId": None},
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode the reported scene identifier and parameters."""

        payload = op_command[3:]
        if len(payload) < 4:
            return
        scene_id = int.from_bytes(payload[0:2], "big")
        scene_param_id = int.from_bytes(payload[2:4], "big")
        self._update_state({"sceneId": scene_id, "sceneParamId": scene_param_id})


class _IdentifierStringState(DeviceState[str | None]):
    """Base class for identifier-backed string states."""

    def __init__(
        self,
        *,
        device: object,
        name: str,
        identifier: Sequence[int] | None = None,
        options: Sequence[str] | None = None,
        state_to_command: Callable[[Any], StateCommandAndStatus | None] | None = None,
    ) -> None:
        """Initialise the identifier-tracked string state."""

        super().__init__(
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.NONE,
            state_to_command=state_to_command,
        )
        self._identifier = list(identifier) if identifier is not None else []
        self.options = list(options) if options is not None else []

    def set_state(self, next_state: Any) -> list[str]:
        """Persist string values after normalising whitespace."""

        if not isinstance(next_state, str):
            return []
        value = next_state.strip()
        if not value:
            return []
        if self.is_commandable:
            command_ids = DeviceState.set_state(self, value)
            if command_ids:
                self._update_state(value)
            return command_ids
        self._update_state(value)
        return [self.name]


class LightEffectState(_IdentifierStringState):
    """Represent the active light effect mode."""

    def __init__(
        self, *, device: object, identifier: Sequence[int] | None = None
    ) -> None:
        """Initialise the light effect selector."""

        entry = _state_entry("scene")
        value_map = entry.parse_options.get("value_map", {})
        options = list(value_map.values())
        self._scene_codes = {
            str(value).strip().upper(): str(key).upper()
            for key, value in value_map.items()
        }
        self._command_template = entry.command_templates[0]
        status_opcode = int(entry.identifiers["status"]["opcode"], 16)
        self._status_opcode = status_opcode
        super().__init__(
            device=device,
            name="lightEffect",
            identifier=identifier,
            options=options,
            state_to_command=self._state_to_command,
        )

    def _state_to_command(self, next_state: Any):
        if not isinstance(next_state, str):
            return None
        token = next_state.strip()
        if not token:
            return None
        key = token.upper()
        code = self._scene_codes.get(key)
        if code is None:
            return None
        command, payload_bytes = _command_payload(
            self._command_template, {"scene_id": code}
        )
        status_sequence = [_REPORT_OPCODE, self._status_opcode, *payload_bytes[1:]]
        return {
            "command": command,
            "status": _status_payload(self.name, token, status_sequence),
        }


_RGBIC_MIC_IDENTIFIER = [0x05, 0x13]
_DEFAULT_MIC_SENSITIVITY = 50


class MicModeState(DeviceOpState[dict[str, Any]]):
    """Track the active microphone reactive mode."""

    def __init__(
        self,
        *,
        device: object,
        identifier: Sequence[int] | None = None,
        op_type: int = _REPORT_OPCODE,
    ) -> None:
        """Initialise the microphone mode selector."""

        identifiers = (
            list(identifier) if identifier is not None else list(_RGBIC_MIC_IDENTIFIER)
        )
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name="micMode",
            initial_value={},
            state_to_command=self._state_to_command,
        )
        # Retain compatibility with select entities expecting an options attribute.
        self.options: list[str] = []

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode microphone mode payloads into structured values."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 7:
            return
        mic_scene, sensitivity, calm, auto_color, red, green, blue = payload[:7]
        self._update_state(
            {
                "micScene": mic_scene,
                "sensitivity": sensitivity,
                "calm": calm == 0x01,
                "autoColor": auto_color == 0x01,
                "color": {"red": red, "green": green, "blue": blue},
            }
        )

    def _coerce_next_state(self, next_state: Any) -> Mapping[str, Any] | None:
        if isinstance(next_state, Mapping):
            return next_state
        if isinstance(next_state, str):
            token = next_state.strip()
            if not token:
                return None
            try:
                decoded = json.loads(token)
            except ValueError:
                return self._parse_assignment_string(token)
            return self._mapping_from_json(decoded)
        return None

    def _parse_assignment_string(self, token: str) -> Mapping[str, Any] | None:
        pairs: dict[str, Any] = {}
        normalised = token.replace(";", ",")
        segments = [segment for segment in normalised.split(",") if segment]
        if not segments:
            return None
        if len(segments) == 1 and "=" not in segments[0]:
            try:
                mic_scene = int(segments[0], 0)
            except ValueError:
                return None
            return {"micScene": mic_scene}
        for segment in segments:
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            key = key.strip()
            raw_value = value.strip()
            if not key:
                continue
            lowered = raw_value.lower()
            if lowered in {"true", "false"}:
                pairs[key] = lowered == "true"
                continue
            try:
                pairs[key] = int(raw_value, 0)
                continue
            except ValueError:
                pass
            try:
                pairs[key] = float(raw_value)
                continue
            except ValueError:
                pairs[key] = raw_value
        if pairs:
            return pairs
        return None

    def _mapping_from_json(self, decoded: Any) -> Mapping[str, Any] | None:
        if isinstance(decoded, Mapping):
            return decoded
        if isinstance(decoded, Sequence) and not isinstance(
            decoded, str | bytes | Mapping
        ):
            pairs = self._pairs_from_sequence(decoded)
            if pairs:
                return pairs
        if isinstance(decoded, int | float):
            return {"micScene": int(decoded)}
        return None

    def _pairs_from_sequence(self, decoded: Sequence[Any]) -> dict[str, Any]:
        pairs: dict[str, Any] = {}
        for entry in decoded:
            if (
                isinstance(entry, Sequence)
                and not isinstance(entry, str | bytes | Mapping)
                and len(entry) >= 2
            ):
                key = entry[0]
                if isinstance(key, str):
                    pairs[key] = entry[1]
        return pairs

    def _state_to_command(
        self, next_state: Any
    ) -> StateCommandAndStatus | None:  # type: ignore[override]
        resolved_next = self._coerce_next_state(next_state)
        if resolved_next is None:
            return None
        next_state = resolved_next

        current = self.value if isinstance(self.value, Mapping) else {}

        def _pick_int(*candidates: Any, default: int) -> int:
            for candidate in candidates:
                if isinstance(candidate, bool):
                    continue
                if isinstance(candidate, int | float):
                    return int(candidate)
            return default

        def _pick_bool(*candidates: Any, default: bool) -> bool:
            for candidate in candidates:
                if isinstance(candidate, bool):
                    return candidate
                if isinstance(candidate, int | float):
                    return bool(int(candidate))
            return default

        current_color = (
            current.get("color") if isinstance(current.get("color"), Mapping) else {}
        )
        next_color = (
            next_state.get("color")
            if isinstance(next_state.get("color"), Mapping)
            else {}
        )

        resolved = {
            "micScene": _pick_int(
                next_state.get("micScene"), current.get("micScene"), default=0
            ),
            "sensitivity": _pick_int(
                next_state.get("sensitivity"),
                current.get("sensitivity"),
                default=_DEFAULT_MIC_SENSITIVITY,
            ),
            "calm": _pick_bool(
                next_state.get("calm"), current.get("calm"), default=False
            ),
            "autoColor": _pick_bool(
                next_state.get("autoColor"),
                current.get("autoColor"),
                default=False,
            ),
            "color": {
                "red": _pick_int(
                    next_color.get("red"), current_color.get("red"), default=0
                ),
                "green": _pick_int(
                    next_color.get("green"), current_color.get("green"), default=0
                ),
                "blue": _pick_int(
                    next_color.get("blue"), current_color.get("blue"), default=0
                ),
            },
        }

        prefix = list(self._identifier or [])
        calm_byte = 0x01 if resolved["calm"] else 0x00
        auto_color_byte = 0x01 if resolved["autoColor"] else 0x00
        color_values = resolved["color"]
        frame = _opcode_frame(
            0x33,
            *prefix,
            resolved["micScene"],
            resolved["sensitivity"],
            calm_byte,
            auto_color_byte,
            color_values["red"],
            color_values["green"],
            color_values["blue"],
        )
        status_sequence = [
            _REPORT_OPCODE,
            *prefix,
            resolved["micScene"],
            resolved["sensitivity"],
            calm_byte,
            auto_color_byte,
            color_values["red"],
            color_values["green"],
            color_values["blue"],
        ]

        return {
            "command": {
                "command": "multi_sync",
                "data": {"command": [frame]},
            },
            "status": {"op": {"command": [status_sequence]}},
        }


class RGBICModes(IntEnum):
    """Enumeration of RGBIC mode identifiers."""

    WHOLE_COLOR = 0x02
    SCENE = 0x04
    DIY = 0x0A
    MIC = 0x13
    SEGMENT_COLOR = 0x15


class DiyModeState(DeviceOpState[dict[str, Any]]):
    """Manage DIY scene selections for RGBIC lights."""

    def __init__(self, *, device: object) -> None:
        """Initialise the DIY mode selector."""

        super().__init__(
            op_identifier={
                "op_type": _REPORT_OPCODE,
                "identifier": [0x05, RGBICModes.DIY],
            },
            device=device,
            name="diyMode",
            initial_value={},
            parse_option=ParseOption.OP_CODE,
            state_to_command=self._state_to_command,
        )
        self._effects: dict[int, dict[str, Any]] = {}
        self._effects_by_name: dict[str, dict[str, Any]] = {}
        self._active_effect_code: int | None = None

    @property
    def active_effect_code(self) -> int | None:
        """Return the code for the active DIY effect."""

        return self._active_effect_code

    def update_effects(self, effects: Sequence[Mapping[str, Any]]) -> None:
        """Store DIY effect metadata provided by catalogue updates."""

        changed = False
        for effect in effects:
            code = effect.get("code") if isinstance(effect, Mapping) else None
            if not isinstance(code, int):
                continue
            stored = dict(effect.items())
            previous = self._effects.get(code)
            if previous is not None:
                old_name = previous.get("name")
                if isinstance(old_name, str):
                    self._effects_by_name.pop(old_name.strip().upper(), None)
            if self._effects.get(code) != stored:
                self._effects[code] = stored
                changed = True
            name = stored.get("name")
            if isinstance(name, str):
                self._effects_by_name[name.strip().upper()] = stored
        if changed and self._active_effect_code is not None:
            active = self._effects.get(self._active_effect_code)
            if active is not None:
                self._update_state(dict(active))

    def parse_op_command(self, op_command: list[int]) -> None:
        """Decode opcode payloads to update the active DIY effect."""

        payload = _strip_op_header(op_command, self._op_type, self._identifier)
        if len(payload) < 2:
            return
        effect_code = (payload[1] << 8) | payload[0]
        self._active_effect_code = effect_code
        effect = self._effects.get(effect_code)
        if effect is not None:
            self._update_state(dict(effect))

    def _state_to_command(self, next_state: Any) -> StateCommandAndStatus | None:
        """Translate DIY selections into opcode command payloads."""

        effect = self._resolve_effect(next_state)
        if effect is None:
            return None
        code = effect.get("code")
        if not isinstance(code, int):
            return None
        identifier = self._command_identifier()
        commands = self._rebuild_diy_commands(code, effect.get("diyOpCodeBase64"))
        if not commands:
            return None
        status_sequence = [
            _REPORT_OPCODE,
            *identifier,
            code & 0xFF,
            (code >> 8) & 0xFF,
        ]
        self._active_effect_code = code
        self._update_state(dict(effect))
        return {
            "command": {
                "type": 1,
                "cmdVersion": effect.get("cmdVersion", 0),
                "data": {"command": commands},
            },
            "status": [
                {"op": {"command": [status_sequence]}},
                {"state": {self.name: dict(effect)}},
            ],
        }

    def _resolve_effect(self, candidate: Any) -> dict[str, Any] | None:
        if isinstance(candidate, Mapping):
            payload = candidate
        elif isinstance(candidate, str):
            payload = {"name": candidate}
        elif isinstance(candidate, int):
            payload = {"code": candidate}
        else:
            return None
        code = payload.get("code")
        if isinstance(code, int):
            effect = self._effects.get(code)
            if effect is not None:
                return effect
        name = payload.get("name")
        if isinstance(name, str):
            return self._effects_by_name.get(name.strip().upper())
        return None

    def _rebuild_diy_commands(self, code: int, opcode_b64: Any) -> list[list[int]]:
        if not isinstance(opcode_b64, str):
            return []
        try:
            decoded = list(base64.b64decode(opcode_b64))
        except (ValueError, TypeError):
            return []
        payload = [0x01, 0x02, 0x04]
        if decoded:
            payload.extend(decoded[1:])
        chunks = [payload[idx : idx + 17] for idx in range(0, len(payload), 17)]
        commands: list[list[int]] = []
        identifier = self._command_identifier()
        command_prefix = identifier
        report_identifier = identifier[:1] if identifier else [0x05]
        for idx, chunk in enumerate(chunks):
            terminator = 0xFF if idx == len(chunks) - 1 else idx
            commands.append(_opcode_frame(0xA3, terminator, *chunk))
        commands.append(
            _opcode_frame(
                0x33,
                *command_prefix,
                code & 0xFF,
                (code >> 8) & 0xFF,
            )
        )
        commands.append(_opcode_frame(0xAA, report_identifier[0], 0x01))
        return commands

    def _command_identifier(self) -> list[int]:
        identifier = self._identifier or [0x05, int(RGBICModes.DIY)]
        return [int(value) for value in identifier]


class UnknownState(DeviceOpState[dict[str, Any]]):
    """Record raw opcode payloads that do not map to known states."""

    def __init__(
        self,
        *,
        device: object,
        op_type: int = _REPORT_OPCODE,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the unknown state handler for passthrough data."""

        identifiers = list(identifier) if identifier is not None else []
        name_suffix = ",".join(str(value) for value in identifiers)
        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifiers},
            device=device,
            name=f"unknown-{name_suffix}",
            initial_value={},
            parse_option=ParseOption.OP_CODE,
        )

    def parse_op_command(self, op_command: list[int]) -> None:
        """Persist the opcode payload for inspection."""

        self._update_state({"codes": list(op_command)})
