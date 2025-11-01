"""Tests for the segment color state."""

import pytest

from custom_components.govee.state.states import (
    RGBICModes,
    SegmentColorState,
)


class DummyDevice:
    """Minimal device stub compatible with DeviceState constructors."""

    def add_status_listener(self, _callback):
        """Accept listeners without retaining them."""


@pytest.fixture
def segment_state() -> SegmentColorState:
    """Provide a fresh SegmentColorState instance for each test."""

    return SegmentColorState(device=DummyDevice())


def test_segment_color_state_parses_multi_op_payload(
    segment_state: SegmentColorState,
) -> None:
    """Multi-op payloads should map to structured segment dictionaries."""

    multi_op_payload = {
        "cmd": "status",
        "op": {
            "command": [
                [
                    0x01,
                    0x10,
                    0x01,
                    0x02,
                    0x03,
                    0x11,
                    0x04,
                    0x05,
                    0x06,
                    0x12,
                    0x07,
                    0x08,
                    0x09,
                ],
                [
                    0x02,
                    0x20,
                    0x21,
                    0x22,
                    0x23,
                    0x30,
                    0x24,
                    0x25,
                    0x26,
                    0x40,
                    0x27,
                    0x28,
                    0x29,
                ],
            ]
        },
    }

    segment_state.parse(multi_op_payload)

    assert segment_state.value == [
        {
            "id": 0,
            "brightness": 0x10,
            "color": {"red": 0x01, "green": 0x02, "blue": 0x03},
        },
        {
            "id": 1,
            "brightness": 0x11,
            "color": {"red": 0x04, "green": 0x05, "blue": 0x06},
        },
        {
            "id": 2,
            "brightness": 0x12,
            "color": {"red": 0x07, "green": 0x08, "blue": 0x09},
        },
        {
            "id": 3,
            "brightness": 0x20,
            "color": {"red": 0x21, "green": 0x22, "blue": 0x23},
        },
        {
            "id": 4,
            "brightness": 0x30,
            "color": {"red": 0x24, "green": 0x25, "blue": 0x26},
        },
        {
            "id": 5,
            "brightness": 0x40,
            "color": {"red": 0x27, "green": 0x28, "blue": 0x29},
        },
    ]


def _expected_index_bytes(mask: int) -> list[int]:
    hex_text = f"{mask:X}"
    if len(hex_text) % 2:
        hex_text = f"0{hex_text}"
    return [int(hex_text[idx : idx + 2], 16) for idx in range(0, len(hex_text), 2)]


def test_segment_color_state_batches_segment_commands(
    segment_state: SegmentColorState,
) -> None:
    """set_state should group identical updates into opcode frames."""

    command_ids = segment_state.set_state(
        [
            {
                "id": 0,
                "color": {"red": 0x10, "green": 0x20, "blue": 0x30},
            },
            {
                "id": 1,
                "color": {"red": 0x10, "green": 0x20, "blue": 0x30},
            },
            {
                "id": 2,
                "color": {"red": 0x40, "green": 0x50, "blue": 0x60},
            },
            {"id": 3, "brightness": 0x50},
            {"id": 4, "brightness": 0x50},
            {"id": 5, "brightness": 0x70},
        ]
    )

    assert command_ids
    command_id = command_ids[0]

    command = segment_state.command_queue.get_nowait()
    assert command["command_id"] == command_id
    assert command["command"] == "multi_sync"

    frames = command["data"]["command"]
    assert isinstance(frames, list)
    assert all(isinstance(frame, list) for frame in frames)

    color_frames = [frame for frame in frames if frame[3] == 0x01]
    brightness_frames = [frame for frame in frames if frame[3] == 0x02]
    assert len(color_frames) == 2
    assert len(brightness_frames) == 2

    first_color = next(
        frame for frame in color_frames if frame[4:7] == [0x10, 0x20, 0x30]
    )
    assert first_color[1:4] == [0x05, RGBICModes.SEGMENT_COLOR, 0x01]
    assert first_color[
        12 : 12 + len(_expected_index_bytes(0b11))
    ] == _expected_index_bytes(0b11)

    second_color = next(
        frame for frame in color_frames if frame[4:7] == [0x40, 0x50, 0x60]
    )
    assert second_color[
        12 : 12 + len(_expected_index_bytes(1 << 2))
    ] == _expected_index_bytes(1 << 2)

    shared_brightness = next(frame for frame in brightness_frames if frame[4] == 0x50)
    assert shared_brightness[1:4] == [0x05, RGBICModes.SEGMENT_COLOR, 0x02]
    assert shared_brightness[
        5 : 5 + len(_expected_index_bytes((1 << 3) | (1 << 4)))
    ] == _expected_index_bytes((1 << 3) | (1 << 4))

    single_brightness = next(frame for frame in brightness_frames if frame[4] == 0x70)
    assert single_brightness[
        5 : 5 + len(_expected_index_bytes(1 << 5))
    ] == _expected_index_bytes(1 << 5)

    pending_status = segment_state._pending_commands[command_id]  # type: ignore[attr-defined]
    assert pending_status == [
        {"state": {"segmentColor": segment_state.value}},
        {"op": {"command": [[0x01, None], [0x02, None]]}},
    ]

    assert segment_state.value == [
        {
            "id": 0,
            "color": {"red": 0x10, "green": 0x20, "blue": 0x30},
        },
        {
            "id": 1,
            "color": {"red": 0x10, "green": 0x20, "blue": 0x30},
        },
        {
            "id": 2,
            "color": {"red": 0x40, "green": 0x50, "blue": 0x60},
        },
        {"id": 3, "brightness": 0x50},
        {"id": 4, "brightness": 0x50},
        {"id": 5, "brightness": 0x70},
    ]
