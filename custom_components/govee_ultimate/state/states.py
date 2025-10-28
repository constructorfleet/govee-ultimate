"""Concrete device state implementations backed by the catalog."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Any

from .. import opcodes
from collections.abc import Sequence

from ..state_catalog import CommandTemplate, StateEntry, load_state_catalog
from .device_state import DeviceOpState, DeviceState, ParseOption

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
    ) -> None:
        """Initialise the composite mode state handler."""

        super().__init__(
            op_identifier={"op_type": op_type, "identifier": identifier},
            device=device,
            name="mode",
            initial_value=None,
            parse_option=ParseOption.OP_CODE | ParseOption.STATE,
        )
        self._identifier_map = identifier_map
        self._inline = inline
        self._active_identifier: list[int] | None = None
        self._modes: list[DeviceState[str]] = []
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


class HumidityState(DeviceState[int | None]):
    """Report the current ambient humidity percentage."""

    def __init__(self, *, device: object) -> None:
        """Initialise the humidity sensor state handler."""

        super().__init__(device=device, name="humidity", initial_value=None)

    def parse(self, data: dict[str, Any]) -> None:
        """Parse humidity readings from nested state payloads."""

        state_section = data.get("state")
        if not isinstance(state_section, Mapping):
            return
        candidates = [state_section]
        inner = state_section.get("state")
        if isinstance(inner, Mapping):
            candidates.append(inner)
        for mapping in candidates:
            value = mapping.get("humidity")
            humidity = _int_from_value(value)
            if humidity is None:
                continue
            if 0 <= humidity <= 100:
                self._update_state(humidity)
            return


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
        frame = _opcode_frame(
            0x33, *self._identifier, 0x01 if on_flag else 0x00, *segments
        )
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
        frame = _opcode_frame(
            0x33, *self._identifier, 0x01 if on_flag else 0x00, brightness
        )
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


class _IdentifierStringState(DeviceState[str | None]):
    """Base class for identifier-backed string states."""

    def __init__(
        self,
        *,
        device: object,
        name: str,
        identifier: Sequence[int] | None = None,
    ) -> None:
        """Initialise the identifier-tracked string state."""

        super().__init__(
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.NONE,
        )
        self._identifier = list(identifier) if identifier is not None else []

    def set_state(self, next_state: Any) -> list[str]:
        """Persist string values after normalising whitespace."""

        if not isinstance(next_state, str):
            return []
        value = next_state.strip()
        if not value:
            return []
        self._update_state(value)
        return [self.name]


class LightEffectState(_IdentifierStringState):
    """Represent the active light effect mode."""

    def __init__(
        self, *, device: object, identifier: Sequence[int] | None = None
    ) -> None:
        """Initialise the light effect selector."""

        super().__init__(device=device, name="lightEffect", identifier=identifier)


class MicModeState(_IdentifierStringState):
    """Track the active microphone reactive mode."""

    def __init__(
        self, *, device: object, identifier: Sequence[int] | None = None
    ) -> None:
        """Initialise the microphone mode selector."""

        super().__init__(device=device, name="micMode", identifier=identifier)


class DiyModeState(_IdentifierStringState):
    """Manage DIY scene selections for RGBIC lights."""

    def __init__(
        self, *, device: object, identifier: Sequence[int] | None = None
    ) -> None:
        """Initialise the DIY mode selector."""

        super().__init__(device=device, name="diyMode", identifier=identifier)
