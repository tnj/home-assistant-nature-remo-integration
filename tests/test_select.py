"""Tests for the Nature Remo select platform (multi-option AC extras)."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import AirconSettings, Appliance
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo.const import DOMAIN

ENTITY = "select.bedroom_ac_humidify"
DEHUMID_ENTITY = "select.bedroom_ac_dehumidify"

HUMID_OPTIONS = ["off", "40%", "45%", "50%", "continuous", "beauty"]


def _with_extra_availability(
    appliances: list[Appliance], appliance_id: str, availability: dict[str, str]
) -> list[Appliance]:
    """Rebuild the appliance list with selected extras' availability changed."""
    modified = []
    for appliance in appliances:
        if appliance.id == appliance_id and appliance.aircon is not None:
            aircon = replace(
                appliance.aircon,
                extras=[
                    replace(
                        extra,
                        availability=availability.get(extra.id, extra.availability),
                    )
                    for extra in appliance.aircon.extras
                ],
            )
            modified.append(replace(appliance, aircon=aircon))
        else:
            modified.append(appliance)
    return modified


async def test_extra_select_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A multi-option choice extra becomes a config-category select.

    Options are the API's raw vocabulary in catalog order; the state is
    unknown because settings.extra never stored a humid value.
    """
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_OPTIONS] == HUMID_OPTIONS

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(ENTITY)
    assert entry is not None
    assert entry.unique_id == "appliance-ac-2_extra_humid"
    assert entry.entity_category is EntityCategory.CONFIG
    assert entry.translation_key == "humid"
    # The entity_id really is the one derived from the translated name.
    assert (
        entity_registry.async_get_entity_id(
            SELECT_DOMAIN, DOMAIN, "appliance-ac-2_extra_humid"
        )
        == ENTITY
    )


async def test_hidden_extra_select_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An extra hidden in the current mode gets a select, marked unavailable.

    dehumid is hidden while the fixture AC sits in warm mode; a write to a
    hidden extra is silently ignored by the API, so the entity must exist
    but be unavailable rather than a silent no-op.
    """
    state = hass.states.get(DEHUMID_ENTITY)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(DEHUMID_ENTITY)
    assert entry is not None
    assert entry.unique_id == "appliance-ac-2_extra_dehumid"


async def test_binary_and_time_extras_get_no_select(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Binary on/off extras (switch territory) and time extras get no select."""
    entity_registry = er.async_get(hass)
    for unique_id in (
        "appliance-ac-2_extra_powerful",
        "appliance-ac-2_extra_hotwind",
        "appliance-ac-2_extra_autoclean",
        "appliance-ac-2_extra_new_sleep",
        "appliance-ac-1_extra_autoclean",
        "appliance-floorheater-1_extra_save_energy",
    ):
        assert (
            entity_registry.async_get_entity_id(SELECT_DOMAIN, DOMAIN, unique_id)
            is None
        )


async def test_extra_select_option_preserves_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Selecting sends only the power button + merged extras."""
    mock_client.set_aircon_settings.return_value = AirconSettings(
        temperature="22",
        temperature_unit="c",
        mode="warm",
        volume="auto",
        direction="auto",
        direction_h="auto",
        button="",
        updated_at=None,
        extra={"powerful": "off", "humid": "50%"},
    )
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "50%"},
        blocking=True,
    )
    mock_client.set_aircon_settings.assert_called_once_with(
        "appliance-ac-2", button="", extra={"powerful": "off", "humid": "50%"}
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "50%"  # optimistic update from the response


async def test_extra_select_ignored_write_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A 200 whose echo lacks the extra means the server ignored the write.

    Happens when the extra went hidden between polls (e.g. right after an
    external mode change): a successful write always echoes the extra back
    (probe-verified), so a missing echo is a silent server-side no-op. The
    entity applies server truth first (state stays unknown), then raises.
    """
    mock_client.set_aircon_settings.return_value = AirconSettings(
        temperature="22",
        temperature_unit="c",
        mode="warm",
        volume="auto",
        direction="auto",
        direction_h="auto",
        button="",
        updated_at=None,
        extra={"powerful": "off"},
    )
    with pytest.raises(HomeAssistantError, match="ignored the write"):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "50%"},
            blocking=True,
        )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN  # server truth applied before the raise


async def test_extra_select_tracks_availability_flip(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Selects follow per-poll availability flips caused by mode changes."""
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN
    assert hass.states.get(DEHUMID_ENTITY).state == STATE_UNAVAILABLE

    mock_client.get_appliances.return_value = _with_extra_availability(
        appliances,
        "appliance-ac-2",
        {"humid": "hidden", "dehumid": "available"},
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    # humid went hidden -> unavailable.
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE
    # dehumid became available; never stored -> unknown.
    assert hass.states.get(DEHUMID_ENTITY).state == STATE_UNKNOWN


async def test_extra_select_rejects_unknown_option(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Core validates the option against the list before the entity is called."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: ENTITY, ATTR_OPTION: "bogus"},
            blocking=True,
        )
    mock_client.set_aircon_settings.assert_not_called()


async def test_select_fallback_name_from_catalog_text(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An extra without a known translation key is named from its text."""
    state = hass.states.get("select.bedroom_ac_aroma")
    assert state is not None
    assert state.attributes["friendly_name"] == "Bedroom AC Aroma"
    assert state.attributes[ATTR_OPTIONS] == ["off", "low", "high"]
