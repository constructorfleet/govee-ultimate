"""Number platform for the Govee Ultimate integration."""

from __future__ import annotations

from collections.abc import Mapping
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

    @property
    def native_value(self) -> float | None:
        """Return the numeric value, extracting mist level when structured."""

        value = self._state.value
        if isinstance(value, Mapping):
            mist_level = value.get("mist_level")
            if mist_level is None:
                return None
            return float(mist_level)
        if isinstance(value, int | float):
            return float(value)
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric value on the device."""

        await self._async_publish_state(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose mapped attributes from the underlying state when provided."""

        attributes = getattr(self._state, "attributes", None)
        if isinstance(attributes, Mapping):
            return dict(attributes)
        return None


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up number entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "number", GoveeNumberEntity)

    await async_add_platform_entities(async_add_entities, entities)
