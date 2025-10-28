"""Tests for the Home Assistant MQTT IoT client wrapper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest


@dataclass
class FakeSubscription:
    """Record a subscription request against the fake MQTT client."""

    topic: str
    qos: int
    callback: Callable[[str, Any], Any]
    unsubscribed: bool = False


class FakeMQTT:
    """Minimal MQTT stub mimicking the Home Assistant helper API."""

    def __init__(self) -> None:
        """Initialise storage for subscriptions and publications."""

        self.subscriptions: list[FakeSubscription] = []
        self.published: list[tuple[str, str | bytes, int, bool]] = []

    async def async_subscribe(
        self,
        topic: str,
        callback: Callable[[str, Any], Any],
        qos: int = 0,
    ) -> Callable[[], None]:
        """Record a subscription request and return an unsubscribe hook."""

        subscription = FakeSubscription(topic, qos, callback)
        self.subscriptions.append(subscription)

        def _unsubscribe() -> None:
            subscription.unsubscribed = True

        return _unsubscribe

    async def async_publish(
        self,
        topic: str,
        payload: str | bytes,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """Capture a publish request for assertions."""

        self.published.append((topic, payload, qos, retain))


class FakeClock:
    """Simple monotonic clock controllable by tests."""

    def __init__(self, initial: float = 0.0) -> None:
        """Start the clock at ``initial`` seconds."""

        self.value = initial

    def __call__(self) -> float:
        """Return the current clock value."""

        return self.value


@pytest.mark.asyncio
async def test_iot_client_subscribes_to_state_topics_on_start() -> None:
    """Client should subscribe to each device state topic when started."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    updates: list[tuple[str, dict[str, Any]]] = []

    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="govee/state/{device_id}",
            command_topic="govee/command/{device_id}",
            refresh_topic="govee/refresh/{device_id}",
            qos=1,
            command_ttl=timedelta(seconds=30),
            debug=False,
        ),
        on_device_update=updates.append,
    )

    await client.async_start(["device-1", "device-2"])

    topics = [sub.topic for sub in mqtt.subscriptions]
    assert topics == [
        "govee/state/device-1",
        "govee/state/device-2",
    ]
    assert all(sub.qos == 1 for sub in mqtt.subscriptions)
    assert updates == []


@pytest.mark.asyncio
async def test_state_callback_deserialises_json_payload() -> None:
    """The state callback should JSON-decode payloads before forwarding."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    updates: list[tuple[str, dict[str, Any]]] = []

    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        on_device_update=updates.append,
    )

    await client.async_start(["device-3"])
    assert len(mqtt.subscriptions) == 1

    subscription = mqtt.subscriptions[0]
    subscription.callback(subscription.topic, '{"battery":80}')

    assert updates == [("device-3", {"battery": 80})]


@pytest.mark.asyncio
async def test_set_update_callback_replaces_listener() -> None:
    """The update callback should be replaceable at runtime."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    first: list[tuple[str, dict[str, Any]]] = []
    second: list[tuple[str, dict[str, Any]]] = []

    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        on_device_update=first.append,
    )

    await client.async_start(["device-4"])
    client.set_update_callback(second.append)

    subscription = mqtt.subscriptions[0]
    subscription.callback(subscription.topic, '{"online":true}')

    assert first == []
    assert second == [("device-4", {"online": True})]


@pytest.mark.asyncio
async def test_update_config_resubscribes_with_new_topics() -> None:
    """Configuration updates should adjust subscriptions accordingly."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        on_device_update=lambda update: None,
    )

    await client.async_start(["device-7"])
    first_sub = mqtt.subscriptions[0]

    await client.async_update_config(
        IoTClientConfig(
            enabled=True,
            state_topic="new/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=1,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        ["device-7"],
    )

    assert first_sub.unsubscribed is True
    assert mqtt.subscriptions[-1].topic == "new/device-7"


@pytest.mark.asyncio
async def test_update_config_disables_all_subscriptions() -> None:
    """Disabling the client should remove existing subscriptions."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        on_device_update=lambda update: None,
    )

    await client.async_start(["device-8"])
    first_sub = mqtt.subscriptions[0]

    await client.async_update_config(
        IoTClientConfig(
            enabled=False,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        ["device-8"],
    )

    assert first_sub.unsubscribed is True


@pytest.mark.asyncio
async def test_publish_command_serialises_payload_and_tracks_pending() -> None:
    """Client should publish commands with generated identifiers and TTL."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=10),
            debug=False,
        ),
        on_device_update=lambda update: None,
        monotonic=lambda: 100.0,
    )

    await client.async_start(["device-1"])

    command_id = await client.async_publish_command("device-1", {"power": True})

    assert mqtt.published == [
        (
            "command/device-1",
            '{"power": true, "command_id": "' + command_id + '"}',
            0,
            False,
        )
    ]
    assert client.pending_commands == {command_id: pytest.approx(110.0)}


@pytest.mark.asyncio
async def test_expire_pending_commands_returns_ids() -> None:
    """Expiry pruning should drop stale commands using the configured TTL."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    clock = FakeClock(25.0)
    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=0,
            command_ttl=timedelta(seconds=5),
            debug=False,
        ),
        on_device_update=lambda update: None,
        monotonic=clock,
    )

    await client.async_start(["device-1"])
    command_id = await client.async_publish_command("device-1", {"fan": "auto"})

    clock.value = 32.0
    expired = client.expire_pending_commands()

    assert expired == [command_id]
    assert client.pending_commands == {}


@pytest.mark.asyncio
async def test_request_refresh_publishes_to_refresh_topic() -> None:
    """Refresh requests should be published to the configured topic."""

    from custom_components.govee_ultimate.iot_client import (
        IoTClient,
        IoTClientConfig,
    )

    mqtt = FakeMQTT()
    client = IoTClient(
        mqtt=mqtt,
        config=IoTClientConfig(
            enabled=True,
            state_topic="state/{device_id}",
            command_topic="command/{device_id}",
            refresh_topic="refresh/{device_id}",
            qos=1,
            command_ttl=timedelta(seconds=10),
            debug=False,
        ),
        on_device_update=lambda update: None,
    )

    await client.async_start(["device-9"])
    await client.async_request_refresh("device-9")

    assert mqtt.published[-1] == ("refresh/device-9", "{}", 1, False)
