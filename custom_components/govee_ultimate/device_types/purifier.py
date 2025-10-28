"""Air purifier device support."""

from __future__ import annotations

from typing import Any

from custom_components.govee_ultimate.state import (
    ActiveState,
    ControlLockState,
    DeviceState,
    DisplayScheduleState,
    FilterExpiredState,
    FilterLifeState,
    ModeState,
    NightLightState,
    ParseOption,
    PowerState,
    TimerState,
)

from .base import BaseDevice, EntityCategory, PurifierEntities


class _NumericState(DeviceState[int | None]):
    """Numeric state with bounded values."""

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

    def set_state(self, next_state: Any) -> list[str]:
        try:
            numeric = int(next_state)
        except (TypeError, ValueError):
            return []
        if numeric < self._minimum or numeric > self._maximum:
            return []
        self._update_state(numeric)
        return [self._command_name]


class _ModeOptionState(DeviceState[str]):
    """Simple mode option used for purifier mode tracking."""

    def __init__(self, device: Any, name: str, identifier: int) -> None:
        super().__init__(
            device=device,
            name=name,
            initial_value=name,
            parse_option=ParseOption.NONE,
        )
        self._identifier = [identifier]


class PurifierActiveState(ModeState):
    """Composite mode tracker with imperative activation."""

    def __init__(self, device: Any, modes: list[_ModeOptionState]) -> None:
        """Initialise the purifier mode tracker."""

        super().__init__(device=device, modes=modes, inline=True)
        self._modes_by_name = {mode.name: mode for mode in modes}

    def activate(self, mode_name: str) -> None:
        """Activate the mode matching ``mode_name``."""

        mode = self._modes_by_name.get(mode_name)
        if mode is None:
            raise KeyError(mode_name)
        identifier = getattr(mode, "_identifier", None)
        if not identifier:
            identifier = [0x00]
        self._set_active_identifier(identifier)


class PurifierFanSpeedState(_NumericState):
    """Fan speed controller gated by manual/custom modes when available."""

    def __init__(self, device: Any, mode_state: PurifierActiveState) -> None:
        """Initialise the fan speed state bound to ``mode_state``."""

        super().__init__(
            device,
            "fanSpeed",
            minimum=1,
            maximum=6,
            command_name="fan_speed",
        )
        self._mode_state = mode_state

    def set_state(self, next_state: Any) -> list[str]:
        """Set the fan speed when manual/custom modes allow it."""

        modes = {mode.name for mode in self._mode_state.modes}
        if {"manual_mode", "custom_mode"} & modes:
            active = self._mode_state.active_mode
            if active is None or active.name not in {"manual_mode", "custom_mode"}:
                return []
        return super().set_state(next_state)


class PurifierDevice(BaseDevice):
    """Simplified purifier port matching the TypeScript factory."""

    _BASE_FEATURES = ("nightLight", "controlLock", "timer")
    _MODEL_FEATURES = {
        "H7126": ("displaySchedule", "filterLife", "filterExpired"),
    }
    _FEATURE_PLATFORMS = {
        "nightLight": ("light", None),
        "timer": ("switch", EntityCategory.CONFIG),
        "controlLock": ("switch", EntityCategory.CONFIG),
        "displaySchedule": ("switch", EntityCategory.CONFIG),
        "filterExpired": ("binary_sensor", EntityCategory.DIAGNOSTIC),
        "filterLife": ("sensor", EntityCategory.DIAGNOSTIC),
    }
    _FEATURE_TRANSLATIONS = {
        "nightLight": "night_light",
        "controlLock": "control_lock",
        "displaySchedule": "display_schedule",
        "timer": "timer",
    }
    _FEATURE_SPEC = {
        "nightLight": (NightLightState, {"identifier": [0x40]}),
        "controlLock": (ControlLockState, {"identifier": [0x0A]}),
        "displaySchedule": (DisplayScheduleState, {"identifier": [0x30]}),
        "timer": (TimerState, {"identifier": [0x32]}),
        "filterLife": (FilterLifeState, {}),
        "filterExpired": (FilterExpiredState, {}),
    }

    def __init__(self, device_model: Any) -> None:
        """Initialise purifier states according to the device model."""

        super().__init__(device_model)
        model_id = getattr(device_model, "model", "")
        power = self.add_state(PowerState(device_model))
        self.expose_entity(platform="fan", state=power)

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=active,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        mode_states: list[_ModeOptionState] = []
        if model_id == "H7126":
            manual = self.add_state(_ModeOptionState(device_model, "manual_mode", 0x00))
            custom = self.add_state(_ModeOptionState(device_model, "custom_mode", 0x01))
            auto = self.add_state(_ModeOptionState(device_model, "auto_mode", 0x02))
            mode_states.extend([manual, custom, auto])
        else:
            auto = self.add_state(_ModeOptionState(device_model, "auto_mode", 0x02))
            mode_states.append(auto)

        self._mode_state = self.add_state(
            PurifierActiveState(device_model, mode_states)
        )
        self.expose_entity(platform="select", state=self._mode_state)
        self._fan_state = self.add_state(
            PurifierFanSpeedState(device_model, self._mode_state)
        )
        self.expose_entity(platform="number", state=self._fan_state)

        extras: list[DeviceState[Any]] = []
        features = list(self._BASE_FEATURES)
        model_features = self._MODEL_FEATURES.get(model_id, ())
        for feature in model_features:
            if feature not in features:
                features.append(feature)

        for feature in features:
            state = self.add_state(self._build_feature_state(device_model, feature))
            extras.append(state)
            translation_key = self._FEATURE_TRANSLATIONS.get(feature)
            self._register_feature_entity(
                feature, state, translation_key=translation_key
            )

        self._entities = PurifierEntities(
            primary=power,
            mode=self._mode_state,
            fan=self._fan_state,
            extras=tuple(extras),
        )

    @property
    def mode_state(self) -> PurifierActiveState:
        """Return the mode controller for the purifier."""

        return self._mode_state

    @property
    def purifier_entities(self) -> PurifierEntities:
        """Return entity metadata for the purifier platform."""

        return self._entities

    def _build_feature_state(self, device_model: Any, feature: str) -> DeviceState[Any]:
        """Create the device state matching ``feature``."""

        try:
            factory, extra_kwargs = self._FEATURE_SPEC[feature]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(feature) from exc
        kwargs = {"device": device_model}
        kwargs.update(extra_kwargs)
        return factory(**kwargs)

    def _register_feature_entity(
        self,
        feature: str,
        state: DeviceState[Any],
        *,
        translation_key: str | None = None,
    ) -> None:
        """Register feature-specific entity metadata."""

        platform, category = self._FEATURE_PLATFORMS.get(feature, ("switch", None))
        self.expose_entity(
            platform=platform,
            state=state,
            translation_key=translation_key,
            entity_category=category,
        )
