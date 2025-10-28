"""Meat thermometer device wiring for Home Assistant."""

from __future__ import annotations

from typing import Any

from custom_components.govee_ultimate.state import PowerState
from custom_components.govee_ultimate.state.states import (
    BuzzerState,
    EarlyWarningState,
    PresetState,
    ProbeTempState,
    TemperatureUnitState,
)

from .base import BaseDevice


class MeatThermometerDevice(BaseDevice):
    """State container for Wi-Fi meat thermometer devices."""

    def __init__(self, device_model: Any) -> None:
        """Register core thermometer states and Home Assistant entities."""

        super().__init__(device_model)

        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="switch", state=power)

        self._register_connected_state(device_model)

        self.add_state(BuzzerState(device=device_model))
        self.add_state(TemperatureUnitState(device=device_model))
        self.add_state(EarlyWarningState(device=device_model))

        self._register_probe_states(device_model)
        self._register_preset_states(device_model)

    def _register_probe_states(self, device_model: Any) -> None:
        """Install probe temperature states and expose sensors."""

        for probe in range(1, 5):
            probe_state = self.add_state(
                ProbeTempState(device=device_model, probe=probe)
            )
            self.expose_entity(platform="sensor", state=probe_state)

    def _register_preset_states(self, device_model: Any) -> None:
        """Install preset states and expose select entities."""

        for probe in range(1, 5):
            preset_state = self.add_state(PresetState(device=device_model, probe=probe))
            self.expose_entity(platform="select", state=preset_state)
