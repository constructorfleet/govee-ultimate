"""Tests for the AWS IoT MQTT client wrapper."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest


class FakeSSLContext:
    """Capture TLS configuration applied to the MQTT connection."""

    def __init__(self) -> None:
        """Initialise fake TLS storage."""
        self.ca_data: str | None = None
        self.cert_chain: tuple[str, str] | None = None

    def load_verify_locations(self, *, cadata: str) -> None:  # type: ignore[override]
        """Record the certificate authority bundle."""
        self.ca_data = cadata

    def load_cert_chain(self, certfile: str, keyfile: str) -> None:  # type: ignore[override]
        """Capture the certificate/key material written to disk."""
        with open(certfile, encoding="utf-8") as cert_fp:
            certificate = cert_fp.read().strip()
        with open(keyfile, encoding="utf-8") as key_fp:
            private_key = key_fp.read().strip()
        self.cert_chain = (certificate, private_key)


class FakePahoClient:
    """Minimal stand-in for the Paho MQTT client."""

    def __init__(self, client_id: str, protocol: int | None = None) -> None:
        """Store client metadata for later inspection."""
        self.client_id = client_id
        self.protocol = protocol
        self.tls_context: FakeSSLContext | None = None
        self.connected: bool = False
        self.subscriptions: list[tuple[str, int]] = []
        self.published: list[tuple[str, str, int, bool]] = []
        self.on_connect: Callable[..., None] | None = None
        self.on_message: Callable[..., None] | None = None

    def tls_set_context(self, context: FakeSSLContext) -> None:
        """Attach the TLS context used when establishing a connection."""
        self.tls_context = context

    def username_pw_set(
        self, username: str | None = None, password: str | None = None
    ) -> None:  # noqa: ARG002
        """Paho compatibility shim for username/password authentication."""

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        """Record asynchronous connection details."""
        self.connected = True
        self._connect_args = (host, port, keepalive)

    def loop_start(self) -> None:
        """Simulate starting the network loop and invoking callbacks."""
        if self.on_connect:
            self.on_connect(self, None, None, 0)

    def subscribe(self, topic: str, qos: int) -> None:
        """Capture subscription requests."""
        self.subscriptions.append((topic, qos))

    def message_callback_add(self, topic: str, callback: Callable[..., None]) -> None:
        """Register the message handler for ``topic``."""
        self.on_message = callback

    def publish(self, topic: str, payload: str, qos: int, retain: bool) -> None:
        """Record published messages for assertions."""
        self.published.append((topic, payload, qos, retain))

    def disconnect(self) -> None:
        """Flag the MQTT client as disconnected."""
        self.connected = False


class FakeMonotonic:
    """Deterministic monotonic clock for TTL calculations."""

    def __init__(self, value: float = 0.0) -> None:
        """Initialise the fake clock with ``value`` seconds."""
        self.value = value

    def __call__(self) -> float:
        """Return the current monotonic reading."""
        return self.value


def _make_config(**overrides: Any) -> Any:
    """Build an ``IoTClientConfig`` with standard defaults for tests."""

    from custom_components.govee.iot_client import IoTClientConfig

    base: dict[str, Any] = {
        "endpoint": "ssl://broker.example:8883",
        "account_topic": "accounts/123",
        "client_id": "account-client",
        "certificate": "-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----",
        "private_key": "-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----",
        "command_ttl": timedelta(seconds=30),
        "qos": 1,
    }
    base.update(overrides)
    return IoTClientConfig(**base)


@pytest.fixture(autouse=True)
def _patch_paho(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the IoT client under test receives the fake MQTT delegate."""

    monkeypatch.setitem(ssl._PROTOCOL_NAMES, ssl.PROTOCOL_TLS_CLIENT, "TLS")

    def _fake_ssl_context(ca: str) -> FakeSSLContext:
        context = FakeSSLContext()
        context.load_verify_locations(cadata=ca)
        return context

    monkeypatch.setattr(
        "custom_components.govee.iot_client._create_ssl_context",
        _fake_ssl_context,
    )

    def _fake_client_factory(client_id: str) -> FakePahoClient:
        return FakePahoClient(client_id)

    monkeypatch.setattr(
        "custom_components.govee.iot_client._create_paho_client",
        _fake_client_factory,
    )


