"""Device type integration tests."""

from __future__ import annotations

import pytest

from custom_components.govee_ultimate.device_types.base import EntityCategory
from custom_components.govee_ultimate.device_types.air_quality import AirQualityDevice
from custom_components.govee_ultimate.device_types.humidifier import HumidifierDevice
from custom_components.govee_ultimate.device_types.ice_maker import IceMakerDevice
from custom_components.govee_ultimate.device_types.hygrometer import HygrometerDevice
from custom_components.govee_ultimate.device_types.presence import PresenceDevice
from custom_components.govee_ultimate.device_types.purifier import PurifierDevice
from custom_components.govee_ultimate.device_types.rgb_light import RGBLightDevice
from custom_components.govee_ultimate.device_types.rgbic_light import RGBICLightDevice
from custom_components.govee_ultimate.state import (
    ActiveState,
    BatteryLevelState,
    BiologicalPresenceState,
    BrightnessState,
    ColorRGBState,
    ConnectedState,
    DetectionSettingsState,
    EnablePresenceState,
    HumidityState,
    MMWavePresenceState,
    ModeState,
    PowerState,
    TemperatureState,
)
from custom_components.govee_ultimate.state.states import (
    ColorTemperatureState,
    ControlLockState,
    DisplayScheduleState,
    DiyModeState,
    IceMakerBasketFullState,
    IceMakerMakingIceState,
    IceMakerNuggetSizeState,
    IceMakerScheduledStartState,
    IceMakerStatusState,
    IceMakerTemperatureState,
    IceMakerWaterEmptyState,
    FilterExpiredState,
    FilterLifeState,
    AirQualityHumidityState,
    AirQualityPM25State,
    AirQualityTemperatureState,
    LightEffectState,
    MicModeState,
    NightLightState,
    SegmentColorState,
    SceneModeState,
    TimerState,
    WaterShortageState,
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
def rgb_light_device_model() -> MockDeviceModel:
    """Return a device model matching a standard RGB light."""

    return MockDeviceModel(
        model="H6003",
        sku="H6003",
        category="LED Strip Light",
        category_group="RGB Strip Lights",
        model_name="Govee RGB Light",
    )


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


@pytest.fixture
def air_quality_model() -> MockDeviceModel:
    """Return metadata for an air quality monitor."""

    return MockDeviceModel(
        model="H6601",
        sku="H6601",
        category="Air Quality Monitor",
        category_group="Air Quality",
        model_name="Air Quality Monitor",
    )


@pytest.fixture
def hygrometer_model() -> MockDeviceModel:
    """Return metadata for a hygrometer device."""

    return MockDeviceModel(
        model="H5075",
        sku="H5075",
        category="Thermo-Hygrometer",
        category_group="Thermo-Hygrometers",
        model_name="Smart Hygrometer",
    )


@pytest.fixture
def presence_sensor_model() -> MockDeviceModel:
    """Return metadata for a presence detection sensor."""

    return MockDeviceModel(
        model="H5109",
        sku="H5109",
        category="Presence Sensor",
        category_group="Presence Sensors",
        model_name="Smart Presence Sensor",
    )


@pytest.fixture
def ice_maker_model() -> MockDeviceModel:
    """Return metadata for a countertop ice maker."""

    return MockDeviceModel(
        model="H7172",
        sku="H7172",
        category="Home Appliances",
        category_group="Kitchen",
        model_name="Smart Countertop Ice Maker",
    )


def test_presence_device_registers_presence_states_and_entities(
    presence_sensor_model: MockDeviceModel,
) -> None:
    """Presence sensors should expose detection and tuning controls."""

    device = PresenceDevice(presence_sensor_model)

    states = device.states
    assert set(states) >= {
        "power",
        "isConnected",
        "presence-mmWave",
        "presence-biological",
        "enablePresence",
        "detectionSettings",
        "presenceEnable-mmWave",
        "presenceEnable-biological",
        "detectionDistance",
        "absenceDuration",
        "reportDetection",
    }
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["presence-mmWave"], MMWavePresenceState)
    assert isinstance(states["presence-biological"], BiologicalPresenceState)
    assert isinstance(states["enablePresence"], EnablePresenceState)
    assert isinstance(states["detectionSettings"], DetectionSettingsState)

    entities = device.home_assistant_entities
    assert entities["power"].platform == "switch"

    connected_entity = entities["isConnected"]
    assert connected_entity.platform == "binary_sensor"
    assert connected_entity.translation_key == "connected"
    assert connected_entity.entity_category is EntityCategory.DIAGNOSTIC

    mmwave_entity = entities["presence-mmWave"]
    assert mmwave_entity.platform == "binary_sensor"
    assert mmwave_entity.translation_key == "presence_mmwave"

    biological_entity = entities["presence-biological"]
    assert biological_entity.platform == "binary_sensor"
    assert biological_entity.translation_key == "presence_biological"

    mmwave_enable_entity = entities["presenceEnable-mmWave"]
    assert mmwave_enable_entity.platform == "switch"
    assert mmwave_enable_entity.translation_key == "presence_mmwave_enabled"

    biological_enable_entity = entities["presenceEnable-biological"]
    assert biological_enable_entity.platform == "switch"
    assert biological_enable_entity.translation_key == "presence_biological_enabled"

    detection_distance = entities["detectionDistance"]
    assert detection_distance.platform == "number"
    assert detection_distance.translation_key == "presence_detection_distance"
    assert detection_distance.entity_category is EntityCategory.CONFIG

    absence_duration = entities["absenceDuration"]
    assert absence_duration.platform == "number"
    assert absence_duration.translation_key == "presence_absence_duration"
    assert absence_duration.entity_category is EntityCategory.CONFIG

    report_detection = entities["reportDetection"]
    assert report_detection.platform == "number"
    assert report_detection.translation_key == "presence_report_interval"
    assert report_detection.entity_category is EntityCategory.CONFIG


