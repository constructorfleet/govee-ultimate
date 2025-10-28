"""Tests for air quality sensor state parsing."""

from __future__ import annotations

import pytest

from custom_components.govee_ultimate.state.states import (
    AirQualityHumidityState,
    AirQualityPM25State,
    AirQualityTemperatureState,
)


class DummyDevice:
    """Minimal device stub for state parsing tests."""

    def add_status_listener(self, _callback):  # pragma: no cover - interface hook
        """Accept a listener callback for interface compatibility."""

        return None


@pytest.fixture
def device() -> DummyDevice:
    """Return a dummy device instance."""

    return DummyDevice()


@pytest.fixture
def temperature_state(device: DummyDevice) -> AirQualityTemperatureState:
    """Return an air quality temperature state."""

    return AirQualityTemperatureState(device=device)


@pytest.fixture
def humidity_state(device: DummyDevice) -> AirQualityHumidityState:
    """Return an air quality humidity state."""

    return AirQualityHumidityState(device=device)


@pytest.fixture
def pm25_state(device: DummyDevice) -> AirQualityPM25State:
    """Return an air quality PM2.5 state."""

    return AirQualityPM25State(device=device)


def test_temperature_state_normalises_measurement_payload(
    temperature_state: AirQualityTemperatureState,
) -> None:
    """Temperature payloads should normalize and store calibration data."""

    payload = {
        "state": {
            "temperature": {
                "current": 2356,
                "calibration": 12,
                "min": 1800,
                "max": 3200,
            }
        }
    }

    temperature_state.parse_state(payload)

    assert temperature_state.value == {
        "current": pytest.approx(23.56),
        "raw": pytest.approx(23.44),
        "calibration": pytest.approx(0.12),
        "range": {"min": pytest.approx(18.0), "max": pytest.approx(32.0)},
    }


def test_humidity_state_clamps_percentage(
    humidity_state: AirQualityHumidityState,
) -> None:
    """Humidity payloads are coerced into a bounded percentage."""

    payload = {"state": {"humidity": {"current": "48.3", "min": 20, "max": 90}}}

    humidity_state.parse_state(payload)

    assert humidity_state.value == {
        "current": pytest.approx(48.3),
        "range": {"min": 20, "max": 90},
    }


def test_pm25_state_preserves_warning_flags(pm25_state: AirQualityPM25State) -> None:
    """PM2.5 payloads expose warning state and range limits."""

    payload = {
        "state": {
            "pm25": {
                "current": 17,
                "warning": True,
                "min": 0,
                "max": 300,
            }
        }
    }

    pm25_state.parse_state(payload)

    assert pm25_state.value == {
        "current": 17,
        "warning": True,
        "range": {"min": 0, "max": 300},
    }
