"""Unit tests for the DIY mode state implementation."""

from __future__ import annotations

import base64
from collections.abc import Iterable

import pytest

from custom_components.govee.state.states import DiyModeState, RGBICModes


def _dummy_effect(name: str, code: int, payload: bytes) -> dict[str, object]:
    """Return a minimal DIY effect payload for testing."""

    return {
        "name": name,
        "code": code,
        "cmdVersion": 0,
        "type": 1,
        "diyOpCodeBase64": base64.b64encode(payload).decode(),
    }


def _as_opcode(opcode: int, *values: int) -> list[int]:
    """Replicate the upstream opcode frame builder for assertions."""

    frame = bytearray([opcode, *values])
    if len(frame) < 19:
        frame.extend([0] * (19 - len(frame)))
    checksum = 0
    for byte in frame:
        checksum ^= byte
    frame.append(checksum)
    return list(frame)


def _expected_diy_commands(
    identifier: Iterable[int], code: int, opcode_b64: str
) -> list[list[int]]:
    """Return the opcode frames expected from rebuild_diy_opcode."""

    decoded = list(base64.b64decode(opcode_b64))
    if decoded:
        decoded = decoded[1:]
    payload = [0x01, 0x02, 0x04, *decoded]
    chunks: list[list[int]] = [
        payload[idx : idx + 17] for idx in range(0, len(payload), 17)
    ]
    frames: list[list[int]] = []
    for idx, chunk in enumerate(chunks):
        terminator = 0xFF if idx == len(chunks) - 1 else idx
        frames.append(_as_opcode(0xA3, terminator, *chunk))
    ident_list = list(identifier)
    frames.append(_as_opcode(0x33, *ident_list, code & 0xFF, (code >> 8) & 0xFF))
    frames.append(_as_opcode(0xAA, ident_list[0] if ident_list else 0x00, 0x01))
    return frames


def test_diy_mode_tracks_active_effect_from_reports() -> None:
    """DIY mode should expose effect metadata after opcode reports."""

    state = DiyModeState(device=object())
    effect = _dummy_effect("Spark", 0x1234, b"\x01\x02\x03")

    state.update_effects([effect])
    state.parse_op_command([0xAA, 0x05, RGBICModes.DIY, 0x34, 0x12])

    assert state.active_effect_code == 0x1234
    assert state.value == effect


def test_diy_mode_applies_effect_after_catalog_update() -> None:
    """Effect metadata arriving after the opcode report should refresh state."""

    state = DiyModeState(device=object())
    state.parse_op_command([0xAA, 0x05, RGBICModes.DIY, 0x78, 0x56])

    assert state.active_effect_code == 0x5678
    assert state.value == {}

    effect = _dummy_effect("Glow", 0x5678, b"\x10\x11\x12")
    state.update_effects([effect])

    assert state.value == effect


def test_diy_mode_set_state_queues_rebuilt_opcodes() -> None:
    """Commands issued by DIY mode should match rebuilt opcode frames."""

    state = DiyModeState(device=object())
    payload = bytes(range(1, 25))
    effect = _dummy_effect("Wave", 0x0ABC, payload)
    state.update_effects([effect])

    command_ids = state.set_state({"name": "Wave"})

    assert command_ids
    queued = state.command_queue.get_nowait()
    assert queued["data"]["command"] == _expected_diy_commands(
        [0x05, RGBICModes.DIY], effect["code"], effect["diyOpCodeBase64"]  # type: ignore[arg-type]
    )

    with pytest.raises(Exception):
        # Queue should now be empty for this state.
        state.command_queue.get_nowait()


def test_diy_mode_channel_update_populates_effect_catalog() -> None:
    """Channel updates should hydrate the effect catalog for DIY mode."""

    state = DiyModeState(device=object())
    payload = bytes(range(1, 25))
    effect = _dummy_effect("Wave", 0x0ABC, payload)

    changed = state.apply_channel_update({"catalog": {"effects": [effect]}})

    assert changed == ["diyMode"]

    command_ids = state.set_state({"name": "Wave"})

    assert command_ids
    queued = state.command_queue.get_nowait()
    assert queued["data"]["command"] == _expected_diy_commands(
        [0x05, RGBICModes.DIY], effect["code"], effect["diyOpCodeBase64"]  # type: ignore[arg-type]
    )

    with pytest.raises(Exception):
        state.command_queue.get_nowait()
