"""Tests for the Nature Remo climate platform."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import AirconSettings, Appliance, NatureRemoRateLimitError
from homeassistant.components.climate import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_SWING_HORIZONTAL_MODE,
    ATTR_SWING_HORIZONTAL_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    ATTR_TARGET_TEMP_STEP,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_HORIZONTAL_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY = "climate.living_ac"


def _settings(**overrides: str | None) -> AirconSettings:
    """Build an AirconSettings for mock command responses."""
    values: dict[str, str | None] = {
        "temperature": "26",
        "temperature_unit": "c",
        "mode": "cool",
        "volume": "auto",
        "direction": "swing",
        "direction_h": "",
        "button": "",
        "updated_at": None,
    }
    values.update(overrides)
    return AirconSettings(**values)  # type: ignore[arg-type]


async def test_climate_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The AC exposes dynamic modes, ranges and current readings."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 26.4
    assert state.attributes[ATTR_CURRENT_HUMIDITY] == 52
    assert state.attributes[ATTR_TEMPERATURE] == 26.0
    assert state.attributes[ATTR_FAN_MODE] == "auto"
    assert state.attributes[ATTR_SWING_MODE] == "swing"
    assert set(state.attributes[ATTR_HVAC_MODES]) == {
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    }
    assert state.attributes[ATTR_FAN_MODES] == ["1", "2", "3", "auto"]
    assert state.attributes[ATTR_SWING_MODES] == ["1", "2", "swing", "auto"]
    assert state.attributes[ATTR_SWING_HORIZONTAL_MODES] == ["1", "2", "3", "swing"]
    assert state.attributes[ATTR_MIN_TEMP] == 18.0  # union across absolute modes
    assert state.attributes[ATTR_MAX_TEMP] == 28.0
    assert state.attributes[ATTR_TARGET_TEMP_STEP] == 1.0


async def test_climate_off_state_from_api(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """button == power-off reports HVACMode.OFF."""
    mock_client.get_appliances.return_value = [
        replace(appliance, settings=replace(appliance.settings, button="power-off"))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF


async def test_climate_turn_off_and_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_off sends the full settings plus power-off; turn_on restores."""
    mock_client.set_aircon_settings.return_value = _settings(button="power-off")
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    call = mock_client.set_aircon_settings.call_args
    assert call.args == ("appliance-ac-1",)
    assert call.kwargs["button"] == "power-off"
    assert call.kwargs["operation_mode"] == "cool"
    assert call.kwargs["temperature"] == "26"
    assert call.kwargs["air_volume"] == "auto"
    assert call.kwargs["air_direction"] == "swing"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.OFF  # optimistic update from the response

    mock_client.set_aircon_settings.return_value = _settings()
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["button"] == ""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL


async def test_climate_set_temperature(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature snaps the value into the mode's allowed list."""
    mock_client.set_aircon_settings.return_value = _settings(temperature="27")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 27},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["temperature"] == "27"
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_TEMPERATURE] == 27.0


async def test_climate_set_temperature_with_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """set_temperature with hvac_mode switches mode in the same command."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="20"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 20, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "20"


async def test_climate_set_hvac_mode_coerces_settings(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """cool(26)→warm snaps the temperature into warm's 18-22 range."""
    mock_client.set_aircon_settings.return_value = _settings(
        mode="warm", temperature="22"
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    kwargs = mock_client.set_aircon_settings.call_args.kwargs
    assert kwargs["operation_mode"] == "warm"
    assert kwargs["temperature"] == "22"  # 26 snapped to warm's max 22
    assert kwargs["button"] == ""
    assert "air_direction_h" not in kwargs  # warm has no dirh range
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.HEAT


async def test_climate_set_fan_and_swing_modes(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Fan, vertical swing and horizontal swing map to vol/dir/dirh."""
    mock_client.set_aircon_settings.return_value = _settings(volume="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_volume"] == "2"

    mock_client.set_aircon_settings.return_value = _settings(direction="1")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_MODE: "1"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction"] == "1"

    mock_client.set_aircon_settings.return_value = _settings(direction_h="2")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_HORIZONTAL_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_HORIZONTAL_MODE: "2"},
        blocking=True,
    )
    assert mock_client.set_aircon_settings.call_args.kwargs["air_direction_h"] == "2"


async def test_climate_command_failure_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """API failures surface as HomeAssistantError."""
    mock_client.set_aircon_settings.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )
    with pytest.raises(HomeAssistantError, match="Living AC"):
        await hass.services.async_call(
            CLIMATE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
