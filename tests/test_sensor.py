"""Tests for the Nature Remo sensor platform."""

from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
from aionatureremo import NatureRemoConnectionError
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)


async def test_remo_device_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Remo 3 exposes temperature, humidity, illuminance and last motion."""
    temperature = hass.states.get("sensor.living_remo_temperature")
    assert temperature is not None
    assert temperature.state == "26.4"
    assert temperature.attributes["device_class"] == "temperature"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["state_class"] == "measurement"

    humidity = hass.states.get("sensor.living_remo_humidity")
    assert humidity is not None
    assert humidity.state == "52.0"
    assert humidity.attributes["device_class"] == "humidity"
    assert humidity.attributes["unit_of_measurement"] == "%"

    illuminance = hass.states.get("sensor.living_remo_illuminance")
    assert illuminance is not None
    assert illuminance.state == "123.4"
    assert "device_class" not in illuminance.attributes
    assert "unit_of_measurement" not in illuminance.attributes

    motion = hass.states.get("sensor.living_remo_last_motion")
    assert motion is not None
    assert motion.state == "2026-07-18T07:50:00+00:00"
    assert motion.attributes["device_class"] == "timestamp"


async def test_sensors_follow_event_presence(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Remo mini (te only) gets no humidity; Remo E lite gets nothing."""
    assert hass.states.get("sensor.bedroom_remo_mini_temperature") is not None
    assert hass.states.get("sensor.bedroom_remo_mini_humidity") is None
    assert hass.states.get("sensor.bedroom_remo_mini_illuminance") is None
    assert hass.states.get("sensor.bedroom_remo_mini_last_motion") is None
    assert hass.states.get("sensor.remo_e_lite_temperature") is None


async def test_sensors_unavailable_on_update_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A failed poll marks sensors unavailable."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.living_remo_temperature")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
