"""Tests for the Home Assistant compatible IoT MQTT client."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import pytest

from custom_components.govee_ultimate.iot_client import IoTClient, IoTClientConfig


class FakeSubscriptionHandle:
    """Record unsubscribe calls triggered by the IoT client."""

    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.cancelled = False

    def __call__(self) -> None:
        self.cancelled = True


@dataclass
class RecordedSubscription:
    """Represent a captured MQTT subscription request."""

    topic: str
    callback: Callable[[str, bytes], Awaitable[None]]
    qos: int
    handle: FakeSubscriptionHandle


class FakeMQTT:
    """Minimal MQTT client double capturing subscribe calls."""

    def __init__(self) -> None:
        self.subscriptions: list[RecordedSubscription] = []
        self.publishes: list[tuple[str, bytes, int, bool]] = []

    async def async_subscribe(
        self,
        topic: str,
        callback: Callable[[str, bytes], Awaitable[None]],
        qos: int = 0,
    ) -> FakeSubscriptionHandle:
        handle = FakeSubscriptionHandle(topic)
        self.subscriptions.append(RecordedSubscription(topic, callback, qos, handle))
        return handle

    async def async_publish(
        self,
        topic: str,
        payload: bytes,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        self.publishes.append((topic, payload, qos, retain))


@pytest.mark.asyncio
async def test_async_connect_subscribes_to_all_topics() -> None:
    """Connecting should subscribe to every configured topic."""

    mqtt = FakeMQTT()
    config = IoTClientConfig(
        broker="mqtt://example.amazonaws.com",
        port=8883,
        username="test-user",
        password="top-secret",
        topics=["govee/state/#", "govee/command/ack"],
        command_expiry=timedelta(seconds=30),
    )
    received: list[tuple[str, bytes]] = []

    async def handle(topic: str, payload: bytes) -> None:
        received.append((topic, payload))

    client = IoTClient(mqtt=mqtt)

    await client.async_configure(config)
    await client.async_connect(handle)

    assert [subscription.topic for subscription in mqtt.subscriptions] == config.topics

    callback = mqtt.subscriptions[0].callback
    await callback("govee/state/device-1", b"{}")
    assert received == [("govee/state/device-1", b"{}")]


@pytest.mark.asyncio
async def test_publish_command_tracks_and_expires_requests() -> None:
    """Publishing a command should track expiry and prune at timeout."""

    mqtt = FakeMQTT()
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def time_source() -> datetime:
        return now

    config = IoTClientConfig(
        broker="mqtt://example.amazonaws.com",
        port=8883,
        username="test-user",
        password="top-secret",
        topics=["govee/state/#"],
        command_expiry=timedelta(seconds=30),
    )

    client = IoTClient(mqtt=mqtt, time_source=time_source)
    await client.async_configure(config)

    await client.async_publish_command(
        topic="govee/command/device-1",
        payload=b"{\"on\": true}",
        command_id="cmd-123",
    )

    assert mqtt.publishes == [
        ("govee/command/device-1", b"{\"on\": true}", 1, False)
    ]
    assert client.is_command_pending("cmd-123")

    now = now + timedelta(seconds=31)
    client.expire_pending_commands()
    assert not client.is_command_pending("cmd-123")
