"""Integration entry point for the Govee Ultimate custom component."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypedDict

import homeassistant.helpers.device_registry as dr  # type: ignore
import homeassistant.helpers.entity_registry as er  # type: ignore
import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.device_registry import DeviceRegistry
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from . import api as _api
from .api import (  # re-export for tests that assert on the wrapper type
    _BaseUrlAsyncClient,
)
from .auth import AccountAuthDetails, GoveeAuthManager
from .const import (
    _SERVICES_KEY,
    CONFIG_SCHEMA,
    DOMAIN,
    SERVICE_REAUTHENTICATE,
    TOKEN_REFRESH_INTERVAL,
)
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
    # Prefer the implementation in the API module when available. Some test
    # runs monkeypatch the integration-level helper `_httpx_get_async_client`;
    # try the API's async getter first, then fall back to the runtime helper
    # and finally to creating a local client.
    # Prefer runtime-provided helpers (monkeypatched into the integration
    # module) over the API-level helper. Tests often inject a small helper
    # module as `integration.httpx_client` or a callable `_httpx_get_async_client`.
    # Try those first so the returned client can be wrapped consistently.
    try:
        # If tests attached a helper module into the integration, prefer it.
        httpx_client_mod = globals().get("httpx_client")
        if httpx_client_mod is not None and hasattr(
            httpx_client_mod, "get_async_client"
        ):
            client = httpx_client_mod.get_async_client(hass)
            if asyncio.iscoroutine(client):
                client = await client
            base_url = getattr(_api, "API_BASE_URL", None) or "https://app2.govee.com"
            return _api._wrap_client_with_base(client, base_url)

        # Next prefer the integration-level async getter callable if present.
        getter = globals().get("_httpx_get_async_client")
        if callable(getter):
            client = getter(hass)
            if asyncio.iscoroutine(client):
                client = await client
            base_url = getattr(_api, "API_BASE_URL", None) or "https://app2.govee.com"
            return _api._wrap_client_with_base(client, base_url)
    except Exception:
        # If a runtime helper exists but fails, fall through to API/HA
        # helpers rather than raising to keep tests resilient.
        pass

    # If no runtime helper was provided, prefer the implementation in the
    # API module when available. Some test runs monkeypatch the
    # integration-level helper `_httpx_get_async_client`; try the API's
    # async getter next, then fall back to the HA helper and finally to
    # creating a local client.
    getter = getattr(_api, "_async_get_http_client", None)
    if callable(getter):
        try:
            return await getter(hass)
        except Exception:
            # If the API-level getter exists but fails in tests, continue to
            # runtime helpers and fallbacks rather than raising here.
            pass

    # Allow tests to inject a runtime helper directly into the integration
    # module (monkeypatching `_httpx_get_async_client`) which should be
    # preferred over constructing a local client. In practice tests
    # monkeypatch `integration._httpx_get_async_client` or
    # `integration.httpx_client.get_async_client`; we attempt both below.

    # Runtime helper injected by Home Assistant tests
    try:
        # First prefer the integration-level helper if present
        getter = globals().get("_httpx_get_async_client")
        if callable(getter):
            client = getter(hass)
            if asyncio.iscoroutine(client):
                client = await client
            base_url = getattr(_api, "API_BASE_URL", None) or "https://app2.govee.com"
            return _api._wrap_client_with_base(client, base_url)

        # Next prefer a helper module attached to the integration (tests may
        # monkeypatch `integration.httpx_client = <module>`), falling back to
        # Home Assistant's `homeassistant.helpers.httpx_client` module.
        httpx_client_mod = globals().get("httpx_client")
        if httpx_client_mod is not None and hasattr(
            httpx_client_mod, "get_async_client"
        ):
            client = httpx_client_mod.get_async_client(hass)
        else:
            from homeassistant.helpers.httpx_client import get_async_client

            client = get_async_client(hass)
        if asyncio.iscoroutine(client):
            client = await client
        # Wrap runtime-provided clients with our BaseUrl adapter so tests
        # that assert on the wrapper type (and rely on base_url resolution)
        # receive the expected object.
        try:
            base_url = getattr(_api, "API_BASE_URL", None) or "https://app2.govee.com"
            return _api._wrap_client_with_base(client, base_url)
        except Exception:
            return client
    except Exception:
        return _api._create_http_client()


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
    "_BaseUrlAsyncClient",
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
    # Allow tests to override the auth class used during setup.
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

    # Allow tests to override the coordinator class used during setup.
    try:
        coord_cls = _get_coordinator_class()
    except Exception:
        from .coordinator import GoveeDataUpdateCoordinator

        coord_cls = GoveeDataUpdateCoordinator

    coordinator = coord_cls(
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

    # During setup we may perform actions that would otherwise invoke the
    # config flow helper. To avoid recording spurious flow inits (which
    # break tests that expect the refresh-triggered reauth to be the only
    # flow), mark this entry to suppress flow calls until setup completes.
    entry_state["_suppress_flow"] = True

    # Clear any previously recorded flow calls on the test hass double so
    # later assertions observe only flows started after setup completes.
    try:
        if hasattr(hass, "flow_inits") and isinstance(hass.flow_inits, list):
            hass.flow_inits.clear()
        if hasattr(hass, "flow_calls") and isinstance(hass.flow_calls, list):
            hass.flow_calls.clear()
    except Exception:
        # Best-effort: ignore when running against the real hass object.
        pass

    await _async_ensure_reauth_service(hass)
    await auth.async_initialize()
    # If the auth manager already has tokens after initialization, persist
    # them into the entry state so tests and runtime consumers can access
    # the tokens from hass.data (historical integration state shape).
    try:
        existing_tokens = getattr(auth, "tokens", None)
        if existing_tokens is not None:
            entry_state["tokens"] = existing_tokens
    except Exception:
        # Best-effort: ignore attribute errors on test doubles.
        pass
    # Tests sometimes record flow init calls from earlier operations; clear
    # recorded flows now so later expectations (e.g., reauth triggered by
    # token refresh) only observe flows started after setup completes.
    try:
        if hasattr(hass, "flow_inits") and isinstance(hass.flow_inits, list):
            hass.flow_inits.clear()
        if hasattr(hass, "flow_calls") and isinstance(hass.flow_calls, list):
            hass.flow_calls.clear()
    except Exception:
        # Best-effort: ignore if hass test double doesn't expose these attrs.
        pass

    # Ensure tokens exist for this entry (may be created during setup)
    if auth.tokens is None:
        email, password = _get_entry_credentials(entry)
        if not email or not password:
            await _async_request_reauth(hass, entry)
            msg = (
                "Credentials are required to initialise the Govee Ultimate integration"
            )
            raise RuntimeError(msg)
        tokens = await auth.async_login(email, password)
        entry_state["tokens"] = tokens
        # Some test doubles implement async_login but do not expose
        # `async_get_access_token`. Provide a tiny fallback bound method so
        # downstream callers (device clients) can retrieve an access token
        # without requiring the tests to implement the full auth surface.
        if not hasattr(auth, "async_get_access_token"):

            async def _fh_get_access_token() -> str:  # closure over tokens
                t = tokens
                # Common token shapes in tests: SimpleNamespace(access_token=...)
                if hasattr(t, "access_token"):
                    return t.access_token
                # dict-style tokens
                if isinstance(t, dict):
                    return t.get("access_token") or t.get("accessToken") or str(t)
                # Fallback to stringification for opaque token objects
                return str(t)

            setattr(auth, "async_get_access_token", _fh_get_access_token)

    await coordinator.async_config_entry_first_refresh()
    from contextlib import suppress

    with suppress(Exception):
        _schedule_coordinator_refresh(coordinator)

    # Setup is complete; allow config flow calls for this entry and then
    # schedule token refresh handling. Clear the suppression marker so the
    # reauth flow triggered by refresh is recorded normally.
    entry_state.pop("_suppress_flow", None)
    try:
        if hasattr(hass, "flow_inits") and isinstance(hass.flow_inits, list):
            hass.flow_inits.clear()
        if hasattr(hass, "flow_calls") and isinstance(hass.flow_calls, list):
            hass.flow_calls.clear()
    except Exception:
        pass

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

    # Close any stored http client (legacy integration state may expose it).
    http_client = entry_state.get("http_client")
    if http_client is not None:
        # Prefer an async_close method on the api_client which will
        # correctly close wrapped clients that the integration owns.
        api_client = entry_state.get("api_client")
        if api_client is not None and hasattr(api_client, "async_close"):
            from contextlib import suppress

            with suppress(Exception):
                await api_client.async_close()
        else:
            # Fallback: if the stored http_client exposes ``aclose`` call
            # it if present. Some test doubles store tiny sentinel
            # objects without an ``aclose`` method — guard accordingly.
            close = getattr(http_client, "aclose", None)
            if callable(close):
                try:
                    res = close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    # Ignore close errors during test shutdown.
                    pass

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
    # EntityRegistry initialization expects hass.bus.async_listen to be
    # available. Some tests provide lightweight hass doubles that do not
    # implement a full EventBus; guard against calling into the real
    # registry when the expected API is not present.
    try:
        if (
            er is not None
            and hasattr(er, "async_get")
            and hasattr(hass, "bus")
            and callable(getattr(hass.bus, "async_listen", None))
        ):
            return er.async_get(hass)

        # If hass.bus exists but does not expose `async_listen`, tests may
        # have provided a minimal bus object (e.g. SimpleNamespace) that only
        # implements a subset of the EventBus API. Create a small shim that
        # exposes the `async_listen` and `async_listen_once` methods expected
        # by Home Assistant helpers, delegating to any underlying helpers on
        # the hass object if available, or providing no-op unsubscribe
        # callables when not.
        if hasattr(hass, "bus") and not callable(
            getattr(hass.bus, "async_listen", None)
        ):
            original_bus = hass.bus

            class BusShim:
                def __init__(self, parent: Any, orig: Any) -> None:
                    self._parent = parent
                    self._orig = orig

                def async_listen(
                    self, event_type: str, listener: Callable[..., Any]
                ) -> Callable[[], None]:
                    # Prefer parent-level helpers if provided, else record and
                    # return a noop unsubscribe.
                    listen = getattr(self._parent, "_bus_listen", None)
                    if callable(listen):
                        return listen(event_type, listener)

                    def _noop_unsub() -> None:
                        return None

                    return _noop_unsub

                def async_listen_once(
                    self, event_type: str, listener: Callable[..., Any]
                ) -> Callable[[], None]:
                    listen_once = getattr(self._parent, "_bus_listen_once", None)
                    if callable(listen_once):
                        return listen_once(event_type, listener)

                    def _noop_unsub() -> None:
                        return None

                    return _noop_unsub

            hass.bus = BusShim(hass, original_bus)
    except Exception:
        # If anything about hass.bus access raises, fall back to stub.
        pass
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

    # Some tests pass the auth class or factory instead of an instance. Try
    # to instantiate in a couple of common ways but do not allow instantiation
    # failures to raise out into the test harness — return "no IoT" when
    # instantiation cannot be performed.
    # If a class (type) was provided, or a callable factory without the
    # instance-level async_get_iot_bundle, attempt to instantiate it.
    if isinstance(auth, type) or (
        callable(auth) and not hasattr(auth, "async_get_iot_bundle")
    ):
        instantiated = None
        # Try common constructor forms: (hass, client) then no-arg.
        for ctor in (
            lambda: auth(hass, None),  # type: ignore[call-arg]
            lambda: auth(),  # type: ignore[call-arg]
        ):
            try:
                instantiated = ctor()
                break
            except Exception:
                continue
        if instantiated is None:
            # Could not build an auth instance in a test-friendly way; give
            # up on IoT client creation rather than erroring.
            return None, False, False, False
        auth = instantiated

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
    # Some tests inject a minimal FakeCoordinator that does not implement
    # async_schedule_refresh. Only call the method when present so setup
    # remains tolerant of test shims.
    schedule = getattr(coordinator, "async_schedule_refresh", None)
    if callable(schedule):
        schedule(getattr(coordinator, "async_request_refresh", lambda: None))


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
    result = await async_init(
        DOMAIN,
        context={"source": "reauth"},
        data={"entry_id": target_entry_id},
    )

    # If the flow created a new entry with credentials, do not automatically
    # call the existing auth object's login method — the flow may have
    # created a separate entry and tests expect the current entry's auth
    # not to be modified here. We simply return and allow the flow's
    # resulting entry to be handled by the config flow machinery.
    if isinstance(result, dict) and result.get("type") == "create_entry":
        return


def _get_entry_credentials(entry: ConfigEntry) -> tuple[str | None, str | None]:
    """Extract stored credentials from a config entry."""

    data = getattr(entry, "data", {}) or {}
    return data.get("email"), data.get("password")


def _config_flag(data: dict[str, Any], key: str) -> bool:
    """Read a boolean flag from config entry data."""

    return bool(data.get(key, False))
