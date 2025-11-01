"""Tests for the composite ModeState helper."""

from __future__ import annotations

from typing import Any

from custom_components.govee.state.device_state import (
    DeviceOpState,
    ParseOption,
)
from custom_components.govee.state.states import ModeState


class DummyDevice:
    """Minimal device stub that collects status callbacks."""

    def __init__(self) -> None:
        """Initialise callback storage."""
        self._callbacks: list[Any] = []

    def add_status_listener(self, callback):  # type: ignore[no-untyped-def]
        """Record the provided callback without execution."""
        self._callbacks.append(callback)


class DummyMode(DeviceOpState[dict[str, Any]]):
    """Opcode-backed mode used to probe identifier matching."""

    def __init__(self, device: DummyDevice, name: str, identifier: list[int]):
        """Initialise the dummy mode with a fixed identifier."""
        super().__init__(
            op_identifier={"op_type": 0xAA, "identifier": identifier},
            device=device,
            name=name,
            initial_value={},
            parse_option=ParseOption.NONE,
        )


def test_mode_state_tracks_active_identifier_and_active_mode() -> None:
    """ModeState exposes the matching sub-state when identifiers update."""

    device = DummyDevice()
    inline_mode = DummyMode(device, "inline", [0x05, 0x01])
    report_mode = DummyMode(device, "report", [0x05, 0x02])

    mode_state = ModeState(
        device=device,
        modes=[inline_mode, None, report_mode],
    )

    assert mode_state.active_mode is None

    mode_state.parse({"cmd": "status", "state": {"mode": 2}})

    assert mode_state.active_identifier == [2]
    assert mode_state.active_mode is report_mode
