"""Integration entry point for the Govee Ultimate custom component."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

DOMAIN = "govee_ultimate"
PLATFORMS: tuple[str, ...] = (
    "light",
    "humidifier",
    "fan",
    "switch",
    "number",
    "sensor",
    "binary_sensor",
)

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]

def _ensure_event_loop() -> None:
    """Ensure a default asyncio event loop exists for synchronous tests."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


_ensure_event_loop()

_ORIGINAL_GET_EVENT_LOOP = asyncio.get_event_loop


def _patched_get_event_loop() -> asyncio.AbstractEventLoop:
    """Backport asyncio.get_event_loop() behaviour for synchronous tests."""

    try:
        return _ORIGINAL_GET_EVENT_LOOP()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


asyncio.get_event_loop = _patched_get_event_loop

try:  # pragma: no cover - prefer httpx when available
    import httpx
except ImportError:  # pragma: no cover - allow tests to stub httpx
    httpx = None  # type: ignore[assignment]

_HTTPXGetAsyncClient = Callable[[Any], Any]

try:  # pragma: no cover - optional Home Assistant httpx helper during tests
    from homeassistant.helpers.httpx_client import (
        get_async_client as _ha_httpx_get_async_client,
    )
except ImportError:  # pragma: no cover - provide fallback when helper missing
    _httpx_get_async_client: _HTTPXGetAsyncClient | None = None
else:  # pragma: no cover - executed only when helper available during runtime
    _httpx_get_async_client = _ha_httpx_get_async_client

try:  # pragma: no cover - optional Home Assistant registries during tests
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
except ImportError:  # pragma: no cover - provide fallbacks for unit tests
    dr = er = None  # type: ignore[assignment]

API_BASE_URL = "https://app2.govee.com"
TOKEN_REFRESH_INTERVAL = 300.0
SERVICE_REAUTHENTICATE = "reauthenticate"
_SERVICES_KEY = f"{DOMAIN}_services_registered"


def _get_auth_class() -> type[Any]:
    from .auth import GoveeAuthManager

    return GoveeAuthManager


def _get_device_client_class() -> type[Any]:
    from .device_client import DeviceListClient

    return DeviceListClient


def _get_coordinator_class() -> type[Any]:
    from .coordinator import GoveeDataUpdateCoordinator

    return GoveeDataUpdateCoordinator


async def async_setup(hass: Any, _config: dict[str, Any]) -> bool:
    """Initialise the integration namespace on Home Assistant startup."""

    hass.data.setdefault(DOMAIN, {})
    _ensure_services_registered(hass)
    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up a config entry for the integration."""

    _ensure_services_registered(hass)
    domain_data = hass.data.setdefault(DOMAIN, {})

    http_client = _async_get_http_client(hass)
    auth_class = _get_auth_class()
    auth = auth_class(hass, http_client)
    await auth.async_initialize()
    tokens = getattr(auth, "tokens", None)
    if tokens is None:
        credentials = await _async_request_credentials(hass, entry)
        tokens = await auth.async_login(
            credentials["email"], credentials["password"]
        )
    device_client_class = _get_device_client_class()
    api_client = device_client_class(hass, http_client, auth)

    device_registry = _get_device_registry(hass)
    entity_registry = _get_entity_registry(hass)
    iot_client, iot_state_enabled, iot_command_enabled, iot_refresh_enabled = (
        await _async_prepare_iot_runtime(hass, entry)
    )

    coordinator_class = _get_coordinator_class()
    coordinator = coordinator_class(
        hass=hass,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
        config_entry_id=getattr(entry, "entry_id", None),
        iot_client=iot_client,
        iot_state_enabled=iot_state_enabled,
        iot_command_enabled=iot_command_enabled,
        iot_refresh_enabled=iot_refresh_enabled,
    )
    await coordinator.async_config_entry_first_refresh()
    entry_state: dict[str, Any] = {
        "config_entry": entry,
        "http_client": http_client,
        "auth": auth,
        "api_client": api_client,
        "coordinator": coordinator,
        "iot_client": iot_client,
        "tokens": tokens,
    }
    token_refresh_cancel = _schedule_token_refresh(hass, entry, auth, entry_state)
    entry_state["token_refresh_cancel"] = token_refresh_cancel
    domain_data[entry.entry_id] = entry_state

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Handle unloading of a config entry."""

    domain_data = hass.data.get(DOMAIN, {})
    entry_data = domain_data.pop(entry.entry_id, None)

    unload_success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if entry_data is None:
        return unload_success

    coordinator = entry_data.get("coordinator")
    if coordinator is not None:
        cancel = getattr(coordinator, "cancel_refresh", None)
        if callable(cancel):
            cancel()

    token_cancel = entry_data.get("token_refresh_cancel")
    if callable(token_cancel):
        token_cancel()

    http_client = entry_data.get("http_client")
    if http_client is not None:
        close = getattr(http_client, "aclose", None)
        if callable(close):
            await close()

    iot_client = entry_data.get("iot_client")
    if iot_client is not None:
        await _async_stop_iot_client(iot_client)

    if not domain_data:
        hass.data.pop(DOMAIN, None)

    return unload_success


