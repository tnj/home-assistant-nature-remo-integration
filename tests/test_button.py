"""Tests for the Nature Remo button platform."""

from unittest.mock import AsyncMock

from aionatureremo import LightState
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nature_remo.const import DOMAIN


async def test_ir_signal_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Each learned IR signal becomes a button that sends it."""
    state = hass.states.get("button.fan_power")
    assert state is not None
    assert hass.states.get("button.fan_speed") is not None

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.fan_power"},
        blocking=True,
    )
    mock_client.send_signal.assert_called_once_with("signal-1")


async def test_light_extra_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Non-power light buttons become buttons; on/off do not."""
    entity_registry = er.async_get(hass)

    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_night"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_on"
        )
        is None
    )
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_off"
        )
        is None
    )

    mock_client.send_light_button.return_value = LightState(
        brightness="0", power="on", last_button="night"
    )
    night_entity = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_night"
    )
    assert night_entity is not None
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: night_entity}, blocking=True
    )
    mock_client.send_light_button.assert_called_once_with("appliance-light-1", "night")