def test_presence_enable_switches_forward_commands(
    presence_sensor_model: MockDeviceModel,
) -> None:
    """Proxy switches should route commands through the enable state."""

    device = PresenceDevice(presence_sensor_model)
    enable_state = device.states["enablePresence"]
    mmwave_switch = device.states["presenceEnable-mmWave"]
    biological_switch = device.states["presenceEnable-biological"]

    enable_state._update_state(  # type: ignore[attr-defined]
        {"biologicalEnabled": True, "mmWaveEnabled": False}
    )
    assert mmwave_switch.value is False
    assert biological_switch.value is True

    mmwave_commands = mmwave_switch.set_state(True)
    assert len(mmwave_commands) == 1
    mmwave_payload = mmwave_switch.command_queue.get_nowait()
    assert mmwave_payload["command_id"] == mmwave_commands[0]
    assert mmwave_payload["command"] == "multi_sync"
    assert enable_state.command_queue.empty()

    enable_state._update_state(  # type: ignore[attr-defined]
        {"biologicalEnabled": False, "mmWaveEnabled": True}
    )
    assert mmwave_switch.value is True
    assert biological_switch.value is False

    biological_commands = biological_switch.set_state(True)
    assert len(biological_commands) == 1
    biological_payload = biological_switch.command_queue.get_nowait()
    assert biological_payload["command_id"] == biological_commands[0]
    assert biological_payload["command"] == "multi_sync"
    assert enable_state.command_queue.empty()


def test_ice_maker_device_registers_states_and_entities(
    ice_maker_model: MockDeviceModel,
) -> None:
    """Ice maker devices should expose specialised states and entities."""

    device = IceMakerDevice(ice_maker_model)

    states = device.states
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["active"], ActiveState)
    assert isinstance(states["temperature"], IceMakerTemperatureState)
    assert isinstance(states["nuggetSize"], IceMakerNuggetSizeState)
    assert isinstance(states["basketFull"], IceMakerBasketFullState)
    assert isinstance(states["waterShortage"], IceMakerWaterEmptyState)
    assert isinstance(states["iceMakerStatus"], IceMakerStatusState)
    assert isinstance(states["scheduledStart"], IceMakerScheduledStartState)
    assert isinstance(states["makeIce"], IceMakerMakingIceState)
    assert states["water_shortage"] is states["waterShortage"]

    entities = device.home_assistant_entities
    assert entities["power"].platform == "switch"

    connected_entity = entities["isConnected"]
    assert connected_entity.platform == "binary_sensor"
    assert connected_entity.entity_category is EntityCategory.DIAGNOSTIC

    active_entity = entities["active"]
    assert active_entity.platform == "binary_sensor"
    assert active_entity.entity_category is EntityCategory.DIAGNOSTIC

    basket_entity = entities["basketFull"]
    assert basket_entity.platform == "binary_sensor"
    assert basket_entity.entity_category is EntityCategory.DIAGNOSTIC

    water_entity = entities["waterShortage"]
    assert water_entity.platform == "binary_sensor"
    assert water_entity.entity_category is EntityCategory.DIAGNOSTIC

    status_entity = entities["iceMakerStatus"]
    assert status_entity.platform == "sensor"
    assert status_entity.entity_category is None

    temperature_entity = entities["temperature"]
    assert temperature_entity.platform == "sensor"
    assert temperature_entity.entity_category is EntityCategory.DIAGNOSTIC