def _create_http_client() -> Any:
    """Return an httpx async client configured for the REST API."""

    if httpx is None:
        msg = "httpx is required for the Govee Ultimate integration"
        raise RuntimeError(msg)
    return httpx.AsyncClient(base_url=API_BASE_URL)


def _async_get_http_client(hass: Any) -> Any:
    """Return an AsyncClient sourced from Home Assistant helpers when possible."""

    if _httpx_get_async_client is not None:
        return _httpx_get_async_client(hass)
    return _create_http_client()


def _get_device_registry(hass: Any) -> Any:
    """Return the Home Assistant device registry or a stub for tests."""

    if dr is not None and hasattr(dr, "async_get"):
        return dr.async_get(hass)
    return _REGISTRY_STUB


def _get_entity_registry(hass: Any) -> Any:
    """Return the Home Assistant entity registry or a stub for tests."""

    if er is not None and hasattr(er, "async_get"):
        return er.async_get(hass)
    return _REGISTRY_STUB


async def _async_perform_reauth(
    hass: Any, entry: Any, auth: Any, entry_state: dict[str, Any]
) -> None:
    """Execute the reauthentication flow and persist new tokens."""

    credentials = await _async_request_credentials(hass, entry)
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        return
    tokens = await auth.async_login(email, password)
    entry_state["tokens"] = tokens


def _ensure_services_registered(hass: Any) -> None:
    """Register integration services exactly once."""

    if hass.data.get(_SERVICES_KEY):
        return

    async def _handle_service(call: Any) -> None:
        await _async_service_reauth(hass, call)

    hass.services.async_register(DOMAIN, SERVICE_REAUTHENTICATE, _handle_service)
    hass.data[_SERVICES_KEY] = True


async def _async_service_reauth(hass: Any, call: Any) -> None:
    """Handle the public service that forces reauthentication."""

    data = getattr(call, "data", call) or {}
    entry_id = data.get("entry_id")
    if entry_id is None:
        return
    entry_state = _resolve_entry_state(hass, entry_id)
    if entry_state is None:
        return
    entry = entry_state.get("config_entry")
    auth = entry_state.get("auth")
    if entry is None or auth is None:
        return
    await _async_perform_reauth(hass, entry, auth, entry_state)


def _is_http_error(error: Exception) -> bool:
    """Return True if the provided exception represents an HTTP error."""

    if httpx is None:
        return False
    http_error = getattr(httpx, "HTTPError", None)
    if http_error is None:
        return False
    return isinstance(error, http_error)


def _resolve_entry_state(hass: Any, entry_id: str) -> dict[str, Any] | None:
    """Look up the cached integration state for the given entry."""

    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return None
    state = domain_data.get(entry_id)
    if not isinstance(state, dict):
        return None
    return state


class _RegistryStub:
    """Fallback registry implementation for unit tests."""

    async def async_get_or_create(self, *args: Any, **kwargs: Any) -> Any:
        return {}


