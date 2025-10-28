"""Config flow tests for the Govee Ultimate integration."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock


if "homeassistant.data_entry_flow" not in sys.modules:
    data_entry_flow = ModuleType("homeassistant.data_entry_flow")

    class FlowResultType:
        """Describe fallback flow result values for unit tests."""

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

        async def async_abort(
            self,
            *,
            reason: str,
            description_placeholders: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "abort",
                "reason": reason,
                "description_placeholders": description_placeholders or {},
            }

    class _ConfigEntry:
        def __init__(self, *, data: dict[str, Any]) -> None:
            self.data = data
            self.options: dict[str, Any] = {}

    config_entries.ConfigFlow = _ConfigFlow
    config_entries.ConfigEntry = _ConfigEntry
    sys.modules["homeassistant.config_entries"] = config_entries


from custom_components.govee_ultimate import config_flow


class _StubHass(SimpleNamespace):
    """Provide a lightweight hass-like object for config flow tests."""

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[str, Any] = {}
        self.config_entries = SimpleNamespace(
            async_update_entry=AsyncMock(),
            async_reload=AsyncMock(),
        )


def _build_user_input(**overrides: Any) -> dict[str, Any]:
    """Return a baseline set of user credentials for submissions."""

    payload = {
        "email": "user@example.com",
        "password": "secret",
        "enable_iot": True,
        "enable_iot_state_updates": True,
        "enable_iot_commands": True,
        "enable_iot_refresh": True,
    }
    payload.update(overrides)
    return payload


def test_stub_flow_result_type_includes_docstring() -> None:
    """Fallback FlowResultType should document its purpose."""

    assert FlowResultType.__doc__ == (
        "Describe fallback flow result values for unit tests."
    )


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
async def test_user_flow_creates_entry_with_credentials_and_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submissions should store credentials and IoT flags in the entry."""

    hass = _StubHass()
    flow = config_flow.GoveeUltimateConfigFlow()
    flow.hass = hass

    async def _fake_validate(_: Any, __: str, ___: str) -> None:
        return None

    monkeypatch.setattr(
        config_flow, "_async_validate_credentials", _fake_validate, raising=False
    )

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


@pytest.mark.asyncio
async def test_options_flow_allows_configuring_iot_topics() -> None:
    """Options flow should surface IoT toggles and topic templates."""

    entry = config_entries.ConfigEntry(data={"enable_iot": True})
    entry.options = {
        "iot_state_enabled": True,
        "iot_command_enabled": False,
        "iot_refresh_enabled": True,
        "iot_state_topic": "custom/state/{device_id}",
        "iot_command_topic": "custom/command/{device_id}",
        "iot_refresh_topic": "custom/refresh/{device_id}",
    }

    flow = config_flow.GoveeUltimateOptionsFlowHandler(entry)

    result = await flow.async_step_init(user_input=None)
    assert result["type"] == FlowResultType.FORM
    schema = result["data_schema"]
    defaults = schema({})
    assert defaults["iot_state_enabled"] is True
    assert defaults["iot_command_enabled"] is False
    assert defaults["iot_refresh_enabled"] is True
    assert defaults["iot_state_topic"] == "custom/state/{device_id}"
    assert defaults["iot_command_topic"] == "custom/command/{device_id}"
    assert defaults["iot_refresh_topic"] == "custom/refresh/{device_id}"

    new_options = {
        "iot_state_enabled": False,
        "iot_command_enabled": True,
        "iot_refresh_enabled": False,
        "iot_state_topic": "next/state/{device_id}",
        "iot_command_topic": "next/command/{device_id}",
        "iot_refresh_topic": "next/refresh/{device_id}",
    }

    result = await flow.async_step_init(user_input=new_options)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == new_options


@pytest.mark.asyncio
async def test_user_flow_validates_credentials_before_creating_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful submissions should authenticate credentials prior to entry creation."""

    hass = _StubHass()
    flow = config_flow.GoveeUltimateConfigFlow()
    flow.hass = hass

    calls: list[tuple[Any, ...]] = []

    async def _fake_validate(hass_obj: Any, email: str, password: str) -> None:
        calls.append((hass_obj, email, password))

    monkeypatch.setattr(
        config_flow,
        "_async_validate_credentials",
        _fake_validate,
        raising=False,
    )

    user_input = _build_user_input()
    result = await flow.async_step_user(user_input=user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert calls == [(hass, "user@example.com", "secret")]


@pytest.mark.asyncio
async def test_user_flow_returns_form_on_invalid_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid credentials should surface a form error rather than creating the entry."""

    hass = _StubHass()
    flow = config_flow.GoveeUltimateConfigFlow()
    flow.hass = hass

    class _InvalidAuth(Exception):
        pass

    async def _fake_validate(_: Any, __: str, ___: str) -> None:
        raise _InvalidAuth

    monkeypatch.setattr(config_flow, "InvalidAuth", _InvalidAuth, raising=False)
    monkeypatch.setattr(
        config_flow,
        "_async_validate_credentials",
        _fake_validate,
        raising=False,
    )

    result = await flow.async_step_user(user_input=_build_user_input())

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_reauth_flow_updates_entry_and_aborts_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reauthentication should update the stored credentials and abort the flow."""

    entry = config_entries.ConfigEntry(
        data={
            "email": "user@example.com",
            "password": "old",
            "enable_iot": True,
            "enable_iot_state_updates": True,
            "enable_iot_commands": False,
            "enable_iot_refresh": True,
        }
    )
    entry.entry_id = "entry-id"  # type: ignore[attr-defined]

    hass = _StubHass()
    hass.config_entries.async_update_entry = AsyncMock()
    hass.config_entries.async_reload = AsyncMock()

    flow = config_flow.GoveeUltimateConfigFlow()
    flow.hass = hass

    async def _fake_validate(_: Any, email: str, password: str) -> None:
        if password != "new-secret":
            raise AssertionError("Expected new password to be validated")

    monkeypatch.setattr(
        config_flow,
        "_async_validate_credentials",
        _fake_validate,
        raising=False,
    )

    result = await flow.async_step_reauth(user_input=None, entry=entry)

    assert result["type"] == FlowResultType.FORM
    defaults = result["data_schema"]({"password": ""})
    assert defaults["email"] == "user@example.com"

    user_input = {"password": "new-secret"}
    result = await flow.async_step_reauth(user_input=user_input, entry=entry)

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    hass.config_entries.async_update_entry.assert_called_once()
    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
