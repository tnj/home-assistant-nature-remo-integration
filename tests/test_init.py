"""Tests for Nature Remo integration setup."""

import logging
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
import pytest
from aionatureremo import Appliance, NatureRemoAuthError, NatureRemoConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo import async_remove_config_entry_device
from custom_components.nature_remo.const import DOMAIN, STALE_POLLS_BEFORE_REMOVAL
from custom_components.nature_remo.coordinator import NatureRemoCoordinator
from tests.conftest import async_poll


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, stores a coordinator, and unloads cleanly."""
    assert init_integration.state is ConfigEntryState.LOADED
    coordinator = init_integration.runtime_data
    assert isinstance(coordinator, NatureRemoCoordinator)
    assert "appliance-ac-1" in coordinator.data.appliances

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_energy_only_hub_is_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Remo E lite with no sensor events is still registered (spec 5.4).

    It reports no te/hu/il/mo events, so no device-scoped entity is ever created
    for it; without eager registration its hub device would be missing.
    """
    device_registry = dr.async_get(hass)

    hub = device_registry.async_get_device(identifiers={(DOMAIN, "device-remoe-1")})
    assert hub is not None
    assert hub.manufacturer == "Nature"
    assert hub.model == "Remo-E-lite"
    assert hub.sw_version == "1.7.2"
    assert hub.serial_number == "4W123456789012"
    assert hub.configuration_url == "https://home.nature.global/"
    assert (dr.CONNECTION_NETWORK_MAC, "ab:cd:ef:12:34:59") in hub.connections


async def test_appliance_links_to_its_hub(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Every appliance points at its parent hub via via_device (spec 5.4).

    The smart meter under the Remo E lite must be linked to the hub rather than
    orphaned at the top level, regardless of platform setup ordering.
    """
    device_registry = dr.async_get(hass)

    hub = device_registry.async_get_device(identifiers={(DOMAIN, "device-remoe-1")})
    meter = device_registry.async_get_device(
        identifiers={(DOMAIN, "appliance-meter-1")}
    )
    assert hub is not None
    assert meter is not None
    assert meter.via_device_id == hub.id

    remo3 = device_registry.async_get_device(identifiers={(DOMAIN, "device-remo3-1")})
    ac = device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ac-1")})
    assert remo3 is not None
    assert ac is not None
    assert ac.via_device_id == remo3.id


async def test_setup_retries_on_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """A connection failure during first refresh puts the entry in retry."""
    mock_client.get_devices.side_effect = NatureRemoConnectionError("refused")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_error_is_setup_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
) -> None:
    """An auth failure during first refresh marks the entry as errored."""
    mock_client.get_devices.side_effect = NatureRemoAuthError(401, "bad token")
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_new_appliance_adds_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list,
) -> None:
    """An appliance appearing on a later poll creates its entities."""
    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-meter-1"
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.smart_meter_power") is None

    mock_client.get_appliances.return_value = appliances
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert hass.states.get("sensor.smart_meter_power") is not None


async def test_stale_device_is_removed_after_the_grace_period(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A vanished appliance is removed, but not on the strength of one poll.

    Removing a device takes its entities, its area and every automation
    referencing them along, so a single truncated response must not be able
    to trigger it — and when it does happen it must be logged, since nothing
    else records that the device ever existed.
    """
    assert STALE_POLLS_BEFORE_REMOVAL == 3
    caplog.set_level(logging.INFO, logger="custom_components.nature_remo")
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )

    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    await async_poll(hass, 2)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )

    await async_poll(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is None
    )
    assert "Removing device Fan (appliance-ir-1)" in caplog.text
    assert "3 consecutive polls" in caplog.text


async def test_stale_device_returning_resets_the_grace_period(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A device reported again mid-streak keeps its registry entry."""
    device_registry = dr.async_get(hass)

    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    await async_poll(hass, 2)
    mock_client.get_appliances.return_value = appliances
    await async_poll(hass)
    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    await async_poll(hass, 2)

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )


async def test_appliance_rename_reaches_the_device_registry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
) -> None:
    """A nickname edited in the Nature app propagates on the next poll.

    The device would otherwise keep the nickname it happened to have when
    its first entity was created.
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
    assert device is not None
    assert device.name == "Fan"

    mock_client.get_appliances.return_value = [
        replace(appliance, nickname="Ceiling fan")
        if appliance.id == "appliance-ir-1"
        else appliance
        for appliance in appliances
    ]
    await async_poll(hass)

    device = device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
    assert device is not None
    assert device.name == "Ceiling fan"


async def test_remove_config_entry_device(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Manual removal is allowed only for devices gone from the account."""
    device_registry = dr.async_get(hass)

    active = device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ac-1")})
    assert active is not None
    assert (
        await async_remove_config_entry_device(hass, init_integration, active) is False
    )

    ghost = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, "ghost-appliance")},
    )
    assert await async_remove_config_entry_device(hass, init_integration, ghost) is True


async def test_appliance_without_a_platform_gets_no_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
    device_registry: dr.DeviceRegistry,
) -> None:
    """A type no platform serves would otherwise be an empty device.

    BLE_SESAME5 exposes only static pairing information and carries no
    signals (verified live: the account's SESAME shows up with zero
    entities), so nothing can be built from it until the API grows a lock
    state.
    """
    mock_client.get_appliances.return_value = [
        replace(appliance, type="BLE_SESAME5", signals=[])
        if appliance.id == "appliance-ir-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is None
    )
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ac-1")})
        is not None
    )


async def test_unserved_type_keeps_its_device_while_it_has_signals(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list[Appliance],
    device_registry: dr.DeviceRegistry,
) -> None:
    """Signals make an appliance serviceable whatever its type says.

    The button platform builds one entity per signal without looking at the
    type, so skipping such an appliance here would only defer its device to
    whichever entity is added first — and leave it out of the per-poll
    re-registration that propagates a nickname edited in the Nature app.
    """
    mock_client.get_appliances.return_value = [
        replace(appliance, type="SOMETHING_NATURE_ADDED_LATER")
        if appliance.id == "appliance-ir-1"
        else appliance
        for appliance in appliances
    ]
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )
