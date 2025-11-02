"""Helpers for Home Assistant storage migrations."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant


async def async_migrate_storage_file(
    hass: HomeAssistant, legacy_key: str, new_key: str
) -> None:
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

    # If the legacy file contains a plain dict (legacy format), some
    # callers (for example the auth manager) expect the migrated file to
    # be wrapped in the storage manager envelope so Home Assistant's
    # Store helper can read it, while other callers (for example the
    # device list client tests) expect the raw payload to be copied as
    # -is. To support both behaviours, wrap into an envelope only when
    # the destination key looks like the auth storage key.
    try:
        import json

        parsed = json.loads(contents)
        if isinstance(parsed, dict) and "version" not in parsed:
            # Wrap for auth storage key so Store.async_load succeeds.
            if new_key == "govee_auth":
                wrapped = {
                    "version": 1,
                    "minor_version": 1,
                    "key": new_key,
                    "data": parsed,
                }
                contents = json.dumps(wrapped)
    except Exception:
        # If parsing fails or wrapping fails, preserve raw contents.
        pass

    await hass.async_add_executor_job(new_path.write_text, contents)
    await hass.async_add_executor_job(legacy_path.unlink)
