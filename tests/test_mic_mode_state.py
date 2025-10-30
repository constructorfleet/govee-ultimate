"""Tests for the microphone reactive mode state."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.govee_ultimate.state.states import MicModeState

REPORT_OPCODE = 0xAA
RGBIC_MIC_IDENTIFIER = [0x05, 0x13]


class DummyDevice:
    """Minimal device stub compatible with DeviceState constructors."""

    def add_status_listener(self, _callback: Any) -> None:
        """Accept listeners without retaining them."""


@pytest.fixture
def mic_state() -> MicModeState:
    """Provide a fresh MicModeState instance for each test."""

    return MicModeState(device=DummyDevice())


def test_mic_mode_state_parses_report_payload(mic_state: MicModeState) -> None:
    """The state should decode report opcodes into structured data."""

    report_frame = [
        REPORT_OPCODE,
        *RGBIC_MIC_IDENTIFIER,
        0x02,
        0x32,
        0x01,
        0x00,
        0x10,
        0x20,
        0x30,
    ]

    mic_state.parse({"cmd": "status", "op": {"command": [report_frame]}})

    assert mic_state.value == {
        "micScene": 0x02,
        "sensitivity": 0x32,
        "calm": True,
        "autoColor": False,
        "color": {"red": 0x10, "green": 0x20, "blue": 0x30},
    }


def test_mic_mode_state_set_state_enqueues_command_and_status(
    mic_state: MicModeState,
) -> None:
    """Calling set_state should enqueue the multi-sync command and expected status."""

    initial_report = [
        REPORT_OPCODE,
        *RGBIC_MIC_IDENTIFIER,
        0x03,
        0x2A,
        0x00,
        0x00,
        0x05,
        0x06,
        0x07,
    ]
    mic_state.parse({"cmd": "status", "op": {"command": [initial_report]}})

    command_ids = mic_state.set_state({"autoColor": True, "color": {"red": 0x40}})

    assert command_ids
    command_id = command_ids[0]

    command = mic_state.command_queue.get_nowait()
    assert command["command_id"] == command_id
    assert command["command"] == "multi_sync"

    opcode_frame = command["data"]["command"][0]
    expected_prefix = [
        0x33,
        *RGBIC_MIC_IDENTIFIER,
        0x03,
        0x2A,
        0x00,
        0x01,
        0x40,
        0x06,
        0x07,
    ]
    assert opcode_frame[: len(expected_prefix)] == expected_prefix

    pending_status = mic_state._pending_commands[command_id]  # type: ignore[attr-defined]
    assert pending_status == [
        {
            "op": {
                "command": [
                    [
                        REPORT_OPCODE,
                        *RGBIC_MIC_IDENTIFIER,
                        0x03,
                        0x2A,
                        0x00,
                        0x01,
                        0x40,
                        0x06,
                        0x07,
                    ]
                ]
            }
        }
    ]


def test_mic_mode_state_accepts_string_option(mic_state: MicModeState) -> None:
    """String inputs should map to structured commands for select entities."""

    initial_report = [
        REPORT_OPCODE,
        *RGBIC_MIC_IDENTIFIER,
        0x03,
        0x2A,
        0x00,
        0x00,
        0x05,
        0x06,
        0x07,
    ]
    mic_state.parse({"cmd": "status", "op": {"command": [initial_report]}})

    command_ids = mic_state.set_state("5")

    assert command_ids
    command_id = command_ids[0]

    command = mic_state.command_queue.get_nowait()
    assert command["command_id"] == command_id
    opcode_frame = command["data"]["command"][0]
    assert opcode_frame[:10] == [
        0x33,
        *RGBIC_MIC_IDENTIFIER,
        0x05,
        0x2A,
        0x00,
        0x00,
        0x05,
        0x06,
        0x07,
    ]

    pending_status = mic_state._pending_commands[command_id]  # type: ignore[attr-defined]
    assert pending_status == [
        {
            "op": {
                "command": [
                    [
                        REPORT_OPCODE,
                        *RGBIC_MIC_IDENTIFIER,
                        0x05,
                        0x2A,
                        0x00,
                        0x00,
                        0x05,
                        0x06,
                        0x07,
                    ]
                ]
            }
        }
    ]
