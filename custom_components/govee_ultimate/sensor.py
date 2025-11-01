"""Sensor platform for the Govee Ultimate integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import voluptuous as vol

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform

from homeassistant.components.sensor import SensorEntity

from .entity import (
    GoveeStateEntity,
    async_add_platform_entities,
    build_platform_entities,
    resolve_coordinator,
)
from .state.states import EarlyWarningState, IceMakerScheduledStartState, SceneModeState


_ICE_MAKER_SCHEDULE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("enabled"): bool,
        vol.Optional("hour_start"): vol.All(int, vol.Range(min=0, max=23)),
        vol.Optional("minute_start"): vol.All(int, vol.Range(min=0, max=59)),
        vol.Optional("nugget_size"): vol.All(str, vol.Length(min=1)),
    }
)


async def _async_set_schedule_service(
    entity: GoveeSensorEntity, data: Mapping[str, Any]
) -> None:
    """Dispatch schedule updates to the scheduled start entity."""

    if not isinstance(entity, GoveeIceMakerScheduledStartSensorEntity):
        return
    try:
        await entity.async_set_schedule(**data)
    except ValueError as exc:
        raise HomeAssistantError(str(exc)) from exc


class GoveeSensorEntity(GoveeStateEntity, SensorEntity):
    """Representation of a diagnostic sensor state."""

    @property
    def native_value(self) -> Any:
        """Return the latest sensor reading."""

        return self._state.value

    @property
    def entity_category(self) -> str | None:
        """Expose the resolved entity category for test stubs."""

        return getattr(self, "_attr_entity_category", None)


class GoveeEarlyWarningSensorEntity(GoveeSensorEntity):
    """Expose parsed early warning metadata for meat thermometers."""

    _state: EarlyWarningState

    def _current_value(self) -> Mapping[str, Any] | None:
        """Return the parsed early warning payload when available."""

        value = self._state.value
        if isinstance(value, Mapping):
            return value
        return None

    @property
    def native_value(self) -> Any:
        """Return the configured early warning offset when available."""

        value = self._current_value()
        if value is not None:
            setting = value.get("setting")
            if isinstance(setting, str):
                return setting
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the entire early warning payload as attributes."""

        value = self._current_value()
        if value is not None:
            return dict(value)
        return {}


class GoveeIceMakerScheduledStartSensorEntity(GoveeSensorEntity):
    """Expose scheduled start metadata for ice makers."""

    _state: IceMakerScheduledStartState

    @property
    def native_value(self) -> Any:
        """Return whether the scheduled start is enabled."""

        value = self._state.value
        if isinstance(value, dict):
            enabled = value.get("enabled")
            if isinstance(enabled, bool):
                return enabled
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the configured schedule fields as state attributes."""

        value = self._state.value
        if isinstance(value, dict):
            return {
                "enabled": value.get("enabled"),
                "hourStart": value.get("hourStart"),
                "minuteStart": value.get("minuteStart"),
                "nuggetSize": value.get("nuggetSize"),
            }
        return {}

    async def async_set_schedule(
        self,
        *,
        enabled: bool,
        hour_start: int | None = None,
        minute_start: int | None = None,
        nugget_size: str | None = None,
    ) -> None:
        """Publish an updated schedule through the backing state."""

        next_value = self._resolve_schedule_value(
            enabled,
            hour_start,
            minute_start,
            nugget_size,
        )
        command_ids = self._state.set_state(next_value)
        if not command_ids:
            return
        publisher = self._ensure_publisher()
        await self._publish_command_queue(publisher)
        self._state._update_state(next_value)  # type: ignore[attr-defined]
        self.async_write_ha_state()

    def _resolve_schedule_value(
        self,
        enabled: bool,
        hour_start: int | None,
        minute_start: int | None,
        nugget_size: str | None,
    ) -> dict[str, Any]:
        """Normalise schedule inputs against the current state value."""

        existing = self._state.value if isinstance(self._state.value, dict) else {}
        if not enabled:
            return {
                "enabled": False,
                "hourStart": None,
                "minuteStart": None,
                "nuggetSize": None,
            }
        resolved_hour = (
            hour_start if hour_start is not None else existing.get("hourStart")
        )
        resolved_minute = (
            minute_start if minute_start is not None else existing.get("minuteStart")
        )
        resolved_nugget = (
            nugget_size if nugget_size is not None else existing.get("nuggetSize")
        )
        if resolved_hour is None or resolved_minute is None or resolved_nugget is None:
            raise ValueError(
                "Schedule updates require hour, minute, and nugget size when enabled"
            )
        try:
            hour_value = int(resolved_hour)
            minute_value = int(resolved_minute)
        except (TypeError, ValueError) as exc:
            raise ValueError("Hour and minute must be integers") from exc
        return {
            "enabled": True,
            "hourStart": hour_value,
            "minuteStart": minute_value,
            "nuggetSize": str(resolved_nugget),
        }

    def _ensure_publisher(self) -> Callable[[dict[str, Any]], Awaitable[None]]:
        """Return the coordinator command publisher, caching the reference."""

        publisher = self._publisher
        if publisher is None:
            publisher = self.coordinator.get_command_publisher(self._device_id)
            self._publisher = publisher
        return publisher

    async def _publish_command_queue(
        self, publisher: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Flush queued command payloads through ``publisher``."""

        while not self._state.command_queue.empty():
            command_payload = await self._state.command_queue.get()
            await publisher(command_payload)


class GoveeSceneModeSensorEntity(GoveeSensorEntity):
    """Expose scene metadata for RGB light devices."""

    _state: SceneModeState

    def _current_scene_value(self) -> Mapping[str, Any] | None:
        """Return the current scene metadata when available."""

        value = self._state.value
        if isinstance(value, Mapping):
            return value
        return None

    @property
    def native_value(self) -> Any:
        """Return the active scene identifier when available."""

        value = self._current_scene_value()
        if value is None:
            return None
        scene_id = value.get("sceneId")
        if isinstance(scene_id, int):
            return scene_id
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the latest scene identifier metadata."""

        value = self._current_scene_value()
        if value is None:
            return {}
        return {
            "sceneId": value.get("sceneId"),
            "sceneParamId": value.get("sceneParamId"),
        }


def _sensor_entity_factory(coordinator: Any, device_id: str, entity: Any) -> Any:
    """Return a specialised entity for known sensor state types."""

    state = entity.state
    if isinstance(state, EarlyWarningState):
        return GoveeEarlyWarningSensorEntity(coordinator, device_id, entity)
    if isinstance(state, IceMakerScheduledStartState):
        return GoveeIceMakerScheduledStartSensorEntity(coordinator, device_id, entity)
    if isinstance(state, SceneModeState):
        return GoveeSceneModeSensorEntity(coordinator, device_id, entity)
    return GoveeSensorEntity(coordinator, device_id, entity)


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up sensor entities for a config entry."""

    coordinator = resolve_coordinator(hass, entry)
    if coordinator is None:
        return

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_schedule",
        _ICE_MAKER_SCHEDULE_SERVICE_SCHEMA,
        _async_set_schedule_service,
    )

    entities = build_platform_entities(coordinator, "sensor", _sensor_entity_factory)

    await async_add_platform_entities(async_add_entities, entities)
