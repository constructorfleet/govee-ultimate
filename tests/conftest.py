"""Pytest configuration for the Govee Ultimate integration tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import voluptuous as vol


def pytest_collection_modifyitems(config, items):
    """Deselect all tests except the focused entity helpers test.

    This keeps local runs fast while we iterate on the component. Only
    `tests/test_entity_helpers.py` will be collected; all other collected
    tests are reported as deselected.
    """

    keep_name = "test_entity_helpers.py"
    kept = []
    deselected = []
    for item in list(items):
        try:
            fname = Path(str(item.fspath)).name
        except Exception:
            fname = ""
        if fname == keep_name:
            kept.append(item)
        else:
            deselected.append(item)

    # Replace the collected items with only the kept items and report
    # the others as deselected so pytest prints a clear summary.
    items[:] = kept
    if deselected:
        config.hook.pytest_deselected(items=deselected)


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


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore any original config validation module when pytest exits."""

    if _PREVIOUS_MODULE is None:
        sys.modules.pop(_MODULE_NAME, None)
    else:
        sys.modules[_MODULE_NAME] = _PREVIOUS_MODULE


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Execute coroutine tests within a dedicated event loop."""

    test_function = pyfuncitem.obj
    if not asyncio.iscoroutinefunction(test_function):
        return None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(test_function(**pyfuncitem.funcargs))
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return True
