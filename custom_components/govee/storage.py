"""Helpers for Home Assistant storage migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def async_migrate_storage_file(hass: Any, legacy_key: str, new_key: str) -> None:
    """Copy a legacy `.storage` file to a new key and remove the original."""

    storage_dir = Path(hass.config.config_dir) / ".storage"
    legacy_path = storage_dir / legacy_key
    if not legacy_path.exists():
        return

    await hass.async_add_executor_job(
        lambda: storage_dir.mkdir(parents=True, exist_ok=True)
    )
    new_path = storage_dir / new_key
    contents = await hass.async_add_executor_job(legacy_path.read_text)
    await hass.async_add_executor_job(new_path.write_text, contents)
    await hass.async_add_executor_job(legacy_path.unlink)
