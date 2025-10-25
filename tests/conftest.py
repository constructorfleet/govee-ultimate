"""Test configuration for path resolution and async helpers."""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: execute test in an event loop")


def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> Optional[bool]:
    if asyncio.iscoroutinefunction(pyfuncitem.obj):
        marker = pyfuncitem.get_closest_marker("asyncio")
        if marker is not None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(pyfuncitem.obj(**pyfuncitem.funcargs))
            finally:
                asyncio.set_event_loop(None)
                loop.close()
            return True
    return None
