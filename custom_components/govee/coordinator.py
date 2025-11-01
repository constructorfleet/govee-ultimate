"""Coordinator and service layer for the Ultimate Govee integration."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import DOMAIN

from .device_types.air_quality import AirQualityDevice
from .device_types.base import BaseDevice
from .device_types.humidifier import HumidifierDevice
from .device_types.ice_maker import IceMakerDevice
from .device_types.presence import PresenceDevice
from .device_types.purifier import PurifierDevice
from .device_types.rgb_light import RGBLightDevice
from .device_types.rgbic_light import RGBICLightDevice
from .device_types.meat_thermometer import MeatThermometerDevice
from .device_types.hygrometer import HygrometerDevice


_DEFAULT_REFRESH_INTERVAL = timedelta(minutes=5)


def _camel_to_snake(value: str) -> str:
    """Convert camelCase or PascalCase identifiers to snake_case."""

    result = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0 and value[index - 1] != "_":
            result.append("_")
        result.append(char.lower())
    return "".join(result)


def _category_matches(group: str, category: str, keywords: tuple[str, ...]) -> bool:
    """Return True when either metadata field contains one of ``keywords``."""

    return any(keyword in group for keyword in keywords) or any(
        keyword in category for keyword in keywords
    )


def _resolve_payload_value(
    payload: dict[str, Any],
    *keys: str,
    default: Any = None,
    required: bool = False,
) -> Any:
    """Return the first non-``None`` value for ``keys`` in ``payload``."""

    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    if required:
        raise KeyError(keys[0])
    return default


@dataclass(slots=True)
class DeviceMetadata:
    """Structured representation of API device metadata."""

    device_id: str
    model: str
    sku: str
    category: str
    category_group: str
    device_name: str
    manufacturer: str
    channels: dict[str, dict[str, Any]]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DeviceMetadata:
        """Normalise payload from the upstream API client."""

        device_id = _resolve_payload_value(
            payload, "device_id", "deviceId", required=True
        )
        model = _resolve_payload_value(payload, "model", "deviceModel", required=True)
        sku = _resolve_payload_value(payload, "sku", "deviceSku", default=model)
        category = _resolve_payload_value(
            payload, "category", "categoryName", default=""
        )
        category_group = _resolve_payload_value(
            payload,
            "category_group",
            "categoryGroup",
            "category_group_name",
            default="",
        )
        device_name = _resolve_payload_value(
            payload, "device_name", "deviceName", "name", default=model
        )
        manufacturer = _resolve_payload_value(
            payload, "manufacturer", "manufacturerName", default="Govee"
        )
        channels_payload = _resolve_payload_value(
            payload, "channels", "deviceChannels", default={}
        )

        channels: dict[str, dict[str, Any]] = {
            channel: {
                _camel_to_snake(key): value
                for key, value in dict(channel_payload).items()
            }
            for channel, channel_payload in channels_payload.items()
        }

        return cls(
            device_id=device_id,
            model=model,
            sku=sku,
            category=category,
            category_group=category_group,
            device_name=device_name,
            manufacturer=manufacturer,
            channels=channels,
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
        self._iot_expiry_handle: asyncio.TimerHandle | None = None
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
        discovered_devices: dict[str, BaseDevice] = {}
        discovered_metadata: dict[str, DeviceMetadata] = {}
        for payload in payloads:
            metadata = DeviceMetadata.from_dict(payload)
            factory = self._resolve_factory(metadata)
            if factory is None:
                continue
            device = factory(metadata)
            discovered_devices[metadata.device_id] = device
            discovered_metadata[metadata.device_id] = metadata
            device_entry = await self._device_registry.async_get_or_create(
                config_entry_id=self._config_entry_id,
                identifiers={(DOMAIN, metadata.device_id)},
                name=metadata.device_name,
                model=metadata.model,
                manufacturer=metadata.manufacturer,
            )
            await self._register_entities(metadata, device, device_entry.id)

        self.devices = discovered_devices
        self.device_metadata = discovered_metadata

        if self._iot_client and self._iot_state_enabled:
            iot_devices = self._iot_device_ids()
            if iot_devices:
                await self._iot_client.async_start()
        self._schedule_command_expiry()

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh metadata and expose a snapshot for Home Assistant entities."""

        await self.async_discover_devices()
        return {"devices": self.devices, "device_metadata": self.device_metadata}

    def _resolve_factory(
        self, metadata: DeviceMetadata
    ) -> Callable[[DeviceMetadata], BaseDevice] | None:
        """Determine the appropriate device factory for ``metadata``."""

        model = metadata.model.upper()
        for prefix, factory in _MODEL_PREFIX_FACTORIES:
            if model.startswith(prefix):
                return factory

        group = metadata.category_group.lower()
        category = metadata.category.lower()
        name = metadata.device_name.lower()
        if category == "home appliances" and group == "kitchen" and "ice maker" in name:
            return IceMakerDevice
        if self._is_meat_thermometer(group, name):
            return MeatThermometerDevice
        if _category_matches(group, category, ("presence",)):
            return PresenceDevice
        if _category_matches(group, category, ("air quality",)):
            return AirQualityDevice
        if _category_matches(group, category, ("hygro", "thermo")):
            return HygrometerDevice
        if _category_matches(group, category, ("rgbic",)):
            return RGBICLightDevice

        light_keywords = ("light", "lighting", "lamp")
        if _category_matches(group, category, light_keywords):
            return RGBLightDevice
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
        self._cancel_command_expiry()

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

        metadata = self.device_metadata.get(device_id)
        if metadata is None:
            raise KeyError(device_id)

        if channel_name == "iot":
            if self._iot_client and self._iot_command_enabled:
                topic = self._resolve_iot_topic(metadata, channel_info, device_id)
                await self._iot_client.async_publish_command(topic, command)
                self._schedule_command_expiry()
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

        channel_info = metadata.channels["iot"]
        topic = self._resolve_iot_topic(metadata, channel_info, device_id)
        await self._iot_client.async_request_refresh(topic)

    def _resolve_iot_topic(
        self,
        metadata: DeviceMetadata,
        channel_info: dict[str, Any],
        device_id: str,
    ) -> str:
        """Determine the IoT topic for ``device_id``."""

        iot_channel = metadata.channels.get("iot", {})
        topic = channel_info.get("topic") or iot_channel.get("topic")
        if isinstance(topic, str) and topic:
            return topic
        raise KeyError(f"No IoT topic available for {device_id}")

    def _schedule_iot_update(self, update: tuple[str, dict[str, Any]]) -> None:
        """Schedule processing of an IoT state update from the MQTT client."""

        task = self._loop.create_task(self._handle_iot_update(update))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _handle_iot_update(self, update: tuple[str, dict[str, Any]]) -> None:
        """Apply an IoT update to the device models."""

        device_id, payload = update
        updates, raw_payload = self._normalise_iot_payload(payload)
        await self.async_process_state_update(
            device_id, updates, raw_payload=raw_payload
        )
        self._schedule_command_expiry()

    async def async_process_state_update(
        self,
        device_id: str,
        updates: dict[str, Any],
        *,
        raw_payload: dict[str, Any] | None = None,
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
        if raw_payload is not None and isinstance(raw_payload, dict):
            for name, state in device.states.items():
                before = state.value
                state.parse(raw_payload)
                if name not in changed and state.value != before:
                    changed.append(name)
        return changed

    def _normalise_iot_payload(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Flatten nested AWS IoT frames for state processing."""

        if not isinstance(payload, dict):
            return payload, payload

        frames: list[dict[str, Any]] = []
        queue: deque[dict[str, Any]] = deque([payload])
        seen: set[int] = set()
        while queue:
            frame = queue.popleft()
            identifier = id(frame)
            if identifier in seen:
                continue
            seen.add(identifier)
            frames.append(frame)
            for key in ("msg", "data"):
                nested = frame.get(key)
                if isinstance(nested, dict):
                    queue.append(nested)

        combined_state: dict[str, Any] = {}
        op_payload: dict[str, Any] | None = None
        combined_payload: dict[str, Any] = {}
        for frame in frames:
            for key, value in frame.items():
                if key in ("msg", "data"):
                    continue
                if key == "state" and isinstance(value, dict):
                    combined_state.update(value)
                    continue
                if key == "op" and isinstance(value, dict):
                    op_payload = value
                    continue
                combined_payload.setdefault(key, value)

        if combined_state:
            combined_payload["state"] = combined_state
        if op_payload is not None:
            combined_payload["op"] = op_payload

        flattened_updates = dict(payload)
        if combined_state:
            for key, value in combined_state.items():
                flattened_updates[key] = value
                if isinstance(key, str):
                    snake_key = _camel_to_snake(key)
                    flattened_updates.setdefault(snake_key, value)
        if op_payload is not None:
            flattened_updates.setdefault("op", op_payload)

        return flattened_updates, combined_payload or payload

    def _apply_state_update(self, name: str, state: Any, value: Any) -> list[str]:
        """Apply ``value`` to ``state`` using any custom hooks available."""

        update_handler = getattr(state, "apply_channel_update", None)
        if callable(update_handler):
            return update_handler(value)
        if isinstance(value, dict) and self._invoke_state_parse(state, value):
            return [name]
        update_method = getattr(state, "_update_state", None)
        if callable(update_method):
            update_method(value)
            return [name]
        return []

    @staticmethod
    def _invoke_state_parse(state: Any, value: dict[str, Any]) -> bool:
        """Invoke the state parse hook when available."""

        parse_method = getattr(state, "parse", None)
        if callable(parse_method):
            parse_method(value)
            return True
        return False

    def _schedule_command_expiry(self) -> None:
        """Schedule the next IoT command expiry sweep if required."""

        if not (self._iot_client and self._iot_command_enabled):
            self._cancel_command_expiry()
            return

        pending = self._iot_pending_commands()
        if not pending:
            self._cancel_command_expiry()
            return

        now = time.monotonic()
        next_expiry = min(pending.values())
        delay = max(0.0, next_expiry - now)
        if self._iot_expiry_handle is not None:
            self._iot_expiry_handle.cancel()
        self._iot_expiry_handle = self._loop.call_later(
            delay, self._expire_pending_commands
        )

    def _cancel_command_expiry(self) -> None:
        """Cancel any scheduled IoT command expiry callbacks."""

        if self._iot_expiry_handle is not None:
            self._iot_expiry_handle.cancel()
            self._iot_expiry_handle = None

    def _expire_pending_commands(self) -> None:
        """Expire pending IoT commands and notify device states."""

        if not self._iot_client:
            return

        expired = self._iot_client.expire_pending_commands()
        if expired:
            for device in self.devices.values():
                for state in device.states.values():
                    expire = getattr(state, "expire_pending_commands", None)
                    if callable(expire):
                        expire(expired)
        self._schedule_command_expiry()

    def _iot_pending_commands(self) -> dict[str, float]:
        """Return a mapping of pending IoT command expirations."""

        if not self._iot_client:
            return {}
        pending = getattr(self._iot_client, "pending_commands", None)
        if isinstance(pending, dict):
            return dict(pending)
        return {}

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

    @staticmethod
    def _is_meat_thermometer(group: str, name: str) -> bool:
        """Return True when metadata matches meat thermometer heuristics."""

        return group == "kitchen" and "meat thermometer" in name


_MODEL_PREFIX_FACTORIES: tuple[tuple[str, type[BaseDevice]], ...] = (
    ("H660", AirQualityDevice),
    ("H714", HumidifierDevice),
    ("H712", PurifierDevice),
    ("H717", IceMakerDevice),
    ("H74", MeatThermometerDevice),
    ("H600", RGBLightDevice),
    ("H51", PresenceDevice),
    ("H5", HygrometerDevice),
)
