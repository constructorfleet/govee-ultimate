"""Switch platform for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)


class GoveeSwitchEntity(GoveeStateEntity, SwitchEntity):
    """Representation of a boolean switch state."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the switch reports an on state."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""

        await self._async_publish_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""

        await self._async_publish_state(False)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up switch entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "switch", GoveeSwitchEntity)

    await async_add_platform_entities(async_add_entities, entities)
