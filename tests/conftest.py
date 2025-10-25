"""Test configuration for path resolution and async helpers."""

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest."""
    config.addinivalue_line("markers", "asyncio: execute test in an event loop")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config._govee_loop = loop  # type: ignore[attr-defined]


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    """Pytext function call."""
    if asyncio.iscoroutinefunction(pyfuncitem.obj):
        marker = pyfuncitem.get_closest_marker("asyncio")
        if marker is not None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(pyfuncitem.obj(**pyfuncitem.funcargs))
            finally:
                default_loop = getattr(pyfuncitem.config, "_govee_loop", None)
                asyncio.set_event_loop(default_loop)
                loop.close()
            return True
    return None


def pytest_unconfigure(config: pytest.Config) -> None:
    """Tear down resources created during configuration."""

    loop = getattr(config, "_govee_loop", None)
    if loop is not None:
        loop.close()
