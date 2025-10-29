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

    _BRIGHTNESS_STATE = "brightness"

    @staticmethod
    def _percent_to_brightness(percent: int) -> int:
        """Convert a device brightness percentage to Home Assistant scale."""

        return round(percent * 255 / 100)

    @staticmethod
    def _brightness_to_percent(value: float | int) -> int:
        """Convert Home Assistant brightness to a device percentage."""

        return max(0, min(100, round(value * 100 / 255)))

    @property
    def _is_brightness(self) -> bool:
        """Return True when the bound state tracks brightness."""

        return self._state.name == self._BRIGHTNESS_STATE

    @property
    def is_on(self) -> bool | None:
        """Return the boolean state value."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)

    @property
    def brightness(self) -> int | None:
        """Return the Home Assistant brightness for brightness states."""

        if not self._is_brightness:
            return None
        value = self._state.value
        if not isinstance(value, int):
            return None
        return self._percent_to_brightness(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""

        if self._is_brightness:
            brightness = kwargs.get("brightness")
            if isinstance(brightness, int | float):
                percent = self._brightness_to_percent(brightness)
            else:
                percent = (
                    self._state.value if isinstance(self._state.value, int) else 100
                )
            await self._async_publish_state(percent)
            return

        await self._async_publish_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""

        if self._is_brightness:
            await self._async_publish_state(0)
            return

        await self._async_publish_state(False)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up the light platform for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "light", GoveeLightEntity)

    await async_add_platform_entities(async_add_entities, entities)
