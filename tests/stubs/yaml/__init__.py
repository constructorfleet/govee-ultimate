"""Test stub providing the limited YAML API required for unit tests."""

from __future__ import annotations

from typing import Any

__all__ = ["safe_load"]


def safe_load(_: str) -> Any:  # pragma: no cover - placeholder implementation
    """Return an empty mapping for environments without PyYAML installed."""

    return {}
