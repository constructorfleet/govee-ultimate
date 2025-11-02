"""Integration entry point for the Govee Ultimate custom component."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, TypedDict

import httpx

import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.httpx_client import get_async_client as httpx_client
from homeassistant.helpers.typing import ConfigType

from .auth import AccountAuthDetails, GoveeAuthManager
from .coordinator import GoveeDataUpdateCoordinator
from .device_client import DeviceListClient
from .iot_client import IoTClient, IoTClientConfig

DOMAIN = "govee"
PLATFORMS: tuple[str, ...] = (
    "light",
    "humidifier",
    "fan",
    "switch",
    "number",
    "sensor",
    "binary_sensor",
    "select",
)

__all__ = [
    "DOMAIN",
    "PLATFORMS",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]


CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


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

API_BASE_URL = "https://app2.govee.com"
SERVICE_REAUTHENTICATE = "reauthenticate"
TOKEN_REFRESH_INTERVAL = timedelta(minutes=5)

_REAUTH_SERVICE_REGISTERED = False
_SERVICES_KEY = f"{DOMAIN}_services_registered"


class DomainData(TypedDict):
    """Type definition for the integration domain data."""

    http_client: httpx.AsyncClient
    auth: GoveeAuthManager
    api_client: DeviceListClient
    coordinator: GoveeDataUpdateCoordinator
    iot_client: IoTClient
    tokens: AccountAuthDetails | None
    refresh_unsub: CALLBACK_TYPE | None
    config_entry: ConfigEntry


async def async_setup(hass: Any, _config: ConfigType) -> bool:
    """Initialise the integration namespace on Home Assistant startup."""

    hass.data.setdefault(DOMAIN, {})
    _ensure_services_registered(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration."""

    _ensure_services_registered(hass)
    http_client = await _async_get_http_client(hass)
    auth = GoveeAuthManager(hass, http_client)
    api_client = DeviceListClient(hass, http_client, auth)
    iot_client, iot_state_enabled, iot_command_enabled, iot_refresh_enabled = (
        await _async_prepare_iot_runtime(hass, entry, auth)
    )
    device_registry = _get_device_registry(hass)
    entity_registry = _get_entity_registry(hass)

    coordinator = GoveeDataUpdateCoordinator(
        hass=hass,
        api_client=api_client,
        device_registry=device_registry,
        entity_registry=entity_registry,
        config_entry_id=entry.entry_id,
        iot_client=iot_client,
        iot_state_enabled=iot_state_enabled,
        iot_command_enabled=iot_command_enabled,
        iot_refresh_enabled=iot_refresh_enabled,
    )
    domain_data: DomainData = DomainData(
        **hass.data.setdefault(
            DOMAIN,
            {
                "api_client": api_client,
                "http_client": http_client,
                "iot_client": iot_client,
                "coordinator": coordinator,
                "auth": auth,
                "config_entry": entry,
            },
        )
    )

    await _async_ensure_reauth_service(hass)
    await auth.async_initialize()

    if auth.tokens is None:
        email, password = _get_entry_credentials(entry)
        if not email or not password:
            await _async_request_reauth(hass, entry)
            msg = (
                "Credentials are required to initialise the Govee Ultimate integration"
            )
            raise RuntimeError(msg)
        domain_data["tokens"] = await auth.async_login(email, password)

    await coordinator.async_config_entry_first_refresh()
    _schedule_coordinator_refresh(coordinator)

    domain_data["refresh_unsub"] = _schedule_token_refresh(hass, auth, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle unloading of a config entry."""

    entry_data: DomainData | None = DomainData(**hass.data.get(DOMAIN, {}))

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
        await http_client.aclose()

    iot_client = entry_data.get("iot_client")
    if iot_client is not None:
        await iot_client.async_stop()

    if not entry_data:
        hass.data.pop(DOMAIN, None)

    return unload_success


def _create_http_client() -> Any:
    """Return an httpx async client configured for the REST API."""

    if httpx is None:
        msg = "httpx is required for the Govee Ultimate integration"
        raise RuntimeError(msg)
    return httpx.AsyncClient(base_url=API_BASE_URL)


class _BaseUrlAsyncClient(httpx.AsyncClient):
    """Wrap an async client to ensure relative URLs resolve against the base URL."""

    def __init__(self, client: httpx.AsyncClient, base_url: httpx.URL | str) -> None:
        self._client = client
        self._base_url = httpx.URL(base_url) if httpx is not None else base_url

    @property
    def base_url(self) -> Any:
        return self._base_url

    def _prepare_url(self, url: httpx.URL | str) -> httpx.URL | str:
        if httpx is None:
            if isinstance(url, str) and url.startswith("/"):
                return f"{self._base_url}{url}"
            return url
        return httpx.URL(url, base_url=self._base_url)

    async def request(
        self, method: str, url: httpx.URL | str, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._client.request(
            method, self._prepare_url(url), *args, **kwargs
        )

    async def post(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        return await self.request("POST", url, *args, **kwargs)

    async def get(self, url: httpx.URL | str, *args: Any, **kwargs: Any) -> Any:
        return await self.request("GET", url, *args, **kwargs)

    async def aclose(self) -> Any:
        return await self._client.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


async def _async_get_http_client(hass: HomeAssistant) -> _BaseUrlAsyncClient:
    """Return an HTTP client, preferring the Home Assistant helper when available."""

    if httpx_client is not None:
        getter = getattr(httpx_client, "get_async_client", None)
        if getter is not None:
            client = getter(hass, verify_ssl=True)
            if asyncio.iscoroutine(client):
                client = await client
            if isinstance(client, _BaseUrlAsyncClient):
                return client
            if httpx is not None:
                base_url = getattr(client, "base_url", None)
                if not base_url or str(base_url) in {"", "/"}:
                    return _BaseUrlAsyncClient(client, API_BASE_URL)
            return client

    return _create_http_client()


def _get_device_registry(hass: HomeAssistant) -> DeviceRegistry:
    """Return the Home Assistant device registry or a stub for tests."""

    if dr is not None and hasattr(dr, "async_get"):
        return dr.async_get(hass)
    return _REGISTRY_STUB  # type: ignore


def _get_entity_registry(hass: HomeAssistant) -> EntityRegistry:
    """Return the Home Assistant entity registry or a stub for tests."""

    if er is not None and hasattr(er, "async_get"):
        return er.async_get(hass)
    return _REGISTRY_STUB  # type: ignore


async def _async_perform_reauth(
    hass: HomeAssistant,
    entry: ConfigEntry,
    auth: GoveeAuthManager,
    entry_state: dict[str, Any],
) -> None:
    """Execute the reauthentication flow and persist new tokens."""

    credentials = await _async_request_credentials(hass, entry)
    email = credentials.get("email")
    password = credentials.get("password")
    if not email or not password:
        return
    tokens = await auth.async_login(email, password)
    entry_state["tokens"] = tokens


def _ensure_services_registered(hass: HomeAssistant) -> None:
    """Register integration services exactly once."""

    if hass.data.get(_SERVICES_KEY):
        return

    async def _handle_service(call: Any) -> None:
        await _async_service_reauth(hass, call)

    hass.services.async_register(DOMAIN, SERVICE_REAUTHENTICATE, _handle_service)
    hass.data[_SERVICES_KEY] = True


async def _async_service_reauth(hass: HomeAssistant, call: Any) -> None:
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


def _resolve_entry_state(hass: HomeAssistant, entry_id: str) -> dict[str, Any] | None:
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


async def _async_request_credentials(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
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


def _get_flow_init_callable(hass: HomeAssistant) -> Any:
    """Return the config flow async_init helper from Home Assistant."""

    flow_container = getattr(hass.config_entries, "flow", hass.config_entries)
    flow = getattr(flow_container, "async_init", None)
    if not callable(flow):
        msg = "Config flow helper unavailable"
        raise TypeError(msg)
    return flow


_REGISTRY_STUB = _RegistryStub()


async def _async_prepare_iot_runtime(
    hass: HomeAssistant, entry: ConfigEntry, auth: GoveeAuthManager
) -> tuple[Any | None, bool, bool, bool]:
    """Create the IoT client when enabled in the configuration entry."""

    data = getattr(entry, "data", {})
    options = getattr(entry, "options", {}) or {}
    enable_iot = _config_flag(data, "enable_iot")

    if not enable_iot:
        return None, False, False, False

    def _flag(option_key: str, fallback_key: str) -> bool:
        if option_key in options:
            return bool(options[option_key])
        return _config_flag(data, fallback_key)

    state_enabled = _flag("iot_state_enabled", "enable_iot_state_updates")
    command_enabled = _flag("iot_command_enabled", "enable_iot_commands")
    refresh_enabled = _flag("iot_refresh_enabled", "enable_iot_refresh")

    if not (state_enabled or command_enabled or refresh_enabled):
        return None, False, False, False

    bundle = await auth.async_get_iot_bundle()
    if bundle is None:
        return None, False, False, False

    if not all(
        [
            bundle.client_id,
            bundle.endpoint,
            bundle.account_id,
            bundle.certificate,
            bundle.private_key,
        ]
    ):
        return None, False, False, False

    client_id = (
        f"AP/{bundle.account_id}/a{bundle.client_id}"
        if bundle.account_id is not None
        else bundle.client_id
    )
    config = IoTClientConfig(
        endpoint=bundle.endpoint,
        account_topic=bundle.topic,
        client_id=client_id,
        certificate=bundle.certificate,
        private_key=bundle.private_key,
    )

    iot_client = IoTClient(
        config=config,
        on_device_update=lambda update: None,
    )
    return iot_client, state_enabled, command_enabled, refresh_enabled


async def _async_ensure_reauth_service(hass: HomeAssistant) -> None:
    """Ensure the reauthentication service is registered once."""

    global _REAUTH_SERVICE_REGISTERED

    if _REAUTH_SERVICE_REGISTERED:
        return

    await _async_register_reauth_service(hass)
    _REAUTH_SERVICE_REGISTERED = True


def _schedule_token_refresh(
    hass: HomeAssistant, auth: GoveeAuthManager, entry: ConfigEntry
) -> CALLBACK_TYPE:
    """Schedule periodic token refresh using the Home Assistant event helper."""

    if async_track_time_interval is None:
        return lambda: None

    async def _async_refresh(_now: Any | None = None) -> None:
        try:
            await auth.async_get_access_token()
        except httpx.HTTPError:
            await _async_request_reauth(hass, entry)
            raise

    return async_track_time_interval(hass, _async_refresh, TOKEN_REFRESH_INTERVAL)


def _schedule_coordinator_refresh(coordinator: GoveeDataUpdateCoordinator) -> None:
    """Schedule metadata refresh callbacks on the coordinator."""
    coordinator.async_schedule_refresh(coordinator.async_request_refresh)


async def _async_register_reauth_service(hass: HomeAssistant) -> None:
    """Register a Home Assistant service for manual reauthentication."""

    services = hass.services
    if services is None:
        return

    register = services.async_register
    if register is None:
        return

    async def _handle_service(call: Any) -> None:
        data = getattr(call, "data", {}) or {}
        entry_id = data.get("entry_id") if isinstance(data, dict) else None
        await _async_request_reauth(hass, entry_id=entry_id)

    result = register(DOMAIN, SERVICE_REAUTHENTICATE, _handle_service)
    if asyncio.iscoroutine(result):
        await result  # type: ignore


async def _async_request_reauth(
    hass: HomeAssistant,
    entry: ConfigEntry | None = None,
    *,
    entry_id: str | None = None,
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


def _get_entry_credentials(entry: ConfigEntry) -> tuple[str | None, str | None]:
    """Extract stored credentials from a config entry."""

    data = getattr(entry, "data", {}) or {}
    return data.get("email"), data.get("password")


def _config_flag(data: dict[str, Any], key: str) -> bool:
    """Read a boolean flag from config entry data."""

    return bool(data.get(key, False))
