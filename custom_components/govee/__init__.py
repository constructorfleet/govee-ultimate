"""Integration entry point for the Govee Ultimate custom component."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

import httpx

from custom_components.govee.const import (
    _SERVICES_KEY,
    SERVICE_REAUTHENTICATE,
    TOKEN_REFRESH_INTERVAL,
)

try:
    import homeassistant.helpers.config_validation as cv  # type: ignore
except Exception:  # pragma: no cover - guard for test stubs
    cv = None  # type: ignore[assignment]

try:
    import homeassistant.helpers.device_registry as dr  # type: ignore
except Exception:  # pragma: no cover - guard for test stubs
    dr = None  # type: ignore[assignment]

try:
    import homeassistant.helpers.entity_registry as er  # type: ignore
except Exception:  # pragma: no cover - guard for test stubs
    er = None  # type: ignore[assignment]
from typing import Any as _Any

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.config_entries import ConfigEntry
except Exception:  # pragma: no cover - test stub fallback
    ConfigEntry = _Any

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
except Exception:  # pragma: no cover - test stub fallback
    CALLBACK_TYPE = _Any
    HomeAssistant = _Any

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.helpers.device_registry import DeviceRegistry
except Exception:  # pragma: no cover - test stub fallback
    DeviceRegistry = _Any

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.helpers.entity_registry import EntityRegistry
except Exception:  # pragma: no cover - test stub fallback
    EntityRegistry = _Any

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.helpers.event import async_track_time_interval
except Exception:  # pragma: no cover - test stub fallback
    async_track_time_interval = None

try:  # pragma: no cover - Home Assistant runtime imports
    from homeassistant.helpers.typing import ConfigType
except Exception:  # pragma: no cover - test stub fallback
    ConfigType = _Any

from . import api as _api
from .auth import AccountAuthDetails, GoveeAuthManager
from .const import CONFIG_SCHEMA, DOMAIN
from .coordinator import GoveeDataUpdateCoordinator


# Package-level factory getters used by tests to override implementation
def _get_auth_class() -> type:
    """Return the auth class used to create auth manager instances.

    Tests monkeypatch this function to provide a FakeAuth implementation.
    """

    return GoveeAuthManager


def _get_device_client_class() -> type:
    """Return the device client class used by the API facade.

    Tests may monkeypatch this to inject a fake device client.
    """

    from . import device_client as _dc

    return getattr(_dc, "DeviceListClient")


def _get_coordinator_class() -> type:
    """Return the coordinator class used during entry setup.

    Tests may override this to inject a FakeCoordinator.
    """

    return GoveeDataUpdateCoordinator


# Re-export HTTP helper functions implemented in the API module so tests
# that monkeypatch `integration._create_http_client` still work.
def _create_http_client() -> object:
    return _api._create_http_client()


async def _async_get_http_client(hass: Any) -> object:
    return await _api._async_get_http_client(hass)


# Avoid importing modules that depend on this package at import-time to
# prevent circular import problems during tests. Import locally where used.

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
    "CONFIG_SCHEMA",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]

_REAUTH_SERVICE_REGISTERED = False


async def async_setup(hass: Any, _config: ConfigType) -> bool:
    """Initialise the integration namespace on Home Assistant startup."""

    hass.data.setdefault(DOMAIN, {})
    _ensure_services_registered(hass)
    return True


class DomainData(TypedDict):
    """Type definition for the integration domain data."""

    http_client: httpx.AsyncClient
    auth: GoveeAuthManager
    api_client: Any
    coordinator: Any
    iot_client: Any
    tokens: AccountAuthDetails | None
    refresh_unsub: CALLBACK_TYPE | None
    config_entry: ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for the integration."""

    _ensure_services_registered(hass)
    # Let the API facade own HTTP client creation; pass only hass and auth and
    # allow the API client to lazily construct the http client when required.
    # Allow tests to override the auth implementation by monkeypatching
    # `_get_auth_class` on the integration module.
    auth_cls = _get_auth_class()
    auth = auth_cls(hass, None)
    # Import the API client lazily to avoid circular import at module import time
    from .api import GoveeAPIClient  # local import

    api_client = GoveeAPIClient(hass, auth)
    # Ensure the API client has created and exposed the http client so the
    # domain state retains the historical `http_client` key for tests.
    await api_client._ensure_client()
    http_client = api_client.http_client
    iot_client, iot_state_enabled, iot_command_enabled, iot_refresh_enabled = (
        await _async_prepare_iot_runtime(hass, entry, auth)
    )
    device_registry = _get_device_registry(hass)
    entity_registry = _get_entity_registry(hass)

    # Import coordinator locally to avoid circular import with the package
    from .coordinator import GoveeDataUpdateCoordinator

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
    # Store integration state keyed by entry id to match how tests and
    # Home Assistant expect per-entry state to be kept in `hass.data`.
    domain = hass.data.setdefault(DOMAIN, {})
    entry_state: DomainData = {
        "api_client": api_client,
        "http_client": http_client,
        "iot_client": iot_client,
        "coordinator": coordinator,
        "auth": auth,
        "config_entry": entry,
    }
    domain[entry.entry_id] = entry_state

    await _async_ensure_reauth_service(hass)
    await auth.async_initialize()

    # Ensure tokens exist for this entry (may be created during setup)
    if auth.tokens is None:
        email, password = _get_entry_credentials(entry)
        if not email or not password:
            await _async_request_reauth(hass, entry)
            msg = (
                "Credentials are required to initialise the Govee Ultimate integration"
            )
            raise RuntimeError(msg)
        entry_state["tokens"] = await auth.async_login(email, password)

    await coordinator.async_config_entry_first_refresh()
    _schedule_coordinator_refresh(coordinator)

    entry_state["refresh_unsub"] = _schedule_token_refresh(hass, auth, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle unloading of a config entry."""

    # Look up per-entry state using the helper that understands both
    # storage layouts (legacy single-state or per-entry mapping).
    entry_state = _resolve_entry_state(hass, entry.entry_id)

    unload_success = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if entry_state is None:
        return unload_success

    coordinator = entry_state.get("coordinator")
    if coordinator is not None:
        if hasattr(coordinator, "cancel_refresh"):
            coordinator.cancel_refresh()

    refresh_unsub = entry_state.get("refresh_unsub")
    if callable(refresh_unsub):
        refresh_unsub()

    api_client = entry_state.get("api_client")
    if api_client is not None and hasattr(api_client, "async_close"):
        await api_client.async_close()

    iot_client = entry_state.get("iot_client")
    if iot_client is not None:
        await iot_client.async_stop()

    # If removing this entry leaves the domain dict empty, clean it up.
    domain = hass.data.get(DOMAIN)
    if isinstance(domain, dict):
        domain.pop(entry.entry_id, None)
        if not domain:
            hass.data.pop(DOMAIN, None)

    return unload_success


# HTTP client helpers are implemented in `custom_components.govee.api` and
# re-exported here for backward compatibility with tests and callers that
# import these symbols from the integration package namespace.


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

    data = call.data if hasattr(call, "data") else call or {}
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
    entry_data = entry.data if hasattr(entry, "data") else {}
    result = await flow(
        DOMAIN,
        context={
            "source": "reauth",
            "entry_id": entry.entry_id if hasattr(entry, "entry_id") else None,
        },
        data={
            "email": entry_data.get("email"),
            "password": entry_data.get("password"),
        },
    )
    data = result.get("data", {}) if isinstance(result, dict) else {}
    return data


def _get_flow_init_callable(hass: HomeAssistant) -> Any:
    """Return the config flow async_init helper from Home Assistant."""

    flow_container = (
        hass.config_entries.flow
        if hasattr(hass.config_entries, "flow")
        else hass.config_entries
    )
    flow = flow_container.async_init if hasattr(flow_container, "async_init") else None
    if not callable(flow):
        msg = "Config flow helper unavailable"
        raise TypeError(msg)
    return flow


_REGISTRY_STUB = _RegistryStub()


async def _async_prepare_iot_runtime(
    hass: HomeAssistant, entry: ConfigEntry, auth: GoveeAuthManager
) -> tuple[Any | None, bool, bool, bool]:
    """Create the IoT client when enabled in the configuration entry."""

    data = dict(getattr(entry, "data", {}) or {})
    options = dict(getattr(entry, "options", {}) or {})
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
    # Import IoT client classes lazily so tests can monkeypatch
    # `custom_components.govee.iot_client.IoTClient` and the config
    # type used to construct it.
    from importlib import import_module

    iot_mod = import_module("custom_components.govee.iot_client")
    IoTClient = getattr(iot_mod, "IoTClient")
    IoTClientConfig = getattr(iot_mod, "IoTClientConfig")

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
        data = call.data if hasattr(call, "data") else (call or {})
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

    flow_manager = (
        hass.config_entries.flow if hasattr(hass.config_entries, "flow") else None
    )
    if flow_manager is None:
        return

    async_init = (
        flow_manager.async_init if hasattr(flow_manager, "async_init") else None
    )
    if async_init is None:
        return

    target_entry_id = entry_id or (
        entry.entry_id if hasattr(entry, "entry_id") else None
    )
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
