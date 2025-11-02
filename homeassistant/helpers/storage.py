"""Lightweight implementation of Home Assistant's storage helper for tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Store:
    """Persist dictionaries to Home Assistant-style storage files."""

    def __init__(
        self,
        hass,
        version: int,
        key: str,
        *,
        private: bool = False,
    ) -> None:
        """Initialise the store with Home Assistant-style metadata."""

        self.hass = hass
        self.version = version
        self.key = key
        self.private = private
        # Mirror Home Assistant's storage layout under `.storage/<key>`
        self._path = Path(hass.config.path(".storage", key))
        self._minor_version = 1

    async def async_load(self) -> dict[str, Any] | None:
        """Load a stored JSON payload if available."""

        if not self._path.exists():
            return None

        def _read() -> dict[str, Any] | None:
            text = self._path.read_text()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return None
            if isinstance(data, dict) and "data" in data:
                inner = data.get("data")
                return inner if isinstance(inner, dict) else None
            return data if isinstance(data, dict) else None

        return await self.hass.async_add_executor_job(_read)

    async def async_save(self, data: dict[str, Any]) -> None:
        """Persist ``data`` to disk using the storage envelope."""

        def _write() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            envelope = {
                "version": self.version,
                "minor_version": self._minor_version,
                "key": self.key,
                "data": data,
            }
            self._path.write_text(json.dumps(envelope))

        await self.hass.async_add_executor_job(_write)

    async def async_remove(self) -> None:
        """Delete the stored file if present."""

        def _remove() -> None:
            if self._path.exists():
                self._path.unlink()

        await self.hass.async_add_executor_job(_remove)


__all__ = ["Store"]
