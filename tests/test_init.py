"""Tests for Nature Remo integration setup."""

from datetime import timedelta
from unittest.mock import AsyncMock

import homeassistant.util.dt as dt_util
from aionatureremo import NatureRemoAuthError, NatureRemoConnectionError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.nature_remo import async_remove_config_entry_device
from custom_components.nature_remo.const import DOMAIN
from custom_components.nature_remo.coordinator import NatureRemoCoordinator


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


async def test_stale_device_is_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: AsyncMock,
    appliances: list,
) -> None:
    """An appliance that disappears is removed from the device registry."""
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is not None
    )

    mock_client.get_appliances.return_value = [
        appliance for appliance in appliances if appliance.id != "appliance-ir-1"
    ]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert (
        device_registry.async_get_device(identifiers={(DOMAIN, "appliance-ir-1")})
        is None
    )


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
