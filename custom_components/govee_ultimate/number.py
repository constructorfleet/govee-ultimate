"""Number platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeNumberEntity(GoveeStateEntity, NumberEntity):
    """Representation of a numeric state."""

    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric value on the device."""

        await self._async_publish_state(value)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up number entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "number", GoveeNumberEntity)

    await async_add_platform_entities(async_add_entities, entities)