def test_hygrometer_registers_expected_states_and_entities(
    hygrometer_model: MockDeviceModel,
) -> None:
    """Hygrometer devices should expose climate sensors and diagnostics."""

    device = HygrometerDevice(hygrometer_model)

    states = device.states
    assert set(states) >= {
        "power",
        "isConnected",
        "temperature",
        "humidity",
        "batteryLevel",
    }
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["temperature"], TemperatureState)
    assert isinstance(states["humidity"], HumidityState)
    assert isinstance(states["batteryLevel"], BatteryLevelState)

    entities = device.home_assistant_entities
    assert entities["power"].platform == "switch"

    connected_entity = entities["isConnected"]
    assert connected_entity.platform == "binary_sensor"
    assert connected_entity.translation_key == "connected"
    assert connected_entity.entity_category is EntityCategory.DIAGNOSTIC

    temperature_entity = entities["temperature"]
    assert temperature_entity.platform == "sensor"
    assert temperature_entity.translation_key == "temperature"

    humidity_entity = entities["humidity"]
    assert humidity_entity.platform == "sensor"
    assert humidity_entity.translation_key == "humidity"

    battery_entity = entities["batteryLevel"]
    assert battery_entity.platform == "sensor"
    assert battery_entity.translation_key == "battery"
    assert battery_entity.entity_category is EntityCategory.DIAGNOSTIC


def test_rgbic_light_registers_expected_states(
    rgbic_device_model: MockDeviceModel,
) -> None:
    """RGBIC devices should expose the expected core light states."""

    device = RGBICLightDevice(rgbic_device_model)

    states = device.states
    assert set(states) >= {
        "power",
        "active",
        "brightness",
        "color",
        "colorTemperature",
        "segmentColor",
        "lightEffect",
        "micMode",
        "diyMode",
    }
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["brightness"], BrightnessState)
    assert isinstance(states["color"], ColorRGBState)
    assert isinstance(states["colorTemperature"], ColorTemperatureState)
    assert isinstance(states["segmentColor"], SegmentColorState)
    assert isinstance(states["lightEffect"], LightEffectState)
    assert isinstance(states["micMode"], MicModeState)
    assert isinstance(states["diyMode"], DiyModeState)

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
        states["colorTemperature"],
        states["segmentColor"],
    }


def test_rgb_light_registers_expected_states(
    rgb_light_device_model: MockDeviceModel,
) -> None:
    """RGB devices should expose the expected core light states."""

    device = RGBLightDevice(rgb_light_device_model)

    states = device.states
    assert {
        "power",
        "isConnected",
        "active",
        "brightness",
        "color",
        "colorTemperature",
        "sceneMode",
    } <= set(states)
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["active"], ActiveState)
    assert isinstance(states["brightness"], BrightnessState)
    assert isinstance(states["color"], ColorRGBState)
    assert isinstance(states["colorTemperature"], ColorTemperatureState)
    assert isinstance(states["sceneMode"], SceneModeState)

    light_entities = device.light_entities
    assert light_entities.primary is states["power"]
    assert set(light_entities.supporting) == {
        states["brightness"],
        states["color"],
        states["colorTemperature"],
    }

    ha_entities = device.home_assistant_entities
    assert ha_entities["power"].platform == "light"
    assert ha_entities["brightness"].platform == "light"
    assert ha_entities["color"].platform == "light"
    assert ha_entities["colorTemperature"].platform == "light"
    assert ha_entities["isConnected"].platform == "binary_sensor"
    assert ha_entities["active"].platform == "binary_sensor"


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
    assert {
        "power",
        "brightness",
        "color",
        "colorTemperature",
        "segmentColor",
        "mode",
        "lightEffect",
        "micMode",
        "diyMode",
    } <= set(light_entities)
    assert light_entities["power"].platform == "light"
    assert light_entities["power"].state is light_device.states["power"]
    assert light_entities["brightness"].platform == "light"
    assert light_entities["colorTemperature"].platform == "light"
    assert light_entities["segmentColor"].platform == "light"
    assert light_entities["mode"].platform == "select"
    assert light_entities["lightEffect"].platform == "select"
    assert light_entities["micMode"].platform == "select"
    assert light_entities["diyMode"].platform == "select"

    humidifier_entities = humidifier_device.home_assistant_entities
    assert {
        "power",
        "mistLevel",
        "targetHumidity",
        "nightLight",
        "uvc",
        "displaySchedule",
        "controlLock",
        "humidity",
    } <= set(humidifier_entities)
    assert humidifier_entities["power"].platform == "humidifier"
    assert humidifier_entities["mistLevel"].platform == "number"
    assert humidifier_entities["targetHumidity"].platform == "number"
    assert humidifier_entities["nightLight"].platform == "light"
    assert humidifier_entities["displaySchedule"].platform == "switch"
    assert humidifier_entities["controlLock"].platform == "switch"
    assert humidifier_entities["uvc"].platform == "switch"
    assert humidifier_entities["humidity"].platform == "sensor"

    purifier_entities = purifier_device.home_assistant_entities
    assert {
        "power",
        "fanSpeed",
        "mode",
        "displaySchedule",
        "controlLock",
        "timer",
        "filterLife",
        "filterExpired",
    } <= set(purifier_entities)
    assert purifier_entities["power"].platform == "fan"
    assert purifier_entities["mode"].platform == "select"
    assert purifier_entities["fanSpeed"].platform == "number"
    assert purifier_entities["displaySchedule"].platform == "switch"
    assert purifier_entities["controlLock"].platform == "switch"
    assert purifier_entities["timer"].platform == "switch"
    assert purifier_entities["filterLife"].platform == "sensor"
    assert purifier_entities["filterExpired"].platform == "binary_sensor"


