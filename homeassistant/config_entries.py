"""Minimal ConfigEntry placeholder for tests."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Container, Iterable, Mapping
from enum import StrEnum
from typing import Any, Generic, Required, Self, TypedDict, TypeVar

import voluptuous as vol


class FlowContext(TypedDict, total=False):
    """Typed context dict."""

    show_advanced_options: bool
    source: str


_FlowContextT = TypeVar("_FlowContextT", bound="FlowContext")
_FlowResultT = TypeVar("_FlowResultT", bound="FlowResult[Any, Any]")
_HandlerT = TypeVar("_HandlerT")


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


class FlowResultType(StrEnum):
    """Result type for a data entry flow."""

    FORM = "form"
    CREATE_ENTRY = "create_entry"
    ABORT = "abort"
    EXTERNAL_STEP = "external"
    EXTERNAL_STEP_DONE = "external_done"
    SHOW_PROGRESS = "progress"
    SHOW_PROGRESS_DONE = "progress_done"
    MENU = "menu"


class FlowResult(TypedDict, Generic[_FlowContextT, _HandlerT], total=False):
    """Typed result dict."""

    context: _FlowContextT
    data_schema: vol.Schema | None
    data: Mapping[str, Any]
    description_placeholders: Mapping[str, str] | None
    description: str | None
    errors: dict[str, str] | None
    extra: str
    flow_id: Required[str]
    handler: Required[_HandlerT]
    last_step: bool | None
    menu_options: Container[str]
    preview: str | None
    progress_action: str
    progress_task: asyncio.Task[Any] | None
    reason: str
    required: bool
    sort: bool
    step_id: str
    title: str
    translation_domain: str
    type: FlowResultType
    url: str


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


class ConfigFlowResult(FlowResult[ConfigFlowContext, str], total=False):
    """Typed result dict for config flow."""

    # Extra keys, only present if type is CREATE_ENTRY
    next_flow: tuple[FlowType, str]  # (flow type, flow id)
    minor_version: int
    options: Mapping[str, Any]
    result: ConfigEntry
    subentries: Iterable[ConfigSubentryData]
    version: int


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
