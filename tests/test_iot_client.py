"""Tests for the Home Assistant facing IoT MQTT client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import asyncio
from typing import Any

import pytest

import json

from unittest.mock import ANY, AsyncMock


@pytest.mark.asyncio
async def test_client_connects_and_subscribes_to_topics() -> None:
    """The client subscribes to configured topics and dispatches callbacks."""

    from custom_components.govee_ultimate.iot_client import (
        GoveeIotClient,
        IotMqttConfig,
    )

    hass: Any = object()

    unsub = AsyncMock()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=unsub)

    received_state: asyncio.Event = asyncio.Event()
    received_response: asyncio.Event = asyncio.Event()

    async def handle_state(payload: dict[str, Any]) -> None:
        received_state.set()

    async def handle_response(payload: dict[str, Any]) -> None:
        received_response.set()

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    client = GoveeIotClient(
        hass,
        mqtt_client,
        config,
        on_state_message=handle_state,
        on_command_response=handle_response,
    )

    await client.async_connect()

    mqtt_client.async_subscribe.assert_any_call("govee/state", ANY)
    mqtt_client.async_subscribe.assert_any_call("govee/response", ANY)

    state_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] = (
        mqtt_client.async_subscribe.call_args_list[0].args[1]
    )
    response_callback: Callable[[str, str, dict[str, Any]], Awaitable[None]] = (
        mqtt_client.async_subscribe.call_args_list[1].args[1]
    )

    await state_callback("govee/state", "state payload", {})
    await response_callback("govee/response", "response payload", {})

    assert received_state.is_set()
    assert received_response.is_set()


@pytest.mark.asyncio
async def test_send_command_publishes_and_tracks_expiry() -> None:
    """Commands are published via MQTT and tracked until expiry."""

    from custom_components.govee_ultimate.iot_client import (
        GoveeIotClient,
        IotMqttConfig,
    )

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    now = 100.0

    def time_source() -> float:
        return now

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=7,
        log_debug=False,
    )

    client = GoveeIotClient(
        hass,
        mqtt_client,
        config,
        time_source=time_source,
    )

    await client.async_connect()

    command_id = await client.async_send_command("device-1", {"turn": "on"})

    mqtt_client.async_publish.assert_awaited_once()
    topic, payload = mqtt_client.async_publish.await_args.args
    kwargs = mqtt_client.async_publish.await_args.kwargs
    assert topic == "govee/command"
    assert json.loads(payload)["cmdId"] == command_id
    assert kwargs == {}

    pending = client.pending_commands
    assert command_id in pending
    assert pending[command_id].expires_at == pytest.approx(now + config.expiry_seconds)


@pytest.mark.asyncio
async def test_response_acknowledgement_clears_pending_commands() -> None:
    """Command acknowledgements remove pending entries and notify callbacks."""

    from custom_components.govee_ultimate.iot_client import (
        GoveeIotClient,
        IotMqttConfig,
    )

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    responses: list[dict[str, Any]] = []

    async def handle_response(payload: dict[str, Any]) -> None:
        responses.append(payload)

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=5,
        log_debug=False,
    )

    client = GoveeIotClient(
        hass,
        mqtt_client,
        config,
        on_command_response=handle_response,
    )

    await client.async_connect()
    command_id = await client.async_send_command("device-1", {"turn": "on"})

    response_callback = mqtt_client.async_subscribe.call_args_list[1].args[1]
    message = json.dumps({"cmdId": command_id, "status": "ok"})
    await response_callback("govee/response", message, {})

    assert command_id not in client.pending_commands
    assert responses[0]["cmdId"] == command_id


@pytest.mark.asyncio
async def test_request_refresh_publishes_refresh_topic() -> None:
    """Device refresh requests publish to the dedicated topic."""

    from custom_components.govee_ultimate.iot_client import (
        GoveeIotClient,
        IotMqttConfig,
    )

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

    client = GoveeIotClient(hass, mqtt_client, config)
    await client.async_connect()

    await client.async_request_refresh("device-2")

    mqtt_client.async_publish.assert_called_with("govee/refresh", json.dumps({"device": "device-2"}))


@pytest.mark.asyncio
async def test_expire_pending_commands_removes_entries() -> None:
    """Expired commands are pruned and callbacks notified."""

    from custom_components.govee_ultimate.iot_client import (
        GoveeIotClient,
        IotMqttConfig,
        PendingCommand,
    )

    hass: Any = object()
    mqtt_client = AsyncMock()
    mqtt_client.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt_client.async_publish = AsyncMock()

    now = 50.0

    def time_source() -> float:
        return now

    expired: list[PendingCommand] = []

    async def on_expired(command: PendingCommand) -> None:
        expired.append(command)

    config = IotMqttConfig(
        enabled=True,
        state_topic="govee/state",
        response_topic="govee/response",
        command_topic="govee/command",
        refresh_topic="govee/refresh",
        expiry_seconds=3,
        log_debug=False,
    )

    client = GoveeIotClient(
        hass,
        mqtt_client,
        config,
        time_source=time_source,
        on_command_expired=on_expired,
    )

    await client.async_connect()

    command_id = await client.async_send_command("device-1", {"turn": "off"})

    now += 1
    await client.async_expire_commands()
    assert command_id in client.pending_commands

    now += 5
    await client.async_expire_commands()

    assert command_id not in client.pending_commands
    assert [item.command_id for item in expired] == [command_id]
