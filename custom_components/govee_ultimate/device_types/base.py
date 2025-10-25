"""Device model helpers used by the custom component."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from custom_components.govee_ultimate.state import DeviceState, ModeState


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


class BaseDevice:
    """Minimal state container mirroring the TypeScript device facade."""

    def __init__(self, device_model: Any) -> None:
        """Initialise the state container with a backing model."""

        self.device = device_model
        self._states: dict[str, DeviceState[Any]] = {}

    def add_state(self, state: DeviceState[Any]) -> DeviceState[Any]:
        """Register a new device state instance."""

        self._states[state.name] = state
        return state

    @property
    def states(self) -> dict[str, DeviceState[Any]]:
        """Return a mapping of state name to state instance."""

        return dict(MappingProxyType(self._states))
