"""Binary sensor platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeBinarySensorEntity(GoveeStateEntity, BinarySensorEntity):
    """Representation of a boolean diagnostic state."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is active."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up binary sensor entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(
        coordinator, "binary_sensor", GoveeBinarySensorEntity
    )

    await async_add_platform_entities(async_add_entities, entities)
