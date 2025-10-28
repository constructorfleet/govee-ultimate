"""Platform entity integration tests for the Govee Ultimate component."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

if "homeassistant.helpers" not in sys.modules:
    helpers_pkg = ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers_pkg

if "homeassistant.helpers.update_coordinator" not in sys.modules:
    coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    class _Coordinator:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.hass = kwargs.get("hass")
            self.data: dict[str, Any] | None = None

        async def async_config_entry_first_refresh(
            self,
        ) -> None:  # pragma: no cover - stub
            return None

    class _CoordinatorEntity:
        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator

        async def async_added_to_hass(self) -> None:  # pragma: no cover - stub
            return None

    coordinator_module.DataUpdateCoordinator = _Coordinator  # type: ignore[attr-defined]
    coordinator_module.CoordinatorEntity = _CoordinatorEntity  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.update_coordinator"] = coordinator_module

from custom_components.govee_ultimate import DOMAIN
from custom_components.govee_ultimate.coordinator import DeviceMetadata
from custom_components.govee_ultimate.device_types.humidifier import HumidifierDevice
from custom_components.govee_ultimate.device_types.purifier import PurifierDevice
from custom_components.govee_ultimate.device_types.rgbic_light import RGBICLightDevice


@pytest.fixture(autouse=True)
def setup_platform_stubs() -> Callable[[], None]:  # noqa: C901
    """Install minimal Home Assistant stubs for platform entities."""

    installed: dict[str, ModuleType] = {}

    def _install(name: str, module: ModuleType) -> None:
        installed[name] = sys.modules.get(name)
        sys.modules[name] = module

    base_module = ModuleType("homeassistant.helpers.entity")

    class _Entity:
        """Lightweight stand-in for Home Assistant's Entity base class."""

        should_poll = False

        def __init__(self) -> None:
            self.hass: Any | None = None
            self._added = asyncio.Event()
            self._written_states: list[Any] = []

        async def async_added_to_hass(self) -> None:
            self._added.set()

        def async_write_ha_state(self) -> None:
            self._written_states.append(getattr(self, "state", None))

    base_module.Entity = _Entity  # type: ignore[attr-defined]
    _install("homeassistant.helpers.entity", base_module)

    class _LightEntity(_Entity):
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

        @property
        def state(self) -> bool | None:
            return self.is_on

        async def async_turn_on(self, **kwargs: Any) -> None:  # pragma: no cover - stub
            raise NotImplementedError

        async def async_turn_off(
            self, **kwargs: Any
        ) -> None:  # pragma: no cover - stub
            raise NotImplementedError

    class _HumidifierEntity(_Entity):
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

        async def async_turn_on(self) -> None:  # pragma: no cover - stub
            raise NotImplementedError

        async def async_turn_off(self) -> None:  # pragma: no cover - stub
            raise NotImplementedError

    class _FanEntity(_Entity):
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

        async def async_turn_on(self, **kwargs: Any) -> None:  # pragma: no cover - stub
            raise NotImplementedError

        async def async_turn_off(
            self, **kwargs: Any
        ) -> None:  # pragma: no cover - stub
            raise NotImplementedError

    class _SwitchEntity(_Entity):
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

        async def async_turn_on(self, **kwargs: Any) -> None:  # pragma: no cover - stub
            raise NotImplementedError

        async def async_turn_off(
            self, **kwargs: Any
        ) -> None:  # pragma: no cover - stub
            raise NotImplementedError

    class _NumberEntity(_Entity):
        _attr_native_value: float | None = None

        @property
        def native_value(self) -> float | None:
            return self._attr_native_value

        async def async_set_native_value(
            self, value: float
        ) -> None:  # pragma: no cover - stub
            raise NotImplementedError

    class _SensorEntity(_Entity):
        _attr_native_value: Any = None

        @property
        def native_value(self) -> Any:
            return self._attr_native_value

    class _BinarySensorEntity(_Entity):
        _attr_is_on: bool | None = None

        @property
        def is_on(self) -> bool | None:
            return self._attr_is_on

    platform_classes = {
        "homeassistant.components.light": ("LightEntity", _LightEntity),
        "homeassistant.components.humidifier": ("HumidifierEntity", _HumidifierEntity),
        "homeassistant.components.fan": ("FanEntity", _FanEntity),
        "homeassistant.components.switch": ("SwitchEntity", _SwitchEntity),
        "homeassistant.components.number": ("NumberEntity", _NumberEntity),
        "homeassistant.components.sensor": ("SensorEntity", _SensorEntity),
        "homeassistant.components.binary_sensor": (
            "BinarySensorEntity",
            _BinarySensorEntity,
        ),
    }

    for module_name, (class_name, class_obj) in platform_classes.items():
        module = ModuleType(module_name)
        setattr(module, class_name, class_obj)
        _install(module_name, module)

    def _teardown() -> None:
        for name, previous in installed.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    return _teardown


