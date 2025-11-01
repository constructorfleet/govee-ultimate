"""RGBIC light device support."""

from __future__ import annotations

from typing import Any

from custom_components.govee.state import (
    ActiveState,
    BrightnessState,
    ColorTemperatureState,
    ColorRGBState,
    DeviceState,
    DiyModeState,
    LightEffectState,
    MicModeState,
    ModeState,
    PowerState,
    SegmentColorState,
)
from custom_components.govee.state.states import RGBICModes

from .base import BaseDevice, LightEntities


class RGBICModeState(ModeState):
    """Composite mode delegator for RGBIC lights."""

    _REPORT_OPCODE = 0xAA

    def __init__(
        self,
        device: Any,
        *,
        color_state: DeviceState[Any] | None,
        segment_state: DeviceState[Any] | None,
        light_effect_state: DeviceState[Any] | None,
        mic_mode_state: DeviceState[Any] | None,
        diy_mode_state: DeviceState[Any] | None,
    ) -> None:
        """Initialise the composite mode handler with real state delegates."""

        modes = [
            state
            for state in (
                color_state,
                segment_state,
                light_effect_state,
                mic_mode_state,
                diy_mode_state,
            )
            if state is not None
        ]
        super().__init__(
            device=device,
            modes=modes,
            identifier=[0x05],
            inline=True,
            identifier_map=self._map_identifier,
        )
        self._color_state = color_state
        self._segment_state = segment_state
        self._light_effect_state = light_effect_state
        self._mic_mode_state = mic_mode_state
        self._diy_mode_state = diy_mode_state
        self._register_aliases(
            {
                "color_whole": color_state,
                "color_segment": segment_state,
                "scene": light_effect_state,
                "mic": mic_mode_state,
                "diy": diy_mode_state,
            }
        )
        identifier_targets = {
            RGBICModes.WHOLE_COLOR: color_state,
            RGBICModes.SEGMENT_COLOR: segment_state,
            RGBICModes.SCENE: light_effect_state,
            RGBICModes.MIC: mic_mode_state,
            RGBICModes.DIY: diy_mode_state,
        }
        self._identifier_targets: dict[int, DeviceState[Any]] = {
            int(mode): state
            for mode, state in identifier_targets.items()
            if state is not None
        }
        self._assign_mode_identifiers(identifier_targets)

    def _register_aliases(self, alias_map: dict[str, DeviceState[Any] | None]) -> None:
        for alias, state in alias_map.items():
            if state is None:
                continue
            token = self._normalise_alias(alias)
            self._mode_lookup[token] = state
            self._mode_aliases.setdefault(token, alias)

    def _assign_mode_identifiers(
        self, mapping: dict[RGBICModes, DeviceState[Any] | None]
    ) -> None:
        for mode, state in mapping.items():
            if state is None:
                continue
            setattr(state, "_mode_identifier", [int(mode)])

    @staticmethod
    def _normalise_alias(name: str) -> str:
        token = name.strip().replace("-", "_").replace(" ", "_")
        if token.lower().endswith("_mode"):
            token = token[: -len("_mode")]
        return token.upper()

    def _normalise_active_identifier(self) -> list[int]:
        sequence = list(self.active_identifier or [])
        if sequence and sequence[0] == self._REPORT_OPCODE:
            sequence = sequence[1:]
        if sequence and sequence[0] == 0x05:
            sequence = sequence[1:]
        return sequence

    def _map_identifier(self, _: ModeState) -> DeviceState[Any] | None:
        sequence = self._normalise_active_identifier()
        if not sequence:
            return None
        return self._identifier_targets.get(sequence[0])

    def set_state(self, next_state: Any) -> list[str]:  # type: ignore[override]
        """Delegate commands to the selected mode state."""

        if isinstance(next_state, DeviceState):
            delegate = next_state
            payload = getattr(delegate, "value", None)
        else:
            delegate = self.resolve_mode(next_state)
            payload = getattr(delegate, "value", None) if delegate else None
        if delegate is None or payload is None:
            return []
        return delegate.set_state(payload)


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

        color_rgb = self.add_state(ColorRGBState(device_model))
        self.expose_entity(platform="light", state=color_rgb)
        self.alias_state("color", color_rgb)
        self.alias_entity("color", color_rgb, keep_canonical=True)

        color_temperature = self.add_state(ColorTemperatureState(device=device_model))
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

        self._mode_state = self.add_state(
            RGBICModeState(
                device=device_model,
                color_state=color_rgb,
                segment_state=segment_color,
                light_effect_state=light_effect,
                mic_mode_state=mic_mode,
                diy_mode_state=diy_mode,
            )
        )
        self.expose_entity(platform="select", state=self._mode_state)

        self._light_entities = LightEntities(
            primary=power,
            supporting=(brightness, color_rgb, color_temperature, segment_color),
        )

    @property
    def mode_state(self) -> RGBICModeState:
        """Return the composite mode state for the device."""

        return self._mode_state

    @property
    def light_entities(self) -> LightEntities:
        """Return Home Assistant entity hints for the light platform."""

        return self._light_entities
