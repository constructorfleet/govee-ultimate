"""Home Assistant compatible IoT client facade for MQTT operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


MessageCallback = Callable[[str, bytes], Awaitable[None]]


@dataclass(slots=True)
class IoTClientConfig:
    """Configuration describing how to connect to the MQTT broker."""

    broker: str
    port: int
    username: str | None
    password: str | None
    topics: list[str]
    command_expiry: timedelta


class IoTClient:
    """Thin wrapper around Home Assistant's MQTT helpers."""

    def __init__(
        self,
        *,
        mqtt: Any,
        logger: Any | None = None,
        time_source: Callable[[], datetime] | None = None,
    ) -> None:
        """Store MQTT dependency and optional logger."""

        self._mqtt = mqtt
        self._logger = logger
        self._config: IoTClientConfig | None = None
        self._message_callback: MessageCallback | None = None
        self._unsubscribe_callbacks: list[Callable[[], None]] = []
        self._pending_commands: dict[str, datetime] = {}
        self._time_source = time_source or self._default_time_source

    async def async_configure(self, config: IoTClientConfig) -> None:
        """Persist configuration for subsequent connections."""

        self._config = config

    async def async_connect(self, callback: MessageCallback) -> None:
        """Subscribe to configured topics and relay incoming messages."""

        config = self._require_config()
        self._message_callback = callback
        self._unsubscribe_callbacks.clear()

        for topic in config.topics:
            handle = await self._mqtt.async_subscribe(topic, self._handle_mqtt_message)
            self._unsubscribe_callbacks.append(handle)

    async def _handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Relay raw MQTT messages to the configured callback."""

        if self._message_callback is None:
            return
        await self._message_callback(topic, payload)

    async def async_publish_command(
        self,
        *,
        topic: str,
        payload: bytes,
        command_id: str,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a command message and record its expiry."""

        config = self._require_config()
        expires_at = self._time_source() + config.command_expiry
        self._pending_commands[command_id] = expires_at
        await self._mqtt.async_publish(topic, payload, qos=qos, retain=retain)

    def expire_pending_commands(self) -> None:
        """Remove any commands whose expiry has elapsed."""

        if not self._pending_commands:
            return

        now = self._time_source()
        expired = [
            command_id
            for command_id, expiry in self._pending_commands.items()
            if expiry <= now
        ]
        for command_id in expired:
            self._pending_commands.pop(command_id, None)

    def is_command_pending(self, command_id: str) -> bool:
        """Return True when the command has not yet expired."""

        return command_id in self._pending_commands

    @staticmethod
    def _default_time_source() -> datetime:
        """Return the current UTC time for expiry calculations."""

        return datetime.now(timezone.utc)

    def _require_config(self) -> IoTClientConfig:
        """Return the current configuration or raise if missing."""

        if self._config is None:
            msg = "IoT client must be configured"
            raise RuntimeError(msg)
        return self._config
