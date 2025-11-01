"""Device type integration tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from custom_components.govee_ultimate.device_types.base import EntityCategory
from custom_components.govee_ultimate.device_types.air_quality import AirQualityDevice
from custom_components.govee_ultimate.device_types.humidifier import HumidifierDevice
from custom_components.govee_ultimate.device_types.ice_maker import IceMakerDevice
from custom_components.govee_ultimate.device_types.hygrometer import HygrometerDevice
from custom_components.govee_ultimate.device_types.presence import PresenceDevice
from custom_components.govee_ultimate.device_types.purifier import PurifierDevice
from custom_components.govee_ultimate.device_types.rgb_light import RGBLightDevice
from custom_components.govee_ultimate.device_types import (
    rgbic_light as rgbic_light_module,
)
from custom_components.govee_ultimate.device_types.meat_thermometer import (
    MeatThermometerDevice,
)
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
    BuzzerState,
    EarlyWarningEnabledState,
    EarlyWarningSettingState,
    PresetState,
    ProbeTempState,
    TemperatureUnitState,
    ManualModeState,
    CustomModeState,
    PurifierManualModeState,
    PurifierCustomModeState,
    PurifierActiveMode,
    AutoModeState,
    RGBICModes,
)


def _next_command_frame(state) -> list[int]:
    """Return the next queued command frame for assertions."""

    queued = state.command_queue.get_nowait()
    return queued["data"]["command"][0]


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


class _DummyManualModeState:
    """Stub manual mode state capturing mist level commands."""

    name = "manual_mode"

    def __init__(self) -> None:
        self.value: int | None = None
        self._listeners: list[Callable[[int | None], None]] = []
        self.commands: list[list[str]] = []

    def register_listener(self, callback: Callable[[int | None], None]) -> None:
        self._listeners.append(callback)

    def emit(self, value: int | None) -> None:
        self.value = value
        for listener in list(self._listeners):
            listener(value)

    def set_state(self, next_state: Any) -> list[str]:
        if not isinstance(next_state, int | float):
            raise TypeError(f"Unexpected manual payload: {next_state!r}")
        level = int(next_state)
        if level < 0:
            level = 0
        if level > 9:
            level = 9
        self.commands.append(["manual"])
        self.emit(level)
        return ["manual"]


class _DummyCustomModeState:
    """Stub custom mode state wiring mist level into program payloads."""

    name = "custom_mode"

    def __init__(self) -> None:
        self.value: dict[str, Any] | None = None
        self._listeners: list[Callable[[dict[str, Any] | None], None]] = []
        self.commands: list[list[str]] = []

    def register_listener(
        self, callback: Callable[[dict[str, Any] | None], None]
    ) -> None:
        self._listeners.append(callback)

    def emit(self, value: dict[str, Any] | None) -> None:
        self.value = value
        for listener in list(self._listeners):
            listener(value)

    def set_state(self, payload: Any) -> list[str]:
        assert isinstance(payload, dict)
        assert "mistLevel" in payload
        self.commands.append(["custom"])
        merged = dict(self.value or {})
        merged.update(payload)
        self.emit(merged)
        return ["custom"]


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
def meat_thermometer_model() -> MockDeviceModel:
    """Return metadata for meat thermometer devices."""

    return MockDeviceModel(
        model="H7480",
        sku="H7480",
        category="Home Improvement",
        category_group="Kitchen",
        model_name="WiFi Meat Thermometer",
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

    nugget_entity = entities["nuggetSize"]
    assert nugget_entity.platform == "select"
    assert nugget_entity.entity_category is None
    assert nugget_entity.options == ["SMALL", "MEDIUM", "LARGE"]

    make_ice_entity = entities["makeIce"]
    assert make_ice_entity.platform == "switch"
    assert make_ice_entity.entity_category is None

    status_entity = entities["iceMakerStatus"]
    assert status_entity.platform == "sensor"
    assert status_entity.entity_category is None

    temperature_entity = entities["temperature"]
    assert temperature_entity.platform == "sensor"
    assert temperature_entity.entity_category is EntityCategory.DIAGNOSTIC


def test_ice_maker_make_ice_switch_forwards_status_commands(
    ice_maker_model: MockDeviceModel,
) -> None:
    """Switch interactions should delegate commands to the status handler."""

    device = IceMakerDevice(ice_maker_model)
    make_ice_state = device.states["makeIce"]

    on_commands = make_ice_state.set_state(True)
    assert len(on_commands) == 1
    on_payload = make_ice_state.command_queue.get_nowait()
    assert on_payload["opcode"] == "0x33"
    assert on_payload["payload_hex"] == "1901"

    off_commands = make_ice_state.set_state(False)
    assert len(off_commands) == 1
    off_payload = make_ice_state.command_queue.get_nowait()
    assert off_payload["opcode"] == "0x33"
    assert off_payload["payload_hex"] == "1900"


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

    device = rgbic_light_module.RGBICLightDevice(rgbic_device_model)

    states = device.states
    assert set(states) >= {
        "power",
        "isConnected",
        "active",
        "brightness",
        "colorRGB",
        "color",
        "colorTemperature",
        "segmentColor",
        "lightEffect",
        "micMode",
        "diyMode",
    }
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["brightness"], BrightnessState)
    assert isinstance(states["colorRGB"], ColorRGBState)
    assert states["color"] is states["colorRGB"]
    assert isinstance(states["colorTemperature"], ColorTemperatureState)
    assert isinstance(states["segmentColor"], SegmentColorState)
    assert isinstance(states["lightEffect"], LightEffectState)
    assert isinstance(states["micMode"], MicModeState)
    assert isinstance(states["diyMode"], DiyModeState)

    mode_state = device.mode_state
    assert isinstance(mode_state, rgbic_light_module.RGBICModeState)
    mode_types = {type(mode) for mode in mode_state.modes}
    assert mode_types == {
        ColorRGBState,
        SegmentColorState,
        LightEffectState,
        MicModeState,
        DiyModeState,
    }
    assert mode_state.resolve_mode("color_whole") is states["colorRGB"]
    assert mode_state.resolve_mode("color_segment") is states["segmentColor"]
    assert mode_state.resolve_mode("scene") is states["lightEffect"]
    assert mode_state.resolve_mode("mic") is states["micMode"]
    assert mode_state.resolve_mode("diy") is states["diyMode"]

    light_entities = device.light_entities
    assert light_entities.primary is states["power"]
    assert set(light_entities.supporting) == {
        states["brightness"],
        states["colorRGB"],
        states["colorTemperature"],
        states["segmentColor"],
    }


def test_rgbic_mode_state_maps_active_identifiers(
    rgbic_device_model: MockDeviceModel,
) -> None:
    """RGBIC mode state should translate identifiers to concrete states."""

    device = rgbic_light_module.RGBICLightDevice(rgbic_device_model)
    mode_state = device.mode_state
    color_state = device.states["colorRGB"]
    assert device.states["color"] is color_state
    segment_state = device.states["segmentColor"]
    light_effect = device.states["lightEffect"]
    mic_mode = device.states["micMode"]
    diy_mode = device.states["diyMode"]

    mode_state.parse_op_command([0xAA, 0x05, int(RGBICModes.WHOLE_COLOR)])
    assert mode_state.active_mode is color_state

    mode_state.parse_op_command([0xAA, 0x05, int(RGBICModes.SEGMENT_COLOR)])
    assert mode_state.active_mode is segment_state

    mode_state.parse_op_command([0xAA, 0x05, int(RGBICModes.SCENE)])
    assert mode_state.active_mode is light_effect

    mode_state.parse_op_command([0xAA, 0x05, int(RGBICModes.MIC), 0x01])
    assert mode_state.active_mode is mic_mode

    mode_state.parse_op_command([0xAA, 0x05, int(RGBICModes.DIY), 0x00, 0x01])
    assert mode_state.active_mode is diy_mode


def test_rgbic_mode_state_delegates_to_selected_state(
    rgbic_device_model: MockDeviceModel,
) -> None:
    """Commands routed through the mode state should invoke the target state."""

    device = rgbic_light_module.RGBICLightDevice(rgbic_device_model)
    mode_state = device.mode_state
    mic_mode = device.states["micMode"]

    mic_mode.parse_op_command(
        [
            0xAA,
            0x05,
            int(RGBICModes.MIC),
            0x02,
            0x32,
            0x01,
            0x00,
            0x10,
            0x20,
            0x30,
        ]
    )

    command_ids = mode_state.set_state(mic_mode)

    assert command_ids
    frame = _next_command_frame(mic_mode)
    assert frame[:3] == [0x33, 0x05, int(RGBICModes.MIC)]


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
        "colorRGB",
        "color",
        "colorTemperature",
        "sceneMode",
        "lightEffect",
    } <= set(states)
    assert isinstance(states["power"], PowerState)
    assert isinstance(states["isConnected"], ConnectedState)
    assert isinstance(states["active"], ActiveState)
    assert isinstance(states["brightness"], BrightnessState)
    assert isinstance(states["colorRGB"], ColorRGBState)
    assert states["color"] is states["colorRGB"]
    assert isinstance(states["colorTemperature"], ColorTemperatureState)
    assert isinstance(states["sceneMode"], SceneModeState)
    assert isinstance(states["lightEffect"], LightEffectState)

    light_entities = device.light_entities
    assert light_entities.primary is states["power"]
    assert set(light_entities.supporting) == {
        states["brightness"],
        states["colorRGB"],
        states["colorTemperature"],
    }

    ha_entities = device.home_assistant_entities
    assert ha_entities["power"].platform == "light"
    assert ha_entities["brightness"].platform == "light"
    assert ha_entities["colorRGB"].platform == "light"
    assert ha_entities["color"].platform == "light"
    assert ha_entities["colorTemperature"].platform == "light"
    assert ha_entities["isConnected"].platform == "binary_sensor"
    assert ha_entities["active"].platform == "binary_sensor"
    scene_mode_sensor = ha_entities["sceneMode"]
    assert scene_mode_sensor.platform == "sensor"
    assert scene_mode_sensor.translation_key == "scene_mode_metadata"
    assert scene_mode_sensor.state is states["sceneMode"]
    scene_select = ha_entities["lightEffect"]
    assert scene_select.platform == "select"
    assert scene_select.translation_key == "scene_mode"
    assert scene_select.options == ["sunrise", "sunset", "candle"]


def test_rgb_light_scene_select_enqueues_command(
    rgb_light_device_model: MockDeviceModel,
) -> None:
    """Selecting a scene should enqueue the expected opcode payload."""

    device = RGBLightDevice(rgb_light_device_model)
    scene_select = device.states["lightEffect"]

    command_ids = scene_select.set_state("sunrise")

    assert command_ids
    command = scene_select.command_queue.get_nowait()
    assert command["name"] == "set_scene"
    assert command["opcode"] == "0x05"
    assert command["payload_hex"].upper() == "050001"


def test_device_states_expose_home_assistant_entities(
    rgbic_device_model: MockDeviceModel,
    humidifier_model_h7142: MockDeviceModel,
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Each device should expose a Home Assistant entity mapping per state."""

    light_device = rgbic_light_module.RGBICLightDevice(rgbic_device_model)
    humidifier_device = HumidifierDevice(humidifier_model_h7142)
    purifier_device = PurifierDevice(purifier_model_h7126)

    light_entities = light_device.home_assistant_entities
    assert {
        "power",
        "isConnected",
        "brightness",
        "colorRGB",
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
    assert light_entities["colorRGB"].platform == "light"
    assert light_entities["color"].platform == "light"
    assert light_entities["colorTemperature"].platform == "light"
    assert light_entities["segmentColor"].platform == "light"
    assert light_entities["isConnected"].platform == "binary_sensor"
    assert light_entities["isConnected"].translation_key == "connected"
    assert light_entities["isConnected"].entity_category is EntityCategory.DIAGNOSTIC
    assert light_entities["mode"].platform == "select"
    assert light_entities["lightEffect"].platform == "select"
    assert light_entities["micMode"].platform == "select"
    assert light_entities["diyMode"].platform == "select"

    humidifier_entities = humidifier_device.home_assistant_entities
    assert {
        "power",
        "isConnected",
        "mistLevel",
        "targetHumidity",
        "nightLight",
        "uvc",
        "displaySchedule",
        "controlLock",
        "humidity",
    } <= set(humidifier_entities)
    assert humidifier_entities["power"].platform == "humidifier"
    assert humidifier_entities["isConnected"].platform == "binary_sensor"
    assert humidifier_entities["isConnected"].translation_key == "connected"
    assert (
        humidifier_entities["isConnected"].entity_category is EntityCategory.DIAGNOSTIC
    )
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
        "isConnected",
        "fanSpeed",
        "mode",
        "displaySchedule",
        "controlLock",
        "timer",
        "filterLife",
        "filterExpired",
    } <= set(purifier_entities)
    assert purifier_entities["power"].platform == "fan"
    assert purifier_entities["isConnected"].platform == "binary_sensor"
    assert purifier_entities["isConnected"].translation_key == "connected"
    assert purifier_entities["isConnected"].entity_category is EntityCategory.DIAGNOSTIC
    assert purifier_entities["mode"].platform == "select"
    assert purifier_entities["fanSpeed"].platform == "number"
    assert purifier_entities["displaySchedule"].platform == "switch"
    assert purifier_entities["controlLock"].platform == "switch"
    assert purifier_entities["timer"].platform == "switch"
    assert purifier_entities["filterLife"].platform == "sensor"
    assert purifier_entities["filterExpired"].platform == "binary_sensor"


