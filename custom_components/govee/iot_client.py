"""AWS IoT client used for account-level MQTT updates."""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse


try:  # pragma: no cover - prefer real MQTT client when available
    import paho.mqtt.client as _paho
except ImportError:  # pragma: no cover - patched in unit tests
    _paho = None  # type: ignore[assignment]


_AMAZON_CA_PATH = (
    Path(__file__).resolve().parents[2] / "lib" / "data" / "iot" / "iot.config.ts"
)


@dataclass(frozen=True, slots=True)
class IoTClientConfig:
    """Runtime configuration for the IoT client."""

    endpoint: str
    account_topic: str
    client_id: str
    certificate: str
    private_key: str
    qos: int = 1
    command_ttl: timedelta = timedelta(seconds=30)


def _load_amazon_root_ca() -> str:
    """Load the Amazon Root CA certificate bundled with the project."""

    contents = _AMAZON_CA_PATH.read_text(encoding="utf-8")
    start = contents.find("`-----BEGIN CERTIFICATE-----")
    end = contents.find("-----END CERTIFICATE-----`", start)
    if start == -1 or end == -1:
        raise ValueError("Amazon Root CA not found in iot.config.ts")
    certificate = contents[start + 1 : end + len("-----END CERTIFICATE-----")]
    return certificate.strip()


def _create_ssl_context(ca_certificate: str) -> ssl.SSLContext:
    """Create a TLS context configured with the Amazon root CA."""

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_verify_locations(cadata=ca_certificate)
    return context


def _apply_cert_chain(
    context: ssl.SSLContext, *, certificate: str, private_key: str
) -> None:
    """Load certificate material into ``context`` from in-memory values."""

    cert_file = tempfile.NamedTemporaryFile("w", delete=False)
    key_file = tempfile.NamedTemporaryFile("w", delete=False)
    try:
        cert_file.write(certificate.strip())
        cert_file.flush()
        key_file.write(private_key.strip())
        key_file.flush()
        context.load_cert_chain(certfile=cert_file.name, keyfile=key_file.name)
    finally:
        cert_file.close()
        key_file.close()
        os.unlink(cert_file.name)
        os.unlink(key_file.name)


def _create_paho_client(client_id: str) -> Any:
    """Instantiate a Paho MQTT client for the provided ``client_id``."""

    if _paho is None:  # pragma: no cover - dependency is optional in tests
        raise RuntimeError("paho-mqtt is required for IoT connectivity")
    return _paho.Client(client_id=client_id, protocol=getattr(_paho, "MQTTv311", 4))


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    """Extract host and port from an AWS IoT endpoint URI."""

    parsed = urlparse(endpoint)
    host = parsed.hostname or endpoint
    port = parsed.port or 8883
    return host, port


def _build_refresh_payload(account_topic: str) -> dict[str, Any]:
    """Create the refresh payload matching the TypeScript implementation."""

    return {
        "topic": account_topic,
        "msg": {
            "accountTopic": account_topic,
            "cmd": "status",
            "cmdVersion": 0,
            "transaction": _new_transaction(),
            "type": 0,
        },
    }


def _new_transaction() -> str:
    """Generate a transaction identifier compatible with the upstream service."""

    millis = int(time.time() * 1000)
    return f"u_{millis}"


