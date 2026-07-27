"""Tests for the Nature Remo number platform."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import Device
from homeassistant.components.number import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_offset_numbers_follow_sensor_presence(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Remo 3 gets both offsets; mini (te only) gets no humidity offset."""
    temperature_offset = hass.states.get("number.living_remo_temperature_offset")
    assert temperature_offset is not None
    assert temperature_offset.state == "0.0"
    assert temperature_offset.attributes["min"] == -10
    assert temperature_offset.attributes["max"] == 10
    assert hass.states.get("number.living_remo_humidity_offset") is not None

    mini_temperature = hass.states.get("number.bedroom_remo_mini_temperature_offset")
    assert mini_temperature is not None
    assert mini_temperature.state == "1.0"
    assert hass.states.get("number.bedroom_remo_mini_humidity_offset") is None

    assert hass.states.get("number.remo_e_lite_temperature_offset") is None


async def test_set_temperature_offset(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    devices: list[Device],
) -> None:
    """Setting the number calls the API and applies the response."""
    mock_client.set_temperature_offset.return_value = replace(
        devices[0], temperature_offset=2.0
    )
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: "number.living_remo_temperature_offset",
            ATTR_VALUE: 2,
        },
        blocking=True,
    )
    mock_client.set_temperature_offset.assert_called_once_with("device-remo3-1", 2)
    state = hass.states.get("number.living_remo_temperature_offset")
    assert state is not None
    assert state.state == "2.0"


async def test_set_temperature_offset_rejects_fractional_value(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A non-integral value is rejected instead of silently rounded."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {
                ATTR_ENTITY_ID: "number.living_remo_temperature_offset",
                ATTR_VALUE: 2.5,
            },
            blocking=True,
        )
    mock_client.set_temperature_offset.assert_not_called()


async def test_set_temperature_offset_accepts_integral_float(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    devices: list[Device],
) -> None:
    """An integral float (e.g. 3.0 from box mode) is accepted as an int."""
    mock_client.set_temperature_offset.return_value = replace(
        devices[0], temperature_offset=3.0
    )
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {
            ATTR_ENTITY_ID: "number.living_remo_temperature_offset",
            ATTR_VALUE: 3.0,
        },
        blocking=True,
    )
    mock_client.set_temperature_offset.assert_called_once_with("device-remo3-1", 3)
