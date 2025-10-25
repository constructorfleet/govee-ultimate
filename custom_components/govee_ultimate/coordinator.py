"""Coordinator and service layer for the Ultimate Govee integration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import DOMAIN

from .device_types.base import BaseDevice
from .device_types.humidifier import HumidifierDevice
from .device_types.purifier import PurifierDevice
from .device_types.rgbic_light import RGBICLightDevice


_DEFAULT_REFRESH_INTERVAL = timedelta(minutes=5)


@dataclass(slots=True)
class DeviceMetadata:
    """Structured representation of API device metadata."""

    device_id: str
    model: str
    sku: str
    category: str
    category_group: str
    device_name: str
    channels: dict[str, dict[str, Any]]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeviceMetadata:
        """Normalise payload from the upstream API client."""

        return cls(
            device_id=payload["device_id"],
            model=payload["model"],
            sku=payload.get("sku", payload["model"]),
            category=payload.get("category", ""),
            category_group=payload.get("category_group", ""),
            device_name=payload.get("device_name", payload["model"]),
            channels={k: dict(v) for k, v in payload.get("channels", {}).items()},
        )

    @property
    def preferred_channel(self) -> str | None:
        """Return the preferred transport channel for commands."""

        if "iot" in self.channels:
            return "iot"
        if self.channels:
            return next(iter(self.channels))
        return None


class GoveeDataUpdateCoordinator(DataUpdateCoordinator):
    """Own device instances and orchestrate refresh/events."""

    def __init__(
        self,
        *,
        hass: Any,
        api_client: Any,
        device_registry: Any,
        entity_registry: Any,
        config_entry_id: str | None = None,
        refresh_interval: timedelta | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        logger: logging.Logger | None = None,
        iot_client: Any | None = None,
        iot_state_enabled: bool = False,
        iot_command_enabled: bool = False,
        iot_refresh_enabled: bool = False,
    ) -> None:
        """Initialise the coordinator with integration dependencies."""

        coordinator_logger = logger or logging.getLogger(__name__)
        interval = refresh_interval or _DEFAULT_REFRESH_INTERVAL
        super().__init__(
            hass,
            coordinator_logger,
            name="Govee Ultimate Data Coordinator",
            update_interval=interval,
        )

        self.hass = hass
        self._api_client = api_client
        self._device_registry = device_registry
        self._entity_registry = entity_registry
        self._config_entry_id = config_entry_id
        hass_loop = getattr(hass, "loop", None)
        self._loop = loop or hass_loop or asyncio.get_event_loop()
        self._refresh_task: asyncio.TimerHandle | None = None
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._iot_client = iot_client
        self._iot_state_enabled = iot_state_enabled
        self._iot_command_enabled = iot_command_enabled
        self._iot_refresh_enabled = iot_refresh_enabled
        if self._iot_client:
            setter = getattr(self._iot_client, "set_update_callback", None)
            if callable(setter):
                setter(self._schedule_iot_update)

        self.devices: dict[str, BaseDevice] = {}
        self.device_metadata: dict[str, DeviceMetadata] = {}

    @property
    def _refresh_interval_seconds(self) -> float:
        """Expose the coordinator refresh interval as seconds."""

        if self.update_interval is None:
            msg = "Refresh interval is not configured"
            raise RuntimeError(msg)
        return self.update_interval.total_seconds()

    async def async_discover_devices(self) -> None:
        """Fetch metadata and materialise device instances."""

        payloads = await self._api_client.async_get_devices()
        for payload in payloads:
            metadata = DeviceMetadata.from_dict(payload)
            factory = self._resolve_factory(metadata)
            if factory is None:
                continue
            device = factory(metadata)
            self.devices[metadata.device_id] = device
            self.device_metadata[metadata.device_id] = metadata
            device_entry = await self._device_registry.async_get_or_create(
                config_entry_id=self._config_entry_id,
                identifiers={(DOMAIN, metadata.device_id)},
                name=metadata.device_name,
                model=metadata.model,
                manufacturer="Govee",
            )
            await self._register_entities(metadata, device, device_entry.id)

        if self._iot_client and self._iot_state_enabled:
            iot_devices = self._iot_device_ids()
            if iot_devices:
                await self._iot_client.async_start(iot_devices)

    def _resolve_factory(
        self, metadata: DeviceMetadata
    ) -> Callable[[DeviceMetadata], BaseDevice] | None:
        """Determine the appropriate device factory for ``metadata``."""

        model = metadata.model.upper()
        for prefix, factory in _MODEL_PREFIX_FACTORIES:
            if model.startswith(prefix):
                return factory

        group = metadata.category_group.lower()
        if "rgbic" in group or "light" in group:
            return RGBICLightDevice
        return None

    def async_schedule_refresh(
        self, callback: Callable[[], Awaitable[Any] | None]
    ) -> asyncio.TimerHandle:
        """Schedule recurring refresh callbacks."""

        def _wrapper() -> None:
            task = callback()
            if isinstance(task, Coroutine):
                task_obj = asyncio.create_task(task)
                self._pending_tasks.add(task_obj)
                task_obj.add_done_callback(self._pending_tasks.discard)
            self._refresh_task = self._loop.call_later(
                self._refresh_interval_seconds, _wrapper
            )

        if self._refresh_task is not None:
            self._refresh_task.cancel()
        self._refresh_task = self._loop.call_later(
            self._refresh_interval_seconds, _wrapper
        )
        return self._refresh_task

    def cancel_refresh(self) -> None:
        """Cancel any scheduled refresh callbacks."""

        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    def get_command_publisher(
        self, device_id: str, *, channel: str | None = None
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        """Return an async callback that publishes commands for ``device_id``."""

        metadata = self.device_metadata.get(device_id)
        if metadata is None:
            raise KeyError(device_id)

        channel_name = channel or metadata.preferred_channel
        if channel_name is None:
            raise ValueError(f"No channels available for {device_id}")

        channel_info = metadata.channels.get(channel_name)
        if channel_info is None:
            raise KeyError(channel_name)

        async def _publisher(command: dict[str, Any]) -> None:
            await self._dispatch_command(device_id, channel_name, channel_info, command)

        return _publisher

    async def _dispatch_command(
        self,
        device_id: str,
        channel_name: str,
        channel_info: dict[str, Any],
        command: dict[str, Any],
    ) -> None:
        """Send ``command`` via the correct transport channel."""

        if channel_name == "iot":
            if self._iot_client and self._iot_command_enabled:
                await self._iot_client.async_publish_command(device_id, command)
            else:
                await self._api_client.async_publish_iot_command(
                    device_id, channel_info, command
                )
        elif channel_name == "ble":
            await self._api_client.async_publish_ble_command(
                device_id, channel_info, command
            )
        else:
            raise ValueError(f"Unsupported channel {channel_name}")

    def _iot_device_ids(self) -> list[str]:
        """Return identifiers for devices that expose an IoT channel."""

        return [
            device_id
            for device_id, metadata in self.device_metadata.items()
            if "iot" in metadata.channels
        ]

    async def async_request_device_refresh(self, device_id: str) -> None:
        """Request a device refresh via the configured IoT transport."""

        if not (self._iot_client and self._iot_refresh_enabled):
            raise RuntimeError("IoT refresh channel is not enabled")

        metadata = self.device_metadata.get(device_id)
        if metadata is None or "iot" not in metadata.channels:
            raise KeyError(device_id)

        await self._iot_client.async_request_refresh(device_id)

    def _schedule_iot_update(self, update: tuple[str, dict[str, Any]]) -> None:
        """Schedule processing of an IoT state update from the MQTT client."""

        task = self._loop.create_task(self._handle_iot_update(update))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _handle_iot_update(self, update: tuple[str, dict[str, Any]]) -> None:
        """Apply an IoT update to the device models."""

        device_id, payload = update
        await self.async_process_state_update(device_id, payload)

    async def async_process_state_update(
        self, device_id: str, updates: dict[str, Any]
    ) -> list[str]:
        """Apply state updates from a transport channel to device models."""

        device = self.devices.get(device_id)
        if device is None:
            raise KeyError(device_id)

        changed: list[str] = []
        for name, value in updates.items():
            state = device.states.get(name)
            if state is None:
                continue
            changed.extend(self._apply_state_update(name, state, value))
        return changed

    @staticmethod
    def _apply_state_update(name: str, state: Any, value: Any) -> list[str]:
        """Apply ``value`` to ``state`` using any custom hooks available."""

        update_handler = getattr(state, "apply_channel_update", None)
        if callable(update_handler):
            return update_handler(value)
        update_method = getattr(state, "_update_state", None)
        if callable(update_method):
            update_method(value)
            return [name]
        return []

    async def _register_entities(
        self, metadata: DeviceMetadata, device: BaseDevice, device_entry_id: str
    ) -> None:
        """Register Home Assistant entities exposed by ``device``."""

        for name, entity in device.home_assistant_entities.items():
            payload = self._build_entity_payload(metadata, name, entity)
            await self._entity_registry.async_get_or_create(
                entity.platform,
                DOMAIN,
                payload.pop("unique_id"),
                device_id=device_entry_id,
                **payload,
            )

    @staticmethod
    def _build_entity_payload(
        metadata: DeviceMetadata, name: str, entity: Any
    ) -> dict[str, Any]:
        """Serialise Home Assistant entity metadata for registry calls."""

        return {
            "unique_id": f"{metadata.device_id}-{name}",
            "translation_key": entity.translation_key,
            "entity_category": (
                entity.entity_category.value if entity.entity_category else None
            ),
        }
_MODEL_PREFIX_FACTORIES: tuple[tuple[str, type[BaseDevice]], ...] = (
    ("H714", HumidifierDevice),
    ("H712", PurifierDevice),
)