@pytest.fixture
def fake_device_metadata() -> DeviceMetadata:
    """Return device metadata for coordinator driven tests."""

    return DeviceMetadata(
        device_id="device-1",
        model="H6099",
        sku="H6099",
        category="LED Strip",
        category_group="Lighting",
        device_name="Example Light",
        manufacturer="Govee",
        channels={"iot": {"topic": "state"}},
    )


@pytest.fixture
def rgbic_device(fake_device_metadata: DeviceMetadata) -> RGBICLightDevice:
    """Return a configured RGBIC light device."""

    model = SimpleNamespace(
        model=fake_device_metadata.model,
        sku=fake_device_metadata.sku,
        category=fake_device_metadata.category,
        category_group=fake_device_metadata.category_group,
        model_name=fake_device_metadata.device_name,
    )
    return RGBICLightDevice(model)


@pytest.fixture
def humidifier_metadata() -> DeviceMetadata:
    """Return device metadata for humidifier platform tests."""

    return DeviceMetadata(
        device_id="humidifier-1",
        model="H7142",
        sku="H7142",
        category="Home Appliances",
        category_group="Air Treatment",
        device_name="Humidifier",
        manufacturer="Govee",
        channels={"iot": {"topic": "state"}},
    )


@pytest.fixture
def humidifier_device(humidifier_metadata: DeviceMetadata) -> HumidifierDevice:
    """Return a configured humidifier device."""

    model = SimpleNamespace(
        model=humidifier_metadata.model,
        sku=humidifier_metadata.sku,
        category=humidifier_metadata.category,
        category_group=humidifier_metadata.category_group,
        model_name=humidifier_metadata.device_name,
    )
    return HumidifierDevice(model)


@pytest.fixture
def purifier_metadata() -> DeviceMetadata:
    """Return device metadata for purifier platform tests."""

    return DeviceMetadata(
        device_id="purifier-1",
        model="H7126",
        sku="H7126",
        category="Home Appliances",
        category_group="Air Treatment",
        device_name="Purifier",
        manufacturer="Govee",
        channels={"iot": {"topic": "state"}},
    )


@pytest.fixture
def purifier_device(purifier_metadata: DeviceMetadata) -> PurifierDevice:
    """Return a configured purifier device."""

    model = SimpleNamespace(
        model=purifier_metadata.model,
        sku=purifier_metadata.sku,
        category=purifier_metadata.category,
        category_group=purifier_metadata.category_group,
        model_name=purifier_metadata.device_name,
    )
    return PurifierDevice(model)


@dataclass
class FakeConfigEntry:
    """Minimal config entry stub."""

    entry_id: str


