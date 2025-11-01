"""Humidifier device mirroring the Ultimate Govee implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from collections.abc import Callable
from asyncio import QueueEmpty
import types

from custom_components.govee.state import (
    ActiveState,
    AutoModeState,
    CustomModeState,
    ControlLockState,
    DeviceState,
    DisplayScheduleState,
    HumidifierUVCState,
    ManualModeState,
    ModeState,
    NightLightState,
    ParseOption,
    PowerState,
    TimerState,
    WaterShortageState,
)
from custom_components.govee.state.states import HumidityState

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


class HumidifierActiveState(ModeState):
    """Composite humidifier mode that exposes an imperative activation API."""

    def __init__(self, device: Any, modes: list[DeviceState[str]]) -> None:
        """Initialise the composite mode tracker."""

        super().__init__(
            device=device,
            modes=modes,
            inline=True,
            catalog_name="humidifier_mode",
        )
        self._by_name = {mode.name: mode for mode in modes}
        self._listeners: list[Callable[[DeviceState[str] | None], None]] = []
        for mode in modes:
            self._wrap_delegate_clear_events(mode)

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

    def set_state(self, next_state: Any) -> list[str]:  # type: ignore[override]
        """Delegate mode changes to the backing mode states."""
        mode = self.resolve_mode(next_state)
        command_ids = super().set_state(next_state)
        if mode is None or not hasattr(mode, "set_state"):
            return command_ids
        payload = getattr(mode, "value", None)
        if payload is None:
            payload = self._default_payload(mode)
        if payload is None:
            return command_ids
        delegate_ids = mode.set_state(payload)
        self._adopt_delegate_pending(mode, delegate_ids)
        self._relay_queues(mode)
        if delegate_ids:
            command_ids.extend(delegate_ids)
        return command_ids

    def _relay_queues(self, mode: DeviceState[Any]) -> None:
        """Relay queued commands and clear events from the mode."""

        self._relay_queue(mode.command_queue, self.command_queue)
        self._relay_queue(mode.clear_queue, self.clear_queue, expire=True)

    def _relay_queue(self, source: Any, target: Any, *, expire: bool = False) -> None:
        while True:
            try:
                payload = source.get_nowait()
            except QueueEmpty:
                break
            target.put_nowait(payload)
            if expire and isinstance(payload, Mapping):
                command_id = payload.get("command_id")
                if command_id is not None:
                    self._pending_commands.pop(command_id, None)  # type: ignore[attr-defined]

    @property
    def is_commandable(self) -> bool:  # type: ignore[override]
        """Expose mode selection as commandable for delegate relaying."""

        return True

    @staticmethod
    def _default_payload(mode: DeviceState[Any]) -> Any:
        """Return a fallback payload when the delegate has no cached value."""

        name = getattr(mode, "name", "")
        if name == "manual_mode":
            return 0
        if name == "custom_mode":
            return {"id": 0}
        if name == "auto_mode":
            return {"targetHumidity": 50}
        return None

    def _wrap_delegate_clear_events(self, mode: DeviceState[Any]) -> None:
        """Wrap delegate clear emission to relay pending command completion."""

        if not hasattr(mode, "_emit_clear_event"):
            return
        if getattr(mode, "_humidifier_active_wrapped", False):
            return

        original = mode._emit_clear_event  # type: ignore[attr-defined]
        active_state = self

        def wrapped(self_mode: DeviceState[Any], command_id: str) -> None:
            original(command_id)
            active_state._handle_delegate_clear(self_mode, command_id)

        mode._emit_clear_event = types.MethodType(wrapped, mode)  # type: ignore[attr-defined]
        setattr(mode, "_humidifier_active_wrapped", True)

    def _adopt_delegate_pending(
        self, mode: DeviceState[Any], command_ids: list[str]
    ) -> None:
        if not command_ids:
            return
        pending = getattr(mode, "_pending_commands", None)
        if not isinstance(pending, dict):
            return
        for command_id in command_ids:
            statuses = pending.get(command_id)
            if statuses is None:
                continue
            self._pending_commands[command_id] = statuses  # type: ignore[attr-defined]

    def _handle_delegate_clear(self, mode: DeviceState[Any], command_id: str) -> None:
        self._relay_queue(mode.clear_queue, self.clear_queue, expire=True)
        self._pending_commands.pop(command_id, None)  # type: ignore[attr-defined]


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
        self._mode_options: dict[str, DeviceState[str] | None] = {
            "manual_mode": self._active_state.resolve_mode("manual_mode"),
            "custom_mode": self._active_state.resolve_mode("custom_mode"),
        }
        self._delegates: dict[str, Any | None] = {
            name: self._extract_delegate(option)
            for name, option in self._mode_options.items()
        }
        self._delegate_callbacks: dict[str, Callable[[Any], None]] = {}
        self._current_mode: str | None = None
        for name, delegate in self._delegates.items():
            self._subscribe_to_delegate(name, delegate)
        self._active_state.register_listener(self._handle_active_mode)
        self._handle_active_mode(self._active_state.active_mode)

    def set_state(self, next_state: Any) -> list[str]:
        """Set mist level when the humidifier is in a valid mode."""

        value = self._coerce(next_state)
        if value is None:
            return []

        active = self._active_state.active_mode
        mode_name = getattr(active, "name", None)
        if mode_name == "manual_mode":
            return self._set_manual_level(value)
        if mode_name == "custom_mode":
            return self._set_custom_level(value)
        if mode_name == "auto_mode":
            return self._set_auto_level(value)
        return []

    def _set_manual_level(self, value: int) -> list[str]:
        result = self._dispatch_delegate("manual_mode", value, ensure_manual=True)
        if result is not None:
            return result
        self._ensure_manual_activation()
        return super().set_state(value)

    def _set_custom_level(self, value: int) -> list[str]:
        result = self._dispatch_delegate("custom_mode", {"mistLevel": value})
        if result is not None:
            return result
        return super().set_state(value)

    def _set_auto_level(self, value: int) -> list[str]:
        result = self._dispatch_delegate("manual_mode", value, ensure_manual=True)
        if result is not None:
            return result
        self._active_state.set_state("manual_mode")
        self._ensure_manual_activation()
        return super().set_state(value)

    def _extract_delegate(self, option: DeviceState[str] | None) -> Any | None:
        if option is None:
            return None
        delegate = getattr(option, "delegate_state", None)
        if delegate is not None:
            return delegate
        if getattr(option, "is_commandable", False) and hasattr(option, "set_state"):
            return option
        return None

    def _subscribe_to_delegate(self, mode_name: str, delegate: Any | None) -> None:
        if delegate is None or mode_name in self._delegate_callbacks:
            return
        register = getattr(delegate, "register_listener", None)
        if not callable(register):
            return

        def _listener(value: Any) -> None:
            self._handle_delegate_update(mode_name, value)

        register(_listener)
        self._delegate_callbacks[mode_name] = _listener

    def _handle_delegate_update(self, mode_name: str, value: Any) -> None:
        level = self._extract_level(mode_name, value)
        if mode_name == self._current_mode:
            if level is None:
                if self.value is not None:
                    self._update_state(None)
            else:
                self._update_state(level)

    def _extract_level(self, mode_name: str, value: Any) -> int | None:
        if mode_name == "custom_mode":
            if isinstance(value, Mapping):
                level = value.get("mistLevel")
            else:
                return None
        else:
            level = value
        return self._coerce(level)

    def _handle_active_mode(self, mode: DeviceState[str] | None) -> None:
        mode_name = getattr(mode, "name", None)
        if mode_name not in {"manual_mode", "custom_mode"}:
            self._current_mode = None
            if self.value is not None:
                self._update_state(None)
            return
        self._current_mode = mode_name
        delegate = self._delegates.get(mode_name)
        self._subscribe_to_delegate(mode_name, delegate)
        level = self._extract_level(mode_name, self._delegate_value(delegate))
        if level is None:
            if self.value is not None:
                self._update_state(None)
        else:
            self._update_state(level)

    @staticmethod
    def _delegate_value(delegate: Any | None) -> Any:
        return getattr(delegate, "value", None) if delegate is not None else None

    def _dispatch_delegate(
        self, mode_name: str, payload: Any, *, ensure_manual: bool = False
    ) -> list[str] | None:
        delegate = self._delegates.get(mode_name)
        if delegate is None or not hasattr(delegate, "set_state"):
            return None
        result = delegate.set_state(payload)
        current = self._delegate_value(delegate)
        level = self._extract_level(
            mode_name, current if current is not None else payload
        )
        if ensure_manual:
            self._ensure_manual_activation()
        if level is not None:
            self._update_state(level)
        return result

    def _ensure_manual_activation(self) -> None:
        active = self._active_state.active_mode
        if getattr(active, "name", None) != "manual_mode":
            self._active_state.activate("manual_mode")


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
        auto_mode = self._active_state.resolve_mode(self._auto_mode_name)
        if auto_mode is not None and hasattr(auto_mode, "set_state"):
            auto_mode.set_state({"targetHumidity": clamped})
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

    @staticmethod
    def _resolve_mode_delegate(device_model: Any, mode_name: str) -> Any | None:
        """Return a backing state for ``mode_name`` when exposed by the model."""

        def _candidates(name: str) -> list[str]:
            base = name.strip()
            parts = base.split("_")
            camel = parts[0] + "".join(part.capitalize() for part in parts[1:])
            return [
                f"{base}_state",
                base,
                camel,
                f"{camel}State",
            ]

        for attribute in _candidates(mode_name):
            if not attribute:
                continue
            candidate = getattr(device_model, attribute, None)
            if candidate is not None:
                return candidate
        return None

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

        manual_delegate = self._resolve_mode_delegate(device_model, "manual_mode")
        custom_delegate = self._resolve_mode_delegate(device_model, "custom_mode")
        auto_delegate = self._resolve_mode_delegate(device_model, "auto_mode")

        manual = self.add_state(
            ManualModeState(device=device_model, delegate=manual_delegate)
        )
        custom = self.add_state(
            CustomModeState(device=device_model, delegate=custom_delegate)
        )
        auto = self.add_state(
            AutoModeState(device=device_model, delegate=auto_delegate)
        )
        for mode_state in (manual, custom, auto):
            self.expose_entity(
                platform="sensor",
                state=mode_state,
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        self._auto_mode_state = auto

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
                self._auto_mode_state.bind_humidity_state(registered)
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
