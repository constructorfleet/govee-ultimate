"""LAN discovery and command helpers for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_DEFAULT_SCAN_PORT = 4001
_DEFAULT_COMMAND_PORT = 4003
_DEFAULT_BROADCAST_ADDRESS = "239.255.255.250"
_SCAN_COMMAND = {
    "msg": {
        "cmd": "scan",
        "data": {
            "account_topic": "reserve",
        },
    }
}


@dataclass(slots=True)
class LanDiscoveryResult:
    """Represent a device discovered via LAN broadcast."""

    device: str
    ip: str | None
    model: str | None
    mac: str | None
    data: dict[str, Any]


class GoveeLanClient:
    """Async UDP helper used for LAN scanning and command dispatch."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        command_port: int = _DEFAULT_COMMAND_PORT,
        scan_port: int = _DEFAULT_SCAN_PORT,
        broadcast_address: str = _DEFAULT_BROADCAST_ADDRESS,
        broadcast_interface: str | None = None,
    ) -> None:
        """Create the LAN client with network configuration options."""

        self._loop = loop or asyncio.get_event_loop()
        self._command_port = command_port
        self._scan_port = scan_port
        self._broadcast_address = broadcast_address
        self._broadcast_interface = broadcast_interface
        self._listen_task: asyncio.Task[Any] | None = None
        self._socket: asyncio.DatagramTransport | None = None
        self._protocol: asyncio.DatagramProtocol | None = None
        self._results: list[LanDiscoveryResult] = []
        self._lock = asyncio.Lock()

    async def async_start(self) -> None:
        """Bind the UDP socket used for discovery."""

        loop = self._loop

        class _Protocol(asyncio.DatagramProtocol):
            def __init__(self, outer: GoveeLanClient) -> None:
                self._outer = outer

            def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
                self._outer._handle_datagram(data, addr)

        async with self._lock:
            if self._socket is not None:
                return
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _Protocol(self),
                local_addr=("0.0.0.0", self._scan_port),
                reuse_port=True,
                allow_broadcast=True,
            )
            self._socket = transport
            self._protocol = protocol  # type: ignore[assignment]

    async def async_stop(self) -> None:
        """Close any open sockets."""

        async with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            self._protocol = None
            task = self._listen_task
            if task is not None:
                task.cancel()
                self._listen_task = None

    async def async_scan(self, timeout: float = 2.0) -> list[LanDiscoveryResult]:
        """Broadcast a scan command and return discovered devices."""

        await self.async_start()
        transport = self._socket
        if transport is None:
            return []

        message = json.dumps(_SCAN_COMMAND).encode("utf-8")
        try:
            transport.sendto(message, (self._broadcast_address, self._scan_port))
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.debug("LAN scan send failed: %s", exc)
            return []

        await asyncio.sleep(timeout)
        async with self._lock:
            results = list(self._results)
            self._results.clear()
        return results

    async def async_send_command(self, device_ip: str, command: dict[str, Any]) -> None:
        """Send a command to the specified device IP."""

        transport = self._socket
        if transport is None:
            await self.async_start()
            transport = self._socket
            if transport is None:
                raise RuntimeError("LAN transport not initialised")

        payload = json.dumps(command).encode("utf-8")
        try:
            transport.sendto(payload, (device_ip, self._command_port))
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.debug("Failed to send LAN command to %s: %s", device_ip, exc)
            raise

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Process UDP payloads emitted by LAN devices."""

        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        msg = payload.get("msg")
        if not isinstance(msg, dict):
            return
        cmd = msg.get("cmd")
        if cmd != "scan":
            return
        data_payload = msg.get("data", {})
        if not isinstance(data_payload, dict):
            return
        device = data_payload.get("device") or data_payload.get("device_id")
        if not isinstance(device, str):
            return
        model = data_payload.get("model")
        mac = data_payload.get("ble") or data_payload.get("mac")
        result = LanDiscoveryResult(
            device=device,
            ip=addr[0],
            model=model if isinstance(model, str) else None,
            mac=mac if isinstance(mac, str) else None,
            data=data_payload,
        )
        self._results.append(result)
