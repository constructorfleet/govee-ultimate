"""Minimal subset of Home Assistant namespace for testing.

This file exposes a module-level __getattr__ that lazily imports
submodules on demand (for example `homeassistant.helpers`). Tests in
the repo import submodules like `homeassistant.helpers.config_validation`.
The lazy importer ensures those imports resolve to the local test stubs
under the `homeassistant` package directory.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazily import and return a submodule like `homeassistant.helpers`.

    This mirrors how real Home Assistant exposes subpackages while keeping
    the test stubs lightweight.
    """

    full_name = f"homeassistant.{name}"
    try:
        module = importlib.import_module(full_name)
    except Exception:  # pragma: no cover - defensive for test environment
        raise
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    # Make introspection show the lazily-imported children when available
    return ["helpers", "core", "config_entries"]


def _ensure_event_loop() -> None:
    """Ensure an asyncio event loop exists for environments that import at module level.

    Some tests and modules call asyncio.get_event_loop() during import; ensure
    this returns a valid loop instead of raising RuntimeError.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


# Ensure a default loop exists for tests that expect it during import time.
_ensure_event_loop()
