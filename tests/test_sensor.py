"""Tests for the Nature Remo sensor platform."""

from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
from aionatureremo import Appliance, NatureRemoConnectionError
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from tests.conftest import load_json_fixture


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


async def test_smart_meter_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The smart meter exposes signed power and cumulative energies."""
    power = hass.states.get("sensor.smart_meter_power")
    assert power is not None
    assert power.state == "520"
    assert power.attributes["device_class"] == "power"
    assert power.attributes["unit_of_measurement"] == "W"
    assert power.attributes["state_class"] == "measurement"

    purchased = hass.states.get("sensor.smart_meter_purchased_energy")
    assert purchased is not None
    assert purchased.state == "12345.6"
    assert purchased.attributes["device_class"] == "energy"
    assert purchased.attributes["unit_of_measurement"] == "kWh"
    assert purchased.attributes["state_class"] == "total_increasing"

    sold = hass.states.get("sensor.smart_meter_sold_energy")
    assert sold is not None
    assert sold.state == "123.4"
    assert sold.attributes["state_class"] == "total_increasing"


async def test_smart_meter_without_reverse_direction(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A meter without EPC 227 (no solar) gets no sold-energy sensor."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-meter-1":
            payload["smart_meter"]["echonetlite_properties"] = [
                prop
                for prop in payload["smart_meter"]["echonetlite_properties"]
                if prop["epc"] != 227
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.smart_meter_purchased_energy") is not None
    assert hass.states.get("sensor.smart_meter_sold_energy") is None
