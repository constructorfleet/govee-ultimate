"""Minimal httpx client helper stub for tests."""

from __future__ import annotations

from typing import Any


def get_async_client(hass: Any, verify_ssl: bool = True) -> Any:
    """Return a simple httpx-like client or None in tests by default."""

    return None
