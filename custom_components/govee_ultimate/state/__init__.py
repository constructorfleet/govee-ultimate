"""State management helpers for Govee Ultimate devices."""

from custom_components.govee_ultimate import _ensure_event_loop as _ensure_loop

from .device_state import DeviceOpState, DeviceState, ParseOption
from .states import (
    ActiveState,
    BiologicalPresenceState,
    BrightnessState,
    ColorRGBState,
    DetectionSettingsState,
    EnablePresenceState,
    MMWavePresenceState,
    ModeState,
    PowerState,
)

__all__ = [
    "DeviceState",
    "DeviceOpState",
    "ParseOption",
    "PowerState",
    "ModeState",
    "ActiveState",
    "BrightnessState",
    "ColorRGBState",
    "MMWavePresenceState",
    "BiologicalPresenceState",
    "EnablePresenceState",
    "DetectionSettingsState",
]

_ensure_loop()
