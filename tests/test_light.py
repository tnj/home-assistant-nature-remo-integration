"""Tests for the Nature Remo light platform."""

from unittest.mock import AsyncMock

from aionatureremo import Appliance, LightState
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import load_json_fixture

ENTITY = "light.bedroom_light"


async def test_light_state_and_turn_off(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The light reflects state.power and sends discrete on/off buttons."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON
    assert ATTR_ASSUMED_STATE not in state.attributes

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="off", last_button="off"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with("appliance-light-1", "off")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_OFF  # optimistic update from the response

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="on", last_button="on"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.send_light_button.call_args.args == ("appliance-light-1", "on")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON


async def test_light_toggle_only_model_is_assumed_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A light with only an onoff button toggles and is assumed_state."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-light-1":
            payload["light"]["buttons"] = [
                {"name": "onoff", "image": "ico_on", "label": "Light_onoff"}
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_ASSUMED_STATE] is True

    mock_client.send_light_button.return_value = LightState(
        brightness="100", power="off", last_button="onoff"
    )
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with("appliance-light-1", "onoff")
