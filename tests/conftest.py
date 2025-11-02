"""Pytest configuration for the Govee Ultimate integration tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

try:
    import voluptuous as vol
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    class _Schema:
        """Minimal stub mirroring ``voluptuous.Schema`` behavior."""

        def __init__(self, schema: Any | None = None) -> None:
            self.schema = schema

        def __call__(self, value: Any) -> Any:
            return value

    class _VoluptuousModule(ModuleType):
        Schema = _Schema

    vol = _VoluptuousModule("voluptuous")

# Previously this file filtered test collection to only run a single
# focused test. Remove that behavior so the pytest-homeassistant-custom-component
# runner and pytest-asyncio can control collection and execution.


_MODULE_NAME = "homeassistant.helpers.config_validation"
_PREVIOUS_MODULE = sys.modules.get(_MODULE_NAME)

root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

_config_validation_module = ModuleType(_MODULE_NAME)


def _empty_config_schema(domain: str) -> Any:
    return vol.Schema({domain: vol.Schema({})})


_config_validation_module.empty_config_schema = _empty_config_schema  # type: ignore[attr-defined]
sys.modules[_MODULE_NAME] = _config_validation_module


def pytest_configure(config: pytest.Config) -> None:
    """Register markers used throughout the test suite."""

    config.addinivalue_line(
        "markers", "asyncio: mark coroutine tests to execute via asyncio loop"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Provide a session-scoped event loop fallback.

    Pytest plugins such as pytest-asyncio or pytest-homeassistant-custom-component
    may provide their own event loop fixture. When present, pytest will prefer
    the plugin's fixture over this one. This function exists to avoid hard
    dependencies on plugin-provided fixtures in minimal test runs.
    """

    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop.close()


# Note: Do not provide a `hass` fixture here. The pytest-homeassistant-custom-component
# plugin exposes a full `hass` fixture tailored for Home Assistant integration
# tests. Defining a local `hass` fixture can unintentionally override the plugin
# fixture and break test discovery or execution. Tests that need a minimal test
# double should construct one explicitly in-test or use dedicated helper
# fixtures provided by the plugin.


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore any original config validation module when pytest exits."""

    if _PREVIOUS_MODULE is None:
        sys.modules.pop(_MODULE_NAME, None)
    else:
        sys.modules[_MODULE_NAME] = _PREVIOUS_MODULE


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Remove custom runner.

    The pytest-homeassistant-custom-component plugin provides its own
    asyncio and Home Assistant fixtures. Returning None here allows
    the standard pytest hooks and plugins to run tests normally.
    """

    return None
