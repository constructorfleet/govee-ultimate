"""Integration entry point for the Govee Ultimate custom component."""

from __future__ import annotations

import asyncio
from datetime import timedelta
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

try:  # pragma: no cover - prefer Home Assistant httpx helper
    from homeassistant.helpers import httpx_client
except ImportError:  # pragma: no cover - allow unit tests to provide stub
    httpx_client = None  # type: ignore[assignment]

try:  # pragma: no cover - schedule refreshes via Home Assistant helper when present
    from homeassistant.helpers.event import async_track_time_interval
except ImportError:  # pragma: no cover - allow tests to patch scheduling helper
    async_track_time_interval = None  # type: ignore[assignment]

try:  # pragma: no cover - optional Home Assistant registries during tests
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
except ImportError:  # pragma: no cover - provide fallbacks for unit tests
    dr = er = None  # type: ignore[assignment]

API_BASE_URL = "https://app2.govee.com"
SERVICE_REAUTHENTICATE = "reauthenticate"
TOKEN_REFRESH_INTERVAL = timedelta(minutes=5)

_REAUTH_SERVICE_REGISTERED = False

if httpx is not None:  # pragma: no branch - defined when httpx is available
    HTTP_ERROR = httpx.HTTPError
else:  # pragma: no cover - stubbed during unit tests

    class HTTP_ERROR(Exception):  # type: ignore[assignment]
        """Fallback HTTP error when httpx is unavailable."""

        pass


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
    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up a config entry for the integration."""

    domain_data = hass.data.setdefault(DOMAIN, {})

    await _async_ensure_reauth_service(hass)

    http_client = await _async_get_http_client(hass)
    auth_class = _get_auth_class()
    auth = auth_class(hass, http_client)
    await auth.async_initialize()
    tokens = getattr(auth, "tokens", None)

    if tokens is None:
        email, password = _get_entry_credentials(entry)
        if not email or not password:
            await _async_request_reauth(hass, entry)
            msg = (
                "Credentials are required to initialise the Govee Ultimate integration"
            )
            raise RuntimeError(msg)
        tokens = await auth.async_login(email, password)

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

    refresh_unsub = _schedule_token_refresh(hass, auth, entry)

    domain_data[entry.entry_id] = {
        "http_client": http_client,
        "auth": auth,
        "api_client": api_client,
        "coordinator": coordinator,
        "iot_client": iot_client,
        "tokens": tokens,
        "refresh_unsub": refresh_unsub,
    }

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

    refresh_unsub = entry_data.get("refresh_unsub")
    if callable(refresh_unsub):
        refresh_unsub()

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


async def _async_get_http_client(hass: Any) -> Any:
    """Return an HTTP client, preferring the Home Assistant helper when available."""

    if httpx_client is not None:
        getter = getattr(httpx_client, "get_async_client", None)
        if getter is not None:
            client = getter(hass, verify_ssl=True)
            if asyncio.iscoroutine(client):
                client = await client
            return client

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


class _RegistryStub:
    """Fallback registry implementation for unit tests."""

    async def async_get_or_create(self, *args: Any, **kwargs: Any) -> Any:
        return {}


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


async def _async_prepare_iot_runtime(
    hass: Any, entry: Any
) -> tuple[Any | None, bool, bool, bool]:
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


async def _async_ensure_reauth_service(hass: Any) -> None:
    """Ensure the reauthentication service is registered once."""

    global _REAUTH_SERVICE_REGISTERED

    if _REAUTH_SERVICE_REGISTERED:
        return

    await _async_register_reauth_service(hass)
    _REAUTH_SERVICE_REGISTERED = True


def _schedule_token_refresh(hass: Any, auth: Any, entry: Any) -> Any:
    """Schedule periodic token refresh using the Home Assistant event helper."""

    if async_track_time_interval is None:
        return lambda: None

    async def _async_refresh(_now: Any | None = None) -> None:
        try:
            await auth.async_get_access_token()
        except HTTP_ERROR:
            await _async_request_reauth(hass, entry)
            raise

    return async_track_time_interval(hass, _async_refresh, TOKEN_REFRESH_INTERVAL)


async def _async_register_reauth_service(hass: Any) -> None:
    """Register a Home Assistant service for manual reauthentication."""

    services = getattr(hass, "services", None)
    if services is None:
        return

    register = getattr(services, "async_register", None)
    if register is None:
        return

    async def _handle_service(call: Any) -> None:
        data = getattr(call, "data", {}) or {}
        entry_id = data.get("entry_id") if isinstance(data, dict) else None
        await _async_request_reauth(hass, entry_id=entry_id)

    result = register(DOMAIN, SERVICE_REAUTHENTICATE, _handle_service)
    if asyncio.iscoroutine(result):
        await result


async def _async_request_reauth(
    hass: Any, entry: Any | None = None, *, entry_id: str | None = None
) -> None:
    """Start a reauthentication flow for the integration entry."""

    flow_manager = getattr(hass.config_entries, "flow", None)
    if flow_manager is None:
        return

    async_init = getattr(flow_manager, "async_init", None)
    if async_init is None:
        return

    target_entry_id = entry_id or getattr(entry, "entry_id", None)
    if target_entry_id is None:
        return

    await async_init(
        DOMAIN,
        context={"source": "reauth"},
        data={"entry_id": target_entry_id},
    )


def _get_entry_credentials(entry: Any) -> tuple[str | None, str | None]:
    """Extract stored credentials from a config entry."""

    data = getattr(entry, "data", {}) or {}
    return data.get("email"), data.get("password")


def _config_flag(data: dict[str, Any], key: str) -> bool:
    """Read a boolean flag from config entry data."""

    return bool(data.get(key, False))
