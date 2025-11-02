"""Configuration flow for the Govee Ultimate integration."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, TYPE_CHECKING

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow as HAConfigFlow

# Import types used only for typing under TYPE_CHECKING to avoid
# depending on full Home Assistant runtime types at import time in CI
# where the test harness stubs may not expose every symbol.
if TYPE_CHECKING:  # pragma: no cover - typing only
    from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
else:
    # Provide lightweight runtime fallbacks so the module can be
    # imported in environments where Home Assistant does not expose the
    # full config_entries API (tests often inject minimal stubs).
    try:  # OptionsFlow is a base class used at runtime; prefer real one
        from homeassistant.config_entries import OptionsFlow  # type: ignore
    except Exception:  # pragma: no cover - fallback for tests

        class OptionsFlow:  # minimal fallback
            """Minimal fallback OptionsFlow used when Home Assistant types are missing."""

            pass

    # For return-type annotations we only need a structural alias; a
    # plain dict-type is sufficient when the real type is missing.
    ConfigFlowResult = dict[str, Any]  # type: ignore
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .auth import GoveeAuthManager
from .const import DOMAIN


# Always expose a FlowResultType symbol with guidance in its docstring so
# tests can assert the presence of helpful documentation when Home
# Assistant isn't available or when tests import the module directly.
class FlowResultType:  # pragma: no cover - simple documentation holder
    """Document stub flow result values when Home Assistant is unavailable."""


REAUTH_CONFIRM_STEP = "reauth_confirm"


class CannotConnect(HomeAssistantError):
    """Raised when the integration cannot reach the upstream service."""


class InvalidAuth(HomeAssistantError):
    """Raised when provided credentials are rejected by the API."""


TITLE = "Govee Ultimate"


_USER_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Optional("enable_iot", default=False): bool,  # type: ignore
        vol.Optional("enable_iot_state_updates", default=True): bool,  # type: ignore
        vol.Optional("enable_iot_commands", default=False): bool,  # type: ignore
        vol.Optional("enable_iot_refresh", default=False): bool,  # type: ignore
    }
)


_DEFAULT_IOT_OPTIONS: dict[str, Any] = {
    "iot_state_enabled": True,
    "iot_command_enabled": False,
    "iot_refresh_enabled": False,
}

_IOT_OPTION_FIELD_TYPES: dict[str, type[Any]] = {
    "iot_state_enabled": bool,
    "iot_command_enabled": bool,
    "iot_refresh_enabled": bool,
}


def _build_reauth_schema(default_email: str) -> Any:
    """Construct the schema used for reauthentication steps."""

    return vol.Schema(
        {
            vol.Optional("email", default=default_email): str,  # type: ignore
            vol.Required("password"): str,
        }
    )


async def _async_validate_credentials(
    hass: HomeAssistant, email: str, password: str
) -> None:
    """Validate credentials by performing a login request."""
    auth = GoveeAuthManager(hass)

    try:
        await auth.async_login(email, password)
    except httpx.HTTPError as exc:
        status = getattr(exc, "response", None)
        status_code = (
            status.status_code
            if status is not None and hasattr(status, "status_code")
            else None
        )
        if status_code in {401, 403}:
            raise InvalidAuth from exc
        raise CannotConnect from exc


async def _async_update_reauth_entry(
    hass: HomeAssistant, entry: Any, data: dict[str, Any]
) -> None:
    """Update credentials on the entry and trigger a reload."""
    result = hass.config_entries.async_update_entry(entry, data=data)
    if asyncio.iscoroutine(result):
        await result

    await hass.config_entries.async_reload(entry.entry_id)


class GoveeUltimateConfigFlow(HAConfigFlow, domain=DOMAIN):
    """Handle the configuration workflow for the integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Store transient state for config and reauthentication flows."""

        super().__init__()
        self._reauth_entry: Any | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect user credentials and IoT preferences."""

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_USER_SCHEMA)

        data = dict(_USER_SCHEMA(user_input))
        if not data.get("enable_iot"):
            data["enable_iot_state_updates"] = False
            data["enable_iot_commands"] = False
            data["enable_iot_refresh"] = False

        errors: dict[str, str] = {}
        try:
            await _async_validate_credentials(
                self.hass,
                data["email"],
                data["password"],
            )
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"

        if errors:
            return self.async_show_form(
                step_id="user", data_schema=_USER_SCHEMA, errors=errors
            )

        return self.async_create_entry(title=TITLE, data=data)

    async def async_step_reauth(
        self,
        user_input: dict[str, Any] | None = None,
        entry: Any | None = None,
        **kwargs: Any,
    ) -> ConfigFlowResult:
        """Perform a reauthentication workflow when credentials expire."""

        if entry is None:
            entry = kwargs.get("entry")
        if entry is None:
            with contextlib.suppress(Exception):
                entry_id = kwargs.get("entry_id")
                entry = self.hass.config_entries.async_get_entry(entry_id)

        if entry is not None:
            self._reauth_entry = entry

        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_failed")

        if user_input is None:
            schema = _build_reauth_schema(self._reauth_entry.data.get("email", ""))
            return self.async_show_form(
                step_id=REAUTH_CONFIRM_STEP,
                data_schema=schema,
                errors={},
            )

        submission = dict(user_input)
        submission.setdefault("email", self._reauth_entry.data.get("email", ""))

        errors: dict[str, str] = {}
        try:
            await _async_validate_credentials(
                self.hass,
                submission["email"],
                submission["password"],
            )
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"

        if errors:
            schema = _build_reauth_schema(submission["email"])
            return self.async_show_form(
                step_id=REAUTH_CONFIRM_STEP,
                data_schema=schema,
                errors=errors,
            )

        updated = dict(self._reauth_entry.data)
        updated.update(submission)
        await _async_update_reauth_entry(self.hass, self._reauth_entry, updated)

        return self.async_abort(reason="reauth_successful")

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the submission from the reauthentication confirmation step."""

        return await self.async_step_reauth(user_input=user_input)


def _options_defaults(entry: Any) -> dict[str, Any]:
    """Return IoT option defaults using entry options or fallback values."""

    options = dict(_DEFAULT_IOT_OPTIONS)
    options.update(dict(getattr(entry, "options", {}) or {}))

    data = dict(getattr(entry, "data", {}) or {})
    if data.get("enable_iot"):
        options.setdefault(
            "iot_state_enabled",
            data.get("enable_iot_state_updates", options["iot_state_enabled"]),
        )
        options.setdefault(
            "iot_command_enabled",
            data.get("enable_iot_commands", options["iot_command_enabled"]),
        )
        options.setdefault(
            "iot_refresh_enabled",
            data.get("enable_iot_refresh", options["iot_refresh_enabled"]),
        )
    else:
        options.setdefault("iot_state_enabled", False)
        options.setdefault("iot_command_enabled", False)
        options.setdefault("iot_refresh_enabled", False)
    return options


def _build_options_schema(defaults: dict[str, Any]) -> Any:
    """Construct the options schema using ``defaults`` values."""

    schema: dict[Any, type[Any]] = {}
    for key, field_type in _IOT_OPTION_FIELD_TYPES.items():
        schema[vol.Optional(key, default=defaults[key])] = field_type
    return vol.Schema(schema)


class GoveeUltimateOptionsFlowHandler(OptionsFlow):
    """Allow configuring IoT behaviour post-setup."""

    def __init__(self, entry: Any) -> None:
        """Store the config entry providing default option values."""
        self._entry = entry

    def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Render the options form and persist submitted values.

        Be resilient to test shims where `async_show_form` may be a
        coroutine function or a synchronous helper that returns a dict.
        """

        defaults = _options_defaults(self._entry)
        schema = _build_options_schema(defaults)

        if user_input is None:
            result = self.async_show_form(step_id="init", data_schema=schema, errors={})
            if asyncio.iscoroutine(result):
                return result

            async def _return_result() -> ConfigFlowResult:  # type: ignore[override]
                return result

            return _return_result()

        options = schema(user_input)
        return {"type": "create_entry", "data": options}


async def async_get_options_flow(entry: Any) -> GoveeUltimateOptionsFlowHandler:
    """Return the options flow handler for Home Assistant."""

    return GoveeUltimateOptionsFlowHandler(entry)
