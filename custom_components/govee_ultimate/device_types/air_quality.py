"""Air quality monitor device wiring."""

from __future__ import annotations

from typing import Any

from ..state import (
    AirQualityHumidityState,
    AirQualityPM25State,
    AirQualityTemperatureState,
    ConnectedState,
    PowerState,
)
from .base import BaseDevice, EntityCategory


class AirQualityDevice(BaseDevice):
    """Home Assistant device wrapper for air quality monitors."""

    def __init__(self, device_model: Any) -> None:
        """Register air quality monitor states and entities."""

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

        temperature = self.add_state(AirQualityTemperatureState(device=device_model))
        self._register_sensor(temperature, translation_key="temperature")

        humidity = self.add_state(AirQualityHumidityState(device=device_model))
        self._register_sensor(humidity, translation_key="humidity")

        pm25 = self.add_state(AirQualityPM25State(device=device_model))
        self._register_sensor(
            pm25, translation_key="pm25", entity_category=EntityCategory.DIAGNOSTIC
        )

    def _register_sensor(
        self,
        state: (
            AirQualityTemperatureState | AirQualityHumidityState | AirQualityPM25State
        ),
        *,
        translation_key: str,
        entity_category: EntityCategory | None = None,
    ) -> None:
        """Expose a sensor entity for ``state`` with shared defaults."""

        self.expose_entity(
            platform="sensor",
            state=state,
            translation_key=translation_key,
            entity_category=entity_category,
        )
