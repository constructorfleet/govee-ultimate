"""Test configuration for path resolution and async helpers."""

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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

    storage_module = ModuleType("homeassistant.helpers.storage")

    class _Store:
        """Minimal storage helper used for style tests."""

        def __init__(
            self,
            hass: Any,
            _version: int,
            key: str,
            *,
            private: bool = False,
        ) -> None:
            """Prepare file path for storage operations."""

            storage_dir = Path(hass.config.config_dir)
            if private:
                storage_dir = storage_dir / ".storage"
            self._hass = hass
            self._path = storage_dir / key

        async def async_remove(self) -> None:
            """Silently ignore missing files when removing."""

            with contextlib.suppress(FileNotFoundError):
                await self._hass.async_add_executor_job(self._path.unlink)

        async def async_load(self) -> dict[str, Any] | None:
            """Load JSON data from disk."""

            if not self._path.exists():
                return None
            text = await self._hass.async_add_executor_job(self._path.read_text)
            return json.loads(text)

        async def async_save(self, data: dict[str, Any]) -> None:
            """Persist JSON data to disk."""

            def _write() -> None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(data))

            await self._hass.async_add_executor_job(_write)

    storage_module.Store = _Store

    helpers_module = ModuleType("homeassistant.helpers")
    helpers_module.storage = storage_module

    homeassistant_module = ModuleType("homeassistant")
    homeassistant_module.helpers = helpers_module

    sys.modules.setdefault("homeassistant", homeassistant_module)
    sys.modules.setdefault("homeassistant.helpers", helpers_module)
    sys.modules.setdefault("homeassistant.helpers.storage", storage_module)


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
