"""Device type integration tests."""

from __future__ import annotations

import pytest

from custom_components.govee_ultimate.device_types.humidifier import HumidifierDevice
from custom_components.govee_ultimate.device_types.purifier import PurifierDevice
from custom_components.govee_ultimate.device_types.rgbic_light import RGBICLightDevice
from custom_components.govee_ultimate.state import (
    BrightnessState,
    ColorRGBState,
    ModeState,
    PowerState,
)


class MockDeviceModel:
    """Minimal device model supporting device factory tests."""

    def __init__(
        self,
        *,
        model: str,
        sku: str,
        category: str,
        category_group: str,
        model_name: str,
    ) -> None:
        """Store identifying metadata for simulated devices."""

        self.model = model
        self.sku = sku
        self.category = category
        self.category_group = category_group
        self.model_name = model_name


@pytest.fixture
def rgbic_device_model() -> MockDeviceModel:
    """Return a device model matching an RGBIC strip light."""

    return MockDeviceModel(
        model="H6099",
        sku="H6099",
        category="LED Strip Light",
        category_group="RGBIC Strip Lights",
        model_name="Govee RGBIC Strip Light",
    )


@pytest.fixture
def humidifier_model_h7141() -> MockDeviceModel:
    """Return metadata for humidifier model H7141."""

    return MockDeviceModel(
        model="H7141",
        sku="H7141",
        category="Home Appliances",
        category_group="Air Treatment",
        model_name="Smart Humidifier",
    )


@pytest.fixture
def humidifier_model_h7142() -> MockDeviceModel:
    """Return metadata for humidifier model H7142."""

    return MockDeviceModel(
        model="H7142",
        sku="H7142",
        category="Home Appliances",
        category_group="Air Treatment",
        model_name="Smart Humidifier Pro",
    )


@pytest.fixture
def purifier_model_default() -> MockDeviceModel:
    """Return metadata for a standard purifier."""

    return MockDeviceModel(
        model="H7120",
        sku="H7120",
        category="Home Appliances",
        category_group="Air Treatment",
        model_name="Smart Air Purifier",
    )


@pytest.fixture
def purifier_model_h7126() -> MockDeviceModel:
    """Return metadata for purifier model H7126 with bespoke states."""

    return MockDeviceModel(
        model="H7126",
        sku="H7126",
        category="Home Appliances",
        category_group="Air Treatment",
        model_name="H7126 Purifier",
    )


def test_rgbic_light_registers_expected_states(
    rgbic_device_model: MockDeviceModel,
) -> None:
    """RGBIC devices should expose the expected core light states."""

    device = RGBICLightDevice(rgbic_device_model)

    states = device.states
    assert set(states) >= {"power", "active", "brightness", "color"}
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["brightness"], BrightnessState)
    assert isinstance(states["color"], ColorRGBState)

    mode_state = device.mode_state
    assert isinstance(mode_state, ModeState)
    mode_names = {mode.name for mode in mode_state.modes}
    assert mode_names == {
        "color_whole",
        "color_segment",
        "scene",
        "mic",
        "diy",
    }

    light_entities = device.light_entities
    assert light_entities.primary is states["power"]
    assert set(light_entities.supporting) == {
        states["brightness"],
        states["color"],
    }


def test_device_states_expose_home_assistant_entities(
    rgbic_device_model: MockDeviceModel,
    humidifier_model_h7142: MockDeviceModel,
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Each device should expose a Home Assistant entity mapping per state."""

    light_device = RGBICLightDevice(rgbic_device_model)
    humidifier_device = HumidifierDevice(humidifier_model_h7142)
    purifier_device = PurifierDevice(purifier_model_h7126)

    light_entities = light_device.home_assistant_entities
    assert {"power", "brightness", "color", "mode"} <= set(light_entities)
    assert light_entities["power"].platform == "light"
    assert light_entities["power"].state is light_device.states["power"]
    assert light_entities["mode"].platform == "select"

    humidifier_entities = humidifier_device.home_assistant_entities
    assert {"power", "mist_level", "target_humidity", "night_light", "uvc"} <= set(
        humidifier_entities
    )
    assert humidifier_entities["power"].platform == "humidifier"
    assert humidifier_entities["mist_level"].platform == "number"
    assert humidifier_entities["night_light"].platform == "light"
    assert humidifier_entities["uvc"].platform == "switch"
    assert humidifier_entities["humidity"].platform == "sensor"

    purifier_entities = purifier_device.home_assistant_entities
    assert {"power", "fan_speed", "mode", "filter_life"} <= set(purifier_entities)
    assert purifier_entities["power"].platform == "fan"
    assert purifier_entities["mode"].platform == "select"
    assert purifier_entities["fan_speed"].platform == "number"
    assert purifier_entities["filter_life"].platform == "sensor"


def test_humidifier_includes_model_specific_states(
    humidifier_model_h7141: MockDeviceModel,
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Humidifiers should register model-specific supplemental states."""

    device_h7141 = HumidifierDevice(humidifier_model_h7141)
    device_h7142 = HumidifierDevice(humidifier_model_h7142)

    assert {"night_light", "control_lock"} <= set(device_h7141.states)
    assert "uvc" not in device_h7141.states

    assert {"night_light", "display_schedule", "uvc", "humidity"} <= set(
        device_h7142.states
    )


def test_humidifier_mode_interlocks_gate_mist_levels(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Mist level writes should depend on the active humidifier mode."""

    device = HumidifierDevice(humidifier_model_h7142)

    mist_state = device.states["mist_level"]
    target_state = device.states["target_humidity"]

    device.mode_state.activate("manual_mode")
    assert mist_state.set_state(40) == ["mist_level"]
    assert mist_state.value == 40
    assert target_state.set_state(55) == []

    device.mode_state.activate("auto_mode")
    assert mist_state.set_state(20) == []
    assert target_state.set_state(60) == ["target_humidity"]


def test_purifier_model_specific_states(
    purifier_model_default: MockDeviceModel,
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Purifier models should customise their state loadout."""

    default_device = PurifierDevice(purifier_model_default)
    h7126_device = PurifierDevice(purifier_model_h7126)

    assert {"fan_speed", "night_light", "control_lock"} <= set(default_device.states)
    assert "filter_life" not in default_device.states

    assert {"manual_mode", "custom_mode", "filter_life", "timer"} <= set(
        h7126_device.states
    )
    assert "fan_speed" in h7126_device.states


def test_purifier_fan_speed_respects_active_modes(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Fan speed adjustments should be locked unless manual/custom are active."""

    device = PurifierDevice(purifier_model_h7126)
    fan_speed = device.states["fan_speed"]

    device.mode_state.activate("manual_mode")
    assert fan_speed.set_state(3) == ["fan_speed"]

    device.mode_state.activate("auto_mode")
    assert fan_speed.set_state(1) == []
