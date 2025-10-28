"""Ensure integration blueprint template is removed."""

from pathlib import Path


def test_integration_blueprint_package_removed():
    """The integration blueprint placeholder folder should not be present."""
    integration_blueprint_path = Path("custom_components") / "integration_blueprint"
    assert not integration_blueprint_path.exists()
