"""Unit tests for the Ultimate Govee state catalog dataset."""

from custom_components.govee_ultimate.state_catalog import load_state_catalog


def test_power_state_entry_includes_identifiers_and_templates():
    """The power state entry captures opcodes and command templates."""

    catalog = load_state_catalog()
    power_entry = catalog.get_state("power")

    assert power_entry.op_type == "toggle"
    assert power_entry.identifiers["status"]["opcode"] == "0x01"
    assert power_entry.command_templates[0].name == "set_power"


def test_rgb_state_payload_layout_is_documented():
    """RGB state metadata exposes payload layout information."""

    catalog = load_state_catalog()
    rgb_entry = catalog.get_state("color_rgb")

    assert rgb_entry.op_type == "color"
    assert rgb_entry.parse_options["payload_format"]["order"] == [
        "red",
        "green",
        "blue",
    ]
    assert rgb_entry.status_templates[0]["expect_bytes"] == 7


def test_presence_detection_settings_mark_multi_step_sequence():
    """Presence detection settings declare their multi-step write sequence."""

    catalog = load_state_catalog()
    detection_entry = catalog.get_state("presence_detection_settings")

    assert detection_entry.identifiers["status"]["sequence"] == ["0x11", "0x12"]
    assert detection_entry.command_templates[0].multi_step is not None
    assert len(detection_entry.command_templates[0].multi_step) == 2


def test_detection_settings_entry_declares_multi_step_payloads():
    """Detection settings include preamble and value commands."""

    catalog = load_state_catalog()
    detection_entry = catalog.get_state("detection_settings")

    assert detection_entry.identifiers["command"]["sequence"] == ["0x33", "0x33"]
    assert len(detection_entry.command_templates) == 2
    assert detection_entry.command_templates[0].multi_step is not None


def test_enable_presence_entry_maps_boolean_flags():
    """Enable presence metadata documents boolean flag layout."""

    catalog = load_state_catalog()
    enable_entry = catalog.get_state("enable_presence")

    assert enable_entry.identifiers["status"]["opcode"] == "0x1F"
    assert enable_entry.command_templates[0].opcode == "0x33"


def test_state_catalog_module_is_documented():
    """Modules, models, and stubs carry documentation strings."""

    import custom_components.govee_ultimate.state_catalog as module
    import pydantic

    assert module.__doc__
    assert module.CommandTemplate.__doc__
    assert module.StateEntry.__doc__
    assert module.StateCatalog.__doc__
    assert pydantic.__doc__
    assert pydantic.BaseModel.__doc__
    assert pydantic.Field.__doc__


def test_pydantic_dependency_reports_v2_version():
    """The project installs Pydantic 2.x from PyPI rather than a local stub."""

    import pydantic

    assert pydantic.version.VERSION.startswith("2."), pydantic.version.VERSION


def test_air_quality_catalog_entries_document_measurements() -> None:
    """Air quality states should describe their measurement payload layout."""

    catalog = load_state_catalog()

    temperature_entry = catalog.get_state("air_quality_temperature")
    assert temperature_entry.parse_options["measurement"]["fields"] == [
        "current",
        "calibration",
        "min",
        "max",
    ]

    humidity_entry = catalog.get_state("air_quality_humidity")
    assert humidity_entry.parse_options["measurement"]["range"]["max"] == 100

    pm_entry = catalog.get_state("air_quality_pm25")
    assert pm_entry.parse_options["measurement"]["warning_flag"] == "warning"
