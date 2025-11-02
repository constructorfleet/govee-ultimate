"""Minimal config_validation helper used by tests."""

from __future__ import annotations

from typing import Any


def empty_config_schema(domain: str) -> Any:
    """Return a minimal schema placeholder for tests."""

    return {domain: {}}
