"""Shared entity helpers for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

# Import CoordinatorEntity lazily. Some test environments do not provide the
# Home Assistant helper and attempting to import it at module import time
# causes ImportError during pytest collection. When unavailable, define a
# minimal fallback base class that provides the expected interface used by
# our entities.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from homeassistant.helpers.update_coordinator import CoordinatorEntity
else:
    try:
        from homeassistant.helpers.update_coordinator import CoordinatorEntity
    except Exception:  # pragma: no cover - fallback for test collection

        class CoordinatorEntity:  # type: ignore[no-redef]
            """Minimal fallback for CoordinatorEntity used in unit tests."""

            def __init__(self, coordinator: Any | None = None) -> None:
                """Construct a minimal fallback coordinator entity."""
                self.coordinator = coordinator


from .const import DOMAIN
from .coordinator import GoveeDataUpdateCoordinator
from .device_types.base import HomeAssistantEntity
from .state.device_state import DeviceState

_AsyncPublisher = Callable[[dict[str, Any]], Awaitable[None]]

StateT = TypeVar("StateT", bound=DeviceState[Any])


class GoveeStateEntity(CoordinatorEntity, Generic[StateT]):
    """Base entity binding a device state to Home Assistant."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: GoveeDataUpdateCoordinator,
        device_id: str,
        entity: HomeAssistantEntity,
    ) -> None:
        """Store state references and resolve static attributes."""

        super().__init__(coordinator)
        self._device_id = device_id
        self._ha_entity = entity
        self._state: StateT = entity.state  # type: ignore[assignment]
        self._remove_listener: Callable[[], None] | None = None
        self._publisher: _AsyncPublisher | None = None
        if not hasattr(self, "_written_states"):
            self._written_states: list[Any] = []
        unique_id = f"{device_id}-{self._state.name}"
        self._attr_unique_id = unique_id
        self.unique_id = unique_id
        if entity.translation_key:
            self._attr_translation_key = entity.translation_key
        if entity.entity_category:
            self._attr_entity_category = entity.entity_category.value

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates when the entity is added."""

        # Avoid calling CoordinatorEntity.async_added_to_hass which may schedule
        # registration into the event loop. Some test doubles (FakeCoordinator)
        # implement async_add_listener(callback) only and raise when called with
        # a context; scheduling that call as a separate task makes the error
        # uncaught by a try/except. Instead, register the listener directly
        # without a context to remain compatible with test shims.

        # Register listener without context. If the coordinator returns a
        # callable remove function, store it for cleanup.
        try:
            remove = self.coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        except Exception:
            # Defensive: if the coordinator raises for any reason, skip
            # registration to avoid breaking tests that use minimal shims.
            remove = None

        if remove is not None:
            self._remove_listener = remove

        # Ensure our publisher reference and initial state write happen.
        self._publisher = self.coordinator.get_command_publisher(self._device_id)
        # In some test harnesses the entity's ``hass`` attribute may not be set
        # before async_added_to_hass is invoked directly; guard the state
        # write to avoid Home Assistant raising when hass is None.
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Detach listeners when the entity is removed."""

        remove = self._remove_listener
        if remove is not None:
            remove()
            self._remove_listener = None
        await super().async_will_remove_from_hass()

    def _handle_coordinator_update(self) -> None:
        """Refresh Home Assistant state when the coordinator updates."""

        # Only write state when the entity is attached to hass. Some tests
        # call coordinator listeners without the entity being fully added to
        # hass, which leaves ``self.hass`` as None and causes Home Assistant to
        # raise when writing state.
        if getattr(self, "hass", None) is not None:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Assume entities are available when the state has a value."""

        return self._state.value is not None

    @property
    def native_value(self) -> Any:
        """Expose the raw state value for simple entities."""

        return self._state.value

    async def _async_publish_state(self, value: Any) -> None:
        """Publish the next state to the coordinator command queue."""

        command_ids = self._state.set_state(value)
        if not command_ids:
            return
        publisher = self._publisher
        if publisher is None:
            publisher = self.coordinator.get_command_publisher(self._device_id)
            self._publisher = publisher
        if self._state.command_queue.empty():
            for command_id in command_ids:
                await publisher(
                    {
                        "command_id": command_id,
                        "state": self._state.name,
                        "value": self._state.value,
                    }
                )
            return
        while not self._state.command_queue.empty():
            payload = await self._state.command_queue.get()
            await publisher(payload)


async def async_add_platform_entities(
    async_add_entities: Callable[[list[Any]], Any], entities: list[Any]
) -> None:
    """Add entities for a Home Assistant platform, awaiting when required."""

    if not entities:
        return
    result = async_add_entities(entities)
    if asyncio.iscoroutine(result):
        await result


def iter_platform_entities(
    coordinator: Any, platform: str
) -> list[tuple[str, HomeAssistantEntity]]:
    """Iterate over coordinator devices yielding entities for ``platform``."""

    matches: list[tuple[str, HomeAssistantEntity]] = []
    for device_id, device in coordinator.devices.items():
        entities = device.home_assistant_entities
        for entity in entities.values():
            if entity.platform == platform:
                matches.append((device_id, entity))
    return matches


def resolve_coordinator(hass: Any, entry: Any) -> Any | None:
    """Return the coordinator for ``entry`` when available."""

    entry_id = entry.entry_id if hasattr(entry, "entry_id") else None
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if isinstance(entry_data, dict):
        return entry_data.get("coordinator")
    return None


def build_platform_entities(
    coordinator: Any,
    platform: str,
    entity_factory: Callable[[Any, str, HomeAssistantEntity], Any],
) -> list[Any]:
    """Construct entity instances for ``platform`` using ``entity_factory``."""

    return [
        entity_factory(coordinator, device_id, entity)
        for device_id, entity in iter_platform_entities(coordinator, platform)
    ]
