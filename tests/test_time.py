"""Tests for the Nature Remo time platform (schedule-type AC extras)."""

from dataclasses import replace
from datetime import time, timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import AirconSettings, Appliance
from homeassistant.components.time import ATTR_TIME, SERVICE_SET_VALUE
from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo.const import DOMAIN

ENTITY = "time.bedroom_ac_night_set_mode"


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


async def test_extra_time_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A schedule-type extra becomes a config-category time entity.

    Nothing is stored in settings.extra for new_sleep, so the state is
    unknown: the catalog's defaultTime ("21:00") is the remote's default,
    deliberately NOT surfaced as state.
    """
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(ENTITY)
    assert entry is not None
    assert entry.unique_id == "appliance-ac-2_extra_new_sleep"
    assert entry.entity_category is EntityCategory.CONFIG
    assert entry.translation_key == "new_sleep"


async def test_non_time_extras_get_no_time_entity(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Choice extras (multi-option or binary) never become time entities."""
    entity_registry = er.async_get(hass)
    for extra_id in ("humid", "dehumid", "powerful", "hotwind", "autoclean"):
        assert (
            entity_registry.async_get_entity_id(
                TIME_DOMAIN, DOMAIN, f"appliance-ac-2_extra_{extra_id}"
            )
            is None
        )
    assert (
        entity_registry.async_get_entity_id(
            TIME_DOMAIN, DOMAIN, "appliance-ac-1_extra_autoclean"
        )
        is None
    )
    assert (
        entity_registry.async_get_entity_id(
            TIME_DOMAIN, DOMAIN, "appliance-floorheater-1_extra_save_energy"
        )
        is None
    )


async def test_extra_time_set_value_preserves_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """Setting the time sends only the power button + merged extras as HH:MM."""
    mock_client.set_aircon_settings.return_value = AirconSettings(
        temperature="22",
        temperature_unit="c",
        mode="warm",
        volume="auto",
        direction="auto",
        direction_h="auto",
        button="",
        updated_at=None,
        extra={"powerful": "off", "new_sleep": "21:00"},
    )
    await hass.services.async_call(
        TIME_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TIME: time(21, 0)},
        blocking=True,
    )
    mock_client.set_aircon_settings.assert_called_once_with(
        "appliance-ac-2", button="", extra={"powerful": "off", "new_sleep": "21:00"}
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == "21:00:00"  # optimistic update from the response


async def test_extra_time_ignored_write_raises(
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
            TIME_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: ENTITY, ATTR_TIME: time(21, 0)},
            blocking=True,
        )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN  # server truth applied before the raise


async def test_extra_time_malformed_stored_value_is_unknown(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A stored value that isn't HH:MM yields unknown instead of an error."""
    mock_client.get_appliances.return_value = [
        replace(
            appliance,
            settings=replace(appliance.settings, extra={"new_sleep": "garbage"}),
        )
        if appliance.id == "appliance-ac-2"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN


async def test_extra_time_tracks_availability_flip(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Time entities follow per-poll availability flips caused by mode changes."""
    assert hass.states.get(ENTITY).state == STATE_UNKNOWN

    mock_client.get_appliances.return_value = _with_extra_availability(
        appliances, "appliance-ac-2", {"new_sleep": "hidden"}
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE


async def test_time_fallback_name_from_catalog_text(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A time extra without a known translation key is named from its text."""
    state = hass.states.get("time.bedroom_ac_off_timer")
    assert state is not None
    assert state.attributes["friendly_name"] == "Bedroom AC Off Timer"