async def _async_request_credentials(hass: Any, entry: Any) -> dict[str, Any]:
    """Request credentials from the config flow to perform authentication."""

    flow = _get_flow_init_callable(hass)
    entry_data = getattr(entry, "data", {})
    result = await flow(
        DOMAIN,
        context={"source": "reauth", "entry_id": getattr(entry, "entry_id", None)},
        data={
            "email": entry_data.get("email"),
            "password": entry_data.get("password"),
        },
    )
    data = result.get("data", {}) if isinstance(result, dict) else {}
    return data


def _get_flow_init_callable(hass: Any) -> Any:
    """Return the config flow async_init helper from Home Assistant."""

    flow_container = getattr(hass.config_entries, "flow", hass.config_entries)
    flow = getattr(flow_container, "async_init", None)
    if not callable(flow):
        msg = "Config flow helper unavailable"
        raise TypeError(msg)
    return flow


def _schedule_token_refresh(hass: Any, entry: Any, auth: Any, entry_state: dict[str, Any]) -> Any:
    """Periodically refresh access tokens via Home Assistant's event loop."""

    loop = getattr(hass, "loop", None) or asyncio.get_event_loop()
    handle: asyncio.TimerHandle | None = None

    async def _refresh() -> None:
        try:
            await auth.async_get_access_token()
        except Exception as exc:  # pragma: no cover - defensive, surfaced via services
            if _is_http_error(exc):
                await _async_perform_reauth(hass, entry, auth, entry_state)
        finally:
            _arm()

    def _arm() -> None:
        nonlocal handle
        handle = loop.call_later(TOKEN_REFRESH_INTERVAL, _tick)

    def _tick() -> None:
        hass.async_create_task(_refresh())

    _arm()

    def _cancel() -> None:
        nonlocal handle
        if handle is not None:
            handle.cancel()
            handle = None

    return _cancel


_REGISTRY_STUB = _RegistryStub()


async def _async_stop_iot_client(client: Any) -> None:
    """Best-effort shutdown for the optional IoT client."""

    stop = getattr(client, "async_stop", None)
    if callable(stop):
        await stop()
        return

    sync_stop = getattr(client, "stop", None)
    if callable(sync_stop):
        sync_stop()


async def _async_prepare_iot_runtime(hass: Any, entry: Any) -> tuple[Any | None, bool, bool, bool]:
    """Create the IoT client when enabled in the configuration entry."""

    data = getattr(entry, "data", {})
    enable_iot = _config_flag(data, "enable_iot")
    state_enabled = enable_iot and _config_flag(data, "enable_iot_state_updates")
    command_enabled = enable_iot and _config_flag(data, "enable_iot_commands")
    refresh_enabled = enable_iot and _config_flag(data, "enable_iot_refresh")

    if not enable_iot:
        return None, False, False, False

    try:
        from .iot_client import IoTClient, IoTClientConfig
    except ImportError:  # pragma: no cover - dependency is optional in tests
        return None, False, False, False

    mqtt_client = await _async_get_mqtt_client(hass)
    if mqtt_client is None:
        return None, False, False, False

    config = IoTClientConfig(
        enabled=True,
        state_topic="govee/{device_id}/state",
        command_topic="govee/{device_id}/command",
        refresh_topic="govee/{device_id}/refresh",
    )

    iot_client = IoTClient(
        mqtt=mqtt_client,
        config=config,
        on_device_update=lambda update: None,
    )
    return iot_client, state_enabled, command_enabled, refresh_enabled


async def _async_get_mqtt_client(hass: Any) -> Any | None:
    """Attempt to retrieve the Home Assistant MQTT client."""

    try:  # pragma: no cover - optional dependency in tests
        from homeassistant.components import mqtt
    except ImportError:
        return None

    getter = getattr(mqtt, "async_get_mqtt", None)
    if getter is None:
        return None
    return await getter(hass)


def _config_flag(data: dict[str, Any], key: str) -> bool:
    """Read a boolean flag from config entry data."""

    return bool(data.get(key, False))
