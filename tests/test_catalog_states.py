"""Tests for catalog-driven device state subclasses."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from custom_components.govee_ultimate import opcodes
from custom_components.govee_ultimate.state.states import (
    ActiveState,
    BrightnessState,
    ColorRGBState,
    ColorTemperatureState,
    PowerState,
)
from custom_components.govee_ultimate.state_catalog import load_state_catalog


class DummyDevice:
    """Minimal device stub for queue-based tests."""

    def add_status_listener(self, _callback):  # pragma: no cover - compatibility shim
        """State classes expect a listener registration hook."""


def _drain(queue) -> list[dict[str, object]]:
    """Drain an asyncio queue synchronously for inspection."""

    items: list[dict[str, object]] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _ble_frame(opcode_hex: str, payload_hex: str) -> str:
    """Assemble a BLE frame for assertions."""

    opcode_int = int(opcode_hex, 16)
    payload = bytes.fromhex(payload_hex)
    return opcodes.ble_command_to_base64([opcode_int], payload)


def _first_pending(state, command_id: str) -> Sequence[dict[str, object]]:
    """Fetch the stored pending expectations for a command id."""

    pending = state._pending_commands[command_id]  # type: ignore[attr-defined]
    assert isinstance(pending, list)
    return pending


def test_power_state_parses_nested_booleans() -> None:
    """Power state accepts top-level or nested boolean payloads."""

    state = PowerState(DummyDevice())

    state.parse({"cmd": "status", "state": {"isOn": True}})
    assert state.value is True

    state.parse({"cmd": "status", "state": {"state": {"onOff": False}}})
    assert state.value is False

    state.parse({"cmd": "status", "state": {"state": {"isOn": True}}})
    assert state.value is True


def test_power_state_generates_catalog_based_command() -> None:
    """Power commands include metadata-driven payloads and expectations."""

    catalog = load_state_catalog()
    entry = catalog.get_state("power")
    command_template = entry.command_templates[0]

    state = PowerState(DummyDevice())

    command_ids = state.set_state(True)
    assert command_ids

    command_payloads = _drain(state.command_queue)
    assert len(command_payloads) == 1
    command = command_payloads[0]

    assert command["name"] == command_template.name
    assert command["opcode"] == command_template.opcode
    assert command["payload_hex"] == "0101"
    assert command["ble_base64"] == _ble_frame(command_template.opcode, "0101")

    pending = _first_pending(state, command_ids[0])
    assert any("state" in expectation for expectation in pending)
    assert any("op" in expectation for expectation in pending)

    state.parse({"cmd": "status", "state": {"power": True}})

    cleared = _drain(state.clear_queue)
    assert cleared
    assert cleared[0]["command_id"] == command_ids[0]


def test_active_state_updates_from_op_payload() -> None:
    """Active state consumes opcode payloads for boolean state."""

    catalog = load_state_catalog()
    entry = catalog.get_state("active")
    command_template = entry.command_templates[0]

    state = ActiveState(DummyDevice())

    command_ids = state.set_state(True)
    assert command_ids

    command_payloads = _drain(state.command_queue)
    assert command_payloads
    command = command_payloads[0]

    assert command["payload_hex"].endswith("01")
    assert command["ble_base64"] == _ble_frame(
        command_template.opcode, command["payload_hex"]
    )

    status_sequence = [0xAA, int(entry.identifiers["status"]["opcode"], 16), 0x01]
    state.parse({"op": {"command": [status_sequence]}})

    assert state.value is True

    cleared = _drain(state.clear_queue)
    assert cleared and cleared[0]["command_id"] == command_ids[0]


@pytest.mark.parametrize("invalid_value", [-1, 101, None])
def test_brightness_state_rejects_out_of_range_values(invalid_value) -> None:
    """Brightness commands validate range before emitting payloads."""

    state = BrightnessState(DummyDevice())

    assert state.set_state(invalid_value) == []
    assert state.command_queue.empty()


def test_brightness_state_command_and_status_alignment() -> None:
    """Brightness command uses catalog template and clears on opcode payload."""

    state = BrightnessState(DummyDevice())

    command_ids = state.set_state(42)
    assert command_ids

    command_payloads = _drain(state.command_queue)
    assert command_payloads
    command = command_payloads[0]

    assert command["payload_hex"] == "022A00"
    assert command["ble_base64"] == _ble_frame(command["opcode"], "022A00")

    state.parse({"cmd": "status", "state": {"brightness": 42}})
    state.parse({"op": {"command": [[0xAA, 0x02, 0x2A]]}})

    assert state.value == 42

    cleared = _drain(state.clear_queue)
    assert cleared and cleared[0]["command_id"] == command_ids[0]


@pytest.mark.parametrize("invalid_value", [None, 1999, 8701])
def test_color_temperature_state_rejects_out_of_range_values(invalid_value) -> None:
    """Color temperature commands require catalog-defined range values."""

    state = ColorTemperatureState(device=DummyDevice())

    assert state.set_state(invalid_value) == []
    assert state.command_queue.empty()


def test_color_temperature_state_generates_catalog_command_and_clears() -> None:
    """Color temperature command uses template payloads and clears on responses."""

    catalog = load_state_catalog()
    entry = catalog.get_state("color_temperature")
    command_template = entry.command_templates[0]
    status_opcode = int(entry.identifiers["status"]["opcode"], 16)

    state = ColorTemperatureState(device=DummyDevice())

    command_ids = state.set_state(3200)
    assert command_ids

    command_payloads = _drain(state.command_queue)
    assert command_payloads
    command = command_payloads[0]

    assert command["name"] == command_template.name
    assert command["opcode"] == command_template.opcode
    assert command["payload_hex"] == "030C80"
    assert command["ble_base64"] == _ble_frame(command["opcode"], "030C80")

    pending = _first_pending(state, command_ids[0])
    assert any(
        expectation.get("state", {}).get("colorTem") == 3200 for expectation in pending
    )
    assert any("op" in expectation for expectation in pending)

    state.parse({"cmd": "status", "state": {"colorTem": 3200}})
    state.parse({"op": {"command": [[0xAA, status_opcode, 0x0C, 0x80]]}})

    assert state.value == 3200

    cleared = _drain(state.clear_queue)
    assert cleared and cleared[0]["command_id"] == command_ids[0]


def test_color_rgb_state_requires_complete_channels() -> None:
    """Color RGB state normalises payloads using the catalog metadata."""

    state = ColorRGBState(DummyDevice())

    # Missing blue channel -> command should be skipped
    assert state.set_state({"red": 16, "green": 32}) == []

    command_ids = state.set_state({"red": 16, "green": 32, "blue": 48})
    assert command_ids

    command_payloads = _drain(state.command_queue)
    assert command_payloads
    command = command_payloads[0]

    assert command["payload_hex"] == "04102030"
    assert command["ble_base64"] == _ble_frame(command["opcode"], "04102030")

    state.parse(
        {
            "op": {"command": [[0xAA, 0x04, 0x10, 0x20, 0x30]]},
            "state": {"color": {"red": 16, "green": 32, "blue": 48}},
        }
    )

    assert state.value == {"red": 16, "green": 32, "blue": 48}


def test_state_handlers_expose_method_docstrings() -> None:
    """All catalog-backed state handlers document their entry points."""

    doc_targets = [
        (PowerState, ["__init__", "parse_state", "parse_op_command"]),
        (ActiveState, ["__init__", "parse_state", "parse_op_command"]),
        (BrightnessState, ["__init__", "parse_state", "parse_op_command"]),
        (ColorRGBState, ["__init__", "parse_state", "parse_op_command"]),
    ]

    for cls, method_names in doc_targets:
        for method_name in method_names:
            method = getattr(cls, method_name)
            assert method.__doc__, f"Missing docstring on {cls.__name__}.{method_name}"
