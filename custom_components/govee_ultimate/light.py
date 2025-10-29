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

    def __init__(self, coordinator: Any, device_id: str, entity: Any) -> None:
        """Initialize the light entity and track brightness history."""

        super().__init__(coordinator, device_id, entity)
        self._last_brightness_percent: int | None = None

    @staticmethod
    def _percent_to_brightness(percent: int) -> int:
        """Convert a device brightness percentage to Home Assistant scale."""

        return round(percent * 255 / 100)

    @staticmethod
    def _brightness_to_percent(value: float | int) -> int:
        """Convert Home Assistant brightness to a device percentage."""

        return max(0, min(100, round(value * 100 / 255)))

    def _set_cached_brightness_from_percent(self, percent: int | None) -> None:
        """Update `_attr_brightness` based on a device percentage."""

        if not self._is_brightness:
            self._attr_brightness = None
            self._last_brightness_percent = None
            return

        if percent is None:
            self._attr_brightness = None
            return

        self._attr_brightness = self._percent_to_brightness(percent)
        if percent > 0:
            self._last_brightness_percent = percent

    @property
    def _is_brightness(self) -> bool:
        """Return True when the bound state tracks brightness."""

        return self._state.name == self._BRIGHTNESS_STATE

    def _fallback_brightness_percent(self) -> int:
        """Return the default percent when no brightness is provided."""

        stored = self._last_brightness_percent
        if stored is None and isinstance(self._state.value, int):
            if self._state.value > 0:
                stored = self._state.value
        if stored is None or stored <= 0:
            return 100
        return stored

    @property
    def is_on(self) -> bool | None:
        """Return the boolean state value."""

        value = self._state.value
        if isinstance(value, bool) or value is None:
            return value
        return bool(value)

    def _update_cached_brightness(self) -> None:
        """Synchronize `_attr_brightness` with the device state."""

        value = self._state.value
        self._set_cached_brightness_from_percent(
            value if isinstance(value, int) else None
        )

    async def async_added_to_hass(self) -> None:
        """Ensure cached light attributes match the initial state."""

        self._update_cached_brightness()
        await super().async_added_to_hass()

    def _handle_coordinator_update(self) -> None:
        """Refresh cached Home Assistant attributes before updating state."""

        self._update_cached_brightness()
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""

        if self._is_brightness:
            brightness = kwargs.get("brightness")
            if isinstance(brightness, int | float):
                ha_value = int(brightness)
                percent = self._brightness_to_percent(ha_value)
                self._attr_brightness = max(0, min(255, ha_value))
                if percent > 0:
                    self._last_brightness_percent = percent
            else:
                percent = self._fallback_brightness_percent()
                self._set_cached_brightness_from_percent(percent)
            await self._async_publish_state(percent)
            return

        await self._async_publish_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""

        if self._is_brightness:
            self._set_cached_brightness_from_percent(0)
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
