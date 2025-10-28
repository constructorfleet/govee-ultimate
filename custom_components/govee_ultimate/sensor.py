"""Sensor platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeSensorEntity(GoveeStateEntity, SensorEntity):
    """Representation of a diagnostic sensor state."""

    @property
    def native_value(self) -> Any:
        """Return the latest sensor reading."""

        return self._state.value


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up sensor entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "sensor", GoveeSensorEntity)

    await async_add_platform_entities(async_add_entities, entities)
