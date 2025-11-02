"""Minimal ConfigEntry placeholder for tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Self, TypedDict

from homeassistant.data_entry_flow import FlowContext


class ConfigSubentryData(TypedDict):
    """Container for configuration subentry data.

    Returned by integrations, a subentry_id will be assigned automatically.
    """

    data: Mapping[str, Any]
    subentry_type: str
    title: str
    unique_id: str | None


class FlowType(StrEnum):
    """Flow type."""

    CONFIG_FLOW = "config_flow"
    # Add other flow types here as needed in the future,
    # if we want to support them in the `next_flow` parameter.


@dataclasses.dataclass(kw_only=True, slots=True)
class DiscoveryKey:
    """Serializable discovery key."""

    domain: str
    key: str | tuple[str, ...]
    version: int

    @classmethod
    def from_json_dict(cls, json_dict: dict[str, Any]) -> Self:
        """Construct from JSON dict."""
        if type(key := json_dict["key"]) is list:
            key = tuple(key)
        return cls(domain=json_dict["domain"], key=key, version=json_dict["version"])


class ConfigFlowContext(FlowContext, total=False):
    """Typed context dict for config flow."""

    alternative_domain: str
    configuration_url: str
    confirm_only: bool
    discovery_key: DiscoveryKey
    entry_id: str
    title_placeholders: Mapping[str, str]
    unique_id: str | None


class ConfigEntry:
    """Simple placeholder for Home Assistant ConfigEntry used in tests."""

    def __init__(
        self,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the test stub ConfigEntry."""
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id


class ConfigEntries:
    """Placeholder manager with optional flow attribute for tests."""

    def __init__(self) -> None:
        """Initialize the test stub ConfigEntries manager."""
        self.flow = None


# Backwards compatibility: some code imports directly from module level
async_init = None
async_update_entry = None
async_reload = None


# Lightweight ConfigFlow / OptionsFlow stubs used by Config Flow code in tests
class ConfigFlow:
    """Minimal ConfigFlow base for tests."""

    def __init__(self) -> None:
        self.hass = None

    @classmethod
    def __init_subclass__(cls, **kwargs: Any) -> None:  # pragma: no cover - test shim
        # Accept and ignore keyword args like `domain=...` used in real HA
        # so subclasses in tests can be declared using the real pattern.
        return super().__init_subclass__()


class OptionsFlow:
    """Minimal OptionsFlow base for tests."""

    def __init__(self, entry: Any) -> None:
        self._entry = entry


# Simplify the result type used in the integration's config flows
ConfigFlowResult = dict[str, Any]


__all__ = [
    "ConfigEntry",
    "ConfigEntries",
    "ConfigFlow",
    "OptionsFlow",
    "ConfigFlowResult",
]


class OptionsFlow:
    """Base class for config options flows."""

    handler: str

    _config_entry: ConfigEntry
    """For compatibility only - to be removed in 2025.12"""

    def _async_abort_entries_match(
        self, match_dict: dict[str, Any] | None = None
    ) -> None:
        """Abort if another current entry matches all data.

        Requires `already_configured` in strings.json in user visible flows.
        """
        pass

    @property
    def _config_entry_id(self) -> str:
        """Return config entry id.

        Please note that this is not available inside `__init__` method, and
        can only be referenced after initialisation.
        """
        # This is the same as handler, but that's an implementation detail
        if self.handler is None:
            raise ValueError(
                "The config entry id is not available during initialisation"
            )
        return self.handler

    @property
    def config_entry(self) -> ConfigEntry:
        """Return the config entry linked to the current options flow.

        Please note that this is not available inside `__init__` method, and
        can only be referenced after initialisation.
        """
        # For compatibility only - to be removed in 2025.12
        return self._config_entry

    @config_entry.setter
    def config_entry(self, value: ConfigEntry) -> None:
        """Set the config entry value."""
        pass
