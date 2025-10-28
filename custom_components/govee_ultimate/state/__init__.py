"""State management helpers for Govee Ultimate devices."""

from custom_components.govee_ultimate import _ensure_event_loop as _ensure_loop

from .device_state import DeviceOpState, DeviceState, ParseOption
from .states import (
    ActiveState,
    BiologicalPresenceState,
    BrightnessState,
    ColorRGBState,
    ControlLockState,
    ColorTemperatureState,
    DetectionSettingsState,
    DisplayScheduleState,
    DiyModeState,
    EnablePresenceState,
    LightEffectState,
    HumidityState,
    MMWavePresenceState,
    MicModeState,
    ModeState,
    NightLightState,
    SegmentColorState,
    TimerState,
    FilterLifeState,
    FilterExpiredState,
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
    "ControlLockState",
    "ColorTemperatureState",
    "MMWavePresenceState",
    "BiologicalPresenceState",
    "EnablePresenceState",
    "DetectionSettingsState",
    "DisplayScheduleState",
    "NightLightState",
    "HumidityState",
    "SegmentColorState",
    "LightEffectState",
    "MicModeState",
    "DiyModeState",
    "TimerState",
    "FilterLifeState",
    "FilterExpiredState",
]

_ensure_loop()
