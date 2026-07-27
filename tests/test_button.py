"""Tests for the Nature Remo button platform."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aionatureremo import (
    Appliance,
    ApplianceButton,
    LightState,
    NatureRemoConnectionError,
)
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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


async def test_signal_button_failure_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A failed IR signal send surfaces as HomeAssistantError."""
    mock_client.send_signal.side_effect = NatureRemoConnectionError("boom")
    with pytest.raises(HomeAssistantError, match="Failed to send IR signal"):
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: "button.fan_power"},
            blocking=True,
        )


async def test_light_button_failure_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A failed light-button press surfaces as HomeAssistantError."""
    entity_registry = er.async_get(hass)
    night_entity = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_night"
    )
    assert night_entity is not None
    mock_client.send_light_button.side_effect = NatureRemoConnectionError("boom")
    with pytest.raises(HomeAssistantError, match="Bedroom Light"):
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: night_entity}, blocking=True
        )


async def test_tv_shortcut_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The everyday TV shortcuts are enabled by default; pressing sends the name."""
    entity_registry = er.async_get(hass)

    for name in (
        "power",
        "select-input-src",
        "ch-up",
        "ch-down",
        "vol-up",
        "vol-down",
    ):
        entity_id = entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, f"appliance-tv-1_button_{name}"
        )
        assert entity_id is not None
        entry = entity_registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is None

    vol_up_entity = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-tv-1_button_vol-up"
    )
    assert vol_up_entity is not None
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: vol_up_entity}, blocking=True
    )
    mock_client.send_tv_button.assert_called_once_with("appliance-tv-1", "vol-up")


async def test_tv_vocabulary_button_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A vocabulary-mapped bulk TV button registers but stays disabled by default."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-tv-1_button_mute"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert entry.translation_key == "mute"
    # Disabled entities have no state.
    assert hass.states.get(entity_id) is None


async def test_tv_button_fallback_label_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A TV button outside the vocabulary falls back to its label, disabled."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-tv-1_button_input"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert entry.translation_key is None
    assert entry.original_name == "TV_input"


async def test_tv_button_empty_name_not_created(
    hass: HomeAssistant, init_integration: MockConfigEntry, appliances: list[Appliance]
) -> None:
    """No entity is created for an empty/duplicate button name."""
    entity_registry = er.async_get(hass)
    tv_appliance = next(a for a in appliances if a.id == "appliance-tv-1")
    assert tv_appliance.tv is not None
    expected_names = {b.name for b in tv_appliance.tv.buttons if b.name}
    assert "" in {b.name for b in tv_appliance.tv.buttons}  # fixture sanity check

    tv_entity_ids = [
        entity_id
        for entity_id in entity_registry.entities
        if entity_id.startswith(f"{BUTTON_DOMAIN}.")
        and (entry := entity_registry.async_get(entity_id)) is not None
        and entry.unique_id.startswith("appliance-tv-1_button_")
    ]
    assert len(tv_entity_ids) == len(expected_names)


async def test_light_button_unknown_name_uses_label(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A light button with an unmapped name falls back to its label."""
    mock_client.get_appliances.return_value = [
        replace(
            appliance,
            light=replace(
                appliance.light,
                buttons=[
                    *appliance.light.buttons,
                    ApplianceButton(
                        name="sleep-timer", image="ico_timer", label="Sleep timer"
                    ),
                ],
            ),
        )
        if appliance.id == "appliance-light-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-light-1_button_sleep-timer"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["friendly_name"] == "Bedroom Light Sleep timer"


async def test_projector_power_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """The projector "io" power key is enabled by default and sends the press."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-projector-1_button_io"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["friendly_name"] == "Projector Power"

    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    mock_client.send_light_projector_button.assert_called_once_with(
        "appliance-projector-1", "io"
    )


async def test_projector_non_power_button_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Non-io projector buttons register but stay disabled by default."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-projector-1_button_plus"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert entry.translation_key is None
    # Disabled entities have no state.
    assert hass.states.get(entity_id) is None


async def test_projector_non_power_button_press_when_enabled(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An enabled non-io projector button sends its layout leaf name."""
    # Pre-register the entity as enabled: entities only pick up
    # disabled_by=INTEGRATION when first created in the registry.
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create(
        BUTTON_DOMAIN,
        DOMAIN,
        "appliance-projector-1_button_plus",
        suggested_object_id="projector_volume_up",
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("button.projector_volume_up")
    assert state is not None
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: "button.projector_volume_up"},
        blocking=True,
    )
    mock_client.send_light_projector_button.assert_called_once_with(
        "appliance-projector-1", "plus"
    )


async def test_projector_all_layout_buttons_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Every button leaf of the flattened layout tree gets a registry entry."""
    entity_registry = er.async_get(hass)
    projector_unique_ids = {
        entry.unique_id
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
        and entry.domain == BUTTON_DOMAIN
        and entry.unique_id.startswith("appliance-projector-1_button_")
    }
    assert projector_unique_ids == {
        f"appliance-projector-1_button_{name}"
        for name in (
            "plus",
            "minus",
            "arrow-top",
            "arrow-left",
            "record",
            "arrow-right",
            "arrow-bottom",
            "light-all",
            "focus",
            "io",
            "home",
            "return",
            "setting",
        )
    }


async def test_projector_button_names_come_from_text(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Entity names use the API "text" verbatim (yes, "Auto Forcus" is real)."""
    entity_registry = er.async_get(hass)
    for name, expected in (("plus", "Volume Up"), ("focus", "Auto Forcus")):
        entity_id = entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, f"appliance-projector-1_button_{name}"
        )
        assert entity_id is not None
        entry = entity_registry.async_get(entity_id)
        assert entry is not None
        assert entry.original_name == expected


async def test_ac_fixed_buttons(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """AC fixed buttons (except power-off) become enabled button entities."""
    entity_registry = er.async_get(hass)

    for name in ("airdir-swing", "airdir-tilt"):
        entity_id = entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, f"appliance-ac-1_button_{name}"
        )
        assert entity_id is not None
        entry = entity_registry.async_get(entity_id)
        assert entry is not None
        assert entry.disabled_by is None

    # power-off stays exclusive to the climate entity.
    assert (
        entity_registry.async_get_entity_id(
            BUTTON_DOMAIN, DOMAIN, "appliance-ac-1_button_power-off"
        )
        is None
    )

    swing_entity = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-ac-1_button_airdir-swing"
    )
    assert swing_entity is not None
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: swing_entity}, blocking=True
    )
    mock_client.set_aircon_settings.assert_called_once_with(
        "appliance-ac-1", button="airdir-swing"
    )


async def test_ac_fixed_button_unknown_name_uses_name(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """An AC fixed button outside the vocabulary falls back to its name."""
    mock_client.get_appliances.return_value = [
        replace(
            appliance,
            aircon=replace(
                appliance.aircon,
                fixed_buttons=[*appliance.aircon.fixed_buttons, "eco"],
            ),
        )
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, "appliance-ac-1_button_eco"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    assert entry.translation_key is None
    assert entry.original_name == "eco"
