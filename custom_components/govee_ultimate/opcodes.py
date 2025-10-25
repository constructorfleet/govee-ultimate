"""Opcode conversion helpers for assembling Ultimate Govee commands."""

from __future__ import annotations

import json
from pathlib import Path
import base64
from typing import Any, Sequence, TypedDict, cast


class OpcodeVectors(TypedDict):
    """Base64-encoded transport payloads."""

    ble: str
    iot: str


class OpcodeCommand(TypedDict):
    """Single opcode catalogue entry."""

    name: str
    opcode: str
    identifiers: list[int]
    payload_hex: str
    extra_payload_hex: str
    vectors: OpcodeVectors
    description: str


class OpcodeCatalog(TypedDict):
    """Top-level opcode catalogue payload."""

    commands: list[OpcodeCommand]


_DEFAULT_CATALOG_PATH = Path(__file__).parent / "data" / "opcode_catalog.json"
_DEFAULT_FRAME_SIZE = 20


def load_opcode_catalog(path: Path | None = None) -> OpcodeCatalog:
    """Load the opcode catalogue JSON data."""

    catalog_path = path or _DEFAULT_CATALOG_PATH
    with catalog_path.open("r", encoding="utf-8") as fp:
        payload: dict[str, Any] = json.load(fp)
    return cast(OpcodeCatalog, payload)


def _ensure_even_length(hex_part: str) -> str:
    """Pad hexadecimal text to an even number of characters."""

    return hex_part if len(hex_part) % 2 == 0 else f"0{hex_part}"


def as_opcode(value: int | str) -> str:
    """Normalise an opcode from integer or string form to ``0x``-prefixed uppercase."""

    if isinstance(value, int):
        if value < 0:
            raise ValueError("Opcode cannot be negative")
        hex_part = f"{value:X}"
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Opcode string is empty")
        text = _normalise_hex(text)
        try:
            int(text, 16)
        except ValueError as exc:  # pragma: no cover - rely on exception chaining for clarity
            raise ValueError(f"Invalid opcode string: {value!r}") from exc
        hex_part = text.upper()
    else:  # pragma: no cover - typing guard
        raise TypeError("Opcode must be provided as int or str")

    return f"0x{_ensure_even_length(hex_part).upper()}"


def _normalise_hex(hex_string: str) -> str:
    """Remove whitespace and ``0x`` prefix before processing a hex string."""

    text = hex_string.strip().replace(" ", "")
    return text[2:] if text.lower().startswith("0x") else text


def hex_to_base64(hex_string: str) -> str:
    """Convert hexadecimal payload text into base64 encoding."""

    normalised = _normalise_hex(hex_string)
    payload = bytes.fromhex(normalised)
    return _to_base64(payload)


def base64_to_hex(payload_b64: str) -> str:
    """Convert base64-encoded payloads back into uppercase hexadecimal text."""

    data = base64.b64decode(payload_b64)
    return data.hex().upper()


def _to_base64(data: bytes) -> str:
    """Encode a byte payload into base64 ASCII text."""

    return base64.b64encode(data).decode("ascii")


def _to_bytes(payload: bytes | Sequence[int] | None) -> bytes:
    """Normalise payload inputs to a byte string."""

    if payload is None:
        return b""
    if isinstance(payload, bytes):
        return payload
    return bytes(payload)


def assemble_command(
    identifiers: Sequence[int],
    payload: bytes | Sequence[int],
    extra_payload: bytes | Sequence[int] | None = None,
    frame_size: int = _DEFAULT_FRAME_SIZE,
) -> bytes:
    """Assemble a BLE command frame with XOR checksum padding."""

    frame = bytearray()
    frame.extend(_to_bytes(identifiers))
    frame.extend(_to_bytes(payload))
    frame.extend(_to_bytes(extra_payload))

    if len(frame) >= frame_size:
        raise ValueError("Payload exceeds frame size")

    frame.extend(b"\x00" * (frame_size - 1 - len(frame)))

    checksum = 0
    for byte in frame:
        checksum ^= byte
    frame.append(checksum)
    return bytes(frame)


def ble_command_to_base64(
    identifiers: Sequence[int],
    payload: bytes | Sequence[int],
    *,
    extra_payload: bytes | Sequence[int] | None = None,
    frame_size: int = _DEFAULT_FRAME_SIZE,
) -> str:
    """Assemble and encode a BLE command frame for transport."""

    frame = assemble_command(identifiers, payload, extra_payload=extra_payload, frame_size=frame_size)
    return _to_base64(frame)


def iot_payload_to_base64(payload: bytes | Sequence[int]) -> str:
    """Encode raw IoT payload bytes into base64."""

    return _to_base64(_to_bytes(payload))
