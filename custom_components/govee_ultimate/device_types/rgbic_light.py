"""RGBIC light device support."""

from __future__ import annotations

from typing import Any

from custom_components.govee_ultimate.state import (
    ActiveState,
    BrightnessState,
    ColorTemperatureState,
    ColorRGBState,
    DeviceState,
    DiyModeState,
    LightEffectState,
    MicModeState,
    ModeState,
    ParseOption,
    PowerState,
    SegmentColorState,
)

from .base import BaseDevice, LightEntities


class _StaticModeState(DeviceState[str]):
    """Simple string-based mode state used for composite mode management."""

    def __init__(self, device: Any, name: str) -> None:
        super().__init__(
            device=device,
            name=name,
            initial_value="",
            parse_option=ParseOption.NONE,
        )


class RGBICLightDevice(BaseDevice):
    """Mirror of the TypeScript RGBIC light device factory."""

    def __init__(self, device_model: Any) -> None:
        """Initialise the RGBIC light states and composite mode."""

        super().__init__(device_model)
        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="light", state=power)

        self._register_connected_state(device_model)

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(platform="binary_sensor", state=active)

        brightness = self.add_state(BrightnessState(device_model))
        self.expose_entity(platform="light", state=brightness)

        color = self.add_state(ColorRGBState(device_model))
        self.expose_entity(platform="light", state=color)

        color_temperature = self.add_state(
            ColorTemperatureState(device=device_model, identifier=[0x2B])
        )
        self.expose_entity(platform="light", state=color_temperature)

        segment_color = self.add_state(
            SegmentColorState(device=device_model, identifier=[0x41])
        )
        self.expose_entity(platform="light", state=segment_color)

        light_effect = self.add_state(
            LightEffectState(device=device_model, identifier=[0x31])
        )
        self.expose_entity(platform="select", state=light_effect)

        mic_mode = self.add_state(
            MicModeState(device=device_model, identifier=[0x05, 0x13])
        )
        self.expose_entity(platform="select", state=mic_mode)

        diy_mode = self.add_state(DiyModeState(device=device_model))
        self.expose_entity(platform="select", state=diy_mode)

        mode_states = self._register_mode_states(
            "color_whole",
            "color_segment",
            "scene",
            "mic",
            "diy",
        )

        self._mode_state = self.add_state(
            ModeState(device=device_model, modes=mode_states)
        )
        self.expose_entity(platform="select", state=self._mode_state)

        self._light_entities = LightEntities(
            primary=power,
            supporting=(brightness, color, color_temperature, segment_color),
        )

    @property
    def mode_state(self) -> ModeState:
        """Return the composite mode state for the device."""

        return self._mode_state

    @property
    def light_entities(self) -> LightEntities:
        """Return Home Assistant entity hints for the light platform."""

        return self._light_entities

    def _register_mode_states(self, *names: str) -> list[DeviceState[str]]:
        """Create and register static mode state placeholders."""

        return [self.add_state(_StaticModeState(self.device, name)) for name in names]