def test_humidifier_includes_model_specific_states(
    humidifier_model_h7141: MockDeviceModel,
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Humidifiers should register model-specific supplemental states."""

    device_h7141 = HumidifierDevice(humidifier_model_h7141)
    device_h7142 = HumidifierDevice(humidifier_model_h7142)

    assert {"nightLight", "controlLock"} <= set(device_h7141.states)
    assert "uvc" not in device_h7141.states

    assert {"nightLight", "displaySchedule", "uvc", "humidity"} <= set(
        device_h7142.states
    )


def test_humidifier_registers_catalog_state_types(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Humidifiers should wire catalog-backed state implementations."""

    device = HumidifierDevice(humidifier_model_h7142)

    states = device.states
    assert isinstance(states["nightLight"], NightLightState)
    assert isinstance(states["displaySchedule"], DisplayScheduleState)
    assert isinstance(states["controlLock"], ControlLockState)
    assert isinstance(states["humidity"], HumidityState)
    assert isinstance(states["waterShortage"], WaterShortageState)

    shortage_entity = device.home_assistant_entities["waterShortage"]
    assert shortage_entity.translation_key == "water_shortage"
    assert shortage_entity.entity_category == EntityCategory.DIAGNOSTIC


def test_humidifier_mode_interlocks_gate_mist_levels(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Mist level writes should depend on the active humidifier mode."""

    device = HumidifierDevice(humidifier_model_h7142)

    mist_state = device.states["mistLevel"]
    target_state = device.states["targetHumidity"]

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

    assert {"fanSpeed", "nightLight", "controlLock"} <= set(default_device.states)
    assert "filterLife" not in default_device.states

    assert {
        "manual_mode",
        "custom_mode",
        "filterLife",
        "timer",
        "displaySchedule",
        "filterExpired",
    } <= set(h7126_device.states)
    assert "fanSpeed" in h7126_device.states


def test_purifier_registers_catalog_state_types(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Purifiers should wire catalog-backed control states."""

    device = PurifierDevice(purifier_model_h7126)
    states = device.states

    assert isinstance(states["displaySchedule"], DisplayScheduleState)
    assert isinstance(states["controlLock"], ControlLockState)
    assert isinstance(states["timer"], TimerState)
    assert isinstance(states["filterLife"], FilterLifeState)
    assert isinstance(states["filterExpired"], FilterExpiredState)


def test_purifier_fan_speed_respects_active_modes(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Fan speed adjustments should be locked unless manual/custom are active."""

    device = PurifierDevice(purifier_model_h7126)
    fan_speed = device.states["fanSpeed"]

    device.mode_state.activate("manual_mode")
    assert fan_speed.set_state(3) == ["fan_speed"]

    device.mode_state.activate("auto_mode")
    assert fan_speed.set_state(1) == []


def test_air_quality_device_registers_environment_states(
    air_quality_model: MockDeviceModel,
) -> None:
    """Air quality devices should expose power and measurement states."""

    device = AirQualityDevice(air_quality_model)

    states = device.states
    assert {"power", "isConnected", "temperature", "humidity", "pm25"} <= set(states)
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["temperature"], AirQualityTemperatureState)
    assert isinstance(states["humidity"], AirQualityHumidityState)
    assert isinstance(states["pm25"], AirQualityPM25State)

    ha_entities = device.home_assistant_entities
    assert ha_entities["power"].platform == "switch"
    assert ha_entities["isConnected"].platform == "binary_sensor"
    assert ha_entities["temperature"].platform == "sensor"
    assert ha_entities["humidity"].platform == "sensor"
    assert ha_entities["pm25"].platform == "sensor"
