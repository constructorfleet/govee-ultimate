"""Integration-oriented tests for the IoT coordinator."""

from __future__ import annotations

from typing import Any

import logging
import pytest

from unittest.mock import ANY, AsyncMock


@pytest.mark.asyncio
async def test_coordinator_sends_command_when_enabled(
    caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest
) -> None:
    """Commands flow through the coordinator when toggles allow it."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=True,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=config,
        options=IotCoordinatorOptions(commands_enabled=True, refresh_enabled=True),
    )

    caplog.set_level(logging.DEBUG)
    await coordinator.async_start()
    command_id = await coordinator.async_send_device_command("device-1", {"turn": "on"})

    assert command_id is not None
    mqtt_client.async_subscribe.assert_any_call("govee/state", ANY)
    mqtt_client.async_subscribe.assert_any_call("govee/response", ANY)
    mqtt_client.async_publish.assert_awaited()
    assert "Publishing command" in caplog.text


@pytest.mark.asyncio
async def test_coordinator_respects_command_toggle() -> None:
    """Commands are not sent when the toggle is disabled."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=config,
        options=IotCoordinatorOptions(commands_enabled=False, refresh_enabled=True),
    )

    await coordinator.async_start()
    result = await coordinator.async_send_device_command("device-1", {"turn": "off"})

    assert result is None
    mqtt_client.async_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_updates_config_and_restarts_client() -> None:
    """Configuration updates tear down the client and apply new topics."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    initial_config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=initial_config,
        options=IotCoordinatorOptions(commands_enabled=True, refresh_enabled=True),
    )

    await coordinator.async_start()
    await coordinator.async_send_device_command("device-1", {"turn": "on"})

    mqtt_client.async_publish.reset_mock()
    new_config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state2",
        response_topic="govee/response2",
        command_topic="govee/command2",
        refresh_topic="govee/refresh2",
        expiry_seconds=5,
        log_debug=False,
    )

    await coordinator.async_update_config(new_config)
    await coordinator.async_send_device_command("device-1", {"turn": "on"})

    publish_args = mqtt_client.async_publish.await_args.args
    assert publish_args[0] == "govee/command2"


@pytest.mark.asyncio
async def test_coordinator_processes_expiry_with_custom_client() -> None:
    """Expiry handling is delegated to the IoT client."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import GoveeIotClient, IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    now = 0.0

    def time_source() -> float:
        return now

    def client_factory(
        hass: Any,
        mqtt: Any,
        config: IotMqttConfig,
        **kwargs: Any,
    ) -> GoveeIotClient:
        return GoveeIotClient(
            hass,
            mqtt,
            config,
            time_source=time_source,
            **kwargs,
        )

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=1,
        log_debug=False,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=config,
        options=IotCoordinatorOptions(commands_enabled=True, refresh_enabled=True),
        client_factory=client_factory,
    )

    await coordinator.async_start()
    command_id = await coordinator.async_send_device_command("device-1", {"turn": "on"})

    now += 2
    expired = await coordinator.async_process_expiry()

    assert [item.command_id for item in expired] == [command_id]


@pytest.mark.asyncio
async def test_coordinator_refresh_toggle_controls_requests() -> None:
    """Refresh requests respect the refresh toggle."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=config,
        options=IotCoordinatorOptions(commands_enabled=True, refresh_enabled=False),
    )

    await coordinator.async_start()
    await coordinator.async_request_device_refresh("device-1")

    mqtt_client.async_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_option_update_enables_commands() -> None:
    """Updating coordinator options toggles command publication."""

    from custom_components.govee_ultimate.coordinator import (
        GoveeIotCoordinator,
        IotCoordinatorOptions,
    )
    from custom_components.govee_ultimate.iot_client import IotMqttConfig

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    coordinator = GoveeIotCoordinator(
        hass,
        mqtt_client,
        config=config,
        options=IotCoordinatorOptions(commands_enabled=False, refresh_enabled=True),
    )

    await coordinator.async_start()
    await coordinator.async_send_device_command("device-1", {"turn": "on"})
    mqtt_client.async_publish.assert_not_awaited()

    await coordinator.async_update_config(
        config,
        options=IotCoordinatorOptions(commands_enabled=True, refresh_enabled=True),
    )

    await coordinator.async_send_device_command("device-1", {"turn": "off"})
    mqtt_client.async_publish.assert_awaited()
