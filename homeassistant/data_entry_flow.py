"""Typed dicts for data entry flow results and context."""

import asyncio
from collections.abc import Container, Iterable, Mapping
from enum import StrEnum
from typing import Any, Generic, Required, TypedDict, TypeVar

import voluptuous as vol

# Avoid importing ConfigEntry and other concrete types here to prevent a
# circular import when test stubs define `homeassistant.config_entries`.
ConfigEntry = Any
ConfigFlowContext = Any
ConfigSubentryData = Any
FlowType = Any

_FlowContextT = TypeVar("_FlowContextT", bound="FlowContext")
_FlowResultT = TypeVar("_FlowResultT", bound="FlowResult[Any, Any]")
_HandlerT = TypeVar("_HandlerT")


class FlowContext(TypedDict, total=False):
    """Typed context dict."""

    show_advanced_options: bool
    source: str


class FlowResultType(StrEnum):
    """Describe fallback flow result values for unit tests."""

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


class ConfigFlowResult(FlowResult[ConfigFlowContext, str], total=False):
    """Typed result dict for config flow."""

    # Extra keys, only present if type is CREATE_ENTRY
    next_flow: tuple[FlowType, str]  # (flow type, flow id)
    minor_version: int
    options: Mapping[str, Any]
    result: ConfigEntry
    subentries: Iterable[ConfigSubentryData]
    version: int
