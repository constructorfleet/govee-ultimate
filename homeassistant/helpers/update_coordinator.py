"""Minimal DataUpdateCoordinator stub for tests."""

from __future__ import annotations

from typing import Any


class DataUpdateCoordinator:  # pragma: no cover - simple test stub
    """Minimal coordinator substitute for unit tests."""

    def __init__(
        self,
        hass: Any,
        logger: Any,
        name: str | None = None,
        update_interval: Any | None = None,
    ) -> None:
        """Initialize the test stub coordinator."""
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    async def async_request_refresh(self) -> None:  # pragma: no cover - stub
        """Request a refresh of the coordinator data."""
        return None

    def async_schedule_refresh(
        self, *args: Any, **kwargs: Any
    ) -> None:  # pragma: no cover - stub
        """Schedule a refresh of the coordinator data."""
        return None
