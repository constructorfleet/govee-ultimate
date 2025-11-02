"""Minimal httpx client helper stub."""

from __future__ import annotations

import httpx


def get_async_client(_hass) -> httpx.AsyncClient:
    """Return a new AsyncClient for tests."""

    return httpx.AsyncClient()


__all__ = ["get_async_client"]
