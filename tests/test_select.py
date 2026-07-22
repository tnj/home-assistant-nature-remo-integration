"""Tests for the Nature Remo select platform."""

from unittest.mock import AsyncMock

from aionatureremo import Appliance, TVState
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import load_json_fixture

ENTITY = "select.living_tv_input"


async def test_select_state_and_options(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The TV input select mirrors state.input."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "t"
    assert state.attributes[ATTR_OPTIONS] == ["t", "bs", "cs"]


async def test_select_option_sends_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Selecting an input presses the matching TV button."""
    mock_client.send_tv_button.return_value = TVState(input="bs")
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "bs"},
        blocking=True,
    )
    mock_client.send_tv_button.assert_called_once_with("appliance-tv-1", "input-bs")
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "bs"


async def test_select_optimistic_when_response_lacks_input(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A response without input still updates the state optimistically."""
    mock_client.send_tv_button.return_value = TVState(input=None)
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "cs"},
        blocking=True,
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "cs"


async def test_no_select_without_input_buttons(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A TV without input-* buttons gets no input select."""
    payloads = load_json_fixture("appliances.json")
    for payload in payloads:
        if payload["id"] == "appliance-tv-1":
            payload["tv"]["buttons"] = [
                button
                for button in payload["tv"]["buttons"]
                if not button["name"].startswith("input-")
            ]
    mock_client.get_appliances.return_value = [
        Appliance.from_dict(item) for item in payloads
    ]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY) is None
