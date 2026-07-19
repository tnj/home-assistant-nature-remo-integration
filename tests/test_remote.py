"""Tests for the Nature Remo remote platform."""

from unittest.mock import AsyncMock, call

import pytest
from aionatureremo import TVState
from homeassistant.components.remote import (
    ATTR_COMMAND,
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    SERVICE_SEND_COMMAND,
)
from homeassistant.components.remote import (
    DOMAIN as REMOTE_DOMAIN,
)
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY = "remote.living_tv"


async def test_remote_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A stateless IR remote reports unknown and assumed_state."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_ASSUMED_STATE] is True


async def test_remote_send_command_with_repeats(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Commands are validated and repeated in order."""
    mock_client.send_tv_button.return_value = TVState(input="t")
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_SEND_COMMAND,
        {
            ATTR_ENTITY_ID: ENTITY,
            ATTR_COMMAND: ["vol-up", "vol-down"],
            ATTR_NUM_REPEATS: 2,
            ATTR_DELAY_SECS: 0,
        },
        blocking=True,
    )
    assert mock_client.send_tv_button.call_args_list == [
        call("appliance-tv-1", "vol-up"),
        call("appliance-tv-1", "vol-down"),
        call("appliance-tv-1", "vol-up"),
        call("appliance-tv-1", "vol-down"),
    ]


async def test_remote_send_unknown_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A button the TV does not have raises and sends nothing."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: ENTITY, ATTR_COMMAND: ["does-not-exist"]},
            blocking=True,
        )
    mock_client.send_tv_button.assert_not_called()


async def test_remote_turn_on_off_press_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """turn_on and turn_off both press the power toggle."""
    mock_client.send_tv_button.return_value = TVState(input="t")
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    await hass.services.async_call(
        REMOTE_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert mock_client.send_tv_button.call_args_list == [
        call("appliance-tv-1", "power"),
        call("appliance-tv-1", "power"),
    ]
