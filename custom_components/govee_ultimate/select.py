"""Select platform for the Govee Ultimate integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.select import SelectEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)
from .state.device_state import DeviceState


class GoveeSelectEntity(GoveeStateEntity, SelectEntity):
    """Representation of a selectable device state."""

    @property
    def options(self) -> list[str]:
        """Return available options for the state when provided."""

        options_attr = getattr(self._state, "options", None)
        if options_attr:
            return list(options_attr)

        modes = getattr(self._state, "modes", None)
        if isinstance(modes, list):
            entries: list[str] = []
            for mode in modes:
                if mode is None:
                    continue
                if isinstance(mode, DeviceState):
                    candidate = mode.value
                    if isinstance(candidate, str):
                        entries.append(candidate)
                        continue
                    name = getattr(mode, "name", None)
                    if isinstance(name, str):
                        entries.append(name)
                elif isinstance(mode, str):
                    entries.append(mode)
            return entries

        return []

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""

        value = self._state.value
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            for key in ("food", "mode", "value"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
            for candidate in value.values():
                if isinstance(candidate, str):
                    return candidate
            return None
        if isinstance(value, DeviceState):
            candidate = value.value
            if isinstance(candidate, str):
                return candidate
            name = getattr(value, "name", None)
            if isinstance(name, str):
                return name
        return None

    async def async_select_option(self, option: str) -> None:
        """Attempt to change the selected option when commandable."""

        if not self._state.is_commandable:
            raise NotImplementedError(f"State {self._state.name} is read-only")
        await self._async_publish_state(option)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up select entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    entities = build_platform_entities(coordinator, "select", GoveeSelectEntity)

    await async_add_platform_entities(async_add_entities, entities)
