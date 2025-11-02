"""Device model helpers used by the custom component."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeVar

from custom_components.govee.state import (
    ConnectedState,
    DeviceState,
    ModeState,
)

T = TypeVar("T", bound=Any)


@dataclass(frozen=True)
class LightEntities:
    """Describe the primary and supporting states for a light platform."""

    primary: DeviceState[Any]
    supporting: tuple[DeviceState[Any], ...] = ()


@dataclass(frozen=True)
class HumidifierEntities:
    """Expose humidifier entities for Home Assistant platforms."""

    primary: DeviceState[Any]
    mode: ModeState
    controls: tuple[DeviceState[Any], ...] = ()
    sensors: tuple[DeviceState[Any], ...] = ()


@dataclass(frozen=True)
class PurifierEntities:
    """Expose purifier entities for Home Assistant platforms."""

    primary: DeviceState[Any]
    mode: ModeState
    fan: DeviceState[Any]
    extras: tuple[DeviceState[Any], ...] = ()


class EntityCategory(str, Enum):
    """Subset of Home Assistant entity categories used for metadata."""

    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class HomeAssistantEntity:
    """Describe a Home Assistant entity bound to a device state."""

    platform: str
    state: DeviceState[Any]
    translation_key: str | None = None
    entity_category: EntityCategory | None = None

    @property
    def options(self) -> list[str]:
        """Return available options exposed by the backing state, if any."""

        options_attr = getattr(self.state, "options", None)
        if options_attr is None:
            return []
        return list(options_attr)


class BaseDevice:
    """Minimal state container mirroring the TypeScript device facade."""

    def __init__(self, device_model: Any) -> None:
        """Initialise the state container with a backing model."""

        self.device = device_model
        self._states: dict[str, DeviceState[Any]] = {}
        self._ha_entities: dict[str, HomeAssistantEntity] = {}

    def add_state(self, state: DeviceState[T | None]) -> DeviceState[T | None]:
        """Register a new device state instance."""

        self._states[state.name] = state
        return state

    def alias_state(self, alias: str, state: DeviceState[Any]) -> None:
        """Expose ``state`` under an additional key for update compatibility."""

        self._states[alias] = state

    def alias_entity(
        self, alias: str, state: DeviceState[Any], *, keep_canonical: bool = False
    ) -> None:
        """Expose the entity registered for ``state`` under ``alias``."""

        if alias == state.name:
            return
        entity = self._ha_entities.get(state.name)
        if entity is None:
            return
        self._ha_entities[alias] = entity
        if not keep_canonical:
            self._ha_entities.pop(state.name, None)

    def expose_entity(
        self,
        *,
        platform: str,
        state: DeviceState[Any],
        translation_key: str | None = None,
        entity_category: EntityCategory | None = None,
    ) -> HomeAssistantEntity:
        """Expose a Home Assistant entity bound to ``state``."""

        entity = HomeAssistantEntity(
            platform=platform,
            state=state,
            translation_key=translation_key,
            entity_category=entity_category,
        )
        self._ha_entities[state.name] = entity
        return entity

    def _register_connected_state(self, device_model: Any) -> ConnectedState:
        """Add a diagnostic connected state and expose its entity."""

        connected = self.add_state(ConnectedState(device=device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=connected,
            translation_key="connected",
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        return connected

    @property
    def states(self) -> dict[str, DeviceState[Any]]:
        """Return a mapping of state name to state instance."""

        return dict(MappingProxyType(self._states))

    @property
    def home_assistant_entities(self) -> dict[str, HomeAssistantEntity]:
        """Return the Home Assistant entity definitions for this device."""

        return dict(MappingProxyType(self._ha_entities))