def test_humidifier_mode_states_expose_diagnostic_entities(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Manual, custom, and auto modes should expose diagnostic sensors."""

    device = HumidifierDevice(humidifier_model_h7142)

    manual_state = device.states["manual_mode"]
    custom_state = device.states["custom_mode"]
    auto_state = device.states["auto_mode"]

    entities = device.home_assistant_entities

    manual_entity = entities["manual_mode"]
    assert manual_entity.platform == "sensor"
    assert manual_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert manual_entity.state is manual_state

    manual_state.parse_op_command([0x00, 0x05, 0x01, 0x04, 0x00])
    assert manual_entity.state.value == 4

    custom_entity = entities["custom_mode"]
    assert custom_entity.platform == "sensor"
    assert custom_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert custom_entity.state is custom_state

    custom_state.parse_op_command(
        [
            0x00,
            0x01,
            0x14,
            0x00,
            0x0A,
            0x00,
            0x0A,
            0x1E,
            0x00,
            0x14,
            0x00,
            0x14,
            0x32,
            0x00,
            0x1E,
            0x00,
            0x1E,
        ]
    )
    assert custom_entity.state.value == {
        "id": 1,
        "mistLevel": 30,
        "duration": 20,
        "remaining": 20,
    }

    auto_entity = entities["auto_mode"]
    assert auto_entity.platform == "sensor"
    assert auto_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert auto_entity.state is auto_state

    auto_state.parse_op_command([55])
    assert auto_entity.state.value == {"targetHumidity": 55}


def test_purifier_mode_states_expose_diagnostic_entities(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Purifier manual, custom, and auto modes should expose diagnostic sensors."""

    device = PurifierDevice(purifier_model_h7126)

    manual_state = device.states["manual_mode"]
    custom_state = device.states["custom_mode"]
    auto_state = device.states["auto_mode"]

    entities = device.home_assistant_entities

    manual_entity = entities["manual_mode"]
    assert manual_entity.platform == "sensor"
    assert manual_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert manual_entity.state is manual_state

    manual_state.parse(
        {"op": {"command": [[0xAA, 0x05, 0x01, 0x03, 0x04, 0x05, 0x00]]}}
    )
    assert manual_entity.state.value == 5

    custom_entity = entities["custom_mode"]
    assert custom_entity.platform == "sensor"
    assert custom_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert custom_entity.state is custom_state

    custom_state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x01,
                        0x05,
                        0x00,
                        0x0A,
                        0x00,
                        0x0A,
                        0x06,
                        0x00,
                        0x14,
                        0x00,
                        0x14,
                        0x07,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )
    assert custom_entity.state.value == {
        "id": 1,
        "fan_speed": 6,
        "duration": 20,
        "remaining": 20,
    }

    auto_entity = entities["auto_mode"]
    assert auto_entity.platform == "sensor"
    assert auto_entity.entity_category is EntityCategory.DIAGNOSTIC
    assert auto_entity.state is auto_state
    assert auto_entity.state.value == "auto_mode"


