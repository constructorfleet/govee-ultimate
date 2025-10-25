"""Concrete device state implementations backed by the catalog."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Any

from .. import opcodes
from ..state_catalog import CommandTemplate, StateEntry, load_state_catalog
from .device_state import DeviceOpState, ParseOption

_REPORT_OPCODE = 0xAA


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


def _command_payload(template: CommandTemplate, context: Mapping[str, Any]) -> tuple[dict[str, Any], list[int]]:
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


def _status_payload(state_key: str, value: Any, status_sequence: list[int]) -> list[dict[str, Any]]:
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
        command, payload_bytes = _command_payload(self._command_template, {"value": value})
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
        command, payload_bytes = _command_payload(self._command_template, {"value": value})
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

    def _validate_channels(self, channels: Mapping[str, Any] | None) -> dict[str, int] | None:
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
        channels = self._validate_channels(next_state if isinstance(next_state, Mapping) else None)
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

