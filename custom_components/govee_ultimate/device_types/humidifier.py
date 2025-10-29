"""Humidifier device mirroring the Ultimate Govee implementation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from custom_components.govee_ultimate.state import (
    ActiveState,
    ControlLockState,
    DeviceState,
    DisplayScheduleState,
    ModeState,
    NightLightState,
    ParseOption,
    PowerState,
    TimerState,
    WaterShortageState,
)
from custom_components.govee_ultimate.state.states import HumidityState

from .base import BaseDevice, EntityCategory, HumidifierEntities


_HUMIDIFIER_MODE_COMMAND = "humidifier_mode"
_PROGRAM_COUNT = 3


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

        super().__init__(device=device, modes=modes, inline=True)
        self._by_name = {mode.name: mode for mode in modes}

    def activate(self, mode_name: str) -> None:
        """Set the active mode via human-readable name."""

        mode = self._by_name.get(mode_name)
        if mode is None:
            raise KeyError(mode_name)
        identifier = getattr(mode, "_identifier", None)
        if not identifier:
            identifier = [0x00]
        self._set_active_identifier(identifier)

    def ensure_mode(self, mode_name: str) -> bool:
        """Activate ``mode_name`` when it is not already active."""

        active = self.active_mode
        if active is not None and active.name == mode_name:
            return False
        self.activate(mode_name)
        return True


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

        commands = super().set_state(next_state)
        if not commands:
            return []
        if self._active_state.ensure_mode("manual_mode"):
            commands = [_HUMIDIFIER_MODE_COMMAND, *commands]
        return commands


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

    def set_state(self, next_state: Any) -> list[str]:
        """Set target humidity when the humidifier supports it."""

        commands = super().set_state(next_state)
        if not commands:
            return []
        if self._active_state.ensure_mode("auto_mode"):
            commands = [_HUMIDIFIER_MODE_COMMAND, *commands]
        return commands


class HumidifierProgramState(DeviceState[dict[str, int]]):
    """Track and update humidifier program configuration."""

    _MIST_MIN = 0
    _MIST_MAX = 100
    _DURATION_MIN = 0
    _DURATION_MAX = 0xFFFF

    def __init__(
        self,
        device: Any,
        active_state: HumidifierActiveState,
        *,
        index: int,
    ) -> None:
        """Initialise the program state wrapper."""

        super().__init__(
            device=device,
            name=f"program{index}",
            initial_value={"mist_level": 0, "duration": 0, "remaining": 0},
            parse_option=ParseOption.NONE,
        )
        self._active_state = active_state
        self._index = index
        self._command_name = f"humidifier_program_{index}"

    @property
    def attributes(self) -> dict[str, int]:
        """Expose auxiliary attributes for Home Assistant entities."""

        value = self.value
        return {
            "duration": int(value.get("duration", 0)),
            "remaining": int(value.get("remaining", 0)),
        }

    def _coerce_mist_level(self, value: Any) -> int | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric < self._MIST_MIN or numeric > self._MIST_MAX:
            return None
        return numeric

    def _coerce_duration(self, value: Any) -> int | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric < self._DURATION_MIN or numeric > self._DURATION_MAX:
            return None
        return numeric

    def _apply_mapping_value(
        self,
        mapping: Mapping[str, Any],
        key: str,
        coerce: Callable[[Any], int | None],
        updates: dict[str, int],
    ) -> bool:
        if key not in mapping:
            return True
        value = coerce(mapping.get(key))
        if value is None:
            return False
        updates[key] = value
        return True

    def _normalise_update(self, next_state: Any) -> dict[str, int] | None:
        if isinstance(next_state, Mapping):
            updates: dict[str, int] = {}
            if not self._apply_mapping_value(
                next_state, "mist_level", self._coerce_mist_level, updates
            ):
                return None
            if not self._apply_mapping_value(
                next_state, "duration", self._coerce_duration, updates
            ):
                return None
            if not self._apply_mapping_value(
                next_state, "remaining", self._coerce_duration, updates
            ):
                return None
            return updates

        mist_level = self._coerce_mist_level(next_state)
        if mist_level is None:
            return None
        return {"mist_level": mist_level}

    def set_state(self, next_state: Any) -> list[str]:
        """Update program configuration and ensure program mode is active."""

        updates = self._normalise_update(next_state)
        if updates is None:
            return []
        current = dict(self.value)
        updated = {**current, **updates}
        commands: list[str] = []
        if self._active_state.ensure_mode("program_mode"):
            commands.append(_HUMIDIFIER_MODE_COMMAND)
        if updated != current:
            self._update_state(updated)
            commands.append(self._command_name)
        elif not commands:
            return []
        return commands


class HumidifierDevice(BaseDevice):
    """Python mirror of the TypeScript humidifier implementation."""

    _MODEL_FEATURES = {
        "H7141": ("nightLight", "controlLock"),
        "H7142": ("nightLight", "controlLock", "displaySchedule", "uvc", "humidity"),
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
        program = self.add_state(_ModeOptionState(device_model, "program_mode", 0x03))

        self._mode_state = self.add_state(
            HumidifierActiveState(device_model, [manual, custom, auto, program])
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

        programs: list[HumidifierProgramState] = []
        for index in range(1, _PROGRAM_COUNT + 1):
            program_state = self.add_state(
                HumidifierProgramState(device_model, self._mode_state, index=index)
            )
            programs.append(program_state)
            self.expose_entity(
                platform="number",
                state=program_state,
                entity_category=EntityCategory.CONFIG,
            )
        self._program_states = tuple(programs)

        for feature in self._MODEL_FEATURES.get(device_model.model, ()):  # type: ignore[attr-defined]
            platform, category = self._FEATURE_PLATFORMS.get(feature, ("sensor", None))
            state: DeviceState[Any]
            if feature == "nightLight":
                state = NightLightState(device=device_model, identifier=[0x40])
            elif feature == "displaySchedule":
                state = DisplayScheduleState(device=device_model, identifier=[0x30])
            elif feature == "controlLock":
                state = ControlLockState(device=device_model, identifier=[0x0A])
            elif feature == "humidity":
                state = HumidityState(device=device_model)
            else:
                state = _BooleanState(device_model, feature)
            registered = self.add_state(state)
            self.expose_entity(
                platform=platform,
                state=registered,
                entity_category=category,
            )

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
            programs=self._program_states,
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

    @property
    def program_states(self) -> tuple[HumidifierProgramState, ...]:
        """Expose configured program state handlers."""

        return self._program_states
