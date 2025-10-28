"""MQTT IoT client for Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any


EMPTY_JSON = "{}"


@dataclass(frozen=True, slots=True)
class IoTClientConfig:
    """Runtime configuration for the IoT client."""

    enabled: bool
    state_topic: str
    command_topic: str
    refresh_topic: str
    qos: int = 0
    command_ttl: timedelta = timedelta(seconds=30)
    debug: bool = False


class IoTClient:
    """Thin wrapper around Home Assistant's MQTT helper."""

    def __init__(
        self,
        *,
        mqtt: Any,
        config: IoTClientConfig,
        on_device_update: Callable[[tuple[str, dict[str, Any]]], Any],
        logger: Any | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        """Bind MQTT helper, configuration, and update callback."""

        self._mqtt = mqtt
        self._config = config
        self._on_device_update = on_device_update
        self._logger = logger
        self._monotonic = monotonic or time.monotonic
        self._pending_commands: dict[str, float] = {}
        self._subscriptions: dict[str, Callable[[], None]] = {}
        self._state_topics: dict[str, str] = {}

    async def async_start(self, device_ids: Sequence[str]) -> None:
        """Subscribe to topics for ``device_ids`` if the client is enabled."""

        if not self._config.enabled:
            return
        for device_id in device_ids:
            await self._subscribe_device(device_id)

    def _wrap_state_callback(self, device_id: str) -> Callable[[str, Any], Any]:
        """Return an MQTT callback that routes payloads to the consumer."""

        def _callback(topic: str, payload: Any) -> None:
            data = self._decode_payload(device_id, payload)
            self._emit_update(device_id, data)

        return _callback

    @property
    def pending_commands(self) -> dict[str, float]:
        """Expose a copy of pending command expiry timestamps."""

        return dict(self._pending_commands)

    def set_update_callback(
        self, callback: Callable[[tuple[str, dict[str, Any]]], Any]
    ) -> None:
        """Override the update callback used for state messages."""

        self._on_device_update = callback

    def _emit_update(self, device_id: str, payload: Any) -> None:
        """Dispatch a processed update to the registered callback."""

        self._on_device_update((device_id, payload))

    async def async_update_config(
        self, config: IoTClientConfig, device_ids: Sequence[str]
    ) -> None:
        """Update runtime configuration and refresh subscriptions."""

        self._config = config
        current = set(self._subscriptions)
        desired = set(device_ids)

        for removed in current - desired:
            self._unsubscribe_device(removed)

        if not self._config.enabled:
            self._unsubscribe_all()
            return

        for device_id in device_ids:
            topic = self._format_topic(self._config.state_topic, device_id)
            if self._state_topics.get(device_id) == topic:
                continue
            self._unsubscribe_device(device_id)
            await self._subscribe_device(device_id)

    async def async_publish_command(
        self, device_id: str, payload: dict[str, Any], *, retain: bool = False
    ) -> str:
        """Publish ``payload`` to the device command topic and track expiry."""

        if not self._config.enabled:
            msg = "IoT client is disabled"
            raise RuntimeError(msg)

        command_id = payload.get("command_id") or uuid.uuid4().hex
        message = dict(payload)
        message["command_id"] = command_id
        topic = self._format_topic(self._config.command_topic, device_id)
        expires_at = self._monotonic() + self._config.command_ttl.total_seconds()
        self._pending_commands[command_id] = expires_at
        await self._mqtt.async_publish(
            topic,
            json.dumps(message),
            qos=self._config.qos,
            retain=retain,
        )
        return command_id

    async def async_request_refresh(self, device_id: str) -> None:
        """Publish a refresh request for ``device_id``."""

        if not self._config.enabled:
            msg = "IoT client is disabled"
            raise RuntimeError(msg)

        topic = self._format_topic(self._config.refresh_topic, device_id)
        await self._mqtt.async_publish(topic, EMPTY_JSON, qos=self._config.qos)

    @staticmethod
    def _format_topic(template: str, device_id: str) -> str:
        """Format an MQTT topic template with ``device_id`` safely."""

        return template.format(device_id=device_id)

    def expire_pending_commands(self) -> list[str]:
        """Remove expired command entries and return their identifiers."""

        now = self._monotonic()
        expired = [
            command_id
            for command_id, expiry in list(self._pending_commands.items())
            if expiry <= now
        ]
        for command_id in expired:
            del self._pending_commands[command_id]
        if expired and self._logger and self._config.debug:
            self._logger.debug("Expired IoT commands: %s", expired)
        return expired

    def _decode_payload(self, device_id: str, payload: Any) -> Any:
        """Best-effort JSON decode for MQTT payloads."""

        data = payload
        if isinstance(payload, bytes | bytearray):
            data = payload.decode()
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                if self._logger and self._config.debug:
                    self._logger.debug(
                        "Failed to decode IoT payload for %s: %s", device_id, data
                    )
        return data

    async def _subscribe_device(self, device_id: str) -> None:
        """Subscribe to the state topic for ``device_id``."""

        topic = self._format_topic(self._config.state_topic, device_id)
        callback = self._wrap_state_callback(device_id)
        unsubscribe = await self._mqtt.async_subscribe(
            topic, callback, qos=self._config.qos
        )
        self._state_topics[device_id] = topic
        if callable(unsubscribe):
            self._subscriptions[device_id] = unsubscribe

    def _unsubscribe_device(self, device_id: str) -> None:
        """Remove any stored subscription for ``device_id``."""

        unsubscribe = self._subscriptions.pop(device_id, None)
        if unsubscribe is not None:
            unsubscribe()
        self._state_topics.pop(device_id, None)

    def _unsubscribe_all(self) -> None:
        """Unsubscribe from all tracked device topics."""

        for device_id in list(self._subscriptions):
            self._unsubscribe_device(device_id)
