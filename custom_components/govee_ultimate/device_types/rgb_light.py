"""RGB light device support mirroring the upstream TypeScript factory."""

from __future__ import annotations

from typing import Any

from custom_components.govee_ultimate.state import (
    ActiveState,
    BrightnessState,
    ColorRGBState,
    ColorTemperatureState,
    ConnectedState,
    PowerState,
)
from custom_components.govee_ultimate.state.states import SceneModeState

from .base import BaseDevice, LightEntities


class RGBLightDevice(BaseDevice):
    """Representation of a standard RGB light device."""

    def __init__(self, device_model: Any) -> None:
        """Initialise the RGB light state registry."""

        super().__init__(device_model)
        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="light", state=power)

        connected = self.add_state(ConnectedState(device_model))
        self.expose_entity(platform="binary_sensor", state=connected)

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(platform="binary_sensor", state=active)

        brightness = self.add_state(BrightnessState(device_model))
        self.expose_entity(platform="light", state=brightness)

        color_rgb = self.add_state(ColorRGBState(device_model))
        self.expose_entity(platform="light", state=color_rgb)
        self.alias_state("color", color_rgb)
        self.alias_entity("color", color_rgb, keep_canonical=True)

        color_temperature = self.add_state(ColorTemperatureState(device=device_model))
        self.expose_entity(platform="light", state=color_temperature)

        self._scene_mode_state = self.add_state(SceneModeState(device=device_model))

        self._light_entities = LightEntities(
            primary=power,
            supporting=(brightness, color_rgb, color_temperature),
        )

    @property
    def light_entities(self) -> LightEntities:
        """Return Home Assistant entity hints for light platforms."""

        return self._light_entities

    @property
    def scene_mode_state(self) -> SceneModeState:
        """Expose the scene mode state for automation consumers."""

        return self._scene_mode_state
