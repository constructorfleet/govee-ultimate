"""Hygrometer device wiring for Home Assistant entities."""

from __future__ import annotations

from typing import Any

from ..state import (
    BatteryLevelState,
    ConnectedState,
    HumidityState,
    PowerState,
    TemperatureState,
)
from .base import BaseDevice, EntityCategory


class HygrometerDevice(BaseDevice):
    """Home Assistant device wrapper for thermo-hygrometers."""

    def __init__(self, device_model: Any) -> None:
        """Register hygrometer states and expose Home Assistant entities."""

        super().__init__(device_model)

        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="switch", state=power)

        connected = self.add_state(ConnectedState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=connected,
            translation_key="connected",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        temperature = self.add_state(TemperatureState(device=device_model))
        self._register_sensor(temperature, translation_key="temperature")

        humidity = self.add_state(HumidityState(device=device_model))
        self._register_sensor(humidity, translation_key="humidity")

        battery = self.add_state(BatteryLevelState(device=device_model))
        self._register_sensor(
            battery,
            translation_key="battery",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

    def _register_sensor(
        self,
        state: TemperatureState | HumidityState | BatteryLevelState,
        *,
        translation_key: str,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Expose a sensor entity for ``state`` using shared defaults."""

        self.expose_entity(
            platform="sensor",
            state=state,
            translation_key=translation_key,
            entity_category=entity_category,
        )
