"""Tests for DreamView-specific state implementations."""

from __future__ import annotations

from typing import Any


import pytest

from custom_components.govee.state.device_state import DeviceState, ParseOption
from custom_components.govee.state.states import (
    AmbiantBrightnessMode,
    AmbiantState,
    SyncBoxActiveState,
    VideoModeState,
)


class DummyDevice:
    """Minimal device stub compatible with DeviceState constructors."""

    def add_status_listener(self, _callback: Any) -> None:
        """Accept listeners without retaining them."""


@pytest.fixture
def ambiant_state() -> AmbiantState:
    """Provide a fresh AmbiantState instance per test."""

    return AmbiantState(device=DummyDevice())


@pytest.fixture
def video_state() -> VideoModeState:
    """Provide a fresh VideoModeState instance per test."""

    return VideoModeState(device=DummyDevice())


REPORT_OPCODE = 0xAA
AMBIANT_IDENTIFIER = [0x07, 0x08]
VIDEO_IDENTIFIER = [0x05, 0x00]
SYNC_BOX_IDENTIFIER = [0x05]


class StubMode(DeviceState[str]):
    """Simple mode stub capturing delegated set_state calls."""

    def __init__(self, device: DummyDevice, name: str):
        """Create a stub mode with a fixed name and value."""
        super().__init__(
            device=device,
            name=name,
            initial_value=name,
            parse_option=ParseOption.NONE,
        )
        self.set_calls: list[Any] = []

    def set_state(self, next_state: Any) -> list[str]:  # type: ignore[override]
        """Record delegated set_state calls for assertions."""
        self.set_calls.append(next_state)
        return [self.name]


def _report_frame(on: int, mode: int, brightness: int) -> list[int]:
    """Construct a report opcode frame for ambiant state updates."""

    return [REPORT_OPCODE, *AMBIANT_IDENTIFIER, on, mode, brightness]


def _video_report_frame(brightness: int) -> list[int]:
    """Construct a report opcode frame for video mode brightness updates."""

    return [REPORT_OPCODE, *VIDEO_IDENTIFIER, brightness]


@pytest.mark.parametrize(
    "payload, expected",
    [
        (_report_frame(0x01, 0x00, 0x32), {"on": True, "brightnessMode": AmbiantBrightnessMode.CONSISTENT, "brightness": 0x32}),
        (_report_frame(0x00, 0x01, 0x64), {"on": False, "brightnessMode": AmbiantBrightnessMode.SEGMENT, "brightness": 0x64}),
    ],
)
def test_ambiant_state_parses_report_payload(
    ambiant_state: AmbiantState, payload: list[int], expected: dict[str, Any]
) -> None:
    """Ambiant state decodes report payloads into structured values."""

    ambiant_state.parse({"cmd": "status", "op": {"command": [payload]}})

    assert ambiant_state.value == expected


def test_ambiant_state_set_state_enqueues_catalog_command(
    ambiant_state: AmbiantState,
) -> None:
    """set_state should emit catalog-backed command metadata and pending status."""

    command_ids = ambiant_state.set_state(
        {"on": True, "brightnessMode": AmbiantBrightnessMode.SEGMENT, "brightness": 0x40}
    )

    assert command_ids
    command_id = command_ids[0]

    command_payload = ambiant_state.command_queue.get_nowait()
    assert command_payload["command_id"] == command_id
    assert command_payload["name"] == "set_ambiant"
    assert command_payload["opcode"] == "0x33"
    assert command_payload["payload_hex"].endswith("0140")

    pending_status = ambiant_state._pending_commands[command_id]  # type: ignore[attr-defined]
    assert any(
        expectation.get("op", {}).get("command")
        for expectation in pending_status
    )


def test_video_mode_state_parses_report_payload(video_state: VideoModeState) -> None:
    """Video mode state should decode brightness from report payloads."""

    payload = _video_report_frame(0x3C)
    video_state.parse({"cmd": "status", "op": {"command": [payload]}})

    assert video_state.value == {"brightness": 0x3C}


def test_video_mode_state_set_state_enqueues_catalog_command(
    video_state: VideoModeState,
) -> None:
    """set_state should emit DreamView video command metadata."""

    command_ids = video_state.set_state({"brightness": 0x40})

    assert command_ids
    command = video_state.command_queue.get_nowait()
    assert command["name"] == "set_video_mode"
    assert command["opcode"] == "0x33"
    assert command["payload_hex"].endswith("0140")

    pending_status = video_state._pending_commands[command_ids[0]]  # type: ignore[attr-defined]
    assert pending_status[0]["state"]["videoMode"] == {"brightness": 0x40}


def test_sync_box_active_state_tracks_modes() -> None:
    """Active state should expose the mode matching the inline identifier."""

    device = DummyDevice()
    mic_mode = StubMode(device, "micMode")
    color_mode = StubMode(device, "segmentColorMode")
    video_mode = StubMode(device, "videoMode")
    scene_mode = StubMode(device, "lightEffect")
    diy_mode = StubMode(device, "diyMode")

    active_state = SyncBoxActiveState(
        device=device,
        states=[mic_mode, color_mode, video_mode, scene_mode, diy_mode],
    )

    assert active_state.active_mode is None

    mode_expectations = [
        (19, mic_mode),
        (21, color_mode),
        (0, video_mode),
        (1, scene_mode),
        (10, diy_mode),
    ]
    for mode_code, expected in mode_expectations:
        payload = [REPORT_OPCODE, *SYNC_BOX_IDENTIFIER, mode_code]
        active_state.parse({"cmd": "status", "op": {"command": [payload]}})
        assert active_state.active_mode is expected

    command_ids = active_state.set_state(video_mode)
    assert command_ids == ["videoMode"]
    assert video_mode.set_calls == [video_mode.value]


def test_sync_box_active_state_ignores_missing_mode() -> None:
    """Calling set_state with None should be a no-op for active state."""

    active_state = SyncBoxActiveState(device=DummyDevice(), states=[])

    assert active_state.set_state(None) == []
