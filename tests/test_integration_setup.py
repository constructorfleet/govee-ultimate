"""Tests for integration setup and teardown lifecycle."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

if "httpx" not in sys.modules:
    httpx_module = ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401 - stub
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class _HTTPError(Exception):
        """Fallback HTTP error used by the auth module."""

    httpx_module.AsyncClient = _AsyncClient
    httpx_module.HTTPError = _HTTPError
    httpx_module.Timeout = Exception  # type: ignore[attr-defined]
    sys.modules["httpx"] = httpx_module

if "homeassistant.helpers.update_coordinator" not in sys.modules:
    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    class _DataUpdateCoordinator:  # pragma: no cover - simple stub
        def __init__(self, hass: Any, logger: Any, name: str | None = None, update_interval: Any | None = None) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval

    coordinator_module.DataUpdateCoordinator = _DataUpdateCoordinator
    helpers_module.update_coordinator = coordinator_module
    homeassistant_module.helpers = helpers_module

    sys.modules.setdefault("homeassistant", homeassistant_module)
    sys.modules.setdefault("homeassistant.helpers", helpers_module)
    sys.modules.setdefault("homeassistant.helpers.update_coordinator", coordinator_module)

import custom_components.govee_ultimate as integration
from custom_components.govee_ultimate import DOMAIN


class FakeHass:
    """Lightweight Home Assistant test double."""

    def __init__(self, *, config_dir: str) -> None:
        """Document stub Home Assistant initialization."""

        self.data: dict[str, Any] = {}
        self.loop = asyncio.get_event_loop()
        self.config = SimpleNamespace(config_dir=config_dir)
        self.config_entries = SimpleNamespace(
            async_forward_entry_setups=self._capture_forward,
            async_unload_platforms=self._capture_unload,
        )
        self.forwarded: list[tuple[Any, tuple[str, ...]]] = []
        self.unloaded: list[tuple[Any, tuple[str, ...]]] = []

    async def _capture_forward(
        self, entry: Any, platforms: tuple[str, ...]
    ) -> None:
        self.forwarded.append((entry, platforms))

    async def _capture_unload(
        self, entry: Any, platforms: tuple[str, ...]
    ) -> bool:
        self.unloaded.append((entry, platforms))
        return True

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        """Document stub executor job helper."""

        return func(*args)


class FakeConfigEntry:
    """Mimic the attributes used by the integration."""

    def __init__(self, *, entry_id: str, data: dict[str, Any]) -> None:
        """Document stub config entry initialization."""

        self.entry_id = entry_id
        self.data = data
        self.title = "Test"
        self.options: dict[str, Any] = {}

    async def async_unload(self) -> None:
        """Document stub unload coroutine."""

    async def async_setup(self) -> None:
        """Document stub setup coroutine."""


@pytest.mark.parametrize(
    ("target", "expected"),
    (
        (FakeHass.__init__, "Document stub Home Assistant initialization."),
        (FakeHass.async_add_executor_job, "Document stub executor job helper."),
        (FakeConfigEntry.__init__, "Document stub config entry initialization."),
        (FakeConfigEntry.async_unload, "Document stub unload coroutine."),
        (FakeConfigEntry.async_setup, "Document stub setup coroutine."),
    ),
    ids=(
        "hass_init",
        "hass_executor",
        "config_entry_init",
        "config_entry_unload",
        "config_entry_setup",
    ),
)
def test_fake_homeassistant_stubs_include_docstrings(
    target: Any, expected: str
) -> None:
    """Ensure the testing doubles expose docstrings for lint coverage."""

    assert target.__doc__ == expected


@pytest.mark.asyncio
async def test_async_setup_initializes_domain(
    tmp_path, tmp_path_factory, request
) -> None:
    """The top-level setup should register the integration domain storage."""

    hass = FakeHass(config_dir=str(tmp_path))

    assert await integration.async_setup(hass, {}) is True
    assert DOMAIN in hass.data
    assert hass.data[DOMAIN] == {}


@pytest.mark.asyncio
async def test_async_setup_entry_creates_coordinator_and_forwards(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """Setup entry should create the coordinator and forward platforms."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(
        entry_id="abc123",
        data={
            "email": "user@example.com",
            "password": "secret",
            "enable_iot": False,
            "enable_iot_state_updates": False,
            "enable_iot_commands": False,
            "enable_iot_refresh": False,
        },
    )

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class FakeAuth:
        def __init__(self, hass: Any, client: Any) -> None:
            self.hass = hass
            self.client = client
            self.initialized = False

        async def async_initialize(self) -> None:
            self.initialized = True

    class FakeApiClient:
        def __init__(self, hass: Any, client: Any, auth: Any) -> None:
            self.hass = hass
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.refreshed = False

        async def async_config_entry_first_refresh(self) -> None:
            self.refreshed = True

        def cancel_refresh(self) -> None:
            pass

    monkeypatch.setattr(
        integration, "httpx", SimpleNamespace(AsyncClient=FakeClient), raising=False
    )
    monkeypatch.setattr(
        integration, "_get_auth_class", lambda: FakeAuth, raising=False
    )
    monkeypatch.setattr(
        integration, "_get_device_client_class", lambda: FakeApiClient, raising=False
    )
    monkeypatch.setattr(
        integration, "_get_coordinator_class", lambda: FakeCoordinator, raising=False
    )
    async def _prepare_iot(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
        return None, False, False, False

    monkeypatch.setattr(
        integration,
        "_async_prepare_iot_runtime",
        _prepare_iot,
        raising=False,
    )

    assert await integration.async_setup_entry(hass, entry) is True

    stored = hass.data[DOMAIN][entry.entry_id]
    assert isinstance(stored["http_client"], FakeClient)
    assert isinstance(stored["coordinator"], FakeCoordinator)
    assert stored["coordinator"].refreshed is True
    assert hass.forwarded == [(entry, integration.PLATFORMS)]


@pytest.mark.asyncio
async def test_async_unload_entry_closes_resources(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """Unloading should forward teardown, cancel updates, and close clients."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(entry_id="entry", data={})

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    class FakeCoordinator:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel_refresh(self) -> None:
            self.cancelled = True

    class FakeIoTClient:
        def __init__(self) -> None:
            self.stopped = False

        async def async_stop(self) -> None:
            self.stopped = True

    client = FakeClient()
    coordinator = FakeCoordinator()
    iot_client = FakeIoTClient()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "http_client": client,
        "coordinator": coordinator,
        "api_client": object(),
        "auth": object(),
        "iot_client": iot_client,
    }

    monkeypatch.setattr(
        integration, "_async_stop_iot_client", lambda client: client.async_stop(), raising=False
    )

    assert await integration.async_unload_entry(hass, entry) is True

    assert hass.unloaded == [(entry, integration.PLATFORMS)]
    assert coordinator.cancelled is True
    assert client.closed is True
    assert iot_client.stopped is True
    assert DOMAIN not in hass.data


@pytest.mark.asyncio
async def test_async_setup_entry_enables_iot_client_when_requested(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """IoT configuration should provision the client and pass flags to the coordinator."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(
        entry_id="iot-entry",
        data={
            "email": "iot@example.com",
            "password": "secret",
            "enable_iot": True,
            "enable_iot_state_updates": True,
            "enable_iot_commands": True,
            "enable_iot_refresh": True,
        },
    )

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def aclose(self) -> None:
            pass

    class FakeAuth:
        async def async_initialize(self) -> None:
            pass

        def __init__(self, hass: Any, client: Any) -> None:
            self.hass = hass
            self.client = client

    class FakeApiClient:
        def __init__(self, hass: Any, client: Any, auth: Any) -> None:
            self.hass = hass
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def async_config_entry_first_refresh(self) -> None:
            pass

    class FakeIoTClient:
        pass

    monkeypatch.setattr(
        integration, "httpx", SimpleNamespace(AsyncClient=FakeClient), raising=False
    )
    monkeypatch.setattr(
        integration, "_get_auth_class", lambda: FakeAuth, raising=False
    )
    monkeypatch.setattr(
        integration, "_get_device_client_class", lambda: FakeApiClient, raising=False
    )
    monkeypatch.setattr(
        integration, "_get_coordinator_class", lambda: FakeCoordinator, raising=False
    )
    async def _prepare_iot_enabled(*args: Any, **kwargs: Any) -> tuple[Any, ...]:
        return FakeIoTClient(), True, True, True

    monkeypatch.setattr(
        integration,
        "_async_prepare_iot_runtime",
        _prepare_iot_enabled,
        raising=False,
    )

    assert await integration.async_setup_entry(hass, entry) is True
    stored = hass.data[DOMAIN][entry.entry_id]
    assert isinstance(stored["iot_client"], FakeIoTClient)
    coordinator = stored["coordinator"]
    assert coordinator.kwargs["iot_client"].__class__ is FakeIoTClient
    assert coordinator.kwargs["iot_state_enabled"] is True
    assert coordinator.kwargs["iot_command_enabled"] is True
    assert coordinator.kwargs["iot_refresh_enabled"] is True