class FakeCoordinator:
    """Coordinator stub used for entity wiring tests."""

    def __init__(
        self,
        devices: dict[str, Any],
        metadata: dict[str, DeviceMetadata],
    ) -> None:
        """Initialise with the supplied device mapping and metadata."""
        self.devices = dict(devices)
        self.device_metadata = dict(metadata)
        self._listeners: list[Callable[[], None]] = []
        self.command_publisher_calls: list[tuple[str, dict[str, Any]]] = []

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener callback and return a removal handle."""
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def notify_listeners(self) -> None:
        """Invoke all registered listener callbacks."""
        for listener in list(self._listeners):
            listener()

    def get_command_publisher(
        self, device_id: str, *, channel: str | None = None
    ) -> Callable[[dict[str, Any]], asyncio.Future[Any]]:
        """Return a publisher that records dispatched commands."""

        async def _publisher(payload: dict[str, Any]) -> None:
            self.command_publisher_calls.append((device_id, payload))

        return _publisher


class FakeHass:
    """Stub Home Assistant core object."""

    def __init__(self) -> None:
        """Prepare storage for integration data."""
        self.data: dict[str, dict[str, Any]] = {}


async def _async_setup_platform(
    platform: str,
    hass: FakeHass,
    entry: FakeConfigEntry,
    coordinator: FakeCoordinator,
    added_entities: list[Any],
) -> None:
    """Load the requested platform and collect created entities."""
    module = importlib.import_module(f"custom_components.govee_ultimate.{platform}")

    async def _async_add_entities(entities: list[Any]) -> None:
        added_entities.extend(entities)

    await module.async_setup_entry(hass, entry, _async_add_entities)


@pytest.mark.asyncio
async def test_light_entity_updates_and_publishes_commands(
    setup_platform_stubs: Callable[[], None],
    fake_device_metadata: DeviceMetadata,
    rgbic_device: RGBICLightDevice,
) -> None:
    """The light platform should mirror state updates and publish commands."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-1")
    coordinator = FakeCoordinator(
        {fake_device_metadata.device_id: rgbic_device},
        {fake_device_metadata.device_id: fake_device_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "light",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    assert any(entity.unique_id == "device-1-power" for entity in added_entities)

    power_entity = next(
        entity for entity in added_entities if entity.unique_id == "device-1-power"
    )
    power_state = rgbic_device.states["power"]
    power_state._update_state(True)
    coordinator.notify_listeners()

    assert power_entity.is_on is True

    await power_entity.async_turn_off()

    assert coordinator.command_publisher_calls


@pytest.mark.asyncio
async def test_humidifier_entity_updates_and_publishes_commands(
    setup_platform_stubs: Callable[[], None],
    humidifier_metadata: DeviceMetadata,
    humidifier_device: HumidifierDevice,
) -> None:
    """Humidifier power entities should dispatch commands."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-2")
    coordinator = FakeCoordinator(
        {humidifier_metadata.device_id: humidifier_device},
        {humidifier_metadata.device_id: humidifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "humidifier",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    unique_id = f"{humidifier_metadata.device_id}-power"
    humidifier_entity = next(
        entity for entity in added_entities if entity.unique_id == unique_id
    )
    power_state = humidifier_device.states["power"]
    power_state._update_state(True)

    await humidifier_entity.async_turn_off()

    assert coordinator.command_publisher_calls


@pytest.mark.asyncio
async def test_switch_entity_updates_and_publishes_commands(
    setup_platform_stubs: Callable[[], None],
    humidifier_metadata: DeviceMetadata,
    humidifier_device: HumidifierDevice,
) -> None:
    """Switch entities should relay commands to the coordinator."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-3")
    coordinator = FakeCoordinator(
        {humidifier_metadata.device_id: humidifier_device},
        {humidifier_metadata.device_id: humidifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "switch",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    timer_entity = next(
        entity
        for entity in added_entities
        if entity.unique_id == f"{humidifier_metadata.device_id}-timer"
    )
    timer_state = humidifier_device.states["timer"]
    timer_state._update_state(False)

    await timer_entity.async_turn_on()

    assert coordinator.command_publisher_calls


@pytest.mark.asyncio
async def test_number_entity_updates_and_publishes_commands(
    setup_platform_stubs: Callable[[], None],
    humidifier_metadata: DeviceMetadata,
    humidifier_device: HumidifierDevice,
) -> None:
    """Number entities should publish numeric commands."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-4")
    coordinator = FakeCoordinator(
        {humidifier_metadata.device_id: humidifier_device},
        {humidifier_metadata.device_id: humidifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "number",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    humidifier_device.mode_state.activate("manual_mode")
    mist_entity = next(
        entity
        for entity in added_entities
        if entity.unique_id == f"{humidifier_metadata.device_id}-mistLevel"
    )

    await mist_entity.async_set_native_value(50)

    assert coordinator.command_publisher_calls


@pytest.mark.asyncio
async def test_sensor_entity_tracks_state_updates(
    setup_platform_stubs: Callable[[], None],
    humidifier_metadata: DeviceMetadata,
    humidifier_device: HumidifierDevice,
) -> None:
    """Sensor entities should expose the latest native value."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-5")
    coordinator = FakeCoordinator(
        {humidifier_metadata.device_id: humidifier_device},
        {humidifier_metadata.device_id: humidifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "sensor",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    humidity_entity = next(
        entity
        for entity in added_entities
        if entity.unique_id == f"{humidifier_metadata.device_id}-humidity"
    )
    humidity_state = humidifier_device.states.get("humidity")
    if humidity_state is None:
        pytest.skip("Humidity sensor not available for this model")
    humidity_state._update_state(55)

    assert humidity_entity.native_value == 55


@pytest.mark.asyncio
async def test_binary_sensor_entity_tracks_state(
    setup_platform_stubs: Callable[[], None],
    humidifier_metadata: DeviceMetadata,
    humidifier_device: HumidifierDevice,
) -> None:
    """Binary sensor entities should mirror the state value."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-6")
    coordinator = FakeCoordinator(
        {humidifier_metadata.device_id: humidifier_device},
        {humidifier_metadata.device_id: humidifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "binary_sensor",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    active_entity = next(
        entity
        for entity in added_entities
        if entity.unique_id == f"{humidifier_metadata.device_id}-active"
    )
    active_state = humidifier_device.states["active"]
    active_state._update_state(True)

    assert active_entity.is_on is True


@pytest.mark.asyncio
async def test_fan_entity_updates_and_publishes_commands(
    setup_platform_stubs: Callable[[], None],
    purifier_metadata: DeviceMetadata,
    purifier_device: PurifierDevice,
) -> None:
    """Fan entities should dispatch toggle commands."""

    teardown = setup_platform_stubs
    hass = FakeHass()
    entry = FakeConfigEntry(entry_id="entry-7")
    coordinator = FakeCoordinator(
        {purifier_metadata.device_id: purifier_device},
        {purifier_metadata.device_id: purifier_metadata},
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    added_entities: list[Any] = []

    try:
        await _async_setup_platform(
            "fan",
            hass,
            entry,
            coordinator,
            added_entities,
        )
    finally:
        teardown()

    fan_entity = next(
        entity
        for entity in added_entities
        if entity.unique_id == f"{purifier_metadata.device_id}-power"
    )
    power_state = purifier_device.states["power"]
    power_state._update_state(True)

    await fan_entity.async_turn_off()

    assert coordinator.command_publisher_calls
