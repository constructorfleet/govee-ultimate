"""Humidifier device mirroring the Ultimate Govee implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from collections.abc import Callable

from custom_components.govee_ultimate.state import (
    ActiveState,
    ControlLockState,
    DeviceState,
    DisplayScheduleState,
    HumidifierUVCState,
    ModeState,
    NightLightState,
    ParseOption,
    PowerState,
    TimerState,
    WaterShortageState,
)
from custom_components.govee_ultimate.state.states import HumidityState

from .base import BaseDevice, EntityCategory, HumidifierEntities


class _BooleanState(DeviceState[bool | None]):
    """Boolean state helper that updates immediately."""

    def __init__(self, device: Any, name: str) -> None:
        super().__init__(
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.NONE,
        )

    def set_state(self, next_state: Any) -> list[str]:
        value = bool(next_state)
        self._update_state(value)
        return [self.name]


class _NumericState(DeviceState[int | None]):
    """Numeric state helper with simple range enforcement."""

    def __init__(
        self,
        device: Any,
        name: str,
        *,
        minimum: int,
        maximum: int,
        command_name: str | None = None,
    ) -> None:
        super().__init__(
            device=device,
            name=name,
            initial_value=None,
            parse_option=ParseOption.NONE,
        )
        self._minimum = minimum
        self._maximum = maximum
        self._command_name = command_name or name

    def _coerce(self, value: Any) -> int | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric < self._minimum or numeric > self._maximum:
            return None
        return numeric

    def set_state(self, next_state: Any) -> list[str]:
        value = self._coerce(next_state)
        if value is None:
            return []
        self._update_state(value)
        return [self._command_name]


class _ModeOptionState(DeviceState[str]):
    """Simple mode option carrying an identifier for ModeState mapping."""

    def __init__(self, device: Any, name: str, identifier: int) -> None:
        super().__init__(
            device=device,
            name=name,
            initial_value=name,
            parse_option=ParseOption.NONE,
        )
        self._identifier = [identifier]


class HumidifierActiveState(ModeState):
    """Composite humidifier mode that exposes an imperative activation API."""

    def __init__(self, device: Any, modes: list[_ModeOptionState]) -> None:
        """Initialise the composite mode tracker."""

        super().__init__(
            device=device,
            modes=modes,
            inline=True,
            catalog_name="humidifier_mode",
        )
        self._by_name = {mode.name: mode for mode in modes}
        self._listeners: list[Callable[[DeviceState[str] | None], None]] = []

    def activate(self, mode_name: str) -> None:
        """Set the active mode via human-readable name."""

        mode = self._by_name.get(mode_name)
        if mode is None:
            raise KeyError(mode_name)
        identifier = getattr(mode, "_identifier", None)
        if not identifier:
            identifier = [0x00]
        self._set_active_identifier(identifier)

    def register_listener(
        self, callback: Callable[[DeviceState[str] | None], None]
    ) -> None:
        """Register a listener invoked when the active mode changes."""

        self._listeners.append(callback)

    def _notify_listeners(self, mode: DeviceState[str] | None) -> None:
        for listener in list(self._listeners):
            listener(mode)

    def _update_state(  # type: ignore[override]
        self, value: DeviceState[str] | None
    ) -> None:
        super()._update_state(value)
        self._notify_listeners(value)


class MistLevelState(_NumericState):
    """Mist level that only applies when manual or custom modes are active."""

    def __init__(self, device: Any, active_state: HumidifierActiveState) -> None:
        """Create the mist level controller bound to ``active_state``."""

        super().__init__(
            device,
            "mistLevel",
            minimum=0,
            maximum=100,
            command_name="mist_level",
        )
        self._active_state = active_state

    def set_state(self, next_state: Any) -> list[str]:
        """Set mist level when the humidifier is in a valid mode."""

        active = self._active_state.active_mode
        if active is None or active.name not in {"manual_mode", "custom_mode"}:
            return []
        return super().set_state(next_state)


class TargetHumidityState(_NumericState):
    """Target humidity that activates for auto and custom modes."""

    def __init__(self, device: Any, active_state: HumidifierActiveState) -> None:
        """Create the target humidity controller bound to ``active_state``."""

        super().__init__(
            device,
            "targetHumidity",
            minimum=30,
            maximum=80,
            command_name="target_humidity",
        )
        self._active_state = active_state
        self._humidity_state: HumidityState | None = None
        self._auto_active = False
        self._auto_mode_name = "auto_mode"
        self._active_state.register_listener(self._handle_active_mode)
        self._handle_active_mode(self._active_state.active_mode)

    def bind_humidity_state(self, humidity_state: HumidityState) -> None:
        """Bind the humidity sensor for range-aware clamping."""

        self._humidity_state = humidity_state

    def set_state(self, next_state: Any) -> list[str]:
        """Set target humidity when the humidifier supports it."""

        if not self._ensure_auto_mode():
            return []

        value = self._coerce(next_state)
        if value is None:
            return []

        clamped = self._clamp_to_humidity_range(value)
        self._update_state(clamped)
        return [self._command_name]

    def _handle_active_mode(self, mode: DeviceState[str] | None) -> None:
        name = getattr(mode, "name", None)
        self._auto_active = name == self._auto_mode_name
        if not self._auto_active and self.value is not None:
            self._update_state(None)

    def _clamp_to_humidity_range(self, value: int) -> int:
        minimum, maximum = self._humidity_bounds()
        clamped = value
        if minimum is not None and clamped < minimum:
            clamped = minimum
        if maximum is not None and clamped > maximum:
            clamped = maximum
        if clamped < self._minimum:
            clamped = self._minimum
        if clamped > self._maximum:
            clamped = self._maximum
        return clamped

    def _ensure_auto_mode(self) -> bool:
        if self._auto_active:
            return True
        if self._active_state.is_commandable:
            self._active_state.set_state(self._auto_mode_name)
        self._active_state.activate(self._auto_mode_name)
        return False

    def _humidity_bounds(self) -> tuple[int | None, int | None]:
        state = self._humidity_state.value if self._humidity_state is not None else None
        if not isinstance(state, Mapping):
            return (None, None)
        range_value = state.get("range")
        if not isinstance(range_value, Mapping):
            return (None, None)
        return (
            self._bound_value(range_value.get("min")),
            self._bound_value(range_value.get("max")),
        )

    @staticmethod
    def _bound_value(value: Any) -> int | None:
        if isinstance(value, int | float):
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


class HumidifierDevice(BaseDevice):
    """Python mirror of the TypeScript humidifier implementation."""

    _MODEL_FEATURES: dict[str, tuple[Any, ...]] = {
        "H7141": (
            ("nightLight", {"identifier": [0x18]}),
            ("controlLock", {"identifier": [0x0A]}),
        ),
        "H7142": (
            ("nightLight", {"identifier": [0x1B]}),
            ("controlLock", {"identifier": [0x0A]}),
            ("displaySchedule", {"identifier": [0x1B]}),
            "uvc",
            "humidity",
        ),
    }

    _FEATURE_PLATFORMS = {
        "nightLight": ("light", None),
        "controlLock": ("switch", EntityCategory.CONFIG),
        "displaySchedule": ("switch", EntityCategory.CONFIG),
        "uvc": ("switch", EntityCategory.CONFIG),
        "humidity": ("sensor", EntityCategory.DIAGNOSTIC),
    }

    def __init__(self, device_model: Any) -> None:
        """Initialise humidifier states based on the device model."""

        super().__init__(device_model)
        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="humidifier", state=power)

        self._register_connected_state(device_model)

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=active,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        shortage = self.add_state(WaterShortageState(device=device_model))
        # Maintain backwards compatibility with snake_case update payloads.
        self.alias_state("water_shortage", shortage)
        self.expose_entity(
            platform="binary_sensor",
            state=shortage,
            translation_key="water_shortage",
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        timer = self.add_state(TimerState(device=device_model, identifier=[0x0A, 0x0B]))
        self.expose_entity(
            platform="switch",
            state=timer,
            translation_key="timer",
            entity_category=EntityCategory.CONFIG,
        )

        manual = self.add_state(_ModeOptionState(device_model, "manual_mode", 0x00))
        custom = self.add_state(_ModeOptionState(device_model, "custom_mode", 0x01))
        auto = self.add_state(_ModeOptionState(device_model, "auto_mode", 0x02))

        self._mode_state = self.add_state(
            HumidifierActiveState(device_model, [manual, custom, auto])
        )
        self.expose_entity(platform="select", state=self._mode_state)

        self._mist_state = self.add_state(
            MistLevelState(device_model, self._mode_state)
        )
        self.expose_entity(platform="number", state=self._mist_state)
        self._target_state = self.add_state(
            TargetHumidityState(device_model, self._mode_state)
        )
        self.expose_entity(platform="number", state=self._target_state)

        for feature_entry in self._MODEL_FEATURES.get(device_model.model, ()):  # type: ignore[attr-defined]
            if isinstance(feature_entry, tuple):
                feature, feature_config = feature_entry
            else:
                feature = feature_entry
                feature_config = {}
            platform, category = self._FEATURE_PLATFORMS.get(feature, ("sensor", None))
            state: DeviceState[Any]
            identifier = (
                feature_config.get("identifier")
                if isinstance(feature_config, dict)
                else None
            )
            op_type = (
                feature_config.get("op_type")
                if isinstance(feature_config, dict)
                else None
            )

            def _build_kwargs(*, include_op_type: bool = True) -> dict[str, Any]:
                kwargs: dict[str, Any] = {"device": device_model}
                if identifier is not None:
                    kwargs["identifier"] = identifier
                if include_op_type and op_type is not None:
                    kwargs["op_type"] = op_type
                return kwargs

            if feature == "nightLight":
                state = NightLightState(**_build_kwargs())
            elif feature == "displaySchedule":
                state = DisplayScheduleState(**_build_kwargs())
            elif feature == "controlLock":
                state = ControlLockState(**_build_kwargs(include_op_type=False))
            elif feature == "uvc":
                state = HumidifierUVCState(device=device_model)
            elif feature == "humidity":
                state = HumidityState(device=device_model)
            else:
                state = _BooleanState(device_model, feature)
            registered = self.add_state(state)
            if feature == "humidity":
                self._target_state.bind_humidity_state(registered)
            entity_kwargs: dict[str, Any] = {
                "platform": platform,
                "state": registered,
                "entity_category": category,
            }
            if feature == "uvc":
                self.alias_state("uvc", registered)
                entity_kwargs["translation_key"] = "uvc"
            self.expose_entity(**entity_kwargs)
            if feature == "uvc":
                self.alias_entity("uvc", registered)

        sensors = []
        current_states = self.states
        for name in ("humidity",):
            state = current_states.get(name)
            if state is not None:
                sensors.append(state)

        self._entities = HumidifierEntities(
            primary=power,
            mode=self._mode_state,
            controls=(self._mist_state, self._target_state),
            sensors=tuple(sensors),
        )

    @property
    def mode_state(self) -> HumidifierActiveState:
        """Return the active humidifier mode handler."""

        return self._mode_state

    @property
    def humidifier_entities(self) -> HumidifierEntities:
        """Expose entities for Home Assistant humidifier platform."""

        return self._entities
