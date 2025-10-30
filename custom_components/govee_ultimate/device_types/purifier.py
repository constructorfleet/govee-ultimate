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
    NightLightState,
    ParseOption,
    PowerState,
    TimerState,
    PurifierManualModeState,
    PurifierCustomModeState,
    PurifierActiveMode,
    PurifierFanSpeedState,
)

from .base import BaseDevice, EntityCategory, PurifierEntities


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

        self._register_connected_state(device_model)

        active = self.add_state(ActiveState(device_model))
        self.expose_entity(
            platform="binary_sensor",
            state=active,
            entity_category=EntityCategory.DIAGNOSTIC,
        )

        mode_states: list[DeviceState[str] | None] = []
        manual_state: PurifierManualModeState | None = None
        custom_state: PurifierCustomModeState | None = None
        if model_id == "H7126":
            manual_state = self.add_state(PurifierManualModeState(device_model))
            custom_state = self.add_state(PurifierCustomModeState(device_model))
            mode_states.extend([manual_state, custom_state])

        auto = self.add_state(
            DeviceState(
                device=device_model,
                name="auto_mode",
                initial_value="auto_mode",
                parse_option=ParseOption.NONE,
            )
        )
        setattr(auto, "_mode_identifier", [0x03])
        mode_states.append(auto)

        self._mode_state = self.add_state(PurifierActiveMode(device_model, mode_states))
        self.expose_entity(platform="select", state=self._mode_state)
        self._fan_state = self.add_state(
            PurifierFanSpeedState(
                device_model,
                self._mode_state,
                manual_state=manual_state,
                custom_state=custom_state,
            )
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
    def mode_state(self) -> PurifierActiveMode:
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
