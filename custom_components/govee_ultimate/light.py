"""Light platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import LightEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeLightEntity(GoveeStateEntity, LightEntity):
    """Representation of a single Govee light state."""

    @property
    def is_on(self) -> bool | None:
        """Return the boolean state value."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""

        await self._async_publish_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""

        await self._async_publish_state(False)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up the light platform for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "light", GoveeLightEntity)

    await async_add_platform_entities(async_add_entities, entities)
