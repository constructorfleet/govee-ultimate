"""Config flow tests for the Govee Ultimate integration."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest


if "homeassistant.data_entry_flow" not in sys.modules:
    data_entry_flow = ModuleType("homeassistant.data_entry_flow")

    class FlowResultType:
        FORM = "form"
        CREATE_ENTRY = "create_entry"

    data_entry_flow.FlowResultType = FlowResultType
    sys.modules["homeassistant.data_entry_flow"] = data_entry_flow
else:
    from homeassistant.data_entry_flow import FlowResultType  # pragma: no cover


if "homeassistant.config_entries" not in sys.modules:
    config_entries = ModuleType("homeassistant.config_entries")

    class _ConfigFlow:
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

    class _ConfigEntry:
        def __init__(self, *, data: dict[str, Any]) -> None:
            self.data = data
            self.options: dict[str, Any] = {}

    config_entries.ConfigFlow = _ConfigFlow
    config_entries.ConfigEntry = _ConfigEntry
    sys.modules["homeassistant.config_entries"] = config_entries


from custom_components.govee_ultimate import config_flow


@pytest.mark.asyncio
async def test_user_flow_requests_credentials_before_submission() -> None:
    """When no input is provided the flow should request credentials."""

    flow = config_flow.GoveeUltimateConfigFlow()
    result = await flow.async_step_user(user_input=None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    schema = result["data_schema"]
    for required in ("email", "password"):
        assert required in schema.schema  # type: ignore[attr-defined]
    for optional in (
        "enable_iot",
        "enable_iot_state_updates",
        "enable_iot_commands",
        "enable_iot_refresh",
    ):
        assert optional in schema.schema  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_flow_creates_entry_with_credentials_and_flags() -> None:
    """Submissions should store credentials and IoT flags in the entry."""

    flow = config_flow.GoveeUltimateConfigFlow()
    user_input = {
        "email": "user@example.com",
        "password": "secret",
        "enable_iot": True,
        "enable_iot_state_updates": True,
        "enable_iot_commands": False,
        "enable_iot_refresh": True,
    }

    result = await flow.async_step_user(user_input=user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Govee Ultimate"
    assert result["data"] == user_input
