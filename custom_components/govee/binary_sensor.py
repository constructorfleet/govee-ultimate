"""Binary sensor platform for the Govee Ultimate integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)

_EXPLICIT_BINARY_FLAGS = ("detected", "is_on", "active", "enabled")
_MISSING = object()


class GoveeBinarySensorEntity(GoveeStateEntity, BinarySensorEntity):
    """Representation of a boolean diagnostic state."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is active."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, Mapping):
            for key in _EXPLICIT_BINARY_FLAGS:
                flag = value.get(key, _MISSING)
                if flag is _MISSING:
                    continue
                if isinstance(flag, bool) or flag is None:
                    return flag
        return bool(value)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: Any
) -> None:
    """Set up binary sensor entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(
        coordinator, "binary_sensor", GoveeBinarySensorEntity
    )

    await async_add_platform_entities(async_add_entities, entities)