class IoTClient:
    """Async wrapper around the AWS IoT MQTT connection."""

    def __init__(
        self,
        *,
        config: IoTClientConfig,
        on_device_update: Callable[[tuple[str, dict[str, Any]]], Any],
        logger: Any | None = None,
        monotonic: Callable[[], float] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Bind configuration and callbacks for MQTT handling."""

        self._config = config
        self._on_device_update = on_device_update
        self._logger = logger
        self._monotonic = monotonic or time.monotonic
        self._loop = loop or asyncio.get_event_loop()
        self._mqtt_client: Any | None = None
        self._device_filter: set[str] | None = None
        self._pending_commands: dict[str, float] = {}

    @property
    def pending_commands(self) -> dict[str, float]:
        """Return a copy of the pending command expiry mapping."""

        return dict(self._pending_commands)

    async def async_start(self, device_ids: Sequence[str] | None = None) -> None:
        """Establish the MQTT connection and subscribe to the account topic."""

        if self._mqtt_client is not None:
            return

        ca_certificate = _load_amazon_root_ca()
        context = _create_ssl_context(ca_certificate)
        _apply_cert_chain(
            context,
            certificate=self._config.certificate,
            private_key=self._config.private_key,
        )

        client = _create_paho_client(self._config.client_id)
        client.tls_set_context(context)
        client.on_connect = self._handle_connect
        client.on_message = self._handle_message
        client.message_callback_add(self._config.account_topic, self._handle_message)
        host, port = _parse_endpoint(self._config.endpoint)
        client.connect_async(host, port, keepalive=60)
        client.loop_start()

        self._device_filter = set(device_ids) if device_ids else None
        self._mqtt_client = client

    def set_update_callback(
        self, callback: Callable[[tuple[str, dict[str, Any]]], Any]
    ) -> None:
        """Replace the update callback used for device state notifications."""

        self._on_device_update = callback

    def _handle_connect(
        self, client: Any, _userdata: Any, _flags: Any, rc: int
    ) -> None:
        """Subscribe to the account topic once the connection succeeds."""

        if rc != 0:
            if self._logger is not None:
                self._logger.error("IoT connection failed with code %s", rc)
            return
        client.subscribe(self._config.account_topic, self._config.qos)

    def _handle_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        """Process incoming MQTT messages on the account topic."""

        try:
            payload = self._decode_payload(message.payload)
        except Exception:  # pragma: no cover - defensive parsing
            if self._logger is not None:
                self._logger.exception("Failed to decode IoT payload")
            return

        device_id = self._extract_device_id(payload)
        if device_id is None:
            return
        if self._device_filter and device_id not in self._device_filter:
            return

        self._loop.call_soon_threadsafe(self._emit_update, device_id, payload)

    @staticmethod
    def _extract_device_id(payload: dict[str, Any]) -> str | None:
        """Extract a device identifier from the IoT payload."""

        if "device" in payload and isinstance(payload["device"], str):
            return payload["device"]
        if "deviceId" in payload and isinstance(payload["deviceId"], str):
            return payload["deviceId"]
        return None

    def _emit_update(self, device_id: str, payload: dict[str, Any]) -> None:
        """Dispatch updates to the registered callback."""

        self._on_device_update((device_id, payload))

    def expire_pending_commands(self) -> list[str]:
        """Remove expired commands and return their identifiers."""

        now = self._monotonic()
        expired = [
            command_id
            for command_id, expiry in list(self._pending_commands.items())
            if expiry <= now
        ]
        for command_id in expired:
            self._pending_commands.pop(command_id, None)
        if expired and self._logger is not None:
            self._logger.debug("Expired IoT commands: %s", expired)
        return expired

    def _track_command(self, command_id: str) -> str:
        """Track ``command_id`` for expiry management in tests."""

        expires_at = self._monotonic() + self._config.command_ttl.total_seconds()
        self._pending_commands[command_id] = expires_at
        return command_id

    async def async_publish_command(
        self, topic: str, payload: dict[str, Any], *, retain: bool = False
    ) -> str:
        """Publish a command message to ``topic`` and track expiry."""

        if self._mqtt_client is None:
            raise RuntimeError("IoT client is not connected")

        command_id = payload.get("command_id") or uuid.uuid4().hex
        message = self._build_command_message(topic, payload, command_id)
        expires_at = self._monotonic() + self._config.command_ttl.total_seconds()
        self._pending_commands[command_id] = expires_at
        self._mqtt_client.publish(
            topic,
            json.dumps(message),
            qos=self._config.qos,
            retain=retain,
        )
        return command_id

    def _build_command_message(
        self, topic: str, payload: dict[str, Any], command_id: str
    ) -> dict[str, Any]:
        """Create a command payload matching the upstream IoT contract."""

        if "topic" in payload and "msg" in payload:
            message = json.loads(json.dumps(payload))
        else:
            message = {
                "topic": topic,
                "msg": {
                    "accountTopic": self._config.account_topic,
                    "cmd": payload.get("cmd") or "ptReal",
                    "cmdVersion": payload.get("cmdVersion")
                    or payload.get("cmd_version", 0),
                    "data": payload.get("data", payload),
                    "transaction": _new_transaction(),
                    "type": payload.get("type", 1),
                },
            }
        msg = message.setdefault("msg", {})
        if isinstance(msg, dict):
            msg.setdefault("accountTopic", self._config.account_topic)
            msg.setdefault("transaction", _new_transaction())
        message.setdefault("topic", topic)
        message.setdefault("commandId", command_id)
        return message

    async def async_request_refresh(self, topic: str) -> None:
        """Publish a refresh request to ``topic``."""

        if self._mqtt_client is None:
            raise RuntimeError("IoT client is not connected")

        payload = _build_refresh_payload(self._config.account_topic)
        payload["topic"] = topic
        self._mqtt_client.publish(
            topic,
            json.dumps(payload),
            qos=self._config.qos,
            retain=False,
        )

    def _decode_payload(self, payload: bytes | bytearray | str) -> dict[str, Any]:
        """Decode a JSON payload from the MQTT broker."""

        if isinstance(payload, (bytes, bytearray)):
            text = payload.decode("utf-8")
        else:
            text = str(payload)
        decoded = json.loads(text)
        if not isinstance(decoded, dict):
            raise TypeError("IoT payload must be an object")
        return decoded

    async def async_stop(self) -> None:
        """Disconnect the MQTT client and stop the network loop."""

        if self._mqtt_client is None:
            return
        client = self._mqtt_client
        self._mqtt_client = None
        client.loop_stop()
        client.disconnect()