@pytest.mark.asyncio
async def test_iot_client_connects_with_tls_and_subscribes(
    monkeypatch: pytest.MonkeyPatch, _patch_paho: None
) -> None:
    """Client should configure TLS and subscribe to the account topic."""

    monkeypatch.setattr(
        "custom_components.govee.iot_client._load_amazon_root_ca",
        lambda: "FAKE-CA",
    )

    from custom_components.govee.iot_client import IoTClient

    updates: list[tuple[str, dict[str, Any]]] = []

    client = IoTClient(
        config=_make_config(),
        on_device_update=updates.append,
    )

    await client.async_start()

    assert client._mqtt_client is not None
    fake_client: FakePahoClient = client._mqtt_client  # type: ignore[assignment]
    assert fake_client.client_id == "account-client"
    assert fake_client.subscriptions == [("accounts/123", 1)]
    assert fake_client.tls_context is not None
    assert fake_client.tls_context.ca_data == "FAKE-CA"
    assert fake_client.tls_context.cert_chain is not None
    assert updates == []


@pytest.mark.asyncio
async def test_state_messages_forward_device_payload(
    monkeypatch: pytest.MonkeyPatch, _patch_paho: None
) -> None:
    """Incoming MQTT messages should be parsed and forwarded to the callback."""

    monkeypatch.setattr(
        "custom_components.govee.iot_client._load_amazon_root_ca",
        lambda: "FAKE-CA",
    )

    from custom_components.govee.iot_client import IoTClient

    updates: list[tuple[str, dict[str, Any]]] = []

    client = IoTClient(
        config=_make_config(),
        on_device_update=updates.append,
    )

    await client.async_start()
    fake_client: FakePahoClient = client._mqtt_client  # type: ignore[assignment]
    assert fake_client.on_message is not None
    fake_client.on_message(
        fake_client,
        None,
        type(
            "Payload",
            (),
            {"payload": b'{"device":"device-42","state":{"connected":true}}'},
        )(),
    )
    await asyncio.sleep(0)

    assert updates == [
        ("device-42", {"device": "device-42", "state": {"connected": True}})
    ]


@pytest.mark.asyncio
async def test_publish_command_serialises_payload_and_tracks_pending(
    monkeypatch: pytest.MonkeyPatch,
    _patch_paho: None,
) -> None:
    """Commands should include generated identifiers and track TTL expiry."""

    monkeypatch.setattr(
        "custom_components.govee.iot_client._load_amazon_root_ca",
        lambda: "FAKE-CA",
    )

    from custom_components.govee.iot_client import IoTClient

    clock = FakeMonotonic(10.0)
    client = IoTClient(
        config=_make_config(),
        on_device_update=lambda *_: None,
        monotonic=clock,
    )

    await client.async_start()
    command_id = await client.async_publish_command(
        "devices/device-42/command",
        {"cmd": "turn", "value": 1},
    )

    fake_client: FakePahoClient = client._mqtt_client  # type: ignore[assignment]
    assert fake_client.published[0][0] == "devices/device-42/command"
    assert command_id in client.pending_commands


@pytest.mark.asyncio
async def test_refresh_requests_publish_expected_payload(
    monkeypatch: pytest.MonkeyPatch, _patch_paho: None
) -> None:
    """Refresh requests should publish the AWS IoT message body."""

    monkeypatch.setattr(
        "custom_components.govee.iot_client._load_amazon_root_ca",
        lambda: "FAKE-CA",
    )

    from custom_components.govee.iot_client import IoTClient

    client = IoTClient(
        config=_make_config(),
        on_device_update=lambda *_: None,
    )

    await client.async_start()
    await client.async_request_refresh("devices/device-42/refresh")

    fake_client: FakePahoClient = client._mqtt_client  # type: ignore[assignment]
    topic, payload, qos, retain = fake_client.published[-1]
    assert topic == "devices/device-42/refresh"
    assert qos == 1
    assert retain is False
    assert "cmd" in payload


def test_expire_pending_commands_drops_stale_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired entries should be pruned when the TTL elapses."""

    monkeypatch.setattr(
        "custom_components.govee.iot_client._load_amazon_root_ca",
        lambda: "FAKE-CA",
    )

    from custom_components.govee.iot_client import IoTClient

    clock = FakeMonotonic(50.0)
    client = IoTClient(
        config=_make_config(command_ttl=timedelta(seconds=5)),
        on_device_update=lambda *_: None,
        monotonic=clock,
    )

    pending_id = client._track_command("cmd-id")
    clock.value = 60.0
    expired = client.expire_pending_commands()

    assert expired == [pending_id]
    assert client.pending_commands == {}
