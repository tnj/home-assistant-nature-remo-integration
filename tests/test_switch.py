"""Tests for the Nature Remo switch platform (AC extras)."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import Appliance, NatureRemoConnectionError, NatureRemoRateLimitError
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import DATA_INSTANCES
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo.const import DOMAIN
from tests.conftest import aircon_settings, with_extra_availability

ENTITY = "switch.living_ac_mold_proof"
FH_ENTITY = "switch.floor_heater_save_energy"


def _without_extra_options(
    appliances: list[Appliance], appliance_id: str, extra_id: str
) -> list[Appliance]:
    """Rebuild the appliance list with one extra's options list emptied."""
    modified = []
    for appliance in appliances:
        if appliance.id == appliance_id and appliance.aircon is not None:
            aircon = replace(
                appliance.aircon,
                extras=[
                    replace(extra, options=[]) if extra.id == extra_id else extra
                    for extra in appliance.aircon.extras
                ],
            )
            modified.append(replace(appliance, aircon=aircon))
        else:
            modified.append(appliance)
    return modified


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
    mock_client.set_aircon_settings.return_value = aircon_settings(
        extra={"autoclean": "off"}
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


async def test_hidden_extra_still_gets_switch_but_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A binary extra hidden at setup gets a switch, marked unavailable.

    The catalog is static across modes; only availability flips with the
    current mode, so the entity must exist from the start and track it.
    """
    mock_client.get_appliances.return_value = with_extra_availability(
        appliances, "appliance-ac-1", {"autoclean": "hidden"}
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE


async def test_bedroom_ac_binary_extras_get_switches(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Every binary extra gets a switch regardless of current availability."""
    # powerful: available in the fixture's warm mode, stored value "off".
    powerful = hass.states.get("switch.bedroom_ac_powerful")
    assert powerful is not None
    assert powerful.state == STATE_OFF

    # hotwind: available but never stored in settings.extra -> is_on None.
    hotwind = hass.states.get("switch.bedroom_ac_hot_airflow")
    assert hotwind is not None
    assert hotwind.state == STATE_UNKNOWN

    # autoclean: hidden in warm mode -> the switch EXISTS but is unavailable
    # (a write to a hidden extra is silently ignored by the API).
    autoclean = hass.states.get("switch.bedroom_ac_mold_proof")
    assert autoclean is not None
    assert autoclean.state == STATE_UNAVAILABLE


async def test_non_binary_extras_get_no_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Multi-option choice and time extras never become switches."""
    entity_registry = er.async_get(hass)
    for extra_id in ("humid", "dehumid", "new_sleep"):
        assert (
            entity_registry.async_get_entity_id(
                SWITCH_DOMAIN, DOMAIN, f"appliance-ac-2_extra_{extra_id}"
            )
            is None
        )


async def test_extra_switch_tracks_availability_flip(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Switches follow per-poll availability flips caused by mode changes."""
    assert hass.states.get("switch.bedroom_ac_powerful").state == STATE_OFF
    assert hass.states.get("switch.bedroom_ac_mold_proof").state == STATE_UNAVAILABLE

    mock_client.get_appliances.return_value = with_extra_availability(
        appliances,
        "appliance-ac-2",
        {"powerful": "hidden", "dehumid": "available", "autoclean": "available"},
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    # powerful went hidden -> unavailable.
    assert hass.states.get("switch.bedroom_ac_powerful").state == STATE_UNAVAILABLE
    # autoclean became available; never stored -> unknown.
    assert hass.states.get("switch.bedroom_ac_mold_proof").state == STATE_UNKNOWN
    # dehumid is now available but non-binary, so it still gets no switch.
    entity_registry = er.async_get(hass)
    assert (
        entity_registry.async_get_entity_id(
            SWITCH_DOMAIN, DOMAIN, "appliance-ac-2_extra_dehumid"
        )
        is None
    )


async def test_extra_switch_preserves_power_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Toggling an extra on an OFF AC resends power-off, never powering it on."""
    mock_client.get_appliances.return_value = [
        replace(appliance, settings=replace(appliance.settings, button="power-off"))
        if appliance.id == "appliance-ac-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_client.set_aircon_settings.return_value = aircon_settings(
        button="power-off", extra={"autoclean": "off"}
    )
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    mock_client.set_aircon_settings.assert_called_once_with(
        "appliance-ac-1", button="power-off", extra={"autoclean": "off"}
    )


async def test_extra_switch_ignored_write_raises(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A 200 whose echo lacks the extra means the server ignored the write.

    Happens when the extra went hidden between polls (e.g. right after an
    external mode change): a successful write always echoes the extra back
    (probe-verified), so a missing echo is a silent server-side no-op. The
    entity applies server truth first (state goes unknown), then raises.
    """
    mock_client.set_aircon_settings.return_value = aircon_settings(extra={})
    with pytest.raises(HomeAssistantError, match="ignored the write"):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN  # server truth applied before the raise


@pytest.mark.parametrize(
    ("entity_id", "service", "client_method", "nickname"),
    [
        (ENTITY, SERVICE_TURN_OFF, "set_aircon_settings", "Living AC"),
        (FH_ENTITY, SERVICE_TURN_ON, "set_floor_heater_settings", "Floor heater"),
    ],
)
async def test_extra_switch_communication_failure_raises(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    entity_id: str,
    service: str,
    client_method: str,
    nickname: str,
) -> None:
    """A failed extras write surfaces as HomeAssistantError on both endpoints.

    Covers the shared ``_async_write_extra`` error conversion for the AC
    (aircon_settings) and floor heater (floor_heater_settings) branches; the
    stored state must survive untouched, since nothing reached the remote.
    """
    before = hass.states.get(entity_id)
    assert before is not None
    getattr(mock_client, client_method).side_effect = NatureRemoConnectionError("boom")

    with pytest.raises(HomeAssistantError, match=f"Failed to update {nickname}"):
        await hass.services.async_call(
            SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == before.state  # no optimistic update on failure


async def test_extra_switch_rate_limited_write_reports_reset(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: AsyncMock
) -> None:
    """A 429 on an extras write includes the reset epoch (spec 5.5)."""
    mock_client.set_aircon_settings.side_effect = NatureRemoRateLimitError(
        429, "limited", reset=1752825600
    )
    with pytest.raises(HomeAssistantError, match="Failed to update Living AC") as exc:
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True
        )
    assert "1752825600" in str(exc.value)


async def test_floor_heater_extra_switch_state(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A floor heater binary extra becomes a config-category switch."""
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == STATE_OFF  # available; stored value "off"

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(FH_ENTITY)
    assert entry is not None
    assert entry.unique_id == "appliance-floorheater-1_extra_save_energy"
    assert entry.entity_category is EntityCategory.CONFIG


async def test_floor_heater_extra_switch_turn_on(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """Toggling writes through floor_heater_settings, never aircon_settings."""
    floor_heater = next(a for a in appliances if a.id == "appliance-floorheater-1")
    assert floor_heater.settings is not None
    # The endpoint returns the FULL updated Appliance, not bare settings.
    mock_client.set_floor_heater_settings.return_value = replace(
        floor_heater,
        settings=replace(floor_heater.settings, extra={"save_energy": "on"}),
    )
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: FH_ENTITY}, blocking=True
    )
    mock_client.set_floor_heater_settings.assert_called_once_with(
        "appliance-floorheater-1", button="power-off", extra={"save_energy": "on"}
    )
    mock_client.set_aircon_settings.assert_not_called()
    state = hass.states.get(FH_ENTITY)
    assert state is not None
    assert state.state == STATE_ON  # optimistic update from the response


async def test_optionless_choice_extra_gets_no_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A choice extra with an empty options list gets no entity at all.

    Covers the shared classification for all three extras platforms:
    nothing can be rendered for a choice with nothing to choose from, so
    neither switch, select nor time may claim it.
    """
    mock_client.get_appliances.return_value = _without_extra_options(
        appliances, "appliance-ac-1", "autoclean"
    )

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY) is None
    entity_registry = er.async_get(hass)
    for domain in (SWITCH_DOMAIN, SELECT_DOMAIN, TIME_DOMAIN):
        assert (
            entity_registry.async_get_entity_id(
                domain, DOMAIN, "appliance-ac-1_extra_autoclean"
            )
            is None
        )


async def test_extra_write_after_appliance_vanishes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An appliance gone from the account fails the write, never with KeyError.

    Drops the appliance from the coordinator data without notifying the
    listeners, which is the race the guard exists for: a write already in
    flight when the poll lands (a completed poll would also unregister the
    entity). Both state reads and the write must survive it — and the write
    is invoked directly because core filters unavailable entities out of
    service calls, so a service call would never reach the entity.
    """
    entity = hass.data[DATA_INSTANCES][SWITCH_DOMAIN].get_entity(ENTITY)
    assert entity is not None
    coordinator = init_integration.runtime_data
    coordinator.data.appliances.pop("appliance-ac-1")

    assert entity.appliance.id == "appliance-ac-1"  # last-known snapshot
    entity.async_write_ha_state()
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    with pytest.raises(HomeAssistantError, match="no longer reported"):
        await entity.async_turn_off()
    mock_client.set_aircon_settings.assert_not_called()
