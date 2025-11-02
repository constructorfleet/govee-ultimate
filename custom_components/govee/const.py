"""Constants for the Govee integration."""

# Avoid importing modules that depend on this package at import-time to
# prevent circular import problems during tests. Import locally where used.

from datetime import timedelta

import homeassistant.helpers.config_validation as cv

DOMAIN = "govee"
_empty_schema = getattr(cv, "empty_config_schema", lambda domain: {})
CONFIG_SCHEMA = _empty_schema(DOMAIN)
SERVICE_REAUTHENTICATE = "reauthenticate"
TOKEN_REFRESH_INTERVAL = timedelta(minutes=5)
_SERVICES_KEY = f"{DOMAIN}_services_registered"
