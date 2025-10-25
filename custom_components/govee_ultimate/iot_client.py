"""MQTT client wrapper for the Govee Ultimate Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
from collections.abc import Awaitable, Callable
from types import MappingProxyType
import uuid
from json import JSONDecodeError


MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
UnsubscribeCallback = Callable[[], None]


@dataclass(slots=True)
class IotMqttConfig:
    """Configuration describing the MQTT topics and behaviour for the IoT client."""

    enabled: bool
    state_topic: str
    response_topic: str
    command_topic: str
    refresh_topic: str
    expiry_seconds: float
    log_debug: bool = False


@dataclass(slots=True)
class PendingCommand:
    """Track the lifecycle of an outbound command."""

    command_id: str
    device_id: str
    payload: dict[str, Any]
    expires_at: float


class GoveeIotClient:
    """High-level MQTT client used by the integration coordinator."""

    def __init__(
        self,
        hass: Any,
        mqtt_client: Any,
        config: IotMqttConfig,
        *,
        on_state_message: MessageHandler | None = None,
        on_command_response: MessageHandler | None = None,
        on_command_expired: Callable[[PendingCommand], Awaitable[None]] | None = None,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        """Store references to Home Assistant, MQTT interface, and callbacks."""

        self._hass = hass
        self._mqtt = mqtt_client
        self._config = config
        self._on_state_message = on_state_message
        self._on_command_response = on_command_response
        self._on_command_expired = on_command_expired
        self._unsubscribe_state: UnsubscribeCallback | None = None
        self._unsubscribe_response: UnsubscribeCallback | None = None
        self._time_source = time_source or time.monotonic
        self._pending_commands: dict[str, PendingCommand] = {}

    async def async_connect(self) -> None:
        """Subscribe to MQTT topics when enabled."""

        if not self._config.enabled:
            return

        self._unsubscribe_state = await self._mqtt.async_subscribe(
            self._config.state_topic,
            self._handle_state_message,
        )
        self._unsubscribe_response = await self._mqtt.async_subscribe(
            self._config.response_topic,
            self._handle_command_response,
        )

    async def async_disconnect(self) -> None:
        """Unsubscribe from MQTT topics."""

        if self._unsubscribe_state is not None:
            self._unsubscribe_state()
            self._unsubscribe_state = None
        if self._unsubscribe_response is not None:
            self._unsubscribe_response()
            self._unsubscribe_response = None

    @property
    def pending_commands(self) -> dict[str, PendingCommand]:
        """Return a snapshot of commands awaiting acknowledgement."""

        return MappingProxyType(self._pending_commands)

    async def async_send_command(self, device_id: str, payload: dict[str, Any]) -> str:
        """Publish an outbound command and track it until acknowledgement."""

        self._ensure_enabled()

        command_id = uuid.uuid4().hex
        message = {
            "cmdId": command_id,
            "device": device_id,
            "payload": payload,
        }
        await self._mqtt.async_publish(
            self._config.command_topic,
            json.dumps(message),
        )
        expires_at = self._time_source() + self._config.expiry_seconds
        self._pending_commands[command_id] = PendingCommand(
            command_id=command_id,
            device_id=device_id,
            payload=payload,
            expires_at=expires_at,
        )
        return command_id

    async def async_expire_commands(self) -> list[PendingCommand]:
        """Drop pending commands whose expiry time has elapsed."""

        now = self._time_source()
        expired: list[PendingCommand] = []
        for command_id, command in list(self._pending_commands.items()):
            if command.expires_at <= now:
                expired.append(command)
                del self._pending_commands[command_id]
        if not expired:
            return []
        if self._on_command_expired is not None:
            for command in expired:
                await self._on_command_expired(command)
        return expired

    async def async_request_refresh(self, device_id: str) -> None:
        """Publish a refresh request when the IoT channel is available."""

        self._ensure_enabled()
        await self._mqtt.async_publish(
            self._config.refresh_topic,
            json.dumps({"device": device_id}),
        )

    def _ensure_enabled(self) -> None:
        """Raise when the IoT channel is disabled."""

        if not self._config.enabled:
            raise RuntimeError("IoT channel disabled")

    async def _handle_state_message(self, topic: str, payload: Any, qos: dict[str, Any]) -> None:
        """Dispatch state payloads to the registered callback."""

        if self._on_state_message is None:
            return
        decoded = self._decode_payload(payload)
        await self._on_state_message(decoded)

    async def _handle_command_response(
        self, topic: str, payload: Any, qos: dict[str, Any]
    ) -> None:
        """Dispatch command acknowledgements to the registered callback."""

        decoded = self._decode_payload(payload)
        if isinstance(decoded, dict):
            command_id = decoded.get("cmdId")
            if command_id is not None:
                self._pending_commands.pop(str(command_id), None)
        if self._on_command_response is None:
            return
        await self._on_command_response(decoded)

    def _decode_payload(self, payload: Any) -> Any:
        """Return a JSON payload if possible, otherwise the raw data."""

        if isinstance(payload, bytes | bytearray):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except JSONDecodeError:
                return {"raw": payload}
        return payload
