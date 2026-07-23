"""Tests for the Nature Remo switch platform (AC extras)."""

from dataclasses import replace
from unittest.mock import AsyncMock

from aionatureremo import AirconSettings, Appliance
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTITY = "switch.living_ac_mold_proof"


async def test_extra_switch_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A writable binary extra becomes a config-category switch."""
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_ON

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(ENTITY)
    assert entry is not None
    assert entry.unique_id == "appliance-ac-1_extra_autoclean"
    assert entry.entity_category is EntityCategory.CONFIG
    assert entry.translation_key == "autoclean"


async def test_extra_switch_turn_off_preserves_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Toggling sends only the power button + new extra value."""
    mock_client.set_aircon_settings.return_value = AirconSettings(
        temperature="26",
        temperature_unit="c",
        mode="cool",
        volume="auto",
        direction="swing",
        direction_h="",
        button="",
        updated_at=None,
        extra={"autoclean": "off"},
    )
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.set_aircon_settings.assert_called_once_with(
        "appliance-ac-1", button="", extra={"autoclean": "off"}
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "off"  # optimistic update from the response


async def test_no_switch_for_unavailable_extra(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Extras whose availability is not 'available' get no switch."""
    modified = []
    for appliance in appliances:
        if appliance.id == "appliance-ac-1" and appliance.aircon is not None:
            aircon = replace(
                appliance.aircon,
                extras=[
                    replace(extra, availability="unavailable")
                    for extra in appliance.aircon.extras
                ],
            )
            modified.append(replace(appliance, aircon=aircon))
        else:
            modified.append(appliance)
    mock_client.get_appliances.return_value = modified

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY) is None
