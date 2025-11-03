"""OpenAPI channel helper used for MQTT-like device messaging."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


class GoveeOpenAPIClient:
    """Minimal async client mirroring the TypeScript OpenAPI channel behaviour."""

    def __init__(self) -> None:
        """Initialise the OpenAPI client stub."""

        self._callback: Callable[[dict[str, Any]], Any] | None = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._published: list[tuple[str, dict[str, Any]]] = []

    async def async_connect(self, api_key: str) -> None:
        """Connect to the OpenAPI backend using the provided API key."""

        _LOGGER.debug("Connecting to OpenAPI with key %s", api_key)
        async with self._lock:
            self._connected = True

    async def async_disconnect(self) -> None:
        """Disconnect the simulated client."""

        async with self._lock:
            self._connected = False

    def set_message_callback(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback invoked when device updates are received."""

        self._callback = callback

    async def async_publish(
        self, topic: str, payload: dict[str, Any], *, qos: int = 0
    ) -> None:
        """Record a published payload for test assertions."""

        if not self._connected:
            raise RuntimeError("OpenAPI client is not connected")
        self._published.append((topic, dict(payload)))

    def emit_message(self, payload: dict[str, Any]) -> None:
        """Emit an incoming message for testing purposes."""

        callback = self._callback
        if callback is None:
            return
        try:
            callback(payload)
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.debug("OpenAPI callback failure: %s", exc)

    @property
    def published(self) -> list[tuple[str, dict[str, Any]]]:
        """Expose published messages for tests."""

        return list(self._published)
