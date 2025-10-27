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
        self.flow_calls: list[dict[str, Any]] = []
        self.flow_results: list[dict[str, Any]] = []
        self.config_entries.flow = SimpleNamespace(async_init=self._flow_async_init)
        self.tasks: list[Any] = []
        self.registered_services: dict[tuple[str, str], Any] = {}
        self.service_calls: list[dict[str, Any]] = []
        self.services = SimpleNamespace(
            async_register=self._register_service,
            async_remove=self._remove_service,
            async_call=self._async_call_service,
        )

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

    def async_create_task(self, coro: Any) -> Any:
        """Schedule a coroutine on the event loop immediately."""

        task = self.loop.create_task(coro)
        self.tasks.append(task)
        return task

    async def _flow_async_init(
        self,
        domain: str,
        *,
        context: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        call = {"domain": domain, "context": context, "data": data}
        self.flow_calls.append(call)
        if self.flow_results:
            return self.flow_results.pop(0)
        return {"type": "create_entry", "data": data or {}}

    def _register_service(self, domain: str, service: str, handler: Any) -> None:
        self.registered_services[(domain, service)] = handler

    def _remove_service(self, domain: str, service: str) -> None:
        self.registered_services.pop((domain, service), None)

    async def _async_call_service(
        self, domain: str, service: str, service_data: dict[str, Any] | None = None
    ) -> None:
        self.service_calls.append(
            {"domain": domain, "service": service, "data": service_data or {}}
        )
        handler = self.registered_services.get((domain, service))
        if handler is None:
            return
        call = SimpleNamespace(data=service_data or {})
        result = handler(call)
        if asyncio.iscoroutine(result):
            await result


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
            self.tokens = object()

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
async def test_async_setup_entry_uses_httpx_helper(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """The integration should rely on Home Assistant's HTTPX helper."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(entry_id="helper", data={})

    fake_client = object()

    class FakeAuth:
        def __init__(self, hass: Any, client: Any) -> None:
            self.hass = hass
            self.client = client
            self.initialized = False
            self.tokens = object()

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

        async def async_config_entry_first_refresh(self) -> None:
            pass

    calls: list[tuple[Any, ...]] = []

    def _get_async_client(hass_param: Any, /) -> Any:
        calls.append((hass_param,))
        return fake_client

    monkeypatch.setattr(
        integration,
        "_httpx_get_async_client",
        _get_async_client,
        raising=False,
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
    assert stored["http_client"] is fake_client
    auth = stored["auth"]
    assert isinstance(auth, FakeAuth)
    assert auth.initialized is True
    assert calls == [(hass,)]


@pytest.mark.asyncio
async def test_async_setup_entry_requests_tokens_when_missing(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """If initialization yields no tokens the setup should request credentials."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(
        entry_id="needs-tokens",
        data={"email": "configured@example.com", "password": "ignored"},
    )

    helper_module = ModuleType("homeassistant.helpers.httpx_client")
    helper_module.get_async_client = lambda hass_param: object()  # type: ignore[attr-defined]
    monkeypatch.setattr(integration, "httpx_client", helper_module, raising=False)

    class FakeTokens:
        pass

    issued_tokens = FakeTokens()

    class FakeAuth:
        def __init__(self, hass_param: Any, client: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.initialized = False
            self._tokens: FakeTokens | None = None
            self.login_calls: list[tuple[str, str]] = []

        async def async_initialize(self) -> None:
            self.initialized = True

        @property
        def tokens(self) -> FakeTokens | None:
            return self._tokens

        async def async_login(self, email: str, password: str) -> FakeTokens:
            self.login_calls.append((email, password))
            self._tokens = issued_tokens
            return issued_tokens

    class FakeApiClient:
        def __init__(self, hass_param: Any, client: Any, auth: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def async_config_entry_first_refresh(self) -> None:
            pass

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

    hass.flow_results.append(
        {"type": "create_entry", "data": {"email": "user@example.com", "password": "secret"}}
    )

    assert await integration.async_setup_entry(hass, entry) is True

    stored = hass.data[DOMAIN][entry.entry_id]
    auth = stored["auth"]
    assert isinstance(auth, FakeAuth)
    assert auth.login_calls == [("user@example.com", "secret")]
    assert stored["tokens"] is issued_tokens
    assert hass.flow_calls == [
        {
            "domain": DOMAIN,
            "context": {"source": "reauth", "entry_id": entry.entry_id},
            "data": {"email": "configured@example.com", "password": "ignored"},
        }
    ]


@pytest.mark.asyncio
async def test_async_setup_entry_schedules_token_refresh(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """Token refresh should be periodically scheduled and cancellable."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(entry_id="refresh", data={})

    helper_module = ModuleType("homeassistant.helpers.httpx_client")
    helper_module.get_async_client = lambda hass_param: object()  # type: ignore[attr-defined]
    monkeypatch.setattr(integration, "httpx_client", helper_module, raising=False)

    class FakeAuth:
        def __init__(self, hass_param: Any, client: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.initialized = False
            self._tokens = object()
            self.access_calls = 0

        async def async_initialize(self) -> None:
            self.initialized = True

        @property
        def tokens(self) -> object:
            return self._tokens

        async def async_get_access_token(self) -> str:
            self.access_calls += 1
            return "token"

    class FakeApiClient:
        def __init__(self, hass_param: Any, client: Any, auth: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def async_config_entry_first_refresh(self) -> None:
            pass

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

    scheduled: list[dict[str, Any]] = []

    def _fake_call_later(delay: float, callback: Any, *args: Any) -> Any:
        handle = SimpleNamespace(cancelled=False)

        def _cancel() -> None:
            handle.cancelled = True

        handle.cancel = _cancel  # type: ignore[attr-defined]
        scheduled.append({"delay": delay, "callback": callback, "args": args, "handle": handle})
        return handle

    monkeypatch.setattr(hass.loop, "call_later", _fake_call_later, raising=False)

    assert await integration.async_setup_entry(hass, entry) is True
    stored = hass.data[DOMAIN][entry.entry_id]
    cancel_refresh = stored.get("token_refresh_cancel")
    assert callable(cancel_refresh)
    assert scheduled and scheduled[0]["delay"] == integration.TOKEN_REFRESH_INTERVAL

    scheduled[0]["callback"](*scheduled[0]["args"])
    await asyncio.sleep(0)
    assert stored["auth"].access_calls == 1
    assert len(scheduled) >= 2

    await integration.async_unload_entry(hass, entry)
    assert scheduled[-1]["handle"].cancelled is True


@pytest.mark.asyncio
async def test_async_setup_entry_registers_reauth_service(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """The integration should expose a service to force reauthentication."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(entry_id="service", data={})

    helper_module = ModuleType("homeassistant.helpers.httpx_client")
    helper_module.get_async_client = lambda hass_param: object()  # type: ignore[attr-defined]
    monkeypatch.setattr(integration, "httpx_client", helper_module, raising=False)

    class FakeTokens:
        pass

    issued_tokens = FakeTokens()

    class FakeAuth:
        def __init__(self, hass_param: Any, client: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.initialized = False
            self._tokens: FakeTokens | None = issued_tokens
            self.login_calls: list[tuple[str, str]] = []

        async def async_initialize(self) -> None:
            self.initialized = True

        @property
        def tokens(self) -> FakeTokens | None:
            return self._tokens

        async def async_login(self, email: str, password: str) -> FakeTokens:
            self.login_calls.append((email, password))
            self._tokens = issued_tokens
            return issued_tokens

    class FakeApiClient:
        def __init__(self, hass_param: Any, client: Any, auth: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def async_config_entry_first_refresh(self) -> None:
            pass

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
    service_name = getattr(integration, "SERVICE_REAUTHENTICATE", "reauthenticate")
    assert (DOMAIN, service_name) in hass.registered_services

    hass.flow_results.append(
        {"type": "create_entry", "data": {"email": "service@example.com", "password": "servpass"}}
    )

    await hass.services.async_call(
        DOMAIN,
        service_name,
        {"entry_id": entry.entry_id},
    )

    stored = hass.data[DOMAIN][entry.entry_id]
    auth = stored["auth"]
    assert auth.login_calls == [("service@example.com", "servpass")]
    assert stored["tokens"] is issued_tokens


@pytest.mark.asyncio
async def test_token_refresh_http_error_triggers_reauth(
    tmp_path, tmp_path_factory, request, monkeypatch
):
    """HTTP errors during refresh should prompt a reauthentication flow."""

    hass = FakeHass(config_dir=str(tmp_path))
    entry = FakeConfigEntry(
        entry_id="error",
        data={"email": "stored@example.com", "password": "stored"},
    )

    class FakeHTTPError(Exception):
        pass

    monkeypatch.setattr(
        integration,
        "httpx",
        SimpleNamespace(HTTPError=FakeHTTPError),
        raising=False,
    )

    helper_module = ModuleType("homeassistant.helpers.httpx_client")
    helper_module.get_async_client = lambda hass_param: object()  # type: ignore[attr-defined]
    monkeypatch.setattr(integration, "httpx_client", helper_module, raising=False)

    class FakeTokens:
        pass

    reissued_tokens = FakeTokens()

    class FakeAuth:
        def __init__(self, hass_param: Any, client: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.initialized = False
            self._tokens: FakeTokens | None = FakeTokens()
            self.login_calls: list[tuple[str, str]] = []
            self.access_attempts = 0

        async def async_initialize(self) -> None:
            self.initialized = True

        @property
        def tokens(self) -> FakeTokens | None:
            return self._tokens

        async def async_get_access_token(self) -> str:
            self.access_attempts += 1
            raise FakeHTTPError()

        async def async_login(self, email: str, password: str) -> FakeTokens:
            self.login_calls.append((email, password))
            self._tokens = reissued_tokens
            return reissued_tokens

    class FakeApiClient:
        def __init__(self, hass_param: Any, client: Any, auth: Any) -> None:
            self.hass = hass_param
            self.client = client
            self.auth = auth

    class FakeCoordinator:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def async_config_entry_first_refresh(self) -> None:
            pass

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

    scheduled: list[dict[str, Any]] = []

    def _fake_call_later(delay: float, callback: Any, *args: Any) -> Any:
        handle = SimpleNamespace(cancelled=False)

        def _cancel() -> None:
            handle.cancelled = True

        handle.cancel = _cancel  # type: ignore[attr-defined]
        scheduled.append({"delay": delay, "callback": callback, "args": args, "handle": handle})
        return handle

    monkeypatch.setattr(hass.loop, "call_later", _fake_call_later, raising=False)

    hass.flow_results.append(
        {"type": "create_entry", "data": {"email": "refresh@example.com", "password": "newpass"}}
    )

    assert await integration.async_setup_entry(hass, entry) is True
    stored = hass.data[DOMAIN][entry.entry_id]

    scheduled[0]["callback"](*scheduled[0]["args"])
    await asyncio.sleep(0)

    assert stored["auth"].login_calls == [("refresh@example.com", "newpass")]
    assert stored["tokens"] is reissued_tokens


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
