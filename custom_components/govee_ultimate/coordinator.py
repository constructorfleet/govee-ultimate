"""Coordinator glue between Home Assistant and the IoT MQTT client."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any
from collections.abc import Awaitable, Callable

try:  # pragma: no cover - optional during unit testing
    from homeassistant.core import HomeAssistant
except ImportError:  # pragma: no cover - fallback for isolated test runs
    HomeAssistant = Any  # type: ignore[misc,assignment]

from .iot_client import GoveeIotClient, IotMqttConfig, PendingCommand

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
ExpiryHandler = Callable[[PendingCommand], Awaitable[None]]


@dataclass(slots=True)
class IotCoordinatorOptions:
    """Runtime toggles controlling how the coordinator uses MQTT."""

    commands_enabled: bool = True
    refresh_enabled: bool = True


class GoveeIotCoordinator:
    """Facade responsible for routing state through the IoT client."""

    def __init__(
        self,
        hass: HomeAssistant,
        mqtt_client: Any,
        *,
        config: IotMqttConfig,
        options: IotCoordinatorOptions | None = None,
        on_state_message: MessageHandler | None = None,
        on_command_response: MessageHandler | None = None,
        on_command_expired: ExpiryHandler | None = None,
        client_factory: Callable[..., GoveeIotClient] = GoveeIotClient,
        logger: logging.Logger | None = None,
    ) -> None:
        """Bind Home Assistant context, MQTT interface, and callbacks."""

        self._hass = hass
        self._mqtt_client = mqtt_client
        self._config = config
        self._options = options or IotCoordinatorOptions()
        self._on_state_message = on_state_message
        self._on_command_response = on_command_response
        self._on_command_expired = on_command_expired
        self._client_factory = client_factory
        self._logger = logger or logging.getLogger(__name__)
        self._client: GoveeIotClient | None = None

    async def async_start(self) -> None:
        """Establish MQTT subscriptions when enabled."""

        await self._ensure_client()

    async def async_stop(self) -> None:
        """Disconnect from MQTT and tear down subscriptions."""

        if self._client is not None:
            await self._client.async_disconnect()
            self._client = None

    async def async_send_device_command(
        self, device_id: str, payload: dict[str, Any]
    ) -> str | None:
        """Publish a device command if toggles allow it."""

        if not self._config.enabled:
            self._log_skip("IoT channel disabled", device_id, "command")
            return None
        if not self._options.commands_enabled:
            self._log_skip("Command publishing disabled", device_id, "command")
            return None
        client = await self._ensure_client()
        if client is None:
            return None
        command_id = await client.async_send_command(device_id, payload)
        if self._config.log_debug:
            self._logger.debug("Publishing command %s for %s", command_id, device_id)
        return command_id

    async def async_request_device_refresh(self, device_id: str) -> bool:
        """Request a device refresh through the MQTT channel."""

        if not self._config.enabled:
            self._log_skip("IoT channel disabled", device_id, "refresh")
            return False
        if not self._options.refresh_enabled:
            self._log_skip("Refresh publishing disabled", device_id, "refresh")
            return False
        client = await self._ensure_client()
        if client is None:
            return False
        await client.async_request_refresh(device_id)
        if self._config.log_debug:
            self._logger.debug("Publishing refresh request for %s", device_id)
        return True

    async def async_process_expiry(self) -> list[PendingCommand]:
        """Expire pending commands via the client."""

        if self._client is None:
            return []
        expired = await self._client.async_expire_commands()
        if expired and self._config.log_debug:
            ids = ", ".join(command.command_id for command in expired)
            self._logger.debug("Expired commands: %s", ids)
        return expired

    async def async_update_config(
        self,
        config: IotMqttConfig,
        options: IotCoordinatorOptions | None = None,
    ) -> None:
        """Apply new MQTT configuration and toggles."""

        updated_options = options or self._options
        config_changed = config != self._config
        options_changed = updated_options != self._options
        self._config = config
        self._options = updated_options
        if not config_changed and not options_changed:
            return
        await self.async_stop()
        await self.async_start()

    async def _ensure_client(self) -> GoveeIotClient | None:
        """Create and connect a client if necessary."""

        if not self._config.enabled:
            return None
        if self._client is None:
            self._client = self._client_factory(
                self._hass,
                self._mqtt_client,
                self._config,
                on_state_message=self._on_state_message,
                on_command_response=self._on_command_response,
                on_command_expired=self._on_command_expired,
            )
            await self._client.async_connect()
        return self._client

    def _log_skip(self, reason: str, device_id: str, action: str) -> None:
        """Emit a debug log describing why a publish was skipped."""

        self._logger.debug("%s; skipping %s for %s", reason, action, device_id)
