"""Tests for opcode conversion and command assembly helpers."""

import pytest

import base64

from custom_components.govee_ultimate import opcodes


def test_as_opcode_normalizes_int_and_string_inputs() -> None:
    """`as_opcode` should normalize numeric and string forms to 0x-prefixed uppercase."""

    assert opcodes.as_opcode(1) == "0x01"
    assert opcodes.as_opcode("1") == "0x01"
    assert opcodes.as_opcode("0x1a") == "0x1A"


def test_as_opcode_rejects_invalid_strings() -> None:
    """Invalid inputs should trigger value errors."""

    with pytest.raises(ValueError):
        opcodes.as_opcode("g1")
    with pytest.raises(ValueError):
        opcodes.as_opcode("")


def test_opcode_catalog_contains_power_and_brightness_commands() -> None:
    """The opcode catalog loader should expose the canonical command vectors."""

    catalog = opcodes.load_opcode_catalog()

    power_on = next(entry for entry in catalog["commands"] if entry["name"] == "power_on")
    assert power_on["identifiers"] == [0x33, 0x01, 0x01]
    assert power_on["vectors"]["ble"] == "MwEBAQAAAAAAAAAAAAAAAAAAADI="

    brightness = next(entry for entry in catalog["commands"] if entry["name"] == "brightness_75")
    assert brightness["identifiers"] == [0x33, 0x04, 0x01]
    assert brightness["extra_payload_hex"] == "00"


def test_hex_base64_round_trip_matches_known_vector() -> None:
    """Hexadecimal payloads should convert to base64 and back consistently."""

    encoded = opcodes.hex_to_base64("330101")
    assert encoded == "MwEB"
    assert opcodes.base64_to_hex(encoded) == "330101"


def test_assemble_command_matches_power_vector() -> None:
    """Command assembly should reproduce the recorded BLE payload."""

    catalog = opcodes.load_opcode_catalog()
    entry = next(item for item in catalog["commands"] if item["name"] == "power_on")
    payload = bytes.fromhex(entry["payload_hex"])
    frame = opcodes.assemble_command(entry["identifiers"], payload)

    assert base64.b64encode(frame).decode("ascii") == entry["vectors"]["ble"]


def test_ble_command_helper_uses_catalog_vectors() -> None:
    """The BLE helper should wrap assembly and return the recorded base64 string."""

    catalog = opcodes.load_opcode_catalog()
    entry = next(item for item in catalog["commands"] if item["name"] == "brightness_75")
    payload = bytes.fromhex(entry["payload_hex"])
    extra = bytes.fromhex(entry["extra_payload_hex"])

    result = opcodes.ble_command_to_base64(entry["identifiers"], payload, extra_payload=extra)

    assert result == entry["vectors"]["ble"]


def test_iot_payload_helper_encodes_bytes() -> None:
    """Raw IoT payloads should be converted to base64 without framing."""

    assert opcodes.iot_payload_to_base64([0x01, 0xFF]) == "Af8="