def test_humidifier_uvc_entity_alias_avoids_duplicate_registration(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """The humidifier UVC entity should expose only the alias key."""

    device = HumidifierDevice(humidifier_model_h7142)

    entities = device.home_assistant_entities

    assert "uvc" in entities
    assert "isUVCActive" not in entities


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


def test_humidifier_h7141_night_light_uses_model_identifier(
    humidifier_model_h7141: MockDeviceModel,
) -> None:
    """Night light commands should include the H7141 identifier sequence."""

    device = HumidifierDevice(humidifier_model_h7141)
    night_light = device.states["nightLight"]

    command_ids = night_light.set_state({"on": True, "brightness": 12})

    assert command_ids
    frame = _next_command_frame(night_light)

    assert frame[:5] == [0x33, 0xAA, 0x18, 0x01, 0x0C]


def test_humidifier_h7142_identifier_sequences(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Night light and display schedule commands should use the H7142 identifiers."""

    device = HumidifierDevice(humidifier_model_h7142)

    night_light = device.states["nightLight"]
    night_light.set_state({"on": True, "brightness": 34})
    night_light_frame = _next_command_frame(night_light)

    assert night_light_frame[:5] == [0x33, 0xAA, 0x1B, 0x01, 0x22]

    schedule = device.states["displaySchedule"]
    schedule.set_state(
        {
            "on": True,
            "from": {"hour": 6, "minute": 30},
            "to": {"hour": 22, "minute": 15},
        }
    )
    schedule_frame = _next_command_frame(schedule)

    assert schedule_frame[:4] == [0x33, 0xAA, 0x1B, 0x01]
    assert schedule_frame[4:8] == [6, 30, 22, 15]


def test_meat_thermometer_registers_probes_and_presets(
    meat_thermometer_model: MockDeviceModel,
) -> None:
    """Meat thermometer devices should expose probe sensors and preset selects."""

    device = MeatThermometerDevice(meat_thermometer_model)

    states = device.states
    assert {
        "power",
        "isConnected",
        "buzzer",
        "temperatureUnit",
        "earlyWarning",
        "earlyWarningEnabled",
        "earlyWarningSetting",
        "probeTemp1",
        "probeTemp2",
        "probeTemp3",
        "probeTemp4",
        "preset1",
        "preset2",
        "preset3",
        "preset4",
    } <= set(states)
    assert isinstance(states["buzzer"], BuzzerState)
    assert isinstance(states["temperatureUnit"], TemperatureUnitState)
    assert isinstance(states["earlyWarningEnabled"], EarlyWarningEnabledState)
    assert isinstance(states["earlyWarningSetting"], EarlyWarningSettingState)
    for index in range(1, 5):
        assert isinstance(states[f"probeTemp{index}"], ProbeTempState)
        assert isinstance(states[f"preset{index}"], PresetState)

    ha_entities = device.home_assistant_entities
    assert ha_entities["power"].platform == "switch"
    assert ha_entities["isConnected"].platform == "binary_sensor"
    assert ha_entities["isConnected"].translation_key == "connected"
    assert ha_entities["buzzer"].platform == "binary_sensor"
    assert ha_entities["buzzer"].entity_category == EntityCategory.CONFIG
    assert ha_entities["buzzer"].translation_key == "buzzer"
    assert ha_entities["temperatureUnit"].platform == "sensor"
    assert ha_entities["temperatureUnit"].translation_key == "temperature_unit"
    assert ha_entities["earlyWarningEnabled"].platform == "binary_sensor"
    assert ha_entities["earlyWarningEnabled"].entity_category == EntityCategory.CONFIG
    assert ha_entities["earlyWarningEnabled"].translation_key == "early_warning_enabled"
    assert ha_entities["earlyWarningSetting"].platform == "sensor"
    assert ha_entities["earlyWarningSetting"].translation_key == "early_warning_setting"
    for index in range(1, 5):
        probe_key = f"probeTemp{index}"
        preset_key = f"preset{index}"
        assert ha_entities[probe_key].platform == "sensor"
        assert ha_entities[preset_key].platform == "select"


def test_humidifier_mode_interlocks_gate_mist_levels(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Mist level writes should depend on the active humidifier mode."""

    device = HumidifierDevice(humidifier_model_h7142)

    mist_state = device.states["mistLevel"]
    target_state = device.states["targetHumidity"]

    manual_mode = device.states["manual_mode"]
    auto_mode = device.states["auto_mode"]

    device.mode_state.activate("manual_mode")
    manual_commands = mist_state.set_state(40)
    assert len(manual_commands) == 1
    manual_frame = _next_command_frame(manual_mode)
    assert manual_frame[:3] == [0x33, 0x05, 0x01]
    assert manual_frame[3] == 9
    assert mist_state.value == 9
    assert target_state.set_state(55) == []

    device.mode_state.activate("auto_mode")
    manual_commands = mist_state.set_state(20)
    assert len(manual_commands) == 1
    manual_frame = _next_command_frame(manual_mode)
    assert manual_frame[3] == 9
    assert device.mode_state.active_mode is not None
    assert device.mode_state.active_mode.name == "manual_mode"
    assert mist_state.value == 9
    assert target_state.set_state(60) == []
    assert device.mode_state.active_mode is not None
    assert device.mode_state.active_mode.name == "auto_mode"
    assert target_state.set_state(60) == ["target_humidity"]
    auto_frame = _next_command_frame(auto_mode)
    assert auto_frame[:3] == [0x33, 0x05, 0x03]
    assert auto_frame[3] == 60


def test_mist_level_state_tracks_mode_and_delegates(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Mist level should mirror manual/custom delegates and switch from auto."""

    manual_delegate = _DummyManualModeState()
    custom_delegate = _DummyCustomModeState()
    humidifier_model_h7142.manual_mode_state = manual_delegate
    humidifier_model_h7142.custom_mode_state = custom_delegate

    device = HumidifierDevice(humidifier_model_h7142)

    mist_state = device.states["mistLevel"]
    mode_state = device.mode_state

    mode_state.activate("manual_mode")
    manual_delegate.emit(4)
    assert mist_state.value == 4

    manual_delegate.commands.clear()
    assert mist_state.set_state(5) == ["manual"]
    assert manual_delegate.commands == [["manual"]]
    assert mist_state.value == 5

    mode_state.activate("custom_mode")
    custom_delegate.emit({"mistLevel": 45})
    assert mist_state.value == 45

    custom_delegate.commands.clear()
    assert mist_state.set_state(50) == ["custom"]
    assert custom_delegate.commands == [["custom"]]
    assert mist_state.value == 50

    assert mist_state.set_state("invalid") == []
    assert custom_delegate.commands == [["custom"]]
    assert mist_state.value == 50

    mode_state.activate("auto_mode")
    assert mist_state.value is None

    manual_delegate.commands.clear()
    assert mist_state.set_state(6) == ["manual"]
    assert manual_delegate.commands == [["manual"]]
    assert mode_state.active_mode is not None
    assert mode_state.active_mode.name == "manual_mode"
    assert mist_state.value == 6

    manual_delegate.commands.clear()
    assert mist_state.set_state(15) == ["manual"]
    assert manual_delegate.commands == [["manual"]]
    assert manual_delegate.value == 9
    assert mist_state.value == 9


def test_target_humidity_switches_to_auto_and_clamps_range(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Target humidity commands clamp to humidity range and require auto mode."""

    device = HumidifierDevice(humidifier_model_h7142)

    target_state = device.states["targetHumidity"]
    humidity_state = device.states["humidity"]

    humidity_state.parse(
        {
            "state": {
                "humidity": {
                    "current": 50,
                    "calibration": 0,
                    "min": 35,
                    "max": 65,
                }
            }
        }
    )

    device.mode_state.activate("manual_mode")

    assert target_state.set_state(60) == []
    assert device.mode_state.active_mode is not None
    assert device.mode_state.active_mode.name == "auto_mode"
    assert target_state.value is None

    assert target_state.set_state(80) == ["target_humidity"]
    assert target_state.value == 65

    device.mode_state.activate("custom_mode")
    assert target_state.value is None

    assert target_state.set_state(30) == []
    assert device.mode_state.active_mode is not None
    assert device.mode_state.active_mode.name == "auto_mode"

    assert target_state.set_state(32) == ["target_humidity"]
    assert target_state.value == 35


def test_target_humidity_auto_activation_queues_mode_command(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Auto activation should promote the mode without queuing a catalog command."""

    device = HumidifierDevice(humidifier_model_h7142)

    target_state = device.states["targetHumidity"]
    auto_mode = device.states["auto_mode"]

    device.mode_state.activate("manual_mode")

    assert target_state.set_state(55) == []

    assert device.mode_state.active_mode is not None
    assert device.mode_state.active_mode.name == "auto_mode"
    assert auto_mode.command_queue.empty()


def test_humidifier_mode_states_parse_and_command(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Manual, custom, and auto states should mirror the TypeScript behaviours."""

    device = HumidifierDevice(humidifier_model_h7142)

    manual_state = device.states["manual_mode"]
    custom_state = device.states["custom_mode"]
    auto_state = device.states["auto_mode"]

    assert isinstance(manual_state, ManualModeState)
    assert isinstance(custom_state, CustomModeState)
    assert isinstance(auto_state, AutoModeState)

    manual_state.parse_op_command([0x00, 0x05, 0x01, 0x04, 0x00])
    assert manual_state.value == 4

    manual_state.set_state(12)
    manual_command = _next_command_frame(manual_state)
    assert manual_command[:4] == [0x33, 0x05, 0x01, 0x09]

    custom_state.parse_op_command(
        [
            0x00,
            0x01,
            0x14,
            0x00,
            0x0A,
            0x00,
            0x0A,
            0x1E,
            0x00,
            0x14,
            0x00,
            0x14,
            0x32,
            0x00,
            0x1E,
            0x00,
            0x1E,
        ]
    )

    assert custom_state.value == {
        "id": 1,
        "mistLevel": 0x1E,
        "duration": 0x0014,
        "remaining": 0x0014,
    }

    custom_state.set_state(
        {"id": 2, "mistLevel": 55, "duration": 360, "remaining": 180}
    )
    custom_command = _next_command_frame(custom_state)
    assert custom_command[0] == 0x33
    assert custom_command[1:3] == [0x05, 0x02]
    assert custom_command[3] == 2

    humidity_state = device.states["humidity"]
    humidity_state.parse(
        {
            "state": {
                "humidity": {
                    "current": 50,
                    "calibration": 0,
                    "min": 40,
                    "max": 70,
                }
            }
        }
    )

    auto_state.parse_op_command([60])
    assert auto_state.value == {"targetHumidity": 60}

    auto_state.set_state({"targetHumidity": 80})
    auto_command = _next_command_frame(auto_state)
    assert auto_command[:3] == [0x33, 0x05, 0x03]
    assert auto_command[3] == 70


def test_humidifier_active_state_tracks_delegate_pending(
    humidifier_model_h7142: MockDeviceModel,
) -> None:
    """Active mode should track delegate pending and relay clear events."""

    device = HumidifierDevice(humidifier_model_h7142)

    mode_state = device.mode_state
    manual_state = device.states["manual_mode"]

    command_ids = mode_state.set_state("manual_mode")

    assert len(command_ids) == 2

    delegate_id = command_ids[-1]
    assert delegate_id in manual_state._pending_commands  # type: ignore[attr-defined]

    assert delegate_id in mode_state._pending_commands  # type: ignore[attr-defined]
    assert (
        mode_state._pending_commands[delegate_id]  # type: ignore[attr-defined]
        == manual_state._pending_commands[delegate_id]  # type: ignore[attr-defined]
    )

    manual_state.expire_pending_commands([delegate_id])

    relayed = mode_state.clear_queue.get_nowait()
    assert relayed["command_id"] == delegate_id
    assert delegate_id not in mode_state._pending_commands  # type: ignore[attr-defined]


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

    assert isinstance(h7126_device.states["manual_mode"], PurifierManualModeState)
    assert isinstance(h7126_device.states["custom_mode"], PurifierCustomModeState)
    assert isinstance(h7126_device.mode_state, PurifierActiveMode)


def test_purifier_feature_identifiers_match_upstream(
    purifier_model_default: MockDeviceModel,
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Purifier feature identifiers should align with the upstream mapping."""

    default_device = PurifierDevice(purifier_model_default)
    h7126_device = PurifierDevice(purifier_model_h7126)

    default_states = default_device.states
    assert default_states["nightLight"]._identifier == [0x18]
    assert default_states["controlLock"]._identifier == [0x10]
    assert default_states["displaySchedule"]._identifier == [0x16]

    default_timer = default_states["timer"]
    assert default_timer._identifier == [0x11]
    assert default_timer._status_identifier == [0x11]

    h7126_timer = h7126_device.states["timer"]
    assert h7126_timer._identifier == [0x26]
    assert h7126_timer._status_identifier == [0x26]


def test_purifier_default_registers_common_features(
    purifier_model_default: MockDeviceModel,
) -> None:
    """Default purifier models should expose the shared feature set."""

    device = PurifierDevice(purifier_model_default)

    assert {"displaySchedule", "filterExpired", "timer"} <= set(device.states)

    entities = device.home_assistant_entities

    assert entities["displaySchedule"].platform == "switch"
    assert entities["displaySchedule"].entity_category is EntityCategory.CONFIG
    assert entities["displaySchedule"].translation_key == "display_schedule"

    assert entities["filterExpired"].platform == "binary_sensor"
    assert entities["filterExpired"].entity_category is EntityCategory.DIAGNOSTIC

    assert entities["timer"].platform == "switch"
    assert entities["timer"].entity_category is EntityCategory.CONFIG


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
    """Fan speed adjustments should only execute when manual/custom are active."""

    device = PurifierDevice(purifier_model_h7126)
    fan_speed = device.states["fanSpeed"]
    manual_state = device.states["manual_mode"]

    manual_state.parse(
        {"op": {"command": [[0xAA, 0x05, 0x01, 0x03, 0x04, 0x05, 0x00]]}}
    )
    device.mode_state.parse_op_command([0x01])

    command_ids = fan_speed.set_state(3)
    assert len(command_ids) == 1

    frame = _next_command_frame(fan_speed)
    assert frame[:6] == [0x33, 0x05, 0x01, 0x00, 0x00, 0x03]

    device.mode_state.parse_op_command([0x03])
    assert fan_speed.set_state(1) == []


def test_purifier_fan_speed_tracks_active_delegate(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Fan speed should mirror the active manual or custom delegate."""

    device = PurifierDevice(purifier_model_h7126)
    fan_speed = device.states["fanSpeed"]
    manual_state = device.states["manual_mode"]
    custom_state = device.states["custom_mode"]
    mode_state = device.mode_state

    manual_state.parse(
        {"op": {"command": [[0xAA, 0x05, 0x01, 0x03, 0x04, 0x05, 0x00]]}}
    )
    mode_state.parse_op_command([0x01])

    assert fan_speed.value == 5

    custom_state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x01,
                        0x05,
                        0x00,
                        0x0A,
                        0x00,
                        0x0A,
                        0x06,
                        0x00,
                        0x14,
                        0x00,
                        0x14,
                        0x07,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )
    mode_state.parse_op_command([0x02])

    assert fan_speed.value == 6


def test_purifier_fan_speed_delegates_custom_mode_commands(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Custom program fan speed commands should reuse the delegate payloads."""

    device = PurifierDevice(purifier_model_h7126)
    fan_speed = device.states["fanSpeed"]
    custom_state = device.states["custom_mode"]
    mode_state = device.mode_state

    custom_state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x01,
                        0x05,
                        0x00,
                        0x0A,
                        0x00,
                        0x0A,
                        0x06,
                        0x00,
                        0x14,
                        0x00,
                        0x14,
                        0x07,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )
    mode_state.parse_op_command([0x02])

    command_ids = fan_speed.set_state(8)
    assert len(command_ids) == 1

    frame = _next_command_frame(fan_speed)
    assert frame[:4] == [0x33, 0x05, 0x02, 0x01]
    assert frame[9] == 0x08


def test_purifier_manual_and_custom_modes_process_reports(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Manual and custom mode states should parse reports and issue commands."""

    device = PurifierDevice(purifier_model_h7126)

    manual_state = device.states["manual_mode"]
    custom_state = device.states["custom_mode"]
    mode_state = device.mode_state

    assert isinstance(manual_state, PurifierManualModeState)
    assert isinstance(custom_state, PurifierCustomModeState)
    assert isinstance(mode_state, PurifierActiveMode)

    manual_state.parse(
        {"op": {"command": [[0xAA, 0x05, 0x01, 0x03, 0x04, 0x05, 0x00]]}}
    )
    assert manual_state.value == 5

    manual_command_ids = manual_state.set_state(2)
    assert manual_command_ids
    manual_frame = _next_command_frame(manual_state)
    assert manual_frame[:6] == [0x33, 0x05, 0x01, 0x00, 0x00, 0x02]

    custom_state.parse(
        {
            "op": {
                "command": [
                    [
                        0xAA,
                        0x05,
                        0x02,
                        0x01,
                        0x05,
                        0x00,
                        0x0A,
                        0x00,
                        0x0A,
                        0x06,
                        0x00,
                        0x14,
                        0x00,
                        0x14,
                        0x07,
                        0x00,
                        0x1E,
                        0x00,
                        0x1E,
                    ]
                ]
            }
        }
    )

    assert custom_state.value == {
        "id": 1,
        "fan_speed": 6,
        "duration": 20,
        "remaining": 20,
    }

    custom_command_ids = custom_state.set_state({"id": 1, "fan_speed": 8})
    assert custom_command_ids
    custom_frame = _next_command_frame(custom_state)
    assert custom_frame[:4] == [0x33, 0x05, 0x02, 0x01]
    assert custom_frame[9] == 0x08

    mode_state.parse_op_command([1])
    assert mode_state.active_mode is manual_state

    mode_state.parse_op_command([2])
    assert mode_state.active_mode is custom_state

    manual_state.parse(
        {"op": {"command": [[0xAA, 0x05, 0x01, 0x01, 0x02, 0x03, 0x00]]}}
    )
    while not manual_state.command_queue.empty():
        manual_state.command_queue.get_nowait()
    delegated_ids = mode_state.set_state(manual_state)
    assert delegated_ids
    delegated_frame = _next_command_frame(manual_state)
    assert delegated_frame[5] == manual_state.value


def test_purifier_active_mode_strips_report_header(
    purifier_model_h7126: MockDeviceModel,
) -> None:
    """Active mode parsing should ignore opcode headers when present."""

    device = PurifierDevice(purifier_model_h7126)
    manual_state = device.states["manual_mode"]
    mode_state = device.mode_state

    assert isinstance(manual_state, PurifierManualModeState)
    assert isinstance(mode_state, PurifierActiveMode)

    manual_identifier = getattr(manual_state, "_mode_identifier", [0x01])
    mode_state.parse_op_command([0xAA, 0x05, int(manual_identifier[0])])

    assert mode_state.active_mode is manual_state
    assert mode_state.active_identifier == [int(manual_identifier[0])]


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
