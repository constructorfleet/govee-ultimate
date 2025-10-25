"""Coordinator and service layer for the Ultimate Govee integration."""

from __future__ import annotations

import asyncio
import json
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
from .iot_client import IoTClient, IoTClientConfig


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
        iot_client: IoTClient | None = None,
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
        self._iot_config: IoTClientConfig | None = None
        self._iot_enabled = False
        self._iot_debug = False
        self._iot_logger = coordinator_logger.getChild("iot")

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
            if self._iot_enabled and self._iot_client is not None:
                topic = channel_info.get("topic")
                if topic is None:
                    raise ValueError(f"IoT channel missing topic for {device_id}")
                await self._iot_client.async_publish_command(
                    topic=topic,
                    payload=self._encode_command_payload(command),
                    command_id=self._resolve_command_id(device_id, command),
                )
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

    async def async_configure_transports(self, config: dict[str, Any]) -> None:
        """Apply runtime transport configuration settings."""

        if self._iot_client is None:
            self._iot_enabled = False
            return

        iot_settings = dict(config.get("iot", {}))
        self._iot_debug = bool(iot_settings.get("debug"))
        enabled = bool(iot_settings.get("enabled"))

        if not enabled:
            self._iot_enabled = False
            self._iot_config = None
            return

        new_config = self._build_iot_config(iot_settings)

        if self._iot_config != new_config:
            if self._iot_debug:
                self._iot_logger.debug(
                    "Configuring IoT client with topics: %s", new_config.topics
                )
            await self._iot_client.async_configure(new_config)
            self._iot_config = new_config

        await self._iot_client.async_connect(self._handle_iot_message)
        self._iot_enabled = True

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

    def _encode_command_payload(self, command: dict[str, Any]) -> bytes:
        """Serialise a command dictionary for IoT publication."""

        if self._iot_debug:
            self._iot_logger.debug("Publishing command: %s", command)
        return json.dumps(command).encode("utf-8")

    @staticmethod
    def _resolve_command_id(device_id: str, command: dict[str, Any]) -> str:
        """Determine the identifier used to track command expiry."""

        for key in ("command_id", "request_id", "transaction_id"):
            value = command.get(key)
            if value is not None:
                return str(value)
        return device_id

    async def _handle_iot_message(self, topic: str, payload: bytes) -> None:
        """Process MQTT messages relayed from the IoT client."""

        if self._iot_debug:
            self._iot_logger.debug("Received MQTT payload on %s: %s", topic, payload)

        data = self._decode_iot_payload(payload)
        if not data:
            return

        device_id = (
            data.get("device")
            or data.get("device_id")
            or data.get("did")
            or data.get("mac")
        )
        state_payload = data.get("state") or data.get("payload") or {}

        if device_id and isinstance(state_payload, dict):
            await self.async_process_state_update(device_id, state_payload)

        if self._iot_client is not None:
            self._iot_client.expire_pending_commands()

    def _decode_iot_payload(self, payload: bytes) -> dict[str, Any] | None:
        """Decode MQTT payloads into dictionaries when possible."""

        if not payload:
            return None

        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            if self._iot_debug:
                self._iot_logger.debug("Unable to decode MQTT payload: %s", payload)
            return None

    def _build_iot_config(self, settings: dict[str, Any]) -> IoTClientConfig:
        """Construct an IoT client configuration from raw settings."""

        expiry_value = settings.get("command_expiry", 30)
        expiry_delta = (
            expiry_value
            if isinstance(expiry_value, timedelta)
            else timedelta(seconds=int(expiry_value))
        )

        return IoTClientConfig(
            broker=settings.get("broker", ""),
            port=int(settings.get("port") or 8883),
            username=settings.get("username"),
            password=settings.get("password"),
            topics=list(settings.get("topics", [])),
            command_expiry=expiry_delta,
        )
_MODEL_PREFIX_FACTORIES: tuple[tuple[str, type[BaseDevice]], ...] = (
    ("H714", HumidifierDevice),
    ("H712", PurifierDevice),
)

