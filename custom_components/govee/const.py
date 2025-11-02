"""Constants for the Govee integration."""

# Avoid importing modules that depend on this package at import-time to
# prevent circular import problems during tests. Import locally where used.

from datetime import timedelta
from typing import TYPE_CHECKING

# Do not import Home Assistant helpers at module import time. Some test
# environments stub parts of Home Assistant and importing the real
# helpers can trigger package initialization that fails during pytest
# collection. Import lazily or use a safe fallback.
DOMAIN = "govee"

if TYPE_CHECKING:  # pragma: no cover - typing only
    import homeassistant.helpers.config_validation as cv  # noqa: F401

try:
    import homeassistant.helpers.config_validation as cv

    _empty_schema = getattr(cv, "empty_config_schema", lambda domain: {})
    CONFIG_SCHEMA = _empty_schema(DOMAIN)
except Exception:
    # Fallback for test environments without HA helpers: provide a
    # no-op config schema so imports succeed.
    CONFIG_SCHEMA = {}
SERVICE_REAUTHENTICATE = "reauthenticate"
TOKEN_REFRESH_INTERVAL = timedelta(minutes=5)
_SERVICES_KEY = f"{DOMAIN}_services_registered"
