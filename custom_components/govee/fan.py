"""Fan platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity
from homeassistant.core import HomeAssistant

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeFanEntity(GoveeStateEntity, FanEntity):
    """Representation of a fan control state."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the fan reports an active state."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the fan on."""

        await self._async_publish_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""

        await self._async_publish_state(False)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: Any
) -> None:
    """Set up fan entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "fan", GoveeFanEntity)

    await async_add_platform_entities(async_add_entities, entities)
