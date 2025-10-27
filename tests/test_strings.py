"""Ensure Home Assistant strings metadata is present."""

from __future__ import annotations

import json
from pathlib import Path

FIELDS = (
    "email",
    "password",
    "enable_iot",
    "enable_iot_state_updates",
    "enable_iot_commands",
    "enable_iot_refresh",
)


def test_config_flow_strings_define_user_step_fields() -> None:
    """The strings file should describe the user step inputs."""

    strings_path = Path("custom_components/govee_ultimate/strings.json")
    translations_path = Path("custom_components/govee_ultimate/translations/en.json")

    assert strings_path.exists(), "Missing strings.json for the integration"
    assert translations_path.exists(), "Missing default translation file"

    strings = json.loads(strings_path.read_text(encoding="utf-8"))
    user_step = strings["config"]["step"]["user"]["data"]
    for field in FIELDS:
        assert field in user_step

    translations = json.loads(translations_path.read_text(encoding="utf-8"))
    assert "config" in translations
