"""Configuration flow for the Govee Ultimate integration."""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - prefer voluptuous when available
    import voluptuous as vol
except ImportError:  # pragma: no cover - fallback for unit tests without voluptuous
    from dataclasses import dataclass

    class _Schema:
        """Minimal schema implementation to emulate voluptuous in tests."""

        def __init__(self, mapping: dict[Any, Any]) -> None:
            self._sequence: list[tuple[Any, Any]] = []
            normalized: dict[str, Any] = {}
            for key, validator in mapping.items():
                if isinstance(key, _SchemaKey):
                    normalized[key.name] = validator
                    self._sequence.append((key, validator))
                else:
                    normalized[str(key)] = validator
                    self._sequence.append((key, validator))
            self.schema = normalized

        def __call__(self, data: dict[str, Any]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, _validator in self._sequence:
                if isinstance(key, _Required):
                    if key.name not in data:
                        msg = f"Missing required key: {key.name}"
                        raise KeyError(msg)
                    result[key.name] = data[key.name]
                elif isinstance(key, _Optional):
                    result[key.name] = data.get(key.name, key.default)
                else:
                    key_name = str(key)
                    result[key_name] = data.get(key_name)
            return result

    @dataclass(frozen=True)
    class _SchemaKey:
        name: str

    @dataclass(frozen=True)
    class _Required(_SchemaKey):
        """Represent a required schema field."""

    @dataclass(frozen=True)
    class _Optional(_SchemaKey):
        """Represent an optional schema field with default."""

        default: Any = None

    class _VolModule:
        @staticmethod
        def Schema(mapping: dict[Any, Any]) -> _Schema:
            return _Schema(mapping)

        @staticmethod
        def Required(name: str) -> _Required:
            return _Required(name)

        @staticmethod
        def Optional(name: str, *, default: Any | None = None) -> _Optional:
            return _Optional(name, default)

    vol = _VolModule()

try:  # pragma: no cover - executed within Home Assistant
    from homeassistant import config_entries
    from homeassistant.data_entry_flow import FlowResult, FlowResultType
except ImportError:  # pragma: no cover - exercised in unit tests via stubs
    from types import SimpleNamespace

    class _ConfigEntry:
        """Minimal stub of Home Assistant config entry for tests."""

        def __init__(self, *, data: dict[str, Any]) -> None:
            self.data = data
            self.options: dict[str, Any] = {}

    class _ConfigFlow:  # type: ignore[too-few-public-methods]
        """Fallback base class used during unit tests."""

        DOMAIN: str | None = None

        def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
            super().__init_subclass__(**kwargs)
            if domain is not None:
                cls.DOMAIN = domain

        async def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": FlowResultType.FORM,
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        async def async_create_entry(
            self, *, title: str, data: dict[str, Any]
        ) -> dict[str, Any]:
            return {
                "type": FlowResultType.CREATE_ENTRY,
                "title": title,
                "data": data,
            }

    class FlowResultType:  # type: ignore[too-few-public-methods]
        """Document stub flow result values when Home Assistant is unavailable."""

        FORM = "form"
        CREATE_ENTRY = "create_entry"

    class _OptionsFlow(_ConfigFlow):
        """Fallback options flow base class used during unit tests."""

    FlowResult = dict[str, Any]
    config_entries = SimpleNamespace(
        ConfigFlow=_ConfigFlow,
        OptionsFlow=_OptionsFlow,
        ConfigEntry=_ConfigEntry,
    )

from . import DOMAIN


TITLE = "Govee Ultimate"


_USER_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
        vol.Optional("enable_iot", default=False): bool,
        vol.Optional("enable_iot_state_updates", default=True): bool,
        vol.Optional("enable_iot_commands", default=False): bool,
        vol.Optional("enable_iot_refresh", default=False): bool,
    }
)


_DEFAULT_IOT_OPTIONS: dict[str, Any] = {
    "iot_state_enabled": True,
    "iot_command_enabled": False,
    "iot_refresh_enabled": False,
    "iot_state_topic": "govee/{device_id}/state",
    "iot_command_topic": "govee/{device_id}/command",
    "iot_refresh_topic": "govee/{device_id}/refresh",
}

_IOT_OPTION_FIELD_TYPES: dict[str, type[Any]] = {
    "iot_state_enabled": bool,
    "iot_command_enabled": bool,
    "iot_refresh_enabled": bool,
    "iot_state_topic": str,
    "iot_command_topic": str,
    "iot_refresh_topic": str,
}


class GoveeUltimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the configuration workflow for the integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect user credentials and IoT preferences."""

        if user_input is None:
            return await self.async_show_form(step_id="user", data_schema=_USER_SCHEMA)

        data = dict(_USER_SCHEMA(user_input))
        if not data.get("enable_iot"):
            data["enable_iot_state_updates"] = False
            data["enable_iot_commands"] = False
            data["enable_iot_refresh"] = False

        return await self.async_create_entry(title=TITLE, data=data)


def _options_defaults(entry: Any) -> dict[str, Any]:
    """Return IoT option defaults using entry options or fallback values."""

    options = dict(_DEFAULT_IOT_OPTIONS)
    options.update(getattr(entry, "options", {}) or {})

    data = getattr(entry, "data", {})
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


class GoveeUltimateOptionsFlowHandler(config_entries.OptionsFlow):
    """Allow configuring IoT behaviour post-setup."""

    def __init__(self, entry: Any) -> None:
        """Store the config entry providing default option values."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Render the options form and persist submitted values."""
        defaults = _options_defaults(self._entry)
        schema = _build_options_schema(defaults)

        if user_input is None:
            return {
                "type": FlowResultType.FORM,
                "step_id": "init",
                "data_schema": schema,
                "errors": {},
            }

        options = schema(user_input)
        return {
            "type": FlowResultType.CREATE_ENTRY,
            "title": TITLE,
            "data": options,
        }


async def async_get_options_flow(entry: Any) -> GoveeUltimateOptionsFlowHandler:
    """Return the options flow handler for Home Assistant."""

    return GoveeUltimateOptionsFlowHandler(entry)
