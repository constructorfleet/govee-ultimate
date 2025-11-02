"""Minimal core stubs required by the integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SupportsAsyncExecutor(Protocol):
    """Protocol exposing the executor helper used by Store."""

    async def async_add_executor_job(self, func, *args) -> Any:  # type: ignore[no-untyped-def]
        """Execute ``func`` in an executor."""


@dataclass
class HomeAssistant:
    """Placeholder ``HomeAssistant`` type for typing compatibility."""

    loop: Any
    config: Any

    async def async_add_executor_job(self, func, *args):  # type: ignore[no-untyped-def]
        """Delegate to the provided helper on the config object if available."""

        helper = getattr(self.config, "async_add_executor_job", None)
        if callable(helper):
            return await helper(func, *args)
        raise NotImplementedError


__all__ = ["HomeAssistant"]
