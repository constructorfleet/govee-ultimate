"""Simplified storage helper mirroring Home Assistant's API."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

DEFAULT_ENCODING = "utf-8"


class Store:
    """Persist data under the Home Assistant configuration directory."""

    def __init__(
        self,
        hass: Any,
        version: int,
        key: str,
        private: bool = False,
    ) -> None:
        """Prepare a storage helper for the given Home Assistant instance."""

        self.hass = hass
        self.version = version
        self.key = key
        self.private = private
        self._path = Path(hass.config.config_dir) / ".storage" / key

    async def async_load(self) -> Any:
        """Load the JSON document if it exists."""

        if not self._path.exists():
            return None

        def _read() -> Any:
            with self._path.open("r", encoding=DEFAULT_ENCODING) as file:
                return json.load(file)

        return await self.hass.async_add_executor_job(_read)

    async def async_save(self, data: Any) -> None:
        """Persist the JSON document to disk."""

        self._path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            with self._path.open("w", encoding=DEFAULT_ENCODING) as file:
                json.dump(data, file)

        await self.hass.async_add_executor_job(_write)

    async def async_remove(self) -> None:
        """Remove the stored file if present."""

        if not self._path.exists():
            return

        def _remove() -> None:
            with contextlib.suppress(FileNotFoundError):
                self._path.unlink()

        await self.hass.async_add_executor_job(_remove)
