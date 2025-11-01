"""Purifier state unit tests."""

from __future__ import annotations

from custom_components.govee_ultimate.state.states import PurifierCustomModeState


def _build_state() -> PurifierCustomModeState:
    return PurifierCustomModeState(device=object())


def test_purifier_custom_mode_state_programs_expose_current_slot() -> None:
    """Custom mode state should expose program metadata for each slot."""

    state = _build_state()
    state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x01,
                        0x05,
                        0x00,
                        0x0A,
                        0x00,
                        0x0A,
                        0x06,
                        0x00,
                        0x14,
                        0x00,
                        0x14,
                        0x07,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )

    assert state.value == {
        "id": 1,
        "fan_speed": 6,
        "duration": 20,
        "remaining": 20,
    }

    programs = state.programs
    assert programs[0]["fan_speed"] == 5
    assert programs[1]["duration"] == 20
    assert programs[2]["remaining"] == 30


def test_purifier_custom_mode_state_set_state_generates_command() -> None:
    """Setting a custom program should enqueue a command frame."""

    state = _build_state()
    state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x00,
                        0x02,
                        0x00,
                        0x64,
                        0x00,
                        0x64,
                        0x03,
                        0x00,
                        0x32,
                        0x00,
                        0x32,
                        0x04,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )

    command_ids = state.set_state(
        {"id": 2, "fan_speed": 7, "duration": 55, "remaining": 44}
    )
    assert command_ids

    payload = state.command_queue.get_nowait()
    assert payload["command"] == "multi_sync"
    assert payload["data"]["command"][0][4] == 2  # slot identifier
